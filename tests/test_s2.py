import copy
import hashlib
import json
import tempfile
import traceback
import unittest
from pathlib import Path
from unittest.mock import patch

from fs_memory_lab.s2 import (
    S2BuildError,
    build_s2_store,
    preflight_s2_build,
    validate_s1_store,
    validate_s2_staging,
    verify_published_s2,
)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def session_bytes(index: int) -> bytes:
    return (
        "---\n"
        f"name: session-{index:02d}\n"
        f"description: Session {index} for a safe S2 test.\n"
        "---\n\n"
        f"# Session {index}\n\n"
        f"Alice: Test memory number {index}.\n"
        f"[S{index}T1] (dia_id: D{index}:1)\n"
    ).encode("utf-8")


def build_s1_fixture(base: Path, count: int = 3) -> tuple[Path, Path]:
    store = base / "stores" / "s1-flat"
    manifest_path = base / "manifests" / "s1-flat.json"
    store.mkdir(parents=True)
    files = {}
    source_index = {}
    total_bytes = 0
    for index in range(1, count + 1):
        name = f"session-{index:02d}.md"
        payload = session_bytes(index)
        (store / name).write_bytes(payload)
        body = payload.split(b"---\n\n", 1)[1]
        files[name] = {
            "body_bytes": len(body),
            "body_sha256": sha256(body),
            "bytes": len(payload),
            "caption_count": 0,
            "first_dia_id": f"D{index}:1",
            "first_locator": f"[S{index}T1]",
            "last_dia_id": f"D{index}:1",
            "last_locator": f"[S{index}T1]",
            "session_date": f"2023-01-{index:02d}",
            "session_index": index,
            "sha256": sha256(payload),
            "turn_count": 1,
        }
        source_index[f"[S{index}T1]"] = {
            "dia_id": f"D{index}:1",
            "end_line": 9,
            "file": name,
            "global_turn_index": index,
            "raw_turn_sha256": "0" * 64,
            "source_sha256": "1" * 64,
            "start_line": 8,
            "turn_index": 1,
        }
        total_bytes += len(payload)
    content_sha = sha256(
        canonical_json_bytes({name: files[name]["sha256"] for name in sorted(files)})
    )
    manifest = {
        "schema_version": 1,
        "artifact_id": "locomo/test/s1-flat/v1",
        "input": {"canonical_sha256": "2" * 64, "source_map_sha256": "3" * 64},
        "counts": {
            "files": count,
            "sessions": count,
            "source_turns": count,
            "turns_with_caption": 0,
            "bytes": total_bytes,
        },
        "files": files,
        "source_index": source_index,
        "store": {"directory_name": "s1-flat", "sha256": content_sha},
    }
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return store, manifest_path


def tool_call(call_id: str, name: str, **arguments) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments, sort_keys=True),
        },
    }


def tool_round(*calls: dict) -> dict:
    return {
        "message": {"role": "assistant", "content": None, "tool_calls": list(calls)},
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "finish_reason": "tool_calls",
        "response_id": "fake-response",
        "served_model": "fake-foldering-model",
        "system_fingerprint": "fake-fingerprint",
    }


def answer_round(text: str = "Foldering complete.") -> dict:
    return {
        "message": {"role": "assistant", "content": text},
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "finish_reason": "stop",
        "response_id": "fake-response-final",
        "served_model": "fake-foldering-model",
        "system_fingerprint": "fake-fingerprint",
    }


class ScriptedProvider:
    model = "fake-requested-alias"
    api_style = "paper"
    endpoint = "https://example.test/v1/chat/completions"

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = []

    def complete(self, messages, tools, config):
        self.calls.append(
            {
                "messages": copy.deepcopy(messages),
                "tools": copy.deepcopy(tools),
                "config": config,
            }
        )
        if not self.steps:
            raise AssertionError("Fake provider script exhausted")
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return copy.deepcopy(step)


class NeverProvider:
    def __init__(self):
        self.call_count = 0

    def complete(self, messages, tools, config):
        self.call_count += 1
        raise AssertionError("Provider must not be called")


def successful_steps(names: list[str]) -> list[dict]:
    folders = ("arts-and-events", "career-and-education", "travel-and-friends")
    moves = [
        tool_call(
            f"move-{index}",
            "rename",
            old_path=f"/memories/{name}",
            new_path=f"/memories/{folders[index % len(folders)]}/{name}",
        )
        for index, name in enumerate(names)
    ]
    return [
        tool_round(tool_call("view-before", "view", path="/memories")),
        tool_round(*moves),
        tool_round(tool_call("view-after", "view", path="/memories")),
        answer_round(f"Organized {len(names)} session files."),
    ]


