import json
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fs_memory_lab.evidence import EvidenceValidationError
from fs_memory_lab.evidence import canonical_json_bytes, sha256_bytes
from fs_memory_lab.agent import TransientProviderError
from fs_memory_lab.formal_v2_model2 import (
    CHILD_FAILURE_METADATA_DIR,
    MODEL2_CHAT_ENDPOINT,
    MODEL2_CONTEXT_LIMIT,
    MODEL2_DRY_RUN_PROTOCOL_VERSION,
    MODEL2_DRY_RUN_REQUIRED_CHECKS,
    MODEL2_OUTER_SAME_CONFIG_ATTEMPT_LIMIT,
    MODEL2_PLANNED_RECORDS,
    MODEL2_REQUESTED_MODEL_ALIAS,
    MODEL2_REQUIRED_SERVED_MODEL,
    ModelIdentityError,
    ModelIdentityProvider,
    Model2RecordError,
    SUITE_IDENTITY_DRIFT_NAME,
    _is_retryable_error,
    _retrieval_failure_metadata,
    guard_provider_for_suite,
    open_suite,
    prepare_suite,
    resume_window,
    run_child,
    run_child_with_recovery,
    verify_pre_gold,
    write_suite_status,
)
from fs_memory_lab.formal_v2_model2_cli import _parser
from fs_memory_lab.model2_preflight import MODEL2_CONTEXT_LIMIT as PREFLIGHT_CONTEXT_LIMIT
from fs_memory_lab.model2_preflight import (
    MODEL2_ROLE_ORDER,
    Model2SmokeReport,
    ModelResponseReceipt,
    RoleSmokeResult,
)
from fs_memory_lab.paper_config import RoleConfig
from fs_memory_lab.r1_agent import R1ResearchAgent


ROOT = Path(__file__).resolve().parents[1]
FAKE_COMMIT = "7" * 40


