import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest import mock

from fs_memory_lab.agent import TransientProviderError
from fs_memory_lab.answerer import render_answerer_user_prompt
from fs_memory_lab.evidence import EvidenceValidationError
from fs_memory_lab.full_context import (
    FULL_CONTEXT_CONDITION_ID,
    build_full_context_bundle,
    build_full_context_items,
    full_context_bundle_from_mapping,
    publish_source_package,
    source_package,
    verify_full_context_bundle,
)
from fs_memory_lab.full_context_cli import _parser, _result_exit_code
from fs_memory_lab.full_context_runner import (
    FULL_CONTEXT_DEV_PILOT_RUN_ID,
    FULL_CONTEXT_PREFLIGHT_QUESTION_ID,
    _append_event,
    _write_exclusive,
    dry_run_full_context,
    evaluate_full_context_run,
    inspect_full_context,
    full_context_record_from_mapping,
    prepare_full_context_run,
    run_full_context,
    verify_full_context_run,
    write_full_context_status,
)
from fs_memory_lab.r1_inputs import load_question_inputs, load_r1_store


ROOT = Path(__file__).resolve().parents[1]
FAKE_COMMIT = "f" * 40


class FakeFullContextProvider:
    api_style = "portable"
    model = "coding"
    timeout = 300
    max_response_bytes = 20_000_000

    def __init__(self, *, served_model: str = "qwen3.8:27b") -> None:
        self.served_model = served_model
        self.calls: list[tuple[list[dict], list[dict], object]] = []

    def complete(self, messages, tools, config):
        self.calls.append((messages, tools, config))
        identifiers = re.findall(r"\[(ev-[0-9a-f]{64})\]", messages[-1]["content"])
        if not identifiers:
            raise AssertionError("Full Context prompt did not contain an evidence ID")
        content = json.dumps(
            {
                "answer": "A supported test answer.",
                "citations": [identifiers[0]],
                "insufficient_evidence": False,
            }
        )
        return {
            "message": {"role": "assistant", "content": content},
            "usage": {
                "prompt_tokens": 40_000,
                "completion_tokens": 10,
                "total_tokens": 40_010,
            },
            "served_model": self.served_model,
            "response_id": f"fake-{len(self.calls)}",
        }


class TimeoutFullContextProvider(FakeFullContextProvider):
    api_key = "clsk_testsecret1234567890"

    def complete(self, messages, tools, config):
        self.calls.append((messages, tools, config))
        raise TransientProviderError(
            f"temporary timeout for {self.api_key}", kind="timeout"
        )


class FullContextSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loaded = load_r1_store(ROOT, "s1")
        cls.items = build_full_context_items(cls.loaded)
        cls.questions = load_question_inputs(ROOT, "dev-6")

    def test_source_package_is_complete_ordered_and_content_addressed(self):
        package = source_package(self.loaded, evidence_items=self.items)
        self.assertEqual(len(self.items), 30)
        self.assertEqual(package["context_stats"]["turn_count"], 568)
        self.assertEqual(package["context_stats"]["caption_turn_count"], 125)
        self.assertEqual(package["context_stats"]["evidence_characters"], 108_960)
        self.assertEqual(
            package["context_stats"]["evidence_text_sha256"],
            "12c3041b32cd7ff32bf6c913b95992cebf48ed3bd1d28ff9f1cdd29c8e927738",
        )
        self.assertEqual(self.items[0].path, "/memories/session-01.md")
        self.assertEqual(self.items[-1].path, "/memories/session-30.md")
        self.assertEqual(self.items[0].source_locators[0], "[S1T1]")
        self.assertTrue(all(item.evidence_id.startswith("ev-") for item in self.items))
        self.assertEqual(
            [row["alias"] for row in package["item_aliases"]],
            [f"FC-S{index:02d}" for index in range(1, 31)],
        )

    def test_bundle_round_trip_prompt_and_frozen_store_verification(self):
        question = next(
            row for row in self.questions if row.question_id == FULL_CONTEXT_PREFLIGHT_QUESTION_ID
        )
        bundle = build_full_context_bundle(
            question=question,
            loaded_store=self.loaded,
            evidence_items=self.items,
        )
        recreated = full_context_bundle_from_mapping(bundle.to_dict())
        self.assertEqual(recreated, bundle)
        verify_full_context_bundle(
            recreated, loaded_store=self.loaded, expected_items=self.items
        )
        prompt = render_answerer_user_prompt(bundle)
        self.assertIn(question.question, prompt)
        self.assertIn("[S1T1]", prompt)
        self.assertIn(self.items[-1].source_locators[-1], prompt)
        self.assertNotIn(FULL_CONTEXT_CONDITION_ID, prompt)
        self.assertNotIn("FC-S01", prompt)

    def test_source_publication_is_idempotent(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            output = Path(folder) / "source"
            first = publish_source_package(repo_root=ROOT, output_dir=output)
            second = publish_source_package(repo_root=ROOT, output_dir=output)
            self.assertEqual(first, second)
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {"context-package.json", "manifest.json", "transcript.txt", "verification.json"},
            )

    def test_inspection_identifies_longest_dev_request_without_api(self):
        report = inspect_full_context(repo_root=ROOT, question_set="dev-6")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["largest_request"]["question_id"], "conv-50-q079")
        self.assertGreater(report["largest_request"]["total_message_characters"], 100_000)
        self.assertTrue(report["api_preflight_required"])