class S2SafeRunnerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.s1, self.s1_manifest = build_s1_fixture(self.base)
        self.paths = {
            "s2": self.base / "stores" / "s2-foldered",
            "manifest": self.base / "manifests" / "s2-foldered.json",
            "path_map": self.base / "manifests" / "s2-foldered-path-map.json",
            "trace": self.base / "traces" / "s2-foldering.json",
            "marker": self.base / "manifests" / "s2-foldered.COMMITTED",
            "work": self.base / "local-runs" / "s2-foldering",
        }
        self.names = sorted(path.name for path in self.s1.glob("*.md"))
        self.s1_before = {path.name: path.read_bytes() for path in self.s1.glob("*.md")}
        self.s1_entries_before = sorted(path.name for path in self.s1.iterdir())
        self.manifest_before = self.s1_manifest.read_bytes()

    def tearDown(self):
        self.temporary.cleanup()

    def build(self, provider, **kwargs):
        return build_s2_store(
            self.s1,
            self.s1_manifest,
            self.paths["s2"],
            self.paths["manifest"],
            self.paths["path_map"],
            self.paths["trace"],
            self.paths["marker"],
            self.paths["work"],
            provider,
            code_revision="test-safe-runner",
            code_dirty=False,
            expected_s1_manifest_sha256=None,
            **kwargs,
        )

    def assert_s1_unchanged(self):
        self.assertEqual(
            {path.name: path.read_bytes() for path in self.s1.glob("*.md")},
            self.s1_before,
        )
        self.assertEqual(self.s1_manifest.read_bytes(), self.manifest_before)
        self.assertEqual(sorted(path.name for path in self.s1.iterdir()), self.s1_entries_before)

    def assert_no_formal_s2(self):
        self.assertFalse(self.paths["s2"].exists())
        self.assertFalse(self.paths["manifest"].exists())
        self.assertFalse(self.paths["path_map"].exists())
        self.assertFalse(self.paths["trace"].exists())
        self.assertFalse(self.paths["marker"].exists())

    def test_successful_staged_build_gate_publish_and_verify(self):
        provider = ScriptedProvider(successful_steps(self.names))
        report = self.build(provider)

        self.assertEqual(report["status"], "published")
        self.assertEqual(report["files"], 3)
        self.assertEqual(report["served_models"], ["fake-foldering-model"])
        self.assertEqual(len(provider.calls), 4)
        self.assertTrue(all(path.exists() for path in self.paths.values() if path != self.paths["work"]))
        self.assert_s1_unchanged()
        self.assertFalse(any(self.paths["s2"].glob("*.md")))
        published = {path.name: path.read_bytes() for path in self.paths["s2"].rglob("*.md")}
        self.assertEqual(published, self.s1_before)

        path_map = json.loads(self.paths["path_map"].read_text(encoding="utf-8"))
        self.assertEqual([entry["basename"] for entry in path_map["entries"]], self.names)
        self.assertTrue(all("/" in entry["s2_path"] for entry in path_map["entries"]))
        manifest = json.loads(self.paths["manifest"].read_text(encoding="utf-8"))
        self.assertEqual(manifest["model"]["requested_model"], "fake-requested-alias")
        self.assertEqual(manifest["model"]["served_models"], ["fake-foldering-model"])
        self.assertFalse(manifest["model"]["sampling"]["seed_sent_to_provider"])
        self.assertTrue(manifest["verification"]["bytes_identical_to_s1"])
        trace = json.loads(self.paths["trace"].read_text(encoding="utf-8"))
        self.assertEqual(trace["status"], "completed")
        self.assertIn("You are a Foldering Agent", trace["protocol"]["system_prompt"])

        verified = verify_published_s2(
            self.s1,
            self.s1_manifest,
            self.paths["s2"],
            self.paths["manifest"],
            self.paths["path_map"],
            self.paths["trace"],
            self.paths["marker"],
            expected_s1_manifest_sha256=None,
        )
        self.assertEqual(verified["status"], "verified")
        self.assertEqual(verified["layout_sha256"], report["layout_sha256"])

    def test_incomplete_classification_is_quarantined(self):
        moves = [
            tool_call(
                f"move-{index}",
                "rename",
                old_path=f"/memories/{name}",
                new_path=f"/memories/topic-{index + 1}/{name}",
            )
            for index, name in enumerate(self.names[:-1])
        ]
        provider = ScriptedProvider([tool_round(*moves), answer_round("Done.")])

        with self.assertRaisesRegex(S2BuildError, "GATE_RUNNING"):
            self.build(provider)

        self.assert_no_formal_s2()
        self.assert_s1_unchanged()
        runs = list(self.paths["work"].iterdir())
        self.assertEqual(len(runs), 1)
        failure = json.loads((runs[0] / "failure.json").read_text(encoding="utf-8"))
        self.assertEqual(failure["state"], "GATE_RUNNING")
        self.assertEqual(failure["quarantine"], "quarantine")
        self.assertTrue((runs[0] / "quarantine" / self.names[-1]).is_file())

    def test_provider_failure_retains_partial_trace_and_quarantine(self):
        first = self.names[0]
        provider = ScriptedProvider(
            [
                tool_round(
                    tool_call(
                        "move-one",
                        "rename",
                        old_path=f"/memories/{first}",
                        new_path=f"/memories/topic-one/{first}",
                    )
                ),
                RuntimeError("synthetic provider outage"),
            ]
        )

        with self.assertRaisesRegex(S2BuildError, "AGENT_RUNNING"):
            self.build(provider)

        self.assert_no_formal_s2()
        self.assert_s1_unchanged()
        run = next(self.paths["work"].iterdir())
        failure = json.loads((run / "failure.json").read_text(encoding="utf-8"))
        partial = failure["partial_episode"]
        self.assertEqual(partial["tool_calls"], 1)
        self.assertTrue(any(event.get("tool") == "rename" and event["ok"] for event in partial["trace"]))
        events = (run / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn('"tool":"rename"', events)
        self.assertTrue((run / "quarantine" / "topic-one" / first).is_file())

    def test_completion_cap_retains_truncated_response(self):
        capped = {
            "message": {"role": "assistant", "content": "partial"},
            "usage": {"prompt_tokens": 10, "completion_tokens": 100},
            "finish_reason": "length",
            "response_id": "truncated-response",
            "served_model": "fake-foldering-model",
        }
        provider = ScriptedProvider([capped])

        with self.assertRaises(S2BuildError):
            self.build(provider)

        run = next(self.paths["work"].iterdir())
        failure = json.loads((run / "failure.json").read_text(encoding="utf-8"))
        partial = failure["partial_episode"]
        self.assertEqual(partial["error"]["stage"], "completion-cap")
        self.assertEqual(partial["trace"][0]["response_id"], "truncated-response")
        self.assert_no_formal_s2()
        self.assert_s1_unchanged()

    def test_tampered_s1_and_existing_targets_fail_before_provider(self):
        provider = NeverProvider()
        target = self.s1 / self.names[0]
        target.write_bytes(target.read_bytes() + b"tampered\n")
        with self.assertRaisesRegex(S2BuildError, "mismatch"):
            self.build(provider)
        self.assertEqual(provider.call_count, 0)
        self.assert_no_formal_s2()

        target.write_bytes(self.s1_before[self.names[0]])
        self.paths["manifest"].parent.mkdir(parents=True, exist_ok=True)
        self.paths["manifest"].write_text("do not overwrite", encoding="utf-8")
        with self.assertRaisesRegex(S2BuildError, "overwrite"):
            self.build(provider)
        self.assertEqual(provider.call_count, 0)
        self.assertEqual(self.paths["manifest"].read_text(encoding="utf-8"), "do not overwrite")

    def test_global_gate_rejects_mutations_extra_entries_symlink_and_empty_directory(self):
        snapshot = validate_s1_store(
            self.s1, self.s1_manifest, expected_manifest_sha256=None
        )
        for case in (
            "content",
            "renamed",
            "extra",
            "extra-markdown",
            "duplicate-basename",
            "symlink",
            "empty",
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                staging = Path(temporary)
                topic = staging / "topic"
                topic.mkdir()
                for name in self.names:
                    (topic / name).write_bytes(self.s1_before[name])
                if case == "content":
                    (topic / self.names[0]).write_bytes(b"changed")
                elif case == "renamed":
                    (topic / self.names[0]).rename(topic / "renamed.md")
                elif case == "extra":
                    (topic / "extra.txt").write_text("extra", encoding="utf-8")
                elif case == "extra-markdown":
                    (topic / "extra.md").write_bytes(self.s1_before[self.names[0]])
                elif case == "duplicate-basename":
                    duplicate = staging / "second-topic"
                    duplicate.mkdir()
                    (duplicate / self.names[0]).write_bytes(self.s1_before[self.names[0]])
                elif case == "symlink":
                    (topic / "link.md").symlink_to(topic / self.names[0])
                elif case == "empty":
                    (staging / "empty-topic").mkdir()
                with self.assertRaises(S2BuildError):
                    validate_s2_staging(snapshot, staging)

    def test_prompt_freeze_and_lock_fail_closed_without_api(self):
        provider = NeverProvider()
        with patch("fs_memory_lab.s2.FOLDERING_PROMPT", "changed prompt"):
            with self.assertRaisesRegex(S2BuildError, "prompt changed"):
                self.build(provider)
        self.assertEqual(provider.call_count, 0)

        with patch("fs_memory_lab.s2.FOLDERING_TASK", "changed task"):
            with self.assertRaisesRegex(S2BuildError, "task changed"):
                self.build(provider)
        self.assertEqual(provider.call_count, 0)

        changed_tools = {
            "view": {"type": "function", "function": {"name": "changed"}},
            "grep": {"type": "function", "function": {"name": "grep"}},
            "rename": {"type": "function", "function": {"name": "rename"}},
        }
        with patch("fs_memory_lab.s2.FOLDERING_TOOL_DEFINITIONS", changed_tools):
            with self.assertRaisesRegex(S2BuildError, "tool schema changed"):
                self.build(provider)
        self.assertEqual(provider.call_count, 0)

        lock = self.paths["s2"].parent / ".s2-foldered.lock"
        lock.write_text("occupied", encoding="utf-8")
        with self.assertRaisesRegex(S2BuildError, "lock"):
            self.build(provider)
        self.assertEqual(provider.call_count, 0)

    def test_offline_preflight_is_read_only(self):
        before = self.manifest_before
        report = preflight_s2_build(
            self.s1,
            self.s1_manifest,
            self.paths["s2"],
            self.paths["manifest"],
            self.paths["path_map"],
            self.paths["trace"],
            self.paths["marker"],
            expected_s1_manifest_sha256=None,
        )
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["files"], 3)
        self.assertEqual(self.s1_manifest.read_bytes(), before)
        self.assertFalse(self.paths["work"].exists())

    def test_all_writable_paths_are_isolated_from_s1(self):
        provider = NeverProvider()
        original_manifest = self.paths["manifest"]
        self.paths["manifest"] = self.s1 / "must-not-be-created.json"
        with self.assertRaisesRegex(S2BuildError, "isolated from the S1"):
            self.build(provider)
        self.assertFalse(self.paths["manifest"].exists())
        self.paths["manifest"] = original_manifest

        original_work = self.paths["work"]
        self.paths["work"] = self.s1 / "work-must-not-be-created"
        with self.assertRaisesRegex(S2BuildError, "isolated from the S1"):
            self.build(provider)
        self.assertFalse(self.paths["work"].exists())
        self.paths["work"] = original_work

        self.assertEqual(provider.call_count, 0)
        self.assert_s1_unchanged()

    def test_lock_write_failure_removes_owned_lock_before_api(self):
        provider = NeverProvider()
        lock = self.paths["s2"].parent / ".s2-foldered.lock"
        with patch("fs_memory_lab.s2.os.write", side_effect=OSError("disk failure")):
            with self.assertRaisesRegex(S2BuildError, "durable S2 build lock"):
                self.build(provider)
        self.assertFalse(lock.exists())
        self.assertEqual(provider.call_count, 0)
        self.assert_no_formal_s2()
        self.assert_s1_unchanged()

    def test_round_limit_and_malformed_tool_calls_keep_failure_records(self):
        for case in ("round-limit", "malformed-tools"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                s1, s1_manifest = build_s1_fixture(base)
                output = base / "stores/s2-foldered"
                manifest = base / "manifests/s2-foldered.json"
                path_map = base / "manifests/s2-foldered-path-map.json"
                trace = base / "traces/s2-foldering.json"
                marker = base / "manifests/s2-foldered.COMMITTED"
                work = base / "local-runs/s2-foldering"
                if case == "round-limit":
                    provider = ScriptedProvider(
                        [
                            tool_round(tool_call("view-1", "view", path="/memories")),
                            tool_round(tool_call("view-2", "view", path="/memories")),
                        ]
                    )
                    max_rounds = 2
                    expected_stage = "round-limit"
                else:
                    malformed = {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": ["not-an-object"],
                        },
                        "usage": {},
                        "finish_reason": "tool_calls",
                    }
                    provider = ScriptedProvider([malformed])
                    max_rounds = None
                    expected_stage = "provider-response"
                with self.assertRaises(S2BuildError):
                    build_s2_store(
                        s1,
                        s1_manifest,
                        output,
                        manifest,
                        path_map,
                        trace,
                        marker,
                        work,
                        provider,
                        code_revision="test-agent-errors",
                        code_dirty=False,
                        expected_s1_manifest_sha256=None,
                        max_rounds=max_rounds,
                    )
                run = next(work.iterdir())
                failure = json.loads((run / "failure.json").read_text(encoding="utf-8"))
                self.assertEqual(
                    failure["partial_episode"]["error"]["stage"], expected_stage
                )
                self.assertFalse(output.exists())

    def test_untrusted_provider_error_is_redacted_from_cli_exception_chain(self):
        secret = "clsk_abcdefghijklmnopqrstuvwxyz0123456789"
        provider = ScriptedProvider([RuntimeError(f"Bearer {secret}")])
        try:
            self.build(provider)
        except S2BuildError as exc:
            rendered = "".join(traceback.format_exception(exc))
            self.assertNotIn(secret, rendered)
            self.assertIsNone(exc.__cause__)
        else:
            self.fail("Expected S2BuildError")
        run = next(self.paths["work"].iterdir())
        failure_text = (run / "failure.json").read_text(encoding="utf-8")
        self.assertNotIn(secret, failure_text)
        self.assertIn("REDACTED_KEY", failure_text)
        self.assert_no_formal_s2()
        self.assert_s1_unchanged()

    def test_verify_rejects_cross_link_tampering_even_if_json_is_valid(self):
        self.build(ScriptedProvider(successful_steps(self.names)))
        marker = json.loads(self.paths["marker"].read_text(encoding="utf-8"))
        marker["run_id"] = "forged-run-id"
        self.paths["marker"].write_text(
            json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(S2BuildError, "run_id"):
            verify_published_s2(
                self.s1,
                self.s1_manifest,
                self.paths["s2"],
                self.paths["manifest"],
                self.paths["path_map"],
                self.paths["trace"],
                self.paths["marker"],
                expected_s1_manifest_sha256=None,
            )

    def test_publish_failure_rolls_back_all_formal_artifacts(self):
        provider = ScriptedProvider(successful_steps(self.names))
        real_rename = __import__("os").rename

        def fail_on_manifest(source, destination):
            if Path(destination).name == "s2-foldered.json":
                raise OSError("synthetic manifest publish failure")
            return real_rename(source, destination)

        with patch("fs_memory_lab.s2.os.rename", side_effect=fail_on_manifest):
            with self.assertRaisesRegex(S2BuildError, "PUBLISHING"):
                self.build(provider)

        self.assert_no_formal_s2()
        self.assert_s1_unchanged()
        run = next(self.paths["work"].iterdir())
        failure = json.loads((run / "failure.json").read_text(encoding="utf-8"))
        self.assertEqual(failure["state"], "PUBLISHING")
        self.assertTrue((run / "quarantine").is_dir())


class OfficialS1S2IntegrationTest(unittest.TestCase):
    def test_checked_in_30_session_s1_passes_the_complete_fake_build(self):
        root = Path(__file__).resolve().parents[1]
        s1 = root / "experiments/locomo-conv50-v1/stores/s1-flat"
        s1_manifest = root / "experiments/locomo-conv50-v1/manifests/s1-flat.json"
        names = sorted(path.name for path in s1.glob("*.md"))
        before = {name: (s1 / name).read_bytes() for name in names}
        manifest_before = s1_manifest.read_bytes()
        self.assertEqual(len(names), 30)

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            output = base / "stores/s2-foldered"
            manifest = base / "manifests/s2-foldered.json"
            path_map = base / "manifests/s2-foldered-path-map.json"
            trace = base / "traces/s2-foldering.json"
            marker = base / "manifests/s2-foldered.COMMITTED"
            work = base / "local-runs/s2-foldering"
            provider = ScriptedProvider(successful_steps(names))
            report = build_s2_store(
                s1,
                s1_manifest,
                output,
                manifest,
                path_map,
                trace,
                marker,
                work,
                provider,
                code_revision="test-official-s1",
                code_dirty=False,
            )
            verified = verify_published_s2(
                s1, s1_manifest, output, manifest, path_map, trace, marker
            )
            self.assertEqual(report["files"], 30)
            self.assertEqual(verified["files"], 30)
            self.assertEqual(len(list(output.rglob("*.md"))), 30)

        self.assertEqual({name: (s1 / name).read_bytes() for name in names}, before)
        self.assertEqual(s1_manifest.read_bytes(), manifest_before)


if __name__ == "__main__":
    unittest.main()
