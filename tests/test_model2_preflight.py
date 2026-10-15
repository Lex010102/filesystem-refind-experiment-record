from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fs_memory_lab.agent import CompatibleChatProvider
from fs_memory_lab.model2_preflight import (
    MODEL2_CHAT_ENDPOINT,
    MODEL2_EXPECTED_SERVED_MODEL,
    MODEL2_MODELS_ENDPOINT,
    MODEL2_REQUESTED_ALIAS,
    Model2IdentityCheckingProvider,
    Model2IdentityError,
    Model2PreflightError,
    check_model2_alias,
    load_model2_provider_from_environment,
    run_model2_smoke_report,
    verify_sanitized_preflight_artifact,
    write_model2_smoke_report,
    write_model_catalog_check,
)
from fs_memory_lab.model2_preflight_cli import main as preflight_main
from fs_memory_lab.paper_config import RoleConfig


def response(content, *, tool_calls=None, finish_reason="stop", served=None):
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "message": message,
        "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        "finish_reason": finish_reason,
        "response_id": "response-test",
        "system_fingerprint": "fingerprint-test",
        "served_model": served or MODEL2_EXPECTED_SERVED_MODEL,
    }


def native_call(name, arguments, *, call_id):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


class ScriptedProvider:
    model = MODEL2_REQUESTED_ALIAS
    api_style = "portable"
    api_key = "unit-test-credential"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, messages, tools, config):
        self.calls.append((messages, tools, config))
        if not self.replies:
            raise AssertionError("unexpected provider call")
        return self.replies.pop(0)


class ResponseContext:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self.value