class FullContextRunnerTests(unittest.TestCase):
    def test_immutable_publication_and_short_event_writes(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            root = Path(folder)
            checkpoint = root / "checkpoint.json"
            _write_exclusive(checkpoint, {"value": 1})
            with self.assertRaises(EvidenceValidationError):
                _write_exclusive(checkpoint, {"value": 2})
            self.assertEqual(
                json.loads(checkpoint.read_text(encoding="utf-8")), {"value": 1}
            )

            original_write = __import__("os").write

            def short_write(descriptor, payload):
                return original_write(descriptor, payload[:7])

            events = root / "events.jsonl"
            with mock.patch(
                "fs_memory_lab.full_context_runner.os.write", side_effect=short_write
            ):
                _append_event(events, {"event": "first", "number": 1})
                _append_event(events, {"event": "second", "number": 2})
            rows = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["event"] for row in rows], ["first", "second"])

    def test_dev_prepare_dry_run_fake_execution_audit_and_evaluation(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            output = Path(folder)
            run_id = FULL_CONTEXT_DEV_PILOT_RUN_ID
            prepare_full_context_run(
                repo_root=ROOT,
                output_root=output,
                run_id=run_id,
                question_set="dev-6",
                implementation_commit=FAKE_COMMIT,
            )
            dry = dry_run_full_context(
                repo_root=ROOT, output_root=output, run_id=run_id
            )
            self.assertEqual(dry["status"], "passed")
            self.assertTrue(dry["checks"]["no_search"])
            self.assertTrue(dry["checks"]["semantic_gold_not_loaded"])

            provider = FakeFullContextProvider()
            preflight = run_full_context(
                repo_root=ROOT,
                output_root=output,
                run_id=run_id,
                provider=provider,
                question_id=FULL_CONTEXT_PREFLIGHT_QUESTION_ID,
                sleeper=lambda _: None,
            )
            self.assertEqual(preflight["completed_records"], 1)
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(provider.calls[0][1], [])
            record_path = (
                output
                / run_id
                / "records"
                / FULL_CONTEXT_CONDITION_ID
                / FULL_CONTEXT_PREFLIGHT_QUESTION_ID
                / "record.json"
            )
            tampered = json.loads(record_path.read_text(encoding="utf-8"))
            tampered["deployment_metrics"]["prompt_tokens"] += 1
            tampered["deployment_metrics"]["total_tokens"] += 1
            with self.assertRaises(EvidenceValidationError):
                full_context_record_from_mapping(tampered)

            # A verified checkpoint is skipped and never billed twice.
            run_full_context(
                repo_root=ROOT,
                output_root=output,
                run_id=run_id,
                provider=provider,
                question_id=FULL_CONTEXT_PREFLIGHT_QUESTION_ID,
                sleeper=lambda _: None,
            )
            self.assertEqual(len(provider.calls), 1)
            with self.assertRaises(EvidenceValidationError):
                verify_full_context_run(
                    repo_root=ROOT, output_root=output, run_id=run_id
                )

            main_run_id = "full-context-main-gate-test"
            prepare_full_context_run(
                repo_root=ROOT,
                output_root=output,
                run_id=main_run_id,
                question_set="main-40",
                implementation_commit=FAKE_COMMIT,
            )
            main_provider = FakeFullContextProvider()
            with self.assertRaises(EvidenceValidationError):
                run_full_context(
                    repo_root=ROOT,
                    output_root=output,
                    run_id=main_run_id,
                    provider=main_provider,
                    question_id="conv-50-q023",
                    sleeper=lambda _: None,
                )
            self.assertEqual(main_provider.calls, [])

            completed = run_full_context(
                repo_root=ROOT,
                output_root=output,
                run_id=run_id,
                provider=provider,
                run_all=True,
                sleeper=lambda _: None,
            )
            self.assertEqual(completed["completed_records"], 6)
            self.assertEqual(len(provider.calls), 6)
            audit1 = verify_full_context_run(
                repo_root=ROOT, output_root=output, run_id=run_id
            )
            audit2 = verify_full_context_run(
                repo_root=ROOT, output_root=output, run_id=run_id
            )
            self.assertEqual(audit1, audit2)
            main_status = run_full_context(
                repo_root=ROOT,
                output_root=output,
                run_id=main_run_id,
                provider=main_provider,
                question_id="conv-50-q023",
                sleeper=lambda _: None,
            )
            self.assertEqual(main_status["completed_records"], 1)
            self.assertEqual(len(main_provider.calls), 1)
            gate = json.loads(
                (output / main_run_id / "dev-pilot-gate.json").read_text(encoding="utf-8")
            )
            self.assertEqual(gate["status"], "passed")
            self.assertEqual(gate["dev_run_id"], FULL_CONTEXT_DEV_PILOT_RUN_ID)
            evaluation = evaluate_full_context_run(
                repo_root=ROOT, output_root=output, run_id=run_id
            )
            self.assertEqual(evaluation["count"], 6)
            self.assertIn("locomo_f1", evaluation["micro"])

    def test_provider_settings_fail_closed_before_request(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            output = Path(folder)
            run_id = "full-context-provider-test"
            prepare_full_context_run(
                repo_root=ROOT,
                output_root=output,
                run_id=run_id,
                question_set="dev-6",
                implementation_commit=FAKE_COMMIT,
            )
            provider = FakeFullContextProvider()
            provider.model = None
            with self.assertRaises(EvidenceValidationError):
                run_full_context(
                    repo_root=ROOT,
                    output_root=output,
                    run_id=run_id,
                    provider=provider,
                    question_id=FULL_CONTEXT_PREFLIGHT_QUESTION_ID,
                )
            self.assertEqual(provider.calls, [])
            provider.model = "coding"
            timeout_provider = TimeoutFullContextProvider()
            failed = run_full_context(
                repo_root=ROOT,
                output_root=output,
                run_id=run_id,
                provider=timeout_provider,
                question_id=FULL_CONTEXT_PREFLIGHT_QUESTION_ID,
                sleeper=lambda _: None,
            )
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(len(timeout_provider.calls), 3)
            failure = next(
                (output / run_id / "failures").rglob("attempt-*.json")
            )
            failure_text = failure.read_text(encoding="utf-8")
            failure_value = json.loads(failure_text)
            self.assertTrue(failure_value["retryable"])
            self.assertNotIn(timeout_provider.api_key, failure_text)
            gap = failure.parent / "attempt-0003.json"
            gap.write_text(failure_text, encoding="utf-8")
            failed_again = run_full_context(
                repo_root=ROOT,
                output_root=output,
                run_id=run_id,
                provider=timeout_provider,
                question_id=FULL_CONTEXT_PREFLIGHT_QUESTION_ID,
                sleeper=lambda _: None,
            )
            self.assertEqual(failed_again["status"], "failed")
            self.assertTrue((failure.parent / "attempt-0004.json").is_file())

    def test_cli_requires_an_explicit_run_target(self):
        parser = _parser()
        base = [
            "--output-root", "/private/tmp/full-context-test",
            "--run-id", "full-context-test",
            "run",
        ]
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(base)
        args = parser.parse_args([*base, "--through-block", "1"])
        self.assertEqual(args.through_block, 1)
        self.assertEqual(_result_exit_code("run", {"status": "failed"}), 1)
        self.assertEqual(_result_exit_code("pilot", {"status": "failed"}), 1)
        self.assertEqual(_result_exit_code("status", {"status": "failed"}), 0)
        self.assertEqual(_result_exit_code("run", {"status": "pending"}), 0)


if __name__ == "__main__":
    unittest.main()