def _write_test_preflight_pair(folder: Path) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    models = folder / "models-check.json"
    models.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifact_type": "model2-models-check",
                "protocol_version": "model2-x-test2-preflight-v1",
                "status": "passed",
                "requested_alias": MODEL2_REQUESTED_MODEL_ALIAS,
                "endpoint": "https://soclaas-api.comp.nus.edu.sg/v1/models",
                "alias_present": True,
                "advertised_model_count": 1,
                "advertised_model_ids": [MODEL2_REQUESTED_MODEL_ALIAS],
                "alias_context_limits": {"max_model_len": MODEL2_CONTEXT_LIMIT},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    role_checks = {
        "r1": {
            "native_tool_calls": True,
            "tool_choice_auto_profile": True,
            "tool_call_count": 1,
            "single_tool_mode": "filesystem",
            "json_arguments": True,
            "take_note_wire_compatibility": True,
            "finish_search_wire_compatibility": True,
        },
        "r1_compaction": {
            "plain_text": True,
            "no_tool_calls": True,
            "finish_stop": True,
        },
        "r2": {
            "textual_react": True,
            "no_native_tool_calls": True,
            "action": "finish_search",
            "action_input_json": True,
            "synthetic_stop_turn": True,
        },
        "r3": {
            "textual_react": True,
            "no_native_tool_calls": True,
            "action": "finish_search",
            "action_input_json": True,
            "synthetic_stop_turn": True,
        },
        "answerer": {
            "exact_json": True,
            "no_tool_calls": True,
            "citation_subset": True,
            "citation_count": 1,
        },
    }
    roles = []
    for component in MODEL2_ROLE_ORDER:
        def receipt(call_index, component=component):
            return ModelResponseReceipt(
                component=component,
                call_index=call_index,
                requested_alias=MODEL2_REQUESTED_MODEL_ALIAS,
                served_model=MODEL2_REQUIRED_SERVED_MODEL,
                usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                finish_reason="stop",
                response_id=None,
                system_fingerprint=None,
            )

        roles.append(
            RoleSmokeResult(
                component=component,
                request_sha256="a" * 64,
                system_prompt_sha256="b" * 64,
                receipt=receipt(1),
                checks=role_checks[component],
                additional_receipts=(receipt(2), receipt(3))
                if component == "r1"
                else (),
                additional_request_sha256s=("c" * 64, "d" * 64)
                if component == "r1"
                else (),
            )
        )
    smoke = folder / "role-smoke.json"
    smoke.write_text(
        json.dumps(
            Model2SmokeReport(
                requested_alias=MODEL2_REQUESTED_MODEL_ALIAS,
                expected_served_model=MODEL2_REQUIRED_SERVED_MODEL,
                roles=tuple(roles),
            ).to_dict(),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return models, smoke


class FakeProvider:
    def __init__(
        self,
        served_model=MODEL2_REQUIRED_SERVED_MODEL,
        model=MODEL2_REQUESTED_MODEL_ALIAS,
    ):
        self.model = model
        self.endpoint = MODEL2_CHAT_ENDPOINT
        self.api_style = "portable"
        self.timeout = 300
        self.max_response_bytes = 20_000_000
        self.served_model = served_model
        self.calls = 0

    def complete(self, messages, tools, config):
        self.calls += 1
        return {
            "message": {"role": "assistant", "content": "ok"},
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "finish_reason": "stop",
            "response_id": "response-1",
            "system_fingerprint": None,
            "served_model": self.served_model,
        }


class ExecutionProvider:
    model = MODEL2_REQUESTED_MODEL_ALIAS
    endpoint = MODEL2_CHAT_ENDPOINT
    api_style = "portable"
    timeout = 300
    max_response_bytes = 20_000_000

    def __init__(self, *, drift_first=False, fail_if_called=False):
        self.calls = 0
        self.drift_first = drift_first
        self.fail_if_called = fail_if_called
        self.paths = {}
        for store_id in ("s1", "s2", "s3"):
            from fs_memory_lab.r1_inputs import load_r1_store

            loaded = load_r1_store(ROOT, store_id)
            span = loaded.verified_manifest.attribution_index.occurrences("[S1T13]")[0]
            self.paths[store_id] = (
                "/memories/" + span.path,
                span.line_start,
                span.line_end,
            )

    def _response(self, *, content, tool_calls=None, finish_reason="stop"):
        self.calls += 1
        if self.fail_if_called:
            raise AssertionError("resume checkpoint unexpectedly called the provider")
        return {
            "message": {
                "role": "assistant",
                "content": content,
                **({"tool_calls": tool_calls} if tool_calls is not None else {}),
            },
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            "finish_reason": finish_reason,
            "response_id": f"model2-fake-{self.calls}",
            "system_fingerprint": None,
            "served_model": (
                "drifted-model"
                if self.drift_first and self.calls == 1
                else MODEL2_REQUIRED_SERVED_MODEL
            ),
        }

    def complete(self, messages, tools, config):
        system = messages[0]["content"]
        if tools:
            if "The store is FLAT" in system:
                store_id = "s1"
            elif "RAW per-session conversation transcripts" in system:
                store_id = "s2"
            else:
                store_id = "s3"
            path, line_start, line_end = self.paths[store_id]
            completed_actions = sum(message.get("role") == "tool" for message in messages)
            if completed_actions == 0:
                name = "view"
                arguments = {
                    "path": path,
                    "start_line": line_start,
                    "end_line": line_end,
                }
            elif completed_actions == 1:
                name = "take_note"
                arguments = {
                    "observation_ids": ["obs-0001"],
                    "path": path,
                    "line_start": line_start,
                    "line_end": line_end,
                }
            else:
                name = "finish_search"
                arguments = {"reason": "evidence_sufficient", "missing_aspects": []}
            tool_call = {
                "id": f"call-{self.calls + 1}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
            return self._response(
                content=None, tool_calls=[tool_call], finish_reason="tool_calls"
            )
        if system.startswith("You answer a question using only the supplied evidence"):
            return self._response(
                content=json.dumps(
                    {
                        "answer": "Insufficient evidence.",
                        "citations": [],
                        "insufficient_evidence": True,
                    }
                )
            )
        return self._response(
            content="Thought: Done.\nAction: finish_search\nAction Input: {}"
        )


class ReplayFailureThenSuccessProvider(ExecutionProvider):
    """Emit two identical corrected-free-text R1 failures, then succeed."""

    def __init__(self):
        super().__init__()
        self.bad_responses_remaining = 2

    def complete(self, messages, tools, config):
        if tools and self.bad_responses_remaining:
            self.bad_responses_remaining -= 1
            self.calls += 1
            return {
                "message": {"role": "assistant", "content": "direct answer"},
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 1,
                    "total_tokens": 3,
                },
                "finish_reason": "stop",
                "response_id": "identical-bad-response",
                "system_fingerprint": None,
                "served_model": MODEL2_REQUIRED_SERVED_MODEL,
            }
        return super().complete(messages, tools, config)


class AnswerFailureThenSuccessProvider(ExecutionProvider):
    """Fail one answer attempt after a durable retrieval, then answer cleanly."""

    def __init__(self):
        super().__init__()
        self.bad_answer_responses_remaining = 2

    def complete(self, messages, tools, config):
        system = messages[0]["content"]
        if (
            not tools
            and (
                system.startswith(
                    "You answer a question using only the supplied evidence"
                )
                or system.startswith(
                    "Reformat the candidate into the exact required JSON schema"
                )
            )
            and self.bad_answer_responses_remaining
        ):
            self.bad_answer_responses_remaining -= 1
            return self._response(content="not valid answer JSON")
        return super().complete(messages, tools, config)


class ExplodingProvider:
    model = MODEL2_REQUESTED_MODEL_ALIAS
    endpoint = MODEL2_CHAT_ENDPOINT
    api_style = "portable"
    timeout = 300
    max_response_bytes = 20_000_000

    def __init__(self, *, secret, transient):
        self.api_key = secret
        self.secret = secret
        self.transient = transient
        self.calls = 0

    def complete(self, messages, tools, config):
        self.calls += 1
        if self.transient:
            raise TransientProviderError(
                f"temporary upstream failure carried {self.secret}", kind="timeout"
            )
        raise RuntimeError(f"DNS failure accidentally carried {self.secret}")


class FormalV2Model2Tests(unittest.TestCase):
    def _prepare(self, output: Path, suite_id: str = "model2-suite-test") -> Path:
        models_check, role_smoke = _write_test_preflight_pair(
            output / "test-preflight"
        )
        return prepare_suite(
            repo_root=ROOT,
            output_root=output,
            suite_id=suite_id,
            implementation_commit=FAKE_COMMIT,
            requested_model_alias=MODEL2_REQUESTED_MODEL_ALIAS,
            required_served_model=MODEL2_REQUIRED_SERVED_MODEL,
            models_check_report_path=models_check,
            role_smoke_report_path=role_smoke,
        )

    def _write_dry_run(self, output: Path, suite_id: str = "model2-suite-test"):
        suite = open_suite(repo_root=ROOT, output_root=output, suite_id=suite_id)
        schedule = [
            {
                "condition_id": row["condition_id"],
                "question_id": row["question_id"],
            }
            for row in suite.manifest["global_schedule"]
        ]
        body = {
            "schema_version": 1,
            "protocol_version": MODEL2_DRY_RUN_PROTOCOL_VERSION,
            "suite_id": suite_id,
            "suite_manifest_id": suite.manifest["suite_manifest_id"],
            "status": "passed",
            "checks": {
                check: True for check in sorted(MODEL2_DRY_RUN_REQUIRED_CHECKS)
            },
            "deployment": dict(suite.manifest["deployment"]),
            "preflight": {
                "verified": True,
                "artifact_type": "model2-role-smoke",
                "requested_alias": MODEL2_REQUESTED_MODEL_ALIAS,
                "served_model": MODEL2_REQUIRED_SERVED_MODEL,
                "role_smokes_passed": 5,
                "components": ["r1", "r1_compaction", "r2", "r3", "answerer"],
            },
            "question_count": 60,
            "planned_records": 420,
            "condition_counts": {f"E{index}": 60 for index in range(1, 8)},
            "execution_order_sha256": sha256_bytes(
                canonical_json_bytes(schedule)
            ),
            "batch_count": 12,
            "records_per_batch": 35,
            "child_checkpoints": {
                "main40": suite.main_store.checkpoint(),
                "extension20": suite.extension_store.checkpoint(),
            },
            "resume_projection_checks": {
                f"completed_{boundary}": True for boundary in range(0, 421, 35)
            },
            "api_boundary": {"provider_constructed": False, "calls": 0},
            "answer_boundary": {"records_generated": 0},
            "gold_boundary": {"semantic_records_loaded": False},
            "judge_boundary": {"judge_constructed": False, "calls": 0},
        }
        report = {
            "dry_run_id": "model2-suite-dry-run-"
            + sha256_bytes(canonical_json_bytes(body)),
            **body,
        }
        (suite.suite_root / "dry-run.json").write_bytes(
            canonical_json_bytes(report) + b"\n"
        )
        return report

    def test_prepare_freezes_two_children_and_global_batch_mapping(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            output = Path(folder)
            manifest_path = self._prepare(output)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["deployment"]["requested_model_alias"], "x-test-2")
            self.assertEqual(
                manifest["deployment"]["required_served_model"],
                "deepseek-v4.1-flash",
            )
            self.assertEqual(
                manifest["deployment"]["chat_endpoint"], MODEL2_CHAT_ENDPOINT
            )
            self.assertEqual(
                manifest["deployment"]["context_limit_tokens"], MODEL2_CONTEXT_LIMIT
            )
            self.assertEqual(
                manifest["preflight_artifacts"]["models_check"]["summary"][
                    "context_limit"
                ],
                MODEL2_CONTEXT_LIMIT,
            )
            self.assertEqual(
                manifest["deployment"]["models_check_report_sha256"],
                manifest["preflight_artifacts"]["models_check"]["sha256"],
            )
            self.assertEqual(
                manifest["deployment"]["preflight_report_sha256"],
                manifest["preflight_artifacts"]["role_smoke"]["sha256"],
            )
            self.assertEqual(MODEL2_CONTEXT_LIMIT, PREFLIGHT_CONTEXT_LIMIT)
            self.assertEqual(len(manifest["global_schedule"]), MODEL2_PLANNED_RECORDS)
            self.assertEqual(len(manifest["batch_map"]), 12)
            self.assertEqual(manifest["batch_map"][0]["batch_id"], "B01")
            self.assertEqual(manifest["batch_map"][7]["child_id"], "main40")
            self.assertEqual(manifest["batch_map"][8]["child_id"], "extension20")
            self.assertEqual(manifest["batch_map"][8]["child_local_batch"], 1)
            self.assertEqual(manifest["batch_map"][11]["batch_id"], "B12")
            suite = open_suite(
                repo_root=ROOT, output_root=output, suite_id="model2-suite-test"
            )
            self.assertEqual(len(suite.main_store.plan.execution_order), 280)
            self.assertEqual(len(suite.extension_store.plan.execution_order), 140)
            guarded = guard_provider_for_suite(suite, FakeProvider())
            self.assertEqual(guarded.model, MODEL2_REQUESTED_MODEL_ALIAS)
            all_conditions = [
                item["condition_id"] for item in manifest["global_schedule"]
            ]
            self.assertEqual(
                {condition: all_conditions.count(condition) for condition in set(all_conditions)},
                {f"E{i}": 60 for i in range(1, 8)},
            )

    def test_open_suite_rejects_tampered_models_check_context_limit(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            output = Path(folder)
            self._prepare(output)
            models_path = (
                output
                / "model2-suite-test"
                / "preflight"
                / "models-check.json"
            )
            value = json.loads(models_path.read_text(encoding="utf-8"))
            value["alias_context_limits"] = {"max_model_len": 32_768}
            models_path.write_bytes(canonical_json_bytes(value) + b"\n")
            with self.assertRaises(EvidenceValidationError):
                open_suite(
                    repo_root=ROOT,
                    output_root=output,
                    suite_id="model2-suite-test",
                )

    def test_checkpoint_resume_preserves_failed_current_key(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            output = Path(folder)
            self._prepare(output)
            suite = open_suite(
                repo_root=ROOT, output_root=output, suite_id="model2-suite-test"
            )
            first = suite.main_store.plan.execution_order[0]
            suite.main_store.publish_failure(
                key=first,
                stage="test",
                error_type="TransientProviderError",
                message="safe synthetic failure",
                retryable=True,
            )
            status = write_suite_status(
                repo_root=ROOT, output_root=output, suite_id="model2-suite-test"
            )
            self.assertEqual(status["status"], "failed")
            self.assertEqual(status["active_failed_keys"], 1)
            window = resume_window(
                repo_root=ROOT,
                output_root=output,
                suite_id="model2-suite-test",
                through_batch=1,
            )
            self.assertEqual(window["pending_records"], 35)
            self.assertEqual(window["next_key"]["condition_id"], first.condition_id)
            self.assertEqual(window["next_key"]["question_id"], first.question_id)
            self.assertEqual(window["execution"], "not-started-by-this-command")

    def test_pre_gold_refuses_incomplete_suite_and_deployment_drift(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            output = Path(folder)
            self._prepare(output)
            with self.assertRaises(EvidenceValidationError):
                verify_pre_gold(
                    repo_root=ROOT,
                    output_root=output,
                    suite_id="model2-suite-test",
                )

    def test_open_suite_revalidates_parent_core_contract(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            output = Path(folder)
            self._prepare(output)
            with patch(
                "fs_memory_lab.formal_v2_model2.verify_formal_manifest",
                side_effect=EvidenceValidationError("synthetic parent core drift"),
            ):
                with self.assertRaisesRegex(EvidenceValidationError, "parent core drift"):
                    open_suite(
                        repo_root=ROOT,
                        output_root=output,
                        suite_id="model2-suite-test",
                    )
            with self.assertRaises(EvidenceValidationError):
                models_check, role_smoke = _write_test_preflight_pair(
                    output / "drifted-test-preflight"
                )
                prepare_suite(
                    repo_root=ROOT,
                    output_root=output,
                    suite_id="model2-suite-test",
                    implementation_commit=FAKE_COMMIT,
                    requested_model_alias=MODEL2_REQUESTED_MODEL_ALIAS,
                    required_served_model="different-model",
                    models_check_report_path=models_check,
                    role_smoke_report_path=role_smoke,
                )

    def test_identity_provider_checks_every_response(self):
        config = RoleConfig(MODEL2_REQUESTED_MODEL_ALIAS, "high", 128, 1)
        provider = FakeProvider()
        guarded = ModelIdentityProvider(
            provider,
            requested_model_alias=MODEL2_REQUESTED_MODEL_ALIAS,
            required_served_model=MODEL2_REQUIRED_SERVED_MODEL,
        )
        response = guarded.complete([], [], config)
        self.assertEqual(response["served_model"], MODEL2_REQUIRED_SERVED_MODEL)
        self.assertEqual(guarded.calls_checked, 1)
        drifted = ModelIdentityProvider(
            FakeProvider("another-model"),
            requested_model_alias=MODEL2_REQUESTED_MODEL_ALIAS,
            required_served_model=MODEL2_REQUIRED_SERVED_MODEL,
        )
        with self.assertRaises(ModelIdentityError):
            drifted.complete([], [], config)
        self.assertIsNotNone(drifted.identity_error)
        # R1 keeps its paper RoleConfig label; an explicit provider.model is
        # the effective wire model and therefore controls the gate.
        guarded.complete([], [], RoleConfig("gpt-5.4-mini", "high", 128, 20))
        fallback = ModelIdentityProvider(
            FakeProvider(model=None),
            requested_model_alias=MODEL2_REQUESTED_MODEL_ALIAS,
            required_served_model=MODEL2_REQUIRED_SERVED_MODEL,
        )
        with self.assertRaises(ModelIdentityError):
            fallback.complete([], [], RoleConfig("coding", "high", 128, 1))
        wrong_endpoint = FakeProvider()
        wrong_endpoint.endpoint = "https://example.invalid/v1/chat/completions"
        with self.assertRaises(ModelIdentityError):
            ModelIdentityProvider(
                wrong_endpoint,
                requested_model_alias=MODEL2_REQUESTED_MODEL_ALIAS,
                required_served_model=MODEL2_REQUIRED_SERVED_MODEL,
            )

    def test_cli_exposes_only_gated_child_execution(self):
        parser = _parser()
        common = [
            "--output-root",
            "/private/tmp/model2-suite-test",
            "--suite-id",
            "model2-suite-test",
        ]
        args = parser.parse_args([*common, "resume-plan", "--through-batch", "12"])
        self.assertEqual(args.through_batch, 12)
        run = parser.parse_args(
            [*common, "run-child", "--child", "main40", "--through-block", "1"]
        )
        self.assertEqual(run.child, "main40")
        self.assertEqual(run.through_block, 1)
        prepared = parser.parse_args(
            [
                *common,
                "prepare",
                "--models-check-report",
                "/private/tmp/models-check.json",
                "--role-smoke-report",
                "/private/tmp/role-smoke.json",
            ]
        )
        self.assertEqual(
            prepared.models_check_report,
            Path("/private/tmp/models-check.json"),
        )
        self.assertEqual(
            prepared.role_smoke_report,
            Path("/private/tmp/role-smoke.json"),
        )
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parser.parse_args([*common, "run"])
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parser.parse_args([*common, "resume-plan", "--through-batch", "13"])

    def test_child_execution_is_dry_run_gated_and_drift_closed_permanently(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            output = Path(folder)
            self._prepare(output)
            ungated = ExecutionProvider(fail_if_called=True)
            with self.assertRaises(EvidenceValidationError):
                run_child(
                    repo_root=ROOT,
                    output_root=output,
                    suite_id="model2-suite-test",
                    child_id="main40",
                    through_block=1,
                    provider=ungated,
                )
            self.assertEqual(ungated.calls, 0)

            self._write_dry_run(output)
            frozen_suite = open_suite(
                repo_root=ROOT, output_root=output, suite_id="model2-suite-test"
            )
            # One planned record is the smallest useful exercise of the real
            # child loop.  Production keeps the frozen value 35; this focused
            # unit test patches only the boundary size to avoid replaying the
            # full immutable store validator 35 times.
            with patch(
                "fs_memory_lab.formal_v2_model2.MODEL2_BATCH_RECORDS", 1
            ), patch(
                "fs_memory_lab.evidence.validate_attribution_index_against_store"
            ), patch(
                "fs_memory_lab.formal_v2_model2.open_suite",
                return_value=frozen_suite,
            ):
                failed = run_child(
                    repo_root=ROOT,
                    output_root=output,
                    suite_id="model2-suite-test",
                    child_id="main40",
                    through_block=1,
                    provider=ExecutionProvider(drift_first=True),
                )
                self.assertEqual(failed["status"], "failed")
                self.assertEqual(failed["progress"]["completed_records"], 0)
                self.assertEqual(failed["progress"]["active_failed_keys"], 1)
                suite = frozen_suite
                first = suite.main_store.plan.execution_order[0]
                self.assertEqual(
                    suite.main_store.failure_attempts(first)[0].error_type,
                    "ModelIdentityError",
                )
                marker = json.loads(
                    (suite.suite_root / SUITE_IDENTITY_DRIFT_NAME).read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(marker["status"], "halted")
                self.assertEqual(marker["observed_served_model"], "drifted-model")
                metadata_path = (
                    suite.main_store.run_root
                    / CHILD_FAILURE_METADATA_DIR
                    / first.condition_id
                    / first.question_id
                    / "attempt-0001.json"
                )
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                self.assertEqual(metadata["observed_served_model"], "drifted-model")
                no_call = ExecutionProvider(fail_if_called=True)
                with self.assertRaises(ModelIdentityError):
                    run_child(
                        repo_root=ROOT,
                        output_root=output,
                        suite_id="model2-suite-test",
                        child_id="main40",
                        through_block=1,
                        provider=no_call,
                    )
                self.assertEqual(no_call.calls, 0)

    def test_dry_run_gate_rejects_missing_or_extra_required_check(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            output = Path(folder)
            self._prepare(output)
            original = self._write_dry_run(output)
            suite = open_suite(
                repo_root=ROOT, output_root=output, suite_id="model2-suite-test"
            )
            path = suite.suite_root / "dry-run.json"
            provider = ExecutionProvider(fail_if_called=True)
            for mutate in ("missing", "extra"):
                report = json.loads(json.dumps(original))
                if mutate == "missing":
                    report["checks"].pop("e7_no_retrieval_contract")
                else:
                    report["checks"]["unversioned_extra_check"] = True
                body = {
                    key: value for key, value in report.items() if key != "dry_run_id"
                }
                report["dry_run_id"] = "model2-suite-dry-run-" + sha256_bytes(
                    canonical_json_bytes(body)
                )
                path.write_bytes(canonical_json_bytes(report) + b"\n")
                with self.assertRaises(EvidenceValidationError):
                    run_child(
                        repo_root=ROOT,
                        output_root=output,
                        suite_id="model2-suite-test",
                        child_id="main40",
                        through_block=1,
                        provider=provider,
                    )
            self.assertEqual(provider.calls, 0)

    def test_child_execution_checkpoint_skip_is_resumable(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            output = Path(folder)
            self._prepare(output)
            self._write_dry_run(output)
            frozen_suite = open_suite(
                repo_root=ROOT, output_root=output, suite_id="model2-suite-test"
            )
            with patch(
                "fs_memory_lab.formal_v2_model2.MODEL2_BATCH_RECORDS", 1
            ), patch(
                "fs_memory_lab.evidence.validate_attribution_index_against_store"
            ), patch(
                "fs_memory_lab.formal_v2_model2.open_suite",
                return_value=frozen_suite,
            ):
                completed = run_child(
                    repo_root=ROOT,
                    output_root=output,
                    suite_id="model2-suite-test",
                    child_id="main40",
                    through_block=1,
                    provider=ExecutionProvider(),
                )
                self.assertEqual(completed["completed_records"], 1)
                self.assertEqual(completed["active_failed_keys"], 0)
                self.assertEqual(completed["completed_by_condition"]["E1"], 1)
                self.assertEqual(frozen_suite.main_store.checkpoint()["completed"], 1)
                self.assertTrue(
                    (frozen_suite.suite_root / "control/batch-01.PASSED").is_file()
                )
                no_call = ExecutionProvider(fail_if_called=True)
                resumed = run_child(
                    repo_root=ROOT,
                    output_root=output,
                    suite_id="model2-suite-test",
                    child_id="main40",
                    through_block=1,
                    provider=no_call,
                )
                self.assertEqual(resumed["completed_records"], 1)
                self.assertEqual(no_call.calls, 0)

    def test_attempt_limit_blocks_provider_before_ninth_attempt(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            output = Path(folder)
            self._prepare(output)
            self._write_dry_run(output)
            frozen_suite = open_suite(
                repo_root=ROOT, output_root=output, suite_id="model2-suite-test"
            )
            first = frozen_suite.main_store.plan.execution_order[0]
            for _ in range(MODEL2_OUTER_SAME_CONFIG_ATTEMPT_LIMIT):
                frozen_suite.main_store.publish_failure(
                    key=first,
                    stage="provider",
                    error_type="TransientProviderError",
                    message="safe synthetic transient failure",
                    retryable=True,
                )
            provider = ExecutionProvider(fail_if_called=True)
            with patch(
                "fs_memory_lab.formal_v2_model2.open_suite",
                return_value=frozen_suite,
            ), patch(
                "fs_memory_lab.formal_v2_model2.load_r1_store", return_value=object()
            ), patch(
                "fs_memory_lab.formal_v2_model2.build_r2_raw_corpus",
                return_value=object(),
            ), patch(
                "fs_memory_lab.formal_v2_model2.load_r3_corpus", return_value=object()
            ), self.assertRaises(EvidenceValidationError):
                run_child(
                    repo_root=ROOT,
                    output_root=output,
                    suite_id="model2-suite-test",
                    child_id="main40",
                    through_block=1,
                    provider=provider,
                )
            self.assertEqual(provider.calls, 0)

    def test_recovery_orchestrator_retries_only_preserved_retryable_failure(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            output = Path(folder)
            self._prepare(output)
            suite = open_suite(
                repo_root=ROOT, output_root=output, suite_id="model2-suite-test"
            )
            first = suite.main_store.plan.execution_order[0]
            suite.main_store.publish_failure(
                key=first,
                stage="provider",
                error_type="TransientProviderError",
                message="safe synthetic transient failure",
                retryable=True,
            )
            failed = {
                "status": "failed",
                "condition_id": first.condition_id,
                "question_id": first.question_id,
            }
            completed = {"status": "pending", "completed_records": 35}
            with patch(
                "fs_memory_lab.formal_v2_model2.run_child",
                side_effect=(failed, completed),
            ) as child:
                result = run_child_with_recovery(
                    repo_root=ROOT,
                    output_root=output,
                    suite_id="model2-suite-test",
                    child_id="main40",
                    through_block=1,
                    provider=FakeProvider(),
                )
            self.assertEqual(child.call_count, 2)
            self.assertEqual(result["recovery"]["status"], "target-reached")
            self.assertEqual(result["recovery"]["runner_invocations"], 2)

    def test_identical_retrieval_failure_collision_keeps_attempt_two_retryable(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            output = Path(folder)
            self._prepare(output)
            self._write_dry_run(output)
            frozen_suite = open_suite(
                repo_root=ROOT, output_root=output, suite_id="model2-suite-test"
            )
            provider = ReplayFailureThenSuccessProvider()
            with patch(
                "fs_memory_lab.formal_v2_model2.MODEL2_BATCH_RECORDS", 1
            ), patch(
                "fs_memory_lab.evidence.validate_attribution_index_against_store"
            ), patch(
                "fs_memory_lab.formal_v2_model2.open_suite",
                return_value=frozen_suite,
            ):
                result = run_child_with_recovery(
                    repo_root=ROOT,
                    output_root=output,
                    suite_id="model2-suite-test",
                    child_id="main40",
                    through_block=1,
                    provider=provider,
                )
            first = frozen_suite.main_store.plan.execution_order[0]
            attempts = frozen_suite.main_store.failure_attempts(first)
            self.assertEqual(len(attempts), 2)
            self.assertTrue(attempts[0].retryable)
            self.assertTrue(attempts[1].retryable)
            self.assertEqual(attempts[0].stage, "provider_response")
            self.assertEqual(attempts[1].stage, "provider_response")
            self.assertEqual(result["recovery"]["runner_invocations"], 3)
            self.assertEqual(result["completed_records"], 1)
            audit = json.loads(
                (frozen_suite.suite_root / "control/batch-01-audit.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(audit["verified_failure_attempts"], 2)
            self.assertEqual(audit["failed_attempt_usage"]["model_calls"], 2)
            self.assertEqual(audit["failed_attempt_usage"]["total_tokens"], 6)

    def test_answer_retry_cost_excludes_reused_retrieval_from_failure_overhead(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            output = Path(folder)
            self._prepare(output)
            self._write_dry_run(output)
            frozen_suite = open_suite(
                repo_root=ROOT, output_root=output, suite_id="model2-suite-test"
            )
            provider = AnswerFailureThenSuccessProvider()
            with patch(
                "fs_memory_lab.formal_v2_model2.MODEL2_BATCH_RECORDS", 1
            ), patch(
                "fs_memory_lab.evidence.validate_attribution_index_against_store"
            ), patch(
                "fs_memory_lab.formal_v2_model2.open_suite",
                return_value=frozen_suite,
            ):
                result = run_child_with_recovery(
                    repo_root=ROOT,
                    output_root=output,
                    suite_id="model2-suite-test",
                    child_id="main40",
                    through_block=1,
                    provider=provider,
                )
            first = frozen_suite.main_store.plan.execution_order[0]
            attempts = frozen_suite.main_store.failure_attempts(first)
            self.assertEqual(len(attempts), 1)
            self.assertEqual(attempts[0].stage, "answer_schema")
            metadata = json.loads(
                (
                    frozen_suite.main_store.run_root
                    / CHILD_FAILURE_METADATA_DIR
                    / first.condition_id
                    / first.question_id
                    / "attempt-0001.json"
                ).read_text(encoding="utf-8")
            )
            # Three retrieval calls (9 tokens) are already represented by the
            # immutable bundle and the eventual RunRecord.  Only the two bad
            # answer calls (6 tokens) belong in failed-attempt overhead.
            self.assertEqual(metadata["failed_attempt_usage"]["model_calls"], 2)
            self.assertEqual(metadata["failed_attempt_usage"]["total_tokens"], 6)
            completed = frozen_suite.main_store.load_completed(first)
            self.assertIsNotNone(completed)
            self.assertEqual(completed.deployment_metrics["total_tokens"], 12)
            self.assertEqual(
                completed.deployment_metrics["total_tokens"]
                + metadata["failed_attempt_usage"]["total_tokens"],
                18,
            )
            self.assertEqual(provider.calls, 6)
            self.assertEqual(result["recovery"]["runner_invocations"], 2)

    def test_retry_classifier_rejects_generic_network_and_http400_wrappers(self):
        for message in ("DNS lookup failed", "HTTP 400 bad request"):
            wrapped = Model2RecordError(
                "provider request failed", stage="provider", retryable=False
            )
            wrapped.__cause__ = RuntimeError(message)
            self.assertFalse(_is_retryable_error(wrapped))

        transient = Model2RecordError(
            "provider request failed", stage="provider", retryable=False
        )
        transient.__cause__ = TransientProviderError("timeout")
        self.assertTrue(_is_retryable_error(transient))
        protocol = Model2RecordError(
            "provider response was malformed",
            stage="provider_response",
            retryable=True,
        )
        self.assertTrue(_is_retryable_error(protocol))

    def test_r2_r3_mixed_transient_then_generic_provider_failure_is_not_retryable(self):
        failure = SimpleNamespace(
            failure_kind="provider_request",
            search_actions=(
                {
                    "event": "provider_retry",
                    "attempt": 1,
                    "kind": "timeout",
                    "http_status": None,
                },
            ),
        )
        transient = {
            "call_index": 1,
            "error_class": "transient",
            "kind": "timeout",
            "http_status": None,
        }
        generic = {
            "call_index": 2,
            "error_class": "generic",
            "kind": None,
            "http_status": None,
        }
        with patch(
            "fs_memory_lab.formal_v2_model2._verify_retrieval_failure",
            return_value=failure,
        ):
            for method in ("r2", "r3"):
                with self.subTest(method=method):
                    stage, retryable = _retrieval_failure_metadata(
                        method,
                        Path("unused-by-patched-verifier"),
                        provider_failures=(transient, generic),
                    )
                    self.assertEqual(stage, "provider_request")
                    self.assertFalse(retryable)
                    _, all_transient = _retrieval_failure_metadata(
                        method,
                        Path("unused-by-patched-verifier"),
                        provider_failures=(transient, transient),
                    )
                    self.assertTrue(all_transient)

    def test_provider_boundary_redacts_low_level_failure_artifacts(self):
        secret = "clsk_UNIT_TEST_SECRET_123456789"
        for transient, expected_retryable, expected_calls in (
            (True, True, 3),
            (False, False, 1),
        ):
            with self.subTest(transient=transient), tempfile.TemporaryDirectory(
                dir=ROOT
            ) as folder:
                output = Path(folder)
                suite_id = "model2-redaction-test"
                self._prepare(output, suite_id=suite_id)
                self._write_dry_run(output, suite_id=suite_id)
                frozen_suite = open_suite(
                    repo_root=ROOT, output_root=output, suite_id=suite_id
                )
                provider = ExplodingProvider(secret=secret, transient=transient)
                kwdefaults = R1ResearchAgent.__init__.__kwdefaults__
                self.assertIsNotNone(kwdefaults)
                with patch(
                    "fs_memory_lab.formal_v2_model2.MODEL2_BATCH_RECORDS", 1
                ), patch(
                    "fs_memory_lab.evidence.validate_attribution_index_against_store"
                ), patch(
                    "fs_memory_lab.formal_v2_model2.open_suite",
                    return_value=frozen_suite,
                ), patch.dict(kwdefaults, {"sleeper": lambda _seconds: None}):
                    result = run_child(
                        repo_root=ROOT,
                        output_root=output,
                        suite_id=suite_id,
                        child_id="main40",
                        through_block=1,
                        provider=provider,
                    )
                self.assertEqual(result["status"], "failed")
                first = frozen_suite.main_store.plan.execution_order[0]
                failure = frozen_suite.main_store.failure_attempts(first)[0]
                self.assertIs(failure.retryable, expected_retryable)
                self.assertEqual(provider.calls, expected_calls)
                metadata = json.loads(
                    (
                        frozen_suite.main_store.run_root
                        / CHILD_FAILURE_METADATA_DIR
                        / first.condition_id
                        / first.question_id
                        / "attempt-0001.json"
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(
                    metadata["failed_attempt_usage"]["model_calls"], expected_calls
                )
                self.assertEqual(
                    metadata["failed_attempt_usage"]["usage_unavailable_calls"],
                    expected_calls,
                )
                self.assertEqual(metadata["failed_attempt_usage"]["total_tokens"], 0)
                self.assertEqual(len(metadata["provider_failures"]), expected_calls)
                self.assertEqual(
                    {row["error_class"] for row in metadata["provider_failures"]},
                    {"transient" if transient else "generic"},
                )
                for path in frozen_suite.suite_root.rglob("*"):
                    if path.is_file():
                        self.assertNotIn(secret.encode(), path.read_bytes(), path)

    def test_recovery_orchestrator_stops_after_nonretryable_failure(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            output = Path(folder)
            self._prepare(output)
            suite = open_suite(
                repo_root=ROOT, output_root=output, suite_id="model2-suite-test"
            )
            first = suite.main_store.plan.execution_order[0]
            suite.main_store.publish_failure(
                key=first,
                stage="provider",
                error_type="RuntimeError",
                message="safe non-transient provider failure",
                retryable=False,
            )
            failed = {
                "status": "failed",
                "condition_id": first.condition_id,
                "question_id": first.question_id,
            }
            with patch(
                "fs_memory_lab.formal_v2_model2.run_child", return_value=failed
            ) as child:
                result = run_child_with_recovery(
                    repo_root=ROOT,
                    output_root=output,
                    suite_id="model2-suite-test",
                    child_id="main40",
                    through_block=1,
                    provider=FakeProvider(),
                )
            self.assertEqual(child.call_count, 1)
            self.assertEqual(result["recovery"]["status"], "non-retryable")

    def test_extension_child_requires_completed_main_gate_before_provider_use(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            output = Path(folder)
            self._prepare(output)
            self._write_dry_run(output)
            provider = ExecutionProvider(fail_if_called=True)
            with self.assertRaises(EvidenceValidationError):
                run_child(
                    repo_root=ROOT,
                    output_root=output,
                    suite_id="model2-suite-test",
                    child_id="extension20",
                    through_block=1,
                    provider=provider,
                )
            self.assertEqual(provider.calls, 0)


if __name__ == "__main__":
    unittest.main()