class Model2PreflightTests(unittest.TestCase):
    def provider(self):
        return CompatibleChatProvider(
            "https://soclaas-api.comp.nus.edu.sg/v1",
            MODEL2_REQUESTED_ALIAS,
            "unit-test-credential",
            api_style="portable",
        )

    def test_models_check_requires_exact_alias_and_sanitizes_artifact(self):
        payload = json.dumps(
            {
                "object": "list",
                "data": [
                    {"id": "x-test-1"},
                    {"id": "x-test-2", "max_model_len": 1_048_576},
                ],
            }
        ).encode()
        seen = {}

        def opener(request, timeout):
            seen["url"] = request.full_url
            seen["method"] = request.get_method()
            seen["timeout"] = timeout
            return ResponseContext(payload)

        check = check_model2_alias(self.provider(), opener=opener)
        self.assertEqual(seen["url"], MODEL2_MODELS_ENDPOINT)
        self.assertEqual(seen["method"], "GET")
        self.assertEqual(check.requested_alias, MODEL2_REQUESTED_ALIAS)
        self.assertEqual(check.alias_context_limits["max_model_len"], 1_048_576)
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            path = write_model_catalog_check(Path(temporary) / "models.json", check)
            text = path.read_text()
            self.assertNotIn("unit-test-credential", text)
            summary = verify_sanitized_preflight_artifact(path)
            self.assertTrue(summary["alias_present"])

    def test_models_check_missing_alias_fails_closed(self):
        payload = json.dumps(
            {"data": [{"id": "x-test-1", "max_model_len": 1_048_576}]}
        ).encode()
        with self.assertRaises(Model2IdentityError):
            check_model2_alias(
                self.provider(), opener=lambda *_args, **_kwargs: ResponseContext(payload)
            )

    def test_environment_loader_requires_frozen_endpoint_alias_and_profile(self):
        values = {
            "FSMEM_API_BASE_URL": "https://soclaas-api.comp.nus.edu.sg/v1",
            "FSMEM_MODEL": MODEL2_REQUESTED_ALIAS,
            "FSMEM_API_KEY": "unit-test-credential",
            "FSMEM_API_STYLE": "portable",
        }
        with patch.dict(os.environ, values, clear=True):
            provider = load_model2_provider_from_environment()
        self.assertEqual(provider.endpoint, MODEL2_CHAT_ENDPOINT)
        self.assertEqual(provider.model, MODEL2_REQUESTED_ALIAS)
        with patch.dict(os.environ, {**values, "FSMEM_MODEL": "coding"}, clear=True):
            with self.assertRaises(Model2IdentityError):
                load_model2_provider_from_environment()

    def test_identity_gate_captures_only_sanitized_receipt(self):
        upstream = ScriptedProvider([response("ok")])
        gate = Model2IdentityCheckingProvider(
            provider=upstream,
            component="r1_compaction",
            expected_served_model=MODEL2_EXPECTED_SERVED_MODEL,
        )
        returned = gate.complete(
            [{"role": "user", "content": "private prompt"}],
            [],
            RoleConfig(MODEL2_REQUESTED_ALIAS, "high", 10, 1),
        )
        self.assertEqual(returned["message"]["content"], "ok")
        receipt = gate.receipts[0].to_dict()
        self.assertEqual(receipt["requested_alias"], MODEL2_REQUESTED_ALIAS)
        self.assertEqual(receipt["served_model"], "deepseek-v4.1-flash")
        self.assertEqual(receipt["usage"]["total_tokens"], 10)
        self.assertNotIn("private prompt", json.dumps(receipt))
        self.assertNotIn('"content": "ok"', json.dumps(receipt))

    def test_identity_gate_rejects_missing_or_drifting_identity_and_usage(self):
        cases = []
        missing = response("ok")
        missing["served_model"] = None
        cases.append(missing)
        cases.append(response("ok", served="another-model"))
        invalid_usage = response("ok")
        invalid_usage["usage"] = {"prompt_tokens": 1, "completion_tokens": 1}
        cases.append(invalid_usage)
        for reply in cases:
            gate = Model2IdentityCheckingProvider(
                provider=ScriptedProvider([reply]),
                component="r1_compaction",
                expected_served_model=MODEL2_EXPECTED_SERVED_MODEL,
            )
            with self.assertRaises(Model2PreflightError):
                gate.complete(
                    [], [], RoleConfig(MODEL2_REQUESTED_ALIAS, "high", 10, 1)
                )
            self.assertEqual(gate.receipts, ())

    def test_identity_gate_uses_upstream_override_for_real_r1_configs(self):
        upstream = ScriptedProvider([response("ok")])
        gate = Model2IdentityCheckingProvider(
            provider=upstream,
            component="r1_compaction",
            expected_served_model=MODEL2_EXPECTED_SERVED_MODEL,
        )
        gate.complete([], [], RoleConfig("gpt-5.4-mini", "high", 8192, 1))
        self.assertEqual(len(upstream.calls), 1)

    def test_identity_gate_without_override_rejects_wrong_config_before_call(self):
        upstream = ScriptedProvider([response("ok")])
        upstream.model = None
        gate = Model2IdentityCheckingProvider(
            provider=upstream,
            component="r1_compaction",
            expected_served_model=MODEL2_EXPECTED_SERVED_MODEL,
        )
        with self.assertRaises(Model2IdentityError):
            gate.complete([], [], RoleConfig("coding", "high", 10, 1))
        self.assertEqual(upstream.calls, [])

    def test_all_role_smokes_use_frozen_protocols_and_emit_no_content(self):
        r1_call = native_call("view", {"path": "/memories"}, call_id="call-1")
        note_call = native_call(
            "take_note",
            {
                "observation_ids": ["obs-0001"],
                "path": "/memories/preflight.md",
                "line_start": 1,
                "line_end": 1,
            },
            call_id="call-note",
        )
        finish_call = native_call(
            "finish_search",
            {"reason": "evidence_sufficient", "missing_aspects": []},
            call_id="call-finish",
        )
        answer = json.dumps(
            {
                "answer": "Kyoto",
                "citations": ["ev-" + "0" * 64],
                "insufficient_evidence": False,
            }
        )
        provider = ScriptedProvider(
            [
                response(None, tool_calls=[r1_call], finish_reason="tool_calls"),
                response(None, tool_calls=[note_call], finish_reason="tool_calls"),
                response(None, tool_calls=[finish_call], finish_reason="tool_calls"),
                response("Kyoto was named in the earlier observation."),
                response("Thought: Done.\nAction: finish_search\nAction Input: {}"),
                response("Thought: Enough.\nAction: finish_search\nAction Input: {}"),
                response(answer),
            ]
        )
        report = run_model2_smoke_report(provider)
        self.assertEqual(len(provider.calls), 7)
        self.assertEqual(
            [row.component for row in report.roles],
            ["r1", "r1_compaction", "r2", "r3", "answerer"],
        )
        self.assertEqual(report.expected_served_model, "deepseek-v4.1-flash")
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            path = write_model2_smoke_report(Path(temporary) / "smoke.json", report)
            text = path.read_text()
            self.assertNotIn("Which city", text)
            self.assertNotIn("Kyoto was named", text)
            self.assertNotIn('"answer": "Kyoto"', text)
            self.assertNotIn("unit-test-credential", text)
            summary = verify_sanitized_preflight_artifact(path)
            self.assertEqual(summary["role_smokes_passed"], 5)
            self.assertEqual(summary["served_model"], "deepseek-v4.1-flash")

    def test_smoke_artifact_drift_and_overwrite_are_rejected(self):
        r1_call = native_call("view", {"path": "/memories"}, call_id="call-1")
        note_call = native_call(
            "take_note",
            {
                "observation_ids": ["obs-0001"],
                "path": "/memories/preflight.md",
                "line_start": 1,
                "line_end": 1,
            },
            call_id="call-note",
        )
        finish_call = native_call(
            "finish_search",
            {"reason": "evidence_sufficient", "missing_aspects": []},
            call_id="call-finish",
        )
        replies = [
            response(None, tool_calls=[r1_call], finish_reason="tool_calls"),
            response(None, tool_calls=[note_call], finish_reason="tool_calls"),
            response(None, tool_calls=[finish_call], finish_reason="tool_calls"),
            response("summary"),
            response("Thought: Done.\nAction: finish_search\nAction Input: {}"),
            response("Thought: Done.\nAction: finish_search\nAction Input: {}"),
            response(
                json.dumps(
                    {
                        "answer": "Kyoto",
                        "citations": ["ev-" + "0" * 64],
                        "insufficient_evidence": False,
                    }
                )
            ),
        ]
        report = run_model2_smoke_report(ScriptedProvider(replies))
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            path = write_model2_smoke_report(Path(temporary) / "smoke.json", report)
            with self.assertRaises(Model2PreflightError):
                write_model2_smoke_report(path, report)
            value = json.loads(path.read_text())
            value["roles"][0]["receipt"]["served_model"] = "other"
            drift = Path(temporary) / "drift.json"
            drift.write_text(json.dumps(value))
            with self.assertRaises(Model2IdentityError):
                verify_sanitized_preflight_artifact(drift)
            value = json.loads(path.read_text())
            value["roles"][1]["checks"]["finish_stop"] = False
            failed_check = Path(temporary) / "failed-check.json"
            failed_check.write_text(json.dumps(value))
            with self.assertRaises(Model2PreflightError):
                verify_sanitized_preflight_artifact(failed_check)

    def test_cli_verify_and_summary_print_only_safe_summary(self):
        payload = {
            "schema_version": 1,
            "artifact_type": "model2-models-check",
            "protocol_version": "model2-x-test2-preflight-v1",
            "status": "passed",
            "requested_alias": "x-test-2",
            "endpoint": MODEL2_MODELS_ENDPOINT,
            "alias_present": True,
            "advertised_model_count": 1,
            "advertised_model_ids": ["x-test-2"],
            "alias_context_limits": {"max_model_len": 1_048_576},
        }
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            path = Path(temporary) / "models.json"
            path.write_text(json.dumps(payload))
            for command in ("verify", "summary"):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(
                        preflight_main([command, "--input", str(path)]), 0
                    )
                printed = json.loads(output.getvalue())
                self.assertTrue(printed["verified"])
                self.assertNotIn("advertised_model_ids", printed)


if __name__ == "__main__":
    unittest.main()
