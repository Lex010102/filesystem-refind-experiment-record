from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fs_memory_lab.evidence import (
    EvidenceValidationError,
    canonical_json_bytes,
    sha256_bytes,
)
from fs_memory_lab.agent import TransientProviderError
from fs_memory_lab.formal_v2_model2 import ModelIdentityError
from fs_memory_lab.model2_pilot import (
    PILOT_FINAL_AUDIT_NAME,
    PILOT_IDENTITY_DRIFT_NAME,
    PILOT_MANIFEST_NAME,
    PILOT_PASSED_MARKER_NAME,
    _PilotProvider,
    _publish_answer_failure_evidence,
    _retrieval_retry_evidence,
    authorize_model2_pilot_retrieval_retry,
    finalize_model2_pilot,
    prepare_model2_pilot_pipeline,
    run_model2_pilot_answers,
    run_model2_pilot_all,
    run_model2_pilot_retrieval,
    write_model2_pilot_status,
)
from fs_memory_lab.run_records import RunKey
from fs_memory_lab.model2_preflight import (
    MODEL2_MODELS_ENDPOINT,
    MODEL2_ROLE_ORDER,
    ModelCatalogCheck,
    Model2SmokeReport,
    ModelResponseReceipt,
    RoleSmokeResult,
)


ROOT = Path(__file__).resolve().parents[1]
SERVED_MODEL = "deepseek-v4.1-flash"
FAKE_COMMIT = "8" * 40


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_valid_smoke(path: Path) -> None:
    roles = []
    for component in MODEL2_ROLE_ORDER:
        def receipt(call_index: int) -> ModelResponseReceipt:
            return ModelResponseReceipt(
                component=component,
                call_index=call_index,
                requested_alias="x-test-2",
                served_model=SERVED_MODEL,
                usage={
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
                finish_reason="stop",
                response_id=None,
                system_fingerprint=None,
            )

        checks = {
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
        }[component]
        roles.append(
            RoleSmokeResult(
                component=component,
                request_sha256="a" * 64,
                system_prompt_sha256="b" * 64,
                receipt=receipt(1),
                checks=checks,
                additional_receipts=(receipt(2), receipt(3))
                if component == "r1"
                else (),
                additional_request_sha256s=("c" * 64, "d" * 64)
                if component == "r1"
                else (),
            )
        )
    report = Model2SmokeReport(
        requested_alias="x-test-2",
        expected_served_model=SERVED_MODEL,
        roles=tuple(roles),
    )
    path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_valid_models_check(path: Path) -> None:
    check = ModelCatalogCheck(
        requested_alias="x-test-2",
        endpoint=MODEL2_MODELS_ENDPOINT,
        advertised_model_ids=("x-test-2",),
        alias_context_limits={"context_length": 1_048_576},
    )
    path.write_text(
        json.dumps(check.to_dict(), ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class WrongServedModelProvider:
    model = "x-test-2"
    api_style = "portable"
    endpoint = "https://soclaas-api.comp.nus.edu.sg/v1/chat/completions"
    timeout = 300
    max_response_bytes = 20_000_000
    api_key = "not-a-real-secret"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools, config):
        self.calls += 1
        return {
            "served_model": "wrong-model",
            "message": {"role": "assistant", "content": "{}"},
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "finish_reason": "stop",
        }


class WrongProtocolProvider:
    model = "x-test-2"
    api_style = "portable"
    endpoint = "https://soclaas-api.comp.nus.edu.sg/v1/chat/completions"
    timeout = 300
    max_response_bytes = 20_000_000
    api_key = "not-a-real-secret"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools, config):
        self.calls += 1
        return {
            "served_model": SERVED_MODEL,
            "message": {
                "role": "assistant",
                "content": f"not a valid tool response {self.calls}",
            },
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "finish_reason": "stop",
        }


class RaisingProvider(WrongProtocolProvider):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def complete(self, messages, tools, config):
        self.calls += 1
        raise self.error


class Model2PilotPipelineTests(unittest.TestCase):
    def _prepare(self, folder: Path) -> tuple[Path, Path, str]:
        preflight = folder / "role-smoke.json"
        _write_valid_smoke(preflight)
        models_check = folder / "models-check.json"
        _write_valid_models_check(models_check)
        output = folder / "runs"
        pilot_id = "model2-dev6-pipeline-test"
        manifest = prepare_model2_pilot_pipeline(
            repo_root=ROOT,
            output_root=output,
            pilot_id=pilot_id,
            implementation_commit=FAKE_COMMIT,
            required_served_model=SERVED_MODEL,
            preflight_report_path=preflight,
            preflight_report_sha256=_sha256(preflight),
            models_check_report_path=models_check,
            models_check_report_sha256=_sha256(models_check),
        )
        return output, manifest, pilot_id

    def test_prepare_is_offline_and_creates_independent_child_roots(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output, manifest_path, pilot_id = self._prepare(Path(temporary))
            self.assertEqual(manifest_path.name, PILOT_MANIFEST_NAME)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["deployment"]["requested_model_alias"], "x-test-2")
            self.assertEqual(
                manifest["deployment"]["required_served_model"], SERVED_MODEL
            )
            self.assertEqual(manifest["planned_retrieval_episodes"], 36)
            self.assertEqual(manifest["planned_answer_records"], 42)
            self.assertEqual(manifest["deployment"]["context_limit"], 1_048_576)
            self.assertEqual(
                manifest["deployment"]["endpoint"],
                "https://soclaas-api.comp.nus.edu.sg/v1/chat/completions",
            )
            launcher = output / pilot_id / "run-all.zsh"
            self.assertTrue(launcher.is_file())
            self.assertEqual(launcher.stat().st_mode & 0o777, 0o700)
            launcher_text = launcher.read_text(encoding="utf-8")
            self.assertIn("/usr/bin/security find-generic-password", launcher_text)
            self.assertIn("unset FSMEM_API_KEY", launcher_text)
            self.assertIn("run-all", launcher_text)
            self.assertNotIn("not-a-real-secret", launcher_text)
            self.assertEqual(manifest["launcher"]["credential_source"], "macos-keychain-only")
            status = write_model2_pilot_status(
                repo_root=ROOT, output_root=output, pilot_id=pilot_id
            )
            self.assertEqual(status["retrieval"]["completed"], 0)
            self.assertEqual(status["answers"]["completed"], 0)
            self.assertFalse(
                (output / pilot_id / "children/retrieval" / f"{pilot_id}-retrieval" / "summary.json").exists()
            )
            self.assertFalse(
                (output / pilot_id / "children/answers" / f"{pilot_id}-answers" / "evaluation.json").exists()
            )

    def test_retrieval_fails_closed_on_first_wrong_served_model(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output, _, pilot_id = self._prepare(Path(temporary))
            provider = WrongServedModelProvider()
            with self.assertRaises(ModelIdentityError):
                run_model2_pilot_retrieval(
                    repo_root=ROOT,
                    output_root=output,
                    pilot_id=pilot_id,
                    provider=provider,
                )
            self.assertEqual(provider.calls, 1)
            marker = output / pilot_id / PILOT_IDENTITY_DRIFT_NAME
            self.assertTrue(marker.is_file())
            marker_value = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(marker_value["observed_served_model"], "wrong-model")
            self.assertEqual(
                write_model2_pilot_status(
                    repo_root=ROOT, output_root=output, pilot_id=pilot_id
                )["status"],
                "halted-model-identity-drift",
            )
            with self.assertRaises(ModelIdentityError):
                run_model2_pilot_retrieval(
                    repo_root=ROOT,
                    output_root=output,
                    pilot_id=pilot_id,
                    provider=provider,
                )
            self.assertEqual(provider.calls, 1)
            self.assertFalse(
                (output / pilot_id / "children/retrieval" / f"{pilot_id}-retrieval" / "summary.json").exists()
            )

    def test_retrieval_allows_only_one_explicit_same_protocol_retry(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output, _, pilot_id = self._prepare(Path(temporary))
            provider = WrongProtocolProvider()
            first = run_model2_pilot_retrieval(
                repo_root=ROOT,
                output_root=output,
                pilot_id=pilot_id,
                provider=provider,
            )
            self.assertEqual(first["status"], "failed")
            policy = authorize_model2_pilot_retrieval_retry(
                repo_root=ROOT, output_root=output, pilot_id=pilot_id
            )
            self.assertTrue(policy.is_file())
            second = run_model2_pilot_retrieval(
                repo_root=ROOT,
                output_root=output,
                pilot_id=pilot_id,
                provider=provider,
            )
            self.assertEqual(second["status"], "failed")
            self.assertTrue(second["retry_exhausted"])
            status = write_model2_pilot_status(
                repo_root=ROOT, output_root=output, pilot_id=pilot_id
            )
            self.assertEqual(status["retrieval"]["failure_attempts"], 2)
            self.assertEqual(
                status["retrieval"]["wrapper_retry_failure_attempts"], 1
            )
            with self.assertRaises(EvidenceValidationError):
                authorize_model2_pilot_retrieval_retry(
                    repo_root=ROOT, output_root=output, pilot_id=pilot_id
                )
            self.assertFalse(
                (output / pilot_id / PILOT_IDENTITY_DRIFT_NAME).exists()
            )

    def test_answer_active_failure_requires_authorization_before_provider_call(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            pilot_root = root / "pilot"
            retrieval_output = root / "retrieval"
            answer_output = root / "answers"
            retrieval_run_id = "retrieval"
            answer_run_id = "answers"
            (retrieval_output / retrieval_run_id).mkdir(parents=True)
            (answer_output / answer_run_id).mkdir(parents=True)
            pilot_root.mkdir()
            (retrieval_output / retrieval_run_id / "summary.json").write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "semantic_gold_loaded": False,
                        "served_models": [SERVED_MODEL],
                    }
                ),
                encoding="utf-8",
            )
            (answer_output / answer_run_id / "pilot-manifest.json").write_text(
                json.dumps({"pilot_manifest_id": "pilot-manifest-test"}),
                encoding="utf-8",
            )
            # Use a real RunKey-compatible object in the frozen execution order.
            from fs_memory_lab.run_records import RunKey

            run_key = RunKey("E1", "dev-q")
            failure = SimpleNamespace(
                failure_id="run-failure-" + "a" * 64,
                stage="provider",
                attempt=1,
            )

            class FakeStore:
                run_root = answer_output / answer_run_id
                plan = SimpleNamespace(
                    run_id=answer_run_id,
                    plan_id="plan-" + "b" * 64,
                    execution_order=(run_key,),
                )

                @staticmethod
                def load_completed(candidate):
                    return None

                @staticmethod
                def failure_attempts(candidate):
                    return (failure,) if candidate == run_key else ()

            manifest = {
                "pilot_id": "pilot",
                "pilot_pipeline_manifest_id": "model2-pilot-pipeline-test",
                "deployment": {
                    "requested_model_alias": "x-test-2",
                    "required_served_model": SERVED_MODEL,
                },
            }
            paths = {
                "root": pilot_root,
                "retrieval_output": retrieval_output,
                "retrieval_run_id": retrieval_run_id,
                "answer_output": answer_output,
                "answer_run_id": answer_run_id,
            }
            provider = WrongProtocolProvider()
            with (
                mock.patch(
                    "fs_memory_lab.model2_pilot._open_pipeline",
                    return_value=(pilot_root, manifest, paths),
                ),
                mock.patch("fs_memory_lab.model2_pilot.legacy_pilot.prepare_pilot"),
                mock.patch(
                    "fs_memory_lab.model2_pilot.verify_run_store",
                    return_value=(FakeStore(), {"completed": 0, "pending": 1}),
                ),
                mock.patch(
                    "fs_memory_lab.model2_pilot.legacy_pilot.run_pilot"
                ) as run_pilot,
            ):
                with self.assertRaisesRegex(
                    EvidenceValidationError, "Unsafe or missing JSON artifact"
                ):
                    run_model2_pilot_answers(
                        repo_root=ROOT,
                        output_root=root,
                        pilot_id="pilot",
                        provider=provider,
                    )
            run_pilot.assert_not_called()
            self.assertEqual(provider.calls, 0)

    def test_run_all_coordinates_one_bounded_retry_per_phase(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            pilot_root = Path(temporary) / "pilot"
            pilot_root.mkdir()
            provider = WrongProtocolProvider()
            with (
                mock.patch(
                    "fs_memory_lab.model2_pilot._open_pipeline",
                    return_value=(pilot_root, {}, {}),
                ),
                mock.patch(
                    "fs_memory_lab.model2_pilot.run_model2_pilot_retrieval",
                    side_effect=[
                        {"status": "failed", "condition_id": "E1", "question_id": "q"},
                        {"status": "completed"},
                    ],
                ) as retrieval,
                mock.patch(
                    "fs_memory_lab.model2_pilot.authorize_model2_pilot_retrieval_retry"
                ) as authorize_retrieval,
                mock.patch(
                    "fs_memory_lab.model2_pilot.run_model2_pilot_answers",
                    side_effect=[
                        {"status": "failed", "condition_id": "E1", "question_id": "q"},
                        {"status": "passed", "model2_pilot_audit_id": "audit-test"},
                    ],
                ) as answers,
                mock.patch(
                    "fs_memory_lab.model2_pilot.authorize_model2_pilot_answer_retry"
                ) as authorize_answer,
            ):
                result = run_model2_pilot_all(
                    repo_root=ROOT,
                    output_root=Path(temporary),
                    pilot_id="pilot",
                    provider=provider,
                )
            self.assertEqual(result["model2_pilot_audit_id"], "audit-test")
            self.assertEqual(retrieval.call_count, 2)
            self.assertEqual(answers.call_count, 2)
            authorize_retrieval.assert_called_once()
            authorize_answer.assert_called_once()

    def test_retry_classification_rejects_dns_and_http400_but_accepts_transient(self):
        base = {
            "condition_id": "E1",
            "question_id": "dev-q",
            "artifact_path": "/synthetic",
            "failure_id": "failure-" + "a" * 64,
            "failure_kind": "provider",
        }
        transient_artifact = SimpleNamespace(
            failure_id=base["failure_id"],
            metrics={
                "provider_request_attempts": 3,
                "model_calls": 0,
                "total_tokens": 0,
            },
            errors=(
                {"message": "Provider request exhausted the frozen retry policy"},
            ),
            search_actions=(),
        )
        dns_artifact = SimpleNamespace(
            failure_id=base["failure_id"],
            metrics={
                "provider_request_attempts": 1,
                "model_calls": 0,
                "total_tokens": 0,
            },
            errors=(
                {"message": "Provider request failed before returning a complete response"},
            ),
            search_actions=(),
        )
        transient_companion = {
            "retrieval_failure_evidence_id": "evidence-transient",
            "provider_failure_evidence": [
                {
                    "classification": "transient-provider-error",
                    "kind": "timeout",
                    "http_status": None,
                    "retryable": True,
                }
                for _ in range(3)
            ],
            "failed_attempt_usage": {
                "request_count": 3,
                "response_count": 0,
                "usage_unavailable_count": 3,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }
        dns_companion = {
            "retrieval_failure_evidence_id": "evidence-dns",
            "provider_failure_evidence": [
                {
                    "classification": "non-transient-provider-error",
                    "error_type": "RuntimeError",
                    "retryable": False,
                }
            ],
            "failed_attempt_usage": {
                "request_count": 1,
                "response_count": 0,
                "usage_unavailable_count": 1,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }
        with mock.patch(
            "fs_memory_lab.model2_pilot.dev._verify_failure",
            return_value=transient_artifact,
        ):
            self.assertTrue(
                _retrieval_retry_evidence(base, transient_companion)["eligible"]
            )
        with mock.patch(
            "fs_memory_lab.model2_pilot.dev._verify_failure",
            return_value=dns_artifact,
        ):
            self.assertFalse(
                _retrieval_retry_evidence(base, dns_companion)["eligible"]
            )

        r2 = {**base, "condition_id": "E2", "failure_kind": "provider_request"}
        for row, expected in (
            ({"event": "provider_retry", "kind": "timeout", "http_status": None}, True),
            ({"event": "provider_retry", "kind": "http", "http_status": 503}, True),
            ({"event": "provider_retry", "kind": "http", "http_status": 400}, False),
        ):
            artifact = SimpleNamespace(
                failure_id=base["failure_id"],
                metrics={
                    "provider_request_attempts": 2,
                    "model_calls": 1,
                    "total_tokens": 2,
                },
                errors=(),
                search_actions=(row,),
            )
            provider_row = (
                {
                    "classification": "transient-provider-error",
                    "kind": row["kind"],
                    "http_status": row["http_status"],
                    "retryable": True,
                }
                if expected
                else {
                    "classification": "non-transient-provider-error",
                    "error_type": "RuntimeError",
                    "retryable": False,
                }
            )
            companion = {
                "retrieval_failure_evidence_id": "evidence-r2",
                "provider_failure_evidence": [provider_row],
                "failed_attempt_usage": {
                    "request_count": 2,
                    "response_count": 1,
                    "usage_unavailable_count": 1,
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
            with mock.patch(
                "fs_memory_lab.model2_pilot.dev._verify_failure",
                return_value=artifact,
            ):
                self.assertEqual(
                    _retrieval_retry_evidence(r2, companion)["eligible"], expected
                )

        mixed_artifact = SimpleNamespace(
            failure_id=base["failure_id"],
            metrics={
                "provider_request_attempts": 3,
                "model_calls": 1,
                "total_tokens": 2,
            },
            errors=(),
            search_actions=(
                {
                    "event": "provider_retry",
                    "kind": "timeout",
                    "http_status": None,
                },
            ),
        )
        mixed_companion = {
            "retrieval_failure_evidence_id": "evidence-mixed",
            "provider_failure_evidence": [
                {
                    "classification": "transient-provider-error",
                    "kind": "timeout",
                    "http_status": None,
                    "retryable": True,
                },
                {
                    "classification": "non-transient-provider-error",
                    "error_type": "RuntimeError",
                    "retryable": False,
                },
            ],
            "failed_attempt_usage": {
                "request_count": 3,
                "response_count": 1,
                "usage_unavailable_count": 2,
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        }
        with mock.patch(
            "fs_memory_lab.model2_pilot.dev._verify_failure",
            return_value=mixed_artifact,
        ):
            self.assertFalse(
                _retrieval_retry_evidence(r2, mixed_companion)["eligible"]
            )

    def test_answer_retry_evidence_accepts_only_transient_or_schema_failures(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            pilot_root = Path(temporary)
            run_key = __import__(
                "fs_memory_lab.run_records", fromlist=["RunKey"]
            ).RunKey("E1", "dev-q")
            manifest = {
                "pilot_pipeline_manifest_id": "pipeline-test",
                "deployment": {"required_served_model": SERVED_MODEL},
            }

            def store(stage: str, suffix: str):
                failure = SimpleNamespace(
                    failure_id="run-failure-" + suffix * 64,
                    stage=stage,
                    attempt=1,
                    key=run_key,
                )

                class FakeStore:
                    plan = SimpleNamespace(
                        plan_id="plan-" + "b" * 64, run_id="answers"
                    )

                    @staticmethod
                    def failure_attempts(key):
                        return (failure,)

                return FakeStore()

            cases = (
                (TransientProviderError("timeout"), "provider", True),
                (RuntimeError("Cannot connect to API endpoint"), "provider", False),
                (RuntimeError("HTTP 400"), "provider", False),
            )
            for index, (error, stage, eligible) in enumerate(cases, start=1):
                gate = _PilotProvider(
                    RaisingProvider(error),
                    requested_model_alias="x-test-2",
                    required_served_model=SERVED_MODEL,
                )
                with self.assertRaises(type(error)):
                    gate.complete([], [], SimpleNamespace(model="x-test-2"))
                evidence = _publish_answer_failure_evidence(
                    pilot_root=pilot_root,
                    manifest=manifest,
                    store=store(stage, str(index)),
                    key=run_key,
                    provider=gate,
                    failure_cursor=0,
                    usage_cursor=0,
                    successful_usage_during_invocation={
                        "request_count": 0,
                        "response_count": 0,
                        "usage_unavailable_count": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                )
                self.assertEqual(evidence["eligible"], eligible)
                if isinstance(error, TransientProviderError):
                    self.assertEqual(
                        evidence["failed_attempt_usage"]["request_count"], 1
                    )
                    self.assertEqual(
                        evidence["failed_attempt_usage"][
                            "usage_unavailable_count"
                        ],
                        1,
                    )
                    self.assertEqual(
                        evidence["failed_attempt_usage"]["total_tokens"], 0
                    )
            schema_gate = _PilotProvider(
                WrongProtocolProvider(),
                requested_model_alias="x-test-2",
                required_served_model=SERVED_MODEL,
            )
            schema_gate.complete(
                [], [], SimpleNamespace(model="x-test-2")
            )
            schema_gate.complete(
                [], [], SimpleNamespace(model="x-test-2")
            )
            schema = _publish_answer_failure_evidence(
                pilot_root=pilot_root,
                manifest=manifest,
                store=store("answer_schema", "4"),
                key=run_key,
                provider=schema_gate,
                failure_cursor=0,
                usage_cursor=0,
                successful_usage_during_invocation={
                    "request_count": 1,
                    "response_count": 1,
                    "usage_unavailable_count": 0,
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            )
            self.assertTrue(schema["eligible"])
            self.assertEqual(schema["failed_attempt_usage"]["total_tokens"], 2)
            self.assertEqual(schema["invocation_usage"]["total_tokens"], 4)

    def test_parent_core_verification_drift_fails_closed(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output, _, pilot_id = self._prepare(Path(temporary))
            with mock.patch(
                "fs_memory_lab.model2_pilot.verify_formal_manifest",
                return_value={"formal_manifest_id": "formal-manifest-drifted"},
            ):
                with self.assertRaisesRegex(
                    EvidenceValidationError, "parent core verification drifted"
                ):
                    write_model2_pilot_status(
                        repo_root=ROOT,
                        output_root=output,
                        pilot_id=pilot_id,
                    )

    def test_self_consistent_manifest_tamper_fails_repository_recompute(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output, manifest_path, pilot_id = self._prepare(Path(temporary))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["gold_boundary"] = "tampered"
            body = {
                key: value
                for key, value in manifest.items()
                if key != "pilot_pipeline_manifest_id"
            }
            manifest["pilot_pipeline_manifest_id"] = (
                "model2-pilot-pipeline-"
                + sha256_bytes(canonical_json_bytes(body))
            )
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                EvidenceValidationError, "manifest body differs"
            ):
                write_model2_pilot_status(
                    repo_root=ROOT,
                    output_root=output,
                    pilot_id=pilot_id,
                )

    def test_provider_error_is_redacted_before_any_persistable_boundary(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            secret = "clsk_model2PilotSecret_1234567890"
            upstream = RaisingProvider(
                RuntimeError(f"HTTP 400 Bearer {secret}; key={secret}")
            )
            upstream.api_key = secret
            gate = _PilotProvider(
                upstream,
                requested_model_alias="x-test-2",
                required_served_model=SERVED_MODEL,
            )
            with self.assertRaises(RuntimeError) as raised:
                gate.complete([], [], SimpleNamespace(model="x-test-2"))
            self.assertNotIn(secret, str(raised.exception))
            self.assertIn("REDACTED_KEY", str(raised.exception))

            run_key = __import__(
                "fs_memory_lab.run_records", fromlist=["RunKey"]
            ).RunKey("E1", "dev-q")
            failure = SimpleNamespace(
                failure_id="run-failure-" + "f" * 64,
                stage="provider",
                attempt=1,
                key=run_key,
            )

            class FakeStore:
                plan = SimpleNamespace(
                    plan_id="plan-" + "b" * 64, run_id="answers"
                )

                @staticmethod
                def failure_attempts(key):
                    return (failure,)

            # These mirror all three durable boundaries used by the wrapper:
            # legacy failure message, message-free event, and companion proof.
            (root / "failure.json").write_text(
                json.dumps({"message": str(raised.exception)}), encoding="utf-8"
            )
            (root / "events.jsonl").write_text(
                json.dumps({"event": "answer_failed", "error_type": "RuntimeError"})
                + "\n",
                encoding="utf-8",
            )
            _publish_answer_failure_evidence(
                pilot_root=root,
                manifest={
                    "pilot_pipeline_manifest_id": "pipeline-test",
                    "deployment": {"required_served_model": SERVED_MODEL},
                },
                store=FakeStore(),
                key=run_key,
                provider=gate,
                failure_cursor=0,
                usage_cursor=0,
                successful_usage_during_invocation={
                    "request_count": 0,
                    "response_count": 0,
                    "usage_unavailable_count": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            )
            persisted = b"".join(
                path.read_bytes() for path in root.rglob("*") if path.is_file()
            )
            self.assertNotIn(secret.encode("utf-8"), persisted)
            self.assertIn(b"REDACTED_KEY", persisted)

    def _synthetic_finalize(
        self,
        folder: Path,
        *,
        break_budget: bool,
        retrieval_usage_unavailable: int = 0,
        failed_retrieval_tokens: int | None = None,
    ):
        pilot_root = folder / "pilot"
        retrieval_output = folder / "retrieval"
        answer_output = folder / "answers"
        retrieval_run_id = "retrieval"
        answer_run_id = "answers"
        pilot_root.mkdir(parents=True)
        (retrieval_output / retrieval_run_id).mkdir(parents=True)
        answer_run_root = answer_output / answer_run_id
        answer_run_root.mkdir(parents=True)
        (answer_run_root / "evaluation.json").write_text("{}\n", encoding="utf-8")

        question_ids = tuple(f"dev-q-{index}" for index in range(1, 7))
        primary_keys = tuple(
            RunKey(condition, question_id)
            for question_id in question_ids
            for condition in ("E1", "E2", "E3", "E4", "E5", "E6")
        )
        all_keys = tuple(
            RunKey(condition, question_id)
            for question_id in question_ids
            for condition in ("E1", "E2", "E3", "E4", "E5", "E6", "E7")
        )
        evidence_item = SimpleNamespace(evidence_id="ev-" + "a" * 64)

        class FakeBundle:
            def __init__(self):
                self.model = {
                    "requested_model": "x-test-2",
                    "served_models": [SERVED_MODEL],
                }
                self.integrity = {"verified": True, "store_unchanged": True}
                self.metrics = {"total_tokens": 10, "provider_rounds": 1}
                self.stop = SimpleNamespace(hit_cap=False)
                self.budget = SimpleNamespace(
                    unit="characters", limit=16_000, truncated=False, skipped_items=0
                )
                self.evidence_items = (evidence_item,)

        completed = {key: FakeBundle() for key in primary_keys}
        if break_budget:
            completed[primary_keys[0]].budget.truncated = True

        class FakeFusion:
            def __init__(self):
                self.retrieval_metrics = {
                    "search_calls": 0,
                    "reused_upstream_retrieval": True,
                }
                self.budget = SimpleNamespace(
                    per_source_limit=16_000, total_limit=32_000
                )
                self.evidence_items = (evidence_item,)

        records = {}
        for key in all_keys:
            if key.condition_id == "E7":
                bundle = FakeFusion()
                retrieval_metrics = {
                    "search_calls": 0,
                    "reused_upstream_retrieval": True,
                    "total_tokens": 20,
                }
                deployment_total = 25
            else:
                bundle = completed[key]
                retrieval_metrics = {"total_tokens": 10}
                deployment_total = 15
            records[key] = SimpleNamespace(
                key=key,
                evidence_bundle=bundle,
                answer_result=SimpleNamespace(
                    requested_model="x-test-2",
                    served_models=(SERVED_MODEL,),
                    citations=(evidence_item.evidence_id,),
                    format_repairs=0,
                ),
                retrieval_metrics=retrieval_metrics,
                answer_metrics={
                    "provider_request_attempts": 1,
                    "model_calls": 1,
                    "prompt_tokens": 3,
                    "completion_tokens": 2,
                    "total_tokens": 5,
                },
                deployment_metrics={"total_tokens": deployment_total},
            )

        class FakeStore:
            plan = SimpleNamespace(
                execution_order=all_keys,
                question_ids=question_ids,
                plan_id="plan-" + "a" * 64,
                run_id=answer_run_id,
            )

            @staticmethod
            def load_completed(key):
                return records.get(key)

            @staticmethod
            def failure_attempts(key):
                return ()

        event_rows = [
            {
                "event": "answer_verified",
                "condition_id": key.condition_id,
                "question_id": key.question_id,
            }
            for key in all_keys
        ] + [{"event": "pilot_finalized"}]
        (answer_run_root / "events.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in event_rows),
            encoding="utf-8",
        )
        manifest = {
            "pilot_id": "pilot",
            "pilot_pipeline_manifest_id": "model2-pilot-pipeline-test",
            "deployment": {
                "requested_model_alias": "x-test-2",
                "required_served_model": SERVED_MODEL,
                "endpoint": "https://soclaas-api.comp.nus.edu.sg/v1/chat/completions",
                "api_style": "portable",
                "request_timeout_seconds": 300,
                "max_response_bytes": 20_000_000,
                "context_limit": 1_048_576,
                "concurrency": 1,
            },
            "caps": {
                "r1_round_cap_by_condition": {"E1": 20, "E3": 20, "E5": 40},
                "r2_action_cap": 4,
                "r3_action_cap": 4,
            },
            "evidence_budget": {
                "unit": "characters",
                "single_source_limit": 16_000,
                "whole_items_only": True,
                "e7_per_source_limit": 16_000,
                "e7_total_limit": 32_000,
            },
            "judge_policy": "forbidden",
        }
        paths = {
            "root": pilot_root,
            "retrieval_output": retrieval_output,
            "retrieval_run_id": retrieval_run_id,
            "answer_output": answer_output,
            "answer_run_id": answer_run_id,
        }
        retrieval_plan = SimpleNamespace(execution_order=primary_keys)
        retrieval_failures = (
            [
                {
                    "failure_id": "retrieval-failure-" + "f" * 64,
                    "condition_id": primary_keys[0].condition_id,
                    "question_id": primary_keys[0].question_id,
                    "total_tokens": failed_retrieval_tokens,
                }
            ]
            if failed_retrieval_tokens is not None
            else []
        )
        retry_audit = {
            "retrieval_authorizations": len(retrieval_failures),
            "answer_authorizations": 0,
            "retrieval_failed_attempt_tokens": failed_retrieval_tokens or 0,
            "retrieval_failed_usage_unavailable_calls": (
                retrieval_usage_unavailable
            ),
            "answer_failed_attempt_prompt_tokens": 0,
            "answer_failed_attempt_completion_tokens": 0,
            "answer_failed_attempt_total_tokens": 0,
            "answer_failed_usage_unavailable_calls": 0,
        }
        with (
            mock.patch(
                "fs_memory_lab.model2_pilot._open_pipeline",
                return_value=(pilot_root, manifest, paths),
            ),
            mock.patch(
                "fs_memory_lab.model2_pilot.dev._scan",
                return_value=(
                    completed,
                    retrieval_failures,
                    retrieval_plan,
                    {},
                ),
            ),
            mock.patch(
                "fs_memory_lab.model2_pilot.verify_run_store",
                return_value=(
                    FakeStore(),
                    {"completed": 42, "pending": 0, "failed_attempts": 0},
                ),
            ),
            mock.patch(
                "fs_memory_lab.model2_pilot.legacy_pilot.load_retrieval_source",
                return_value=object(),
            ),
            mock.patch(
                "fs_memory_lab.model2_pilot.legacy_pilot._r2_first_rank_backend_invariant",
                return_value=True,
            ),
            mock.patch(
                "fs_memory_lab.model2_pilot._trace_files_complete",
                return_value=True,
            ),
            mock.patch(
                "fs_memory_lab.model2_pilot.write_model2_pilot_status",
                return_value={},
            ),
            mock.patch(
                "fs_memory_lab.model2_pilot._audit_retry_authorizations",
                return_value=retry_audit,
            ),
            mock.patch("fs_memory_lab.model2_pilot.FusionEvidenceBundle", FakeFusion),
        ):
            return finalize_model2_pilot(
                repo_root=ROOT, output_root=folder, pilot_id="pilot"
            )

    def test_finalize_complete_42_passes_and_one_invariant_fails(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            audit = self._synthetic_finalize(root / "good", break_budget=False)
            self.assertEqual(audit["status"], "passed")
            self.assertTrue(
                (root / "good" / "pilot" / PILOT_FINAL_AUDIT_NAME).is_file()
            )
            self.assertTrue(
                (root / "good" / "pilot" / PILOT_PASSED_MARKER_NAME).is_file()
            )
            self.assertTrue(audit["checks"]["served_model_exact"])
            self.assertTrue(audit["checks"]["e7_no_retrieval"])
            self.assertTrue(audit["checks"]["gold_loaded_only_after_42"])
            self.assertTrue(audit["checks"]["judge_not_called"])
            self.assertEqual(
                audit["metrics"]["token_cost_accounting"]["known_total_model_tokens"],
                570,
            )
            self.assertEqual(
                audit["metrics"]["token_cost_accounting"]["completeness"],
                "complete",
            )

        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            audit = self._synthetic_finalize(root / "bad", break_budget=True)
            self.assertEqual(audit["status"], "failed")
            self.assertFalse(audit["checks"]["whole_item_budget_only"])
            self.assertFalse(
                (root / "bad" / "pilot" / PILOT_PASSED_MARKER_NAME).exists()
            )

        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            audit = self._synthetic_finalize(
                root / "unknown-cost",
                break_budget=False,
                retrieval_usage_unavailable=1,
            )
            self.assertEqual(audit["status"], "failed")
            self.assertFalse(audit["checks"]["token_safety_fuse_not_hit"])
            self.assertEqual(
                audit["metrics"]["token_cost_accounting"]["completeness"],
                "partial-known-token-lower-bound",
            )
            self.assertFalse(
                (
                    root
                    / "unknown-cost"
                    / "pilot"
                    / PILOT_PASSED_MARKER_NAME
                ).exists()
            )

        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            audit = self._synthetic_finalize(
                root / "failed-attempt-fuse",
                break_budget=False,
                failed_retrieval_tokens=1_000_000,
            )
            self.assertEqual(audit["status"], "failed")
            self.assertFalse(audit["checks"]["token_safety_fuse_not_hit"])
            self.assertEqual(
                audit["metrics"]["max_failed_retrieval_episode_total_tokens"],
                1_000_000,
            )


if __name__ == "__main__":
    unittest.main()
