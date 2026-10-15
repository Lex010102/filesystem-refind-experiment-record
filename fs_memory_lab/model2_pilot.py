"""Independent executable Model 2 dev-6 retrieval/answer pilot pipeline.

The controller reuses the reviewed R1/R2/R3 and shared Answerer implementations
without changing the Qwen formal runners or results.  It binds a sanitized
preflight artifact, wraps *every* model call in the fail-closed Model 2 identity
decorator, keeps retrieval and answer checkpoints in distinct child roots, and
does not load semantic gold until all 42 answer records have verified.

Preparing or reading status is offline.  Only ``run_retrieval`` and
``run_answers`` can call the provider supplied by the caller.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shlex
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from . import dev_retrieval as dev
from . import pilot as legacy_pilot
from .agent import ChatProvider, TransientProviderError
from .evidence import EvidenceBundle, EvidenceValidationError, canonical_json_bytes, sha256_bytes
from .formal_v1 import FORMAL_MANIFEST_RELATIVE_PATH, verify_formal_manifest
from .formal_v2_model2 import (
    MODEL2_API_STYLE,
    MODEL2_CHAT_ENDPOINT,
    MODEL2_CONCURRENCY,
    MODEL2_MAX_RESPONSE_BYTES,
    MODEL2_REQUEST_TIMEOUT_SECONDS,
    ModelIdentityError,
    ModelIdentityProvider,
)
from .fusion import FusionEvidenceBundle
from .model2_preflight import MODEL2_CONTEXT_LIMIT, verify_sanitized_preflight_artifact
from .model2_validation import (
    BUDGET_SKIP_EPISODE_FRACTION_LIMIT,
    MODEL2_REQUESTED_MODEL_ALIAS,
    PILOT_QUESTION_COUNT,
    PILOT_RECORD_COUNT,
    R1_ROUND_CAP_BY_CONDITION,
    R2_ACTION_CAP,
    R3_ACTION_CAP,
    SYSTEM_FAILURE_RATE_LIMIT,
    TOKEN_SAFETY_FUSE_LIMIT,
)
from .r1_inputs import load_question_inputs, load_r1_store
from .r1_runner import execute_r1_question
from .r2_inputs import build_r2_raw_corpus
from .r2_runner import execute_r2_question
from .r3_inputs import load_r3_corpus
from .r3_runner import execute_r3_question
from .run_records import CONDITION_IDS, RunKey, verify_run_store


MODEL2_PILOT_PIPELINE_PROTOCOL_VERSION = "formal-v2-model2-dev6-pipeline-v1"
MODEL2_PILOT_RECOVERY_PROTOCOL_VERSION = "formal-v2-model2-dev6-recovery-v1"
PILOT_MANIFEST_NAME = "pilot-pipeline-manifest.json"
PILOT_STATUS_NAME = "status.json"
PILOT_FINAL_AUDIT_NAME = "model2-final-audit.json"
PILOT_PASSED_MARKER_NAME = "MODEL2-PILOT-42.PASSED"
PILOT_IDENTITY_DRIFT_NAME = "MODEL-IDENTITY-DRIFT.json"
PILOT_LAUNCHER_NAME = "run-all.zsh"
RETRIEVAL_SUMMARY_NAME = "summary.json"
RUNNER_RELATIVE_PATH = "fs_memory_lab/model2_pilot.py"
CLI_RELATIVE_PATH = "fs_memory_lab/model2_pilot_cli.py"
DIRECT_DEPENDENCY_PATHS = (
    "fs_memory_lab/formal_v2_model2.py",
    "fs_memory_lab/model2_preflight.py",
    "fs_memory_lab/model2_validation.py",
)
RETRIEVAL_PROTOCOL_RETRYABLE_FAILURE_KINDS = frozenset(
    {"provider_response", "compaction_response"}
)
ANSWER_RETRYABLE_FAILURE_STAGES = frozenset({"answer_schema", "provider"})

_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_API_KEY_LIKE = re.compile(
    r"(?<![A-Za-z0-9])(?:clsk|sk)[_-][A-Za-z0-9_-]{6,}",
    flags=re.IGNORECASE,
)
_BEARER_CREDENTIAL = re.compile(r"\bBearer\s+\S+", flags=re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _file_sha256(path: Path) -> str:
    lexical = Path(path)
    if lexical.is_symlink() or not lexical.is_file():
        raise EvidenceValidationError(f"Unsafe or missing artifact: {lexical}")
    digest = hashlib.sha256()
    with lexical.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    lexical = Path(path)
    if lexical.is_symlink() or not lexical.is_file():
        raise EvidenceValidationError(f"Unsafe or missing JSON artifact: {lexical}")
    try:
        value = json.loads(lexical.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError(f"Invalid JSON artifact: {lexical}") from exc
    if not isinstance(value, dict):
        raise EvidenceValidationError("Model 2 pilot artifact must contain an object")
    return value


def _publish_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value) + b"\n"
    if path.exists() or path.is_symlink():
        if path.is_symlink() or path.read_bytes() != payload:
            raise EvidenceValidationError(f"Existing pilot artifact differs: {path.name}")
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o644)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short Model 2 pilot artifact write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_executable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise EvidenceValidationError(f"Existing launcher differs: {path.name}")
        if (path.stat().st_mode & 0o777) != 0o700:
            raise EvidenceValidationError("Existing Model 2 launcher mode differs")
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o700)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short Model 2 launcher write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _append_event(path: Path, value: Mapping[str, Any]) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o644)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _redact_provider_error(error: BaseException, provider: ChatProvider) -> str:
    """Return a bounded provider error message that is safe to persist.

    The legacy dev-6 Answerer stores ``str(error)``.  Model 2 therefore has to
    remove credentials *before* an exception crosses the provider boundary;
    redacting only the later companion audit would be too late.
    """
    message = " ".join(str(error).split()) or type(error).__name__
    secret = getattr(provider, "api_key", None)
    if isinstance(secret, str) and secret:
        message = message.replace(secret, "[REDACTED_KEY]")
    message = _BEARER_CREDENTIAL.sub("Bearer [REDACTED_KEY]", message)
    message = _API_KEY_LIKE.sub("[REDACTED_KEY]", message)
    return message[:800]


def _safe_observed_model(value: str | None) -> str | None:
    if value is None:
        return None
    message = " ".join(str(value).split())[:256]
    message = _BEARER_CREDENTIAL.sub("Bearer [REDACTED_KEY]", message)
    return _API_KEY_LIKE.sub("[REDACTED_KEY]", message)


@contextmanager
def _pipeline_lock(root: Path) -> Iterator[None]:
    lock_path = root / "run.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise EvidenceValidationError("Another Model 2 pilot process holds run.lock") from exc
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@contextmanager
def _launcher_lock(root: Path) -> Iterator[None]:
    lock_path = root / "launcher.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise EvidenceValidationError(
                "Another Model 2 pilot launcher holds launcher.lock"
            ) from exc
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _pilot_paths(output_root: Path, pilot_id: str) -> dict[str, Path | str]:
    root = Path(output_root).resolve() / pilot_id
    return {
        "root": root,
        "retrieval_output": root / "children/retrieval",
        "retrieval_run_id": f"{pilot_id}-retrieval",
        "answer_output": root / "children/answers",
        "answer_run_id": f"{pilot_id}-answers",
    }


def _keychain_launcher_payload(
    *, repo_root: Path, output_root: Path, pilot_id: str
) -> bytes:
    command = " ".join(
        shlex.quote(value)
        for value in (
            "python3",
            "-m",
            "fs_memory_lab.model2_pilot_cli",
            "--repo-root",
            str(repo_root),
            "--output-root",
            str(output_root),
            "--pilot-id",
            pilot_id,
            "run-all",
        )
    )
    return f"""#!/bin/zsh
set -euo pipefail
umask 077

repo_root={shlex.quote(str(repo_root))}
keychain_service='filesystem-refind-experiment-record.soclaas-api-key'
keychain_account="${{USER:-wangwenqi}}"

# Deliberately ignore any inherited credential: this launcher is Keychain-only.
unset FSMEM_API_KEY
if ! fsmem_model2_key="$(
  /usr/bin/security find-generic-password \\
    -a "$keychain_account" \\
    -s "$keychain_service" \\
    -w 2>/dev/null
)"; then
  printf '%s\n' 'No non-interactive SoCLaaS credential is available in Keychain.' >&2
  exit 43
fi
export FSMEM_API_KEY="$fsmem_model2_key"
export FSMEM_API_BASE_URL='https://soclaas-api.comp.nus.edu.sg/v1'
export FSMEM_MODEL='x-test-2'
export FSMEM_API_STYLE='portable'
trap 'unset FSMEM_API_KEY fsmem_model2_key' EXIT HUP INT TERM

cd "$repo_root"
{command}
""".encode("utf-8")


def _write_keychain_launcher(
    *, repo_root: Path, output_root: Path, pilot_id: str, pilot_root: Path
) -> Path:
    """Publish a secret-free launcher that only reads the existing Keychain item."""
    script = _keychain_launcher_payload(
        repo_root=repo_root, output_root=output_root, pilot_id=pilot_id
    )
    path = pilot_root / PILOT_LAUNCHER_NAME
    _publish_executable(path, script)
    return path


def _manifest_body(
    *,
    repo_root: Path,
    output_root: Path,
    pilot_id: str,
    implementation_commit: str,
    required_served_model: str,
    preflight_report_path: Path,
    preflight_report_sha256: str,
    models_check_report_path: Path,
    models_check_report_sha256: str,
) -> dict[str, Any]:
    formal_verification = verify_formal_manifest(repo_root)
    questions = load_question_inputs(repo_root, "dev-6")
    if len(questions) != PILOT_QUESTION_COUNT:
        raise EvidenceValidationError("Model 2 pilot requires exactly six dev questions")
    if _file_sha256(preflight_report_path) != preflight_report_sha256:
        raise EvidenceValidationError("Model 2 pilot preflight hash differs")
    preflight = verify_sanitized_preflight_artifact(preflight_report_path)
    if (
        preflight.get("artifact_type") != "model2-role-smoke"
        or preflight.get("requested_alias") != MODEL2_REQUESTED_MODEL_ALIAS
        or preflight.get("served_model") != required_served_model
        or preflight.get("role_smokes_passed") != 5
    ):
        raise EvidenceValidationError("Model 2 pilot requires a passing role-smoke report")
    if _file_sha256(models_check_report_path) != models_check_report_sha256:
        raise EvidenceValidationError("Model 2 pilot models-check hash differs")
    models_check = verify_sanitized_preflight_artifact(models_check_report_path)
    if (
        models_check.get("artifact_type") != "model2-models-check"
        or models_check.get("requested_alias") != MODEL2_REQUESTED_MODEL_ALIAS
        or models_check.get("alias_present") is not True
        or models_check.get("context_limit") != MODEL2_CONTEXT_LIMIT
    ):
        raise EvidenceValidationError("Model 2 pilot requires a passing models-check report")
    paths = _pilot_paths(Path("."), pilot_id)
    launcher_payload = _keychain_launcher_payload(
        repo_root=repo_root, output_root=output_root, pilot_id=pilot_id
    )
    return {
        "schema_version": 1,
        "protocol_version": MODEL2_PILOT_PIPELINE_PROTOCOL_VERSION,
        "status": "prepared",
        "pilot_id": pilot_id,
        "implementation_git_commit": implementation_commit,
        "runner_relative_path": RUNNER_RELATIVE_PATH,
        "runner_sha256": _file_sha256(repo_root / RUNNER_RELATIVE_PATH),
        "cli_relative_path": CLI_RELATIVE_PATH,
        "cli_sha256": _file_sha256(repo_root / CLI_RELATIVE_PATH),
        "direct_dependency_sha256": {
            path: _file_sha256(repo_root / path)
            for path in DIRECT_DEPENDENCY_PATHS
        },
        "parent_formal_manifest_relative_path": FORMAL_MANIFEST_RELATIVE_PATH,
        "parent_formal_manifest_id": formal_verification["formal_manifest_id"],
        "parent_formal_manifest_sha256": _file_sha256(
            repo_root / FORMAL_MANIFEST_RELATIVE_PATH
        ),
        "deployment": {
            "requested_model_alias": MODEL2_REQUESTED_MODEL_ALIAS,
            "required_served_model": required_served_model,
            "endpoint": MODEL2_CHAT_ENDPOINT,
            "api_style": MODEL2_API_STYLE,
            "request_timeout_seconds": MODEL2_REQUEST_TIMEOUT_SECONDS,
            "max_response_bytes": MODEL2_MAX_RESPONSE_BYTES,
            "context_limit": MODEL2_CONTEXT_LIMIT,
            "concurrency": MODEL2_CONCURRENCY,
            "preflight_report_path": str(preflight_report_path),
            "preflight_report_sha256": preflight_report_sha256,
            "models_check_report_path": str(models_check_report_path),
            "models_check_report_sha256": models_check_report_sha256,
            "identity_policy": "every-response-exact-match-fail-closed",
        },
        "launcher": {
            "relative_path": PILOT_LAUNCHER_NAME,
            "sha256": sha256_bytes(launcher_payload),
            "mode": "0700",
            "credential_source": "macos-keychain-only",
            "keychain_service": "filesystem-refind-experiment-record.soclaas-api-key",
            "inherited_api_key": "ignored",
            "single_launcher_lock": True,
            "automatic_retry_limit_per_failed_key": 1,
            "identity_drift_recovery": "forbidden",
        },
        "question_set_id": questions[0].question_set_id,
        "question_ids": [item.question_id for item in questions],
        "condition_ids": list(CONDITION_IDS),
        "planned_retrieval_episodes": 36,
        "planned_answer_records": PILOT_RECORD_COUNT,
        "children": {
            "retrieval": {
                "output_root_relative": "children/retrieval",
                "run_id": paths["retrieval_run_id"],
            },
            "answers": {
                "output_root_relative": "children/answers",
                "run_id": paths["answer_run_id"],
            },
        },
        "evidence_budget": {
            "unit": "characters",
            "single_source_limit": 16_000,
            "whole_items_only": True,
            "e7_per_source_limit": 16_000,
            "e7_total_limit": 32_000,
        },
        "caps": {
            "r1_round_cap_by_condition": dict(R1_ROUND_CAP_BY_CONDITION),
            "r2_action_cap": R2_ACTION_CAP,
            "r3_action_cap": R3_ACTION_CAP,
        },
        "e7": {
            "inputs": ["E2", "E6"],
            "retrieval": "none-reuse-upstream-evidence",
        },
        "gold_boundary": (
            "semantic gold must not be loaded before all 42 answer records verify; "
            "post-completion pilot evaluation may load dev-6 gold"
        ),
        "judge_policy": "forbidden",
        "go_no_go": {
            "retrieval_system_failure_rate_lt": SYSTEM_FAILURE_RATE_LIMIT,
            "answer_system_failure_rate_lt": SYSTEM_FAILURE_RATE_LIMIT,
            "budget_skipped_episode_fraction_lt": BUDGET_SKIP_EPISODE_FRACTION_LIMIT,
            "token_safety_fuse_limit": TOKEN_SAFETY_FUSE_LIMIT,
            "empty_evidence_bundles": 0,
            "e7_retrieval_calls": 0,
        },
    }


def prepare_model2_pilot_pipeline(
    *,
    repo_root: Path,
    output_root: Path,
    pilot_id: str,
    implementation_commit: str,
    required_served_model: str,
    preflight_report_path: Path,
    preflight_report_sha256: str,
    models_check_report_path: Path,
    models_check_report_sha256: str,
) -> Path:
    """Prepare independent retrieval and answer roots without any API call."""
    if _SAFE.fullmatch(pilot_id) is None:
        raise EvidenceValidationError("Model 2 pilot_id is unsafe")
    if _COMMIT.fullmatch(implementation_commit) is None:
        raise EvidenceValidationError("Pilot implementation commit must be a full Git SHA")
    if not isinstance(required_served_model, str) or not required_served_model.strip():
        raise EvidenceValidationError("Pilot required served model is empty")
    if _SHA.fullmatch(preflight_report_sha256) is None:
        raise EvidenceValidationError("Pilot preflight hash must be SHA-256")
    if _SHA.fullmatch(models_check_report_sha256) is None:
        raise EvidenceValidationError("Pilot models-check hash must be SHA-256")
    root = Path(repo_root).resolve()
    verify_formal_manifest(root)
    base = Path(output_root).resolve()
    pilot_root = base / pilot_id
    pilot_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if pilot_root.is_symlink() or not pilot_root.is_dir():
        raise EvidenceValidationError("Model 2 pilot root is unsafe")
    preflight_path = Path(preflight_report_path).resolve()
    models_check_path = Path(models_check_report_path).resolve()
    body = _manifest_body(
        repo_root=root,
        output_root=base,
        pilot_id=pilot_id,
        implementation_commit=implementation_commit,
        required_served_model=required_served_model,
        preflight_report_path=preflight_path,
        preflight_report_sha256=preflight_report_sha256,
        models_check_report_path=models_check_path,
        models_check_report_sha256=models_check_report_sha256,
    )
    manifest = {
        "pilot_pipeline_manifest_id": "model2-pilot-pipeline-"
        + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    path = pilot_root / PILOT_MANIFEST_NAME
    _publish_json(path, manifest)
    paths = _pilot_paths(base, pilot_id)
    dev.prepare_dev_run(
        repo_root=root,
        output_root=Path(paths["retrieval_output"]),
        run_id=str(paths["retrieval_run_id"]),
        budget_limit=16_000,
        requested_model=MODEL2_REQUESTED_MODEL_ALIAS,
    )
    _write_keychain_launcher(
        repo_root=root,
        output_root=base,
        pilot_id=pilot_id,
        pilot_root=pilot_root,
    )
    _append_event(
        pilot_root / "events.jsonl",
        {
            "event": "model2_pilot_prepared",
            "at": _now(),
            "pilot_pipeline_manifest_id": manifest["pilot_pipeline_manifest_id"],
        },
    )
    write_model2_pilot_status(repo_root=root, output_root=base, pilot_id=pilot_id)
    return path


def _open_pipeline(
    *, repo_root: Path, output_root: Path, pilot_id: str
) -> tuple[Path, dict[str, Any], dict[str, Path | str]]:
    root = Path(repo_root).resolve()
    paths = _pilot_paths(Path(output_root).resolve(), pilot_id)
    pilot_root = Path(paths["root"])
    manifest = _read_json(pilot_root / PILOT_MANIFEST_NAME)
    identity = manifest.get("pilot_pipeline_manifest_id")
    body = {
        key: value for key, value in manifest.items()
        if key != "pilot_pipeline_manifest_id"
    }
    if identity != "model2-pilot-pipeline-" + sha256_bytes(canonical_json_bytes(body)):
        raise EvidenceValidationError("Model 2 pilot manifest hash differs")
    if manifest.get("pilot_id") != pilot_id:
        raise EvidenceValidationError("Model 2 pilot identity differs")
    deployment = manifest.get("deployment")
    if not isinstance(deployment, Mapping):
        raise EvidenceValidationError("Model 2 pilot deployment is missing")
    formal_verification = verify_formal_manifest(root)
    if formal_verification.get("formal_manifest_id") != manifest.get(
        "parent_formal_manifest_id"
    ):
        raise EvidenceValidationError("Model 2 pilot parent core verification drifted")
    expected_body = _manifest_body(
        repo_root=root,
        output_root=Path(output_root).resolve(),
        pilot_id=pilot_id,
        implementation_commit=str(manifest.get("implementation_git_commit", "")),
        required_served_model=str(deployment.get("required_served_model", "")),
        preflight_report_path=Path(str(deployment.get("preflight_report_path", ""))),
        preflight_report_sha256=str(
            deployment.get("preflight_report_sha256", "")
        ),
        models_check_report_path=Path(
            str(deployment.get("models_check_report_path", ""))
        ),
        models_check_report_sha256=str(
            deployment.get("models_check_report_sha256", "")
        ),
    )
    if body != expected_body:
        raise EvidenceValidationError(
            "Model 2 pilot manifest body differs from the frozen repository contract"
        )
    if _file_sha256(root / RUNNER_RELATIVE_PATH) != manifest.get("runner_sha256"):
        raise EvidenceValidationError("Model 2 pilot runner drifted")
    if _file_sha256(root / CLI_RELATIVE_PATH) != manifest.get("cli_sha256"):
        raise EvidenceValidationError("Model 2 pilot CLI drifted")
    expected_dependencies = manifest.get("direct_dependency_sha256")
    if (
        not isinstance(expected_dependencies, Mapping)
        or set(expected_dependencies) != set(DIRECT_DEPENDENCY_PATHS)
        or any(
            _file_sha256(root / path) != expected_dependencies.get(path)
            for path in DIRECT_DEPENDENCY_PATHS
        )
    ):
        raise EvidenceValidationError("Model 2 pilot direct dependency drifted")
    if _file_sha256(root / FORMAL_MANIFEST_RELATIVE_PATH) != manifest.get(
        "parent_formal_manifest_sha256"
    ):
        raise EvidenceValidationError("Model 2 pilot parent manifest drifted")
    preflight_path = Path(str(deployment.get("preflight_report_path", "")))
    if _file_sha256(preflight_path) != deployment.get("preflight_report_sha256"):
        raise EvidenceValidationError("Model 2 pilot preflight artifact drifted")
    preflight = verify_sanitized_preflight_artifact(preflight_path)
    if (
        preflight.get("requested_alias") != deployment.get("requested_model_alias")
        or preflight.get("served_model") != deployment.get("required_served_model")
    ):
        raise EvidenceValidationError("Model 2 pilot preflight identity drifted")
    models_check_path = Path(
        str(deployment.get("models_check_report_path", ""))
    )
    if _file_sha256(models_check_path) != deployment.get(
        "models_check_report_sha256"
    ):
        raise EvidenceValidationError("Model 2 pilot models-check artifact drifted")
    models_check = verify_sanitized_preflight_artifact(models_check_path)
    if (
        models_check.get("artifact_type") != "model2-models-check"
        or models_check.get("requested_alias")
        != deployment.get("requested_model_alias")
        or models_check.get("alias_present") is not True
        or models_check.get("context_limit") != MODEL2_CONTEXT_LIMIT
    ):
        raise EvidenceValidationError("Model 2 pilot models-check identity drifted")
    if {
        "endpoint": deployment.get("endpoint"),
        "api_style": deployment.get("api_style"),
        "request_timeout_seconds": deployment.get("request_timeout_seconds"),
        "max_response_bytes": deployment.get("max_response_bytes"),
        "context_limit": deployment.get("context_limit"),
        "concurrency": deployment.get("concurrency"),
    } != {
        "endpoint": MODEL2_CHAT_ENDPOINT,
        "api_style": MODEL2_API_STYLE,
        "request_timeout_seconds": MODEL2_REQUEST_TIMEOUT_SECONDS,
        "max_response_bytes": MODEL2_MAX_RESPONSE_BYTES,
        "context_limit": MODEL2_CONTEXT_LIMIT,
        "concurrency": MODEL2_CONCURRENCY,
    }:
        raise EvidenceValidationError("Model 2 pilot API deployment contract drifted")
    launcher = manifest.get("launcher", {})
    launcher_path = pilot_root / PILOT_LAUNCHER_NAME
    expected_launcher = _keychain_launcher_payload(
        repo_root=root,
        output_root=Path(output_root).resolve(),
        pilot_id=pilot_id,
    )
    if (
        launcher.get("relative_path") != PILOT_LAUNCHER_NAME
        or launcher.get("sha256") != sha256_bytes(expected_launcher)
        or launcher.get("mode") != "0700"
        or launcher.get("credential_source") != "macos-keychain-only"
        or launcher.get("keychain_service")
        != "filesystem-refind-experiment-record.soclaas-api-key"
        or launcher.get("inherited_api_key") != "ignored"
        or launcher.get("single_launcher_lock") is not True
        or launcher.get("automatic_retry_limit_per_failed_key") != 1
        or launcher.get("identity_drift_recovery") != "forbidden"
        or launcher_path.is_symlink()
        or not launcher_path.is_file()
        or launcher_path.read_bytes() != expected_launcher
        or (launcher_path.stat().st_mode & 0o777) != 0o700
    ):
        raise EvidenceValidationError("Model 2 pilot launcher contract drifted")
    return pilot_root, manifest, paths


class _PilotProvider(ModelIdentityProvider):
    """Public identity gate plus sanitized per-response usage accounting."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._call_rows: list[dict[str, Any]] = []
        self._provider_failure_rows: list[dict[str, Any]] = []

    def complete(self, messages: list[dict], tools: list[dict], config: Any) -> dict:
        call_row: dict[str, Any] = {
            "usage_available": False,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        self._call_rows.append(call_row)
        try:
            response = super().complete(messages, tools, config)
        except TransientProviderError as error:
            self._provider_failure_rows.append(
                {
                    "classification": "transient-provider-error",
                    "kind": error.kind,
                    "http_status": error.http_status,
                    "retryable": True,
                }
            )
            # Preserve the retry classification while ensuring downstream
            # Answerer/R1 failure records can never receive the raw message.
            raise TransientProviderError(
                _redact_provider_error(error, self),
                kind=error.kind,
                http_status=error.http_status,
            ) from None
        except ModelIdentityError:
            self._provider_failure_rows.append(
                {
                    "classification": "model-identity-error",
                    "retryable": False,
                }
            )
            raise
        except Exception as error:
            self._provider_failure_rows.append(
                {
                    "classification": "non-transient-provider-error",
                    "error_type": type(error).__name__,
                    "retryable": False,
                }
            )
            # Do not try to reconstruct an arbitrary provider exception: some
            # constructors carry unsafe state.  A plain RuntimeError retains
            # the non-transient semantics required by all frozen agents.
            raise RuntimeError(_redact_provider_error(error, self)) from None
        usage = response.get("usage")
        if isinstance(usage, Mapping):
            row: dict[str, int] = {}
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = usage.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    row[key] = value
            if len(row) == 3:
                call_row.update({"usage_available": True, **row})
        return response

    def usage_cursor(self) -> int:
        return len(self._call_rows)

    def usage_since(self, cursor: int) -> dict[str, int]:
        rows = self._call_rows[cursor:]
        available = [row for row in rows if row["usage_available"] is True]
        return {
            "request_count": len(rows),
            "response_count": len(available),
            "usage_unavailable_count": len(rows) - len(available),
            "prompt_tokens": sum(row["prompt_tokens"] for row in available),
            "completion_tokens": sum(row["completion_tokens"] for row in available),
            "total_tokens": sum(row["total_tokens"] for row in available),
        }

    def failure_cursor(self) -> int:
        return len(self._provider_failure_rows)

    def failures_since(self, cursor: int) -> tuple[dict[str, Any], ...]:
        return tuple(dict(row) for row in self._provider_failure_rows[cursor:])


def _identity_provider(
    provider: ChatProvider,
    manifest: Mapping[str, Any],
    *,
    pilot_root: Path | None = None,
) -> _PilotProvider:
    deployment = manifest["deployment"]
    try:
        return _PilotProvider(
            provider,
            requested_model_alias=deployment["requested_model_alias"],
            required_served_model=deployment["required_served_model"],
        )
    except ModelIdentityError:
        if pilot_root is not None:
            _publish_identity_drift_marker(
                pilot_root=pilot_root,
                manifest=manifest,
                observed_served_model=None,
                reason="provider configuration violated the frozen deployment contract",
            )
        raise


def _assert_no_identity_drift(pilot_root: Path) -> None:
    if (pilot_root / PILOT_IDENTITY_DRIFT_NAME).exists():
        raise ModelIdentityError(
            "Model 2 pilot is permanently halted after a model identity violation"
        )


def _publish_identity_drift_marker(
    *,
    pilot_root: Path,
    manifest: Mapping[str, Any],
    observed_served_model: str | None,
    reason: str,
) -> None:
    _publish_json(
        pilot_root / PILOT_IDENTITY_DRIFT_NAME,
        {
            "schema_version": 1,
            "protocol_version": MODEL2_PILOT_PIPELINE_PROTOCOL_VERSION,
            "status": "halted",
            "pilot_id": manifest["pilot_id"],
            "pilot_pipeline_manifest_id": manifest[
                "pilot_pipeline_manifest_id"
            ],
            "requested_model_alias": manifest["deployment"][
                "requested_model_alias"
            ],
            "required_served_model": manifest["deployment"][
                "required_served_model"
            ],
            "observed_served_model": _safe_observed_model(observed_served_model),
            "error_type": "ModelIdentityError",
            "reason": reason,
            "recovery": "forbidden",
        },
    )


def _raise_and_seal_identity_drift(
    *,
    pilot_root: Path,
    manifest: Mapping[str, Any],
    provider: ModelIdentityProvider,
) -> None:
    """Persist a non-recoverable gate if a legacy runner wrapped identity drift."""
    try:
        provider.raise_if_identity_error()
    except ModelIdentityError:
        _publish_identity_drift_marker(
            pilot_root=pilot_root,
            manifest=manifest,
            observed_served_model=provider.observed_served_model,
            reason="provider response violated the frozen model identity",
        )
        raise


def _active_retrieval_failures(
    *, completed: Mapping[RunKey, EvidenceBundle], failures: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [
        item
        for item in failures
        if RunKey(item["condition_id"], item["question_id"]) not in completed
    ]


def _retrieval_failure_evidence_path(pilot_root: Path, failure_id: str) -> Path:
    return pilot_root / "recovery" / f"retrieval-failure-evidence-{failure_id}.json"


def _publish_retrieval_failure_evidence(
    *,
    pilot_root: Path,
    manifest: Mapping[str, Any],
    failure: Mapping[str, Any],
    provider: _PilotProvider,
    failure_cursor: int,
    usage_cursor: int,
) -> dict[str, Any]:
    provider_failures = provider.failures_since(failure_cursor)
    usage = provider.usage_since(usage_cursor)
    if int(failure["total_tokens"]) != int(usage["total_tokens"]):
        raise EvidenceValidationError(
            "Model 2 retrieval failure token evidence differs"
        )
    body = {
        "schema_version": 1,
        "protocol_version": MODEL2_PILOT_RECOVERY_PROTOCOL_VERSION,
        "pilot_pipeline_manifest_id": manifest["pilot_pipeline_manifest_id"],
        "failure_id": failure["failure_id"],
        "failure_kind": failure["failure_kind"],
        "retry_key": {
            "condition_id": failure["condition_id"],
            "question_id": failure["question_id"],
        },
        "provider_failure_evidence": list(provider_failures),
        "failed_attempt_usage": usage,
        "required_served_model": manifest["deployment"]["required_served_model"],
        "observed_served_model": _safe_observed_model(
            provider.observed_served_model
        ),
    }
    evidence = {
        "retrieval_failure_evidence_id": "model2-retrieval-failure-evidence-"
        + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    _publish_json(
        _retrieval_failure_evidence_path(
            pilot_root, str(failure["failure_id"])
        ),
        evidence,
    )
    return evidence


def _load_retrieval_failure_evidence(
    *,
    pilot_root: Path,
    manifest: Mapping[str, Any],
    failure: Mapping[str, Any],
) -> dict[str, Any]:
    evidence = _read_json(
        _retrieval_failure_evidence_path(
            pilot_root, str(failure["failure_id"])
        )
    )
    identity = evidence.get("retrieval_failure_evidence_id")
    body = {
        key: value
        for key, value in evidence.items()
        if key != "retrieval_failure_evidence_id"
    }
    if identity != "model2-retrieval-failure-evidence-" + sha256_bytes(
        canonical_json_bytes(body)
    ):
        raise EvidenceValidationError(
            "Model 2 retrieval failure companion hash differs"
        )
    usage = evidence.get("failed_attempt_usage")
    usage_fields = {
        "request_count",
        "response_count",
        "usage_unavailable_count",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    }
    if (
        evidence.get("pilot_pipeline_manifest_id")
        != manifest["pilot_pipeline_manifest_id"]
        or evidence.get("failure_id") != failure["failure_id"]
        or evidence.get("failure_kind") != failure["failure_kind"]
        or evidence.get("required_served_model")
        != manifest["deployment"]["required_served_model"]
        or evidence.get("retry_key")
        != {
            "condition_id": failure["condition_id"],
            "question_id": failure["question_id"],
        }
        or not isinstance(evidence.get("provider_failure_evidence"), list)
        or not isinstance(usage, Mapping)
        or set(usage) != usage_fields
        or any(
            not isinstance(usage.get(name), int)
            or isinstance(usage.get(name), bool)
            or usage.get(name, -1) < 0
            for name in usage_fields
        )
        or usage["request_count"]
        != usage["response_count"] + usage["usage_unavailable_count"]
        or usage["total_tokens"]
        != usage["prompt_tokens"] + usage["completion_tokens"]
        or int(usage["total_tokens"]) != int(failure["total_tokens"])
    ):
        raise EvidenceValidationError(
            "Model 2 retrieval failure companion differs"
        )
    return evidence


def _retrieval_retry_evidence(
    failure: Mapping[str, Any], companion: Mapping[str, Any]
) -> dict[str, Any]:
    """Classify retryability only from the verified, content-addressed artifact."""
    condition = str(failure["condition_id"])
    kind = str(failure["failure_kind"])
    artifact = dev._verify_failure(Path(str(failure["artifact_path"])), condition)
    provider_attempts = int(artifact.metrics["provider_request_attempts"])
    model_calls = int(artifact.metrics["model_calls"])
    if provider_attempts < model_calls:
        raise EvidenceValidationError(
            "Model 2 retrieval failure provider attempts are inconsistent"
        )
    failed_usage = companion.get("failed_attempt_usage")
    if (
        not isinstance(failed_usage, Mapping)
        or failed_usage.get("request_count") != provider_attempts
        or failed_usage.get("response_count") != model_calls
        or failed_usage.get("usage_unavailable_count")
        != provider_attempts - model_calls
        or failed_usage.get("total_tokens") != artifact.metrics["total_tokens"]
    ):
        raise EvidenceValidationError(
            "Model 2 retrieval failure usage evidence differs"
        )
    eligible = False
    classification = "non-retryable"
    proof: dict[str, Any] = {
        "failure_id": artifact.failure_id,
        "failure_kind": kind,
        "provider_request_attempts": provider_attempts,
        "model_calls_with_usage": model_calls,
        "usage_unavailable_calls": int(
            failed_usage["usage_unavailable_count"]
        ),
        "retrieval_failure_evidence_id": companion.get(
            "retrieval_failure_evidence_id"
        ),
    }
    provider_failures = companion.get("provider_failure_evidence")
    if not isinstance(provider_failures, list):
        raise EvidenceValidationError(
            "Model 2 retrieval provider failure evidence is invalid"
        )
    terminal_provider_transient = bool(provider_failures) and all(
        row.get("classification") == "transient-provider-error"
        and row.get("retryable") is True
        and row.get("kind") in {"timeout", "http"}
        and (
            row.get("kind") == "timeout"
            or row.get("http_status") in {408, 429, 500, 502, 503, 504}
        )
        for row in provider_failures
        if isinstance(row, Mapping)
    ) and all(isinstance(row, Mapping) for row in provider_failures)
    if kind in RETRIEVAL_PROTOCOL_RETRYABLE_FAILURE_KINDS:
        eligible = not provider_failures
        classification = "bounded-protocol-response-error"
    elif condition in {"E1", "E3", "E5"} and kind == "provider":
        messages = [
            row.get("message")
            for row in artifact.errors
            if isinstance(row, Mapping)
        ]
        eligible = (
            messages == ["Provider request exhausted the frozen retry policy"]
            and terminal_provider_transient
        )
        classification = (
            "transient-provider-retries-exhausted"
            if eligible
            else "non-transient-provider-error"
        )
    elif condition in {"E2", "E4", "E6"} and kind == "provider_request":
        retry_rows = [
            row
            for row in artifact.search_actions
            if isinstance(row, Mapping) and row.get("event") == "provider_retry"
        ]
        eligible = terminal_provider_transient and bool(retry_rows) and all(
            row.get("kind") in {"timeout", "http"}
            and (
                row.get("kind") == "timeout"
                or row.get("http_status") in {408, 429, 500, 502, 503, 504}
            )
            for row in retry_rows
        )
        classification = (
            "transient-provider-retries-exhausted"
            if eligible
            else "non-transient-provider-error"
        )
        proof["provider_retry_rows"] = [
            {
                "kind": row.get("kind"),
                "http_status": row.get("http_status"),
                "attempt": row.get("attempt"),
            }
            for row in retry_rows
        ]
    proof["provider_failure_evidence"] = list(provider_failures)
    proof.update({"eligible": eligible, "classification": classification})
    return {
        **proof,
        "proof_sha256": sha256_bytes(canonical_json_bytes(proof)),
    }


def authorize_model2_pilot_retrieval_retry(
    *, repo_root: Path, output_root: Path, pilot_id: str
) -> Path:
    """Authorize one same-protocol retry while preserving the failed attempt.

    Authorization is deliberately a separate offline operation.  It accepts
    exactly one first failure for the current key; a second failed whole
    episode exhausts the retry budget.  Model-identity failures are sealed by a
    separate terminal marker and can never reach this path.
    """
    root = Path(repo_root).resolve()
    pilot_root, manifest, paths = _open_pipeline(
        repo_root=root, output_root=output_root, pilot_id=pilot_id
    )
    _assert_no_identity_drift(pilot_root)
    retrieval_output = Path(paths["retrieval_output"])
    retrieval_run_id = str(paths["retrieval_run_id"])
    completed, failures, plan, retrieval_manifest = dev._scan(
        repo_root=root,
        output_root=retrieval_output,
        run_id=retrieval_run_id,
    )
    active = _active_retrieval_failures(completed=completed, failures=failures)
    active_keys = {
        RunKey(item["condition_id"], item["question_id"]) for item in active
    }
    if len(active) != 1 or len(active_keys) != 1:
        raise EvidenceValidationError(
            "Retrieval retry requires exactly one first active failure"
        )
    key = next(iter(active_keys))
    attempts_for_key = [
        item
        for item in failures
        if RunKey(item["condition_id"], item["question_id"]) == key
    ]
    if len(attempts_for_key) != 1:
        raise EvidenceValidationError("Model 2 retrieval retry limit is exhausted")
    failure = active[0]
    companion = _load_retrieval_failure_evidence(
        pilot_root=pilot_root,
        manifest=manifest,
        failure=failure,
    )
    retry_evidence = _retrieval_retry_evidence(failure, companion)
    if retry_evidence["eligible"] is not True:
        raise EvidenceValidationError(
            "Model 2 retrieval failure is not eligible for retry"
        )
    body = {
        "schema_version": 1,
        "protocol_version": MODEL2_PILOT_RECOVERY_PROTOCOL_VERSION,
        "pilot_id": pilot_id,
        "pilot_pipeline_manifest_id": manifest["pilot_pipeline_manifest_id"],
        "retrieval_run_id": retrieval_run_id,
        "retrieval_plan_id": plan.plan_id,
        "retrieval_manifest_id": retrieval_manifest["manifest_id"],
        "retry_key": key.to_dict(),
        "prior_failure_id": failure["failure_id"],
        "prior_failure_kind": failure["failure_kind"],
        "retry_eligibility_evidence": retry_evidence,
        "prior_failure_total_tokens": int(failure["total_tokens"]),
        "maximum_whole_episode_retries": 1,
        "preserve_failure_artifact": True,
        "include_failed_attempt_cost_in_final_audit": True,
        "configuration_overrides": "forbidden",
        "authorization": "automatic-bounded-retry-after-frozen-evidence-check",
    }
    policy = {
        "recovery_id": "model2-pilot-recovery-"
        + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    path = pilot_root / "recovery" / f"{policy['recovery_id']}.json"
    consumption = (
        pilot_root / "recovery" / f"consumed-{policy['recovery_id']}.json"
    )
    if consumption.exists() or consumption.is_symlink():
        raise EvidenceValidationError("Model 2 retrieval retry was already consumed")
    _publish_json(path, policy)
    _append_event(
        pilot_root / "events.jsonl",
        {
            "event": "model2_retrieval_retry_authorized",
            "at": _now(),
            "recovery_id": policy["recovery_id"],
            **key.to_dict(),
            "prior_failure_id": failure["failure_id"],
        },
    )
    return path


def _load_authorized_retrieval_retry(
    *,
    pilot_root: Path,
    manifest: Mapping[str, Any],
    retrieval_run_id: str,
    plan: Any,
    retrieval_manifest: Mapping[str, Any],
    completed: Mapping[RunKey, EvidenceBundle],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    active = _active_retrieval_failures(completed=completed, failures=failures)
    if len(active) != 1:
        raise EvidenceValidationError(
            "Model 2 retrieval has no single authorized retry candidate"
        )
    failure = active[0]
    key = RunKey(failure["condition_id"], failure["question_id"])
    if sum(
        RunKey(item["condition_id"], item["question_id"]) == key
        for item in failures
    ) != 1:
        raise EvidenceValidationError("Model 2 retrieval retry limit is exhausted")
    companion = _load_retrieval_failure_evidence(
        pilot_root=pilot_root,
        manifest=manifest,
        failure=failure,
    )
    retry_evidence = _retrieval_retry_evidence(failure, companion)
    if retry_evidence["eligible"] is not True:
        raise EvidenceValidationError(
            "Model 2 retrieval failure is not eligible for retry"
        )
    policies: list[dict[str, Any]] = []
    recovery_root = pilot_root / "recovery"
    if recovery_root.is_dir() and not recovery_root.is_symlink():
        for path in sorted(recovery_root.glob("model2-pilot-recovery-*.json")):
            value = _read_json(path)
            identity = value.get("recovery_id")
            body = {name: item for name, item in value.items() if name != "recovery_id"}
            if identity != "model2-pilot-recovery-" + sha256_bytes(
                canonical_json_bytes(body)
            ):
                raise EvidenceValidationError("Model 2 recovery hash differs")
            if (
                value.get("protocol_version") == MODEL2_PILOT_RECOVERY_PROTOCOL_VERSION
                and value.get("pilot_pipeline_manifest_id")
                == manifest["pilot_pipeline_manifest_id"]
                and value.get("retrieval_run_id") == retrieval_run_id
                and value.get("retrieval_plan_id") == plan.plan_id
                and value.get("retrieval_manifest_id")
                == retrieval_manifest["manifest_id"]
                and value.get("retry_key") == key.to_dict()
                and value.get("prior_failure_id") == failure["failure_id"]
                and value.get("prior_failure_kind") == failure["failure_kind"]
                and value.get("retry_eligibility_evidence") == retry_evidence
                and value.get("maximum_whole_episode_retries") == 1
                and value.get("preserve_failure_artifact") is True
                and value.get("include_failed_attempt_cost_in_final_audit") is True
                and value.get("configuration_overrides") == "forbidden"
                and value.get("authorization")
                == "automatic-bounded-retry-after-frozen-evidence-check"
            ):
                policies.append(value)
    if len(policies) != 1:
        raise EvidenceValidationError(
            "Model 2 retrieval failure lacks one exact retry authorization"
        )
    policy = policies[0]
    consumption = (
        pilot_root / "recovery" / f"consumed-{policy['recovery_id']}.json"
    )
    if consumption.exists() or consumption.is_symlink():
        raise EvidenceValidationError("Model 2 retrieval retry was already consumed")
    return policy


def _retry_outcome_path(pilot_root: Path, recovery: Mapping[str, Any]) -> Path:
    return (
        pilot_root
        / "recovery"
        / f"outcome-{recovery['recovery_id']}.json"
    )


def _publish_retry_collision_outcome(
    *,
    pilot_root: Path,
    recovery: Mapping[str, Any],
    provider: _PilotProvider,
    usage_cursor: int,
    error: Exception,
) -> dict[str, Any]:
    """Account for a repeated content-identical failure without base-code edits."""
    body = {
        "schema_version": 1,
        "protocol_version": MODEL2_PILOT_RECOVERY_PROTOCOL_VERSION,
        "status": "failed-retry-exhausted",
        "recovery_id": recovery["recovery_id"],
        "retry_key": recovery["retry_key"],
        "prior_failure_id": recovery["prior_failure_id"],
        "failure_artifact": "content-identical-existing-artifact",
        "unique_failure_artifact_count": 1,
        "logical_failed_attempt_count": 2,
        "retry_usage": provider.usage_since(usage_cursor),
        "error_type": type(error).__name__,
        "reason": "authorized retry reproduced the same content-addressed failure",
        "further_retry": "forbidden",
    }
    outcome = {
        "retry_outcome_id": "model2-pilot-retry-outcome-"
        + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    _publish_json(_retry_outcome_path(pilot_root, recovery), outcome)
    return outcome


def _wrapper_retry_failure_outcomes(pilot_root: Path) -> list[dict[str, Any]]:
    recovery_root = pilot_root / "recovery"
    if not recovery_root.is_dir() or recovery_root.is_symlink():
        return []
    output: list[dict[str, Any]] = []
    for path in sorted(recovery_root.glob("outcome-model2-pilot-recovery-*.json")):
        value = _read_json(path)
        identity = value.get("retry_outcome_id")
        body = {key: item for key, item in value.items() if key != "retry_outcome_id"}
        if identity != "model2-pilot-retry-outcome-" + sha256_bytes(
            canonical_json_bytes(body)
        ):
            raise EvidenceValidationError("Model 2 retry outcome hash differs")
        if value.get("status") == "failed-retry-exhausted":
            output.append(value)
    return output


def _consume_retrieval_retry(
    *, pilot_root: Path, recovery: Mapping[str, Any]
) -> None:
    """Consume authorization before the retried provider request (fail closed)."""
    _publish_json(
        pilot_root
        / "recovery"
        / f"consumed-{recovery['recovery_id']}.json",
        {
            "schema_version": 1,
            "protocol_version": MODEL2_PILOT_RECOVERY_PROTOCOL_VERSION,
            "status": "consumed",
            "recovery_id": recovery["recovery_id"],
            "pilot_pipeline_manifest_id": recovery[
                "pilot_pipeline_manifest_id"
            ],
            "retry_key": recovery["retry_key"],
            "prior_failure_id": recovery["prior_failure_id"],
        },
    )


def _build_no_gold_retrieval_summary(
    *, repo_root: Path, retrieval_output: Path, retrieval_run_id: str,
    required_served_model: str,
) -> dict[str, Any]:
    completed, failures, plan, manifest = dev._scan(
        repo_root=repo_root, output_root=retrieval_output, run_id=retrieval_run_id
    )
    if len(completed) != 36 or len(plan.execution_order) != 36:
        raise EvidenceValidationError("Cannot summarize incomplete Model 2 retrieval")
    bundles = [completed[key] for key in plan.execution_order]
    if any(
        bundle.model["requested_model"] != MODEL2_REQUESTED_MODEL_ALIAS
        or set(bundle.model["served_models"]) != {required_served_model}
        for bundle in bundles
    ):
        raise EvidenceValidationError("Model 2 retrieval model identity differs")
    if any(bundle.budget.unit != "characters" or bundle.budget.limit != 16_000 for bundle in bundles):
        raise EvidenceValidationError("Model 2 retrieval budget differs")
    skipped_episode_count = sum(bundle.budget.skipped_items > 0 for bundle in bundles)
    skipped_fraction = skipped_episode_count / len(bundles)
    empty_count = sum(not bundle.evidence_items for bundle in bundles)
    truncated_count = sum(bundle.budget.truncated for bundle in bundles)
    by_condition: dict[str, dict[str, Any]] = {}
    for condition in CONDITION_IDS[:-1]:
        rows = [bundle for key, bundle in completed.items() if key.condition_id == condition]
        by_condition[condition] = {
            "episode_count": len(rows),
            "total_tokens_max": max(int(bundle.metrics["total_tokens"]) for bundle in rows),
            "budget_skipped_episode_count": sum(bundle.budget.skipped_items > 0 for bundle in rows),
            "empty_evidence_count": sum(not bundle.evidence_items for bundle in rows),
        }
    passed_budget_gate = (
        skipped_fraction < BUDGET_SKIP_EPISODE_FRACTION_LIMIT
        and empty_count == 0
        and truncated_count == 0
    )
    body = {
        "schema_version": 1,
        "protocol_version": MODEL2_PILOT_PIPELINE_PROTOCOL_VERSION,
        "status": "completed",
        "run_id": retrieval_run_id,
        "manifest_id": manifest["manifest_id"],
        "episode_count": 36,
        "semantic_gold_loaded": False,
        "served_models": [required_served_model],
        "overall": {
            "episode_count": 36,
            "capped_episode_count": sum(bundle.status == "capped" for bundle in bundles),
            "empty_evidence_count": empty_count,
            "budget_truncated_episode_count": truncated_count,
        },
        "by_condition": by_condition,
        "budget_decision": {
            "decision": "freeze-candidate-16000" if passed_budget_gate else "pilot-gate-failed",
            "budget_skipped_episode_count": skipped_episode_count,
            "budget_skipped_episode_fraction": skipped_fraction,
            "empty_evidence_count": empty_count,
            "budget_truncated_episode_count": truncated_count,
        },
        "recovery_overhead": {
            "failed_attempt_count": len(failures),
        },
    }
    summary = {
        "summary_id": "model2-retrieval-summary-"
        + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    _publish_json(Path(retrieval_output) / retrieval_run_id / RETRIEVAL_SUMMARY_NAME, summary)
    if not passed_budget_gate:
        raise EvidenceValidationError("Model 2 retrieval failed the preregistered budget gate")
    return summary


def run_model2_pilot_retrieval(
    *, repo_root: Path, output_root: Path, pilot_id: str, provider: ChatProvider,
) -> dict[str, Any]:
    """Run/resume 36 retrieval episodes, then write a no-gold summary."""
    root = Path(repo_root).resolve()
    pilot_root, manifest, paths = _open_pipeline(
        repo_root=root, output_root=output_root, pilot_id=pilot_id
    )
    _assert_no_identity_drift(pilot_root)
    gated = _identity_provider(provider, manifest, pilot_root=pilot_root)
    retrieval_output = Path(paths["retrieval_output"])
    retrieval_run_id = str(paths["retrieval_run_id"])
    with _pipeline_lock(pilot_root):
        completed, failures, plan, retrieval_manifest = dev._scan(
            repo_root=root, output_root=retrieval_output, run_id=retrieval_run_id
        )
        active_failures = _active_retrieval_failures(
            completed=completed, failures=failures
        )
        recovery = None
        if active_failures:
            recovery = _load_authorized_retrieval_retry(
                pilot_root=pilot_root,
                manifest=manifest,
                retrieval_run_id=retrieval_run_id,
                plan=plan,
                retrieval_manifest=retrieval_manifest,
                completed=completed,
                failures=failures,
            )
            _consume_retrieval_retry(pilot_root=pilot_root, recovery=recovery)
        questions = {item.question_id: item for item in load_question_inputs(root, "dev-6")}
        stores = {name: load_r1_store(root, name) for name in ("s1", "s2", "s3")}
        r2_corpora = {name: build_r2_raw_corpus(root, name) for name in ("s1", "s2")}
        r3_corpus = load_r3_corpus(root)
        events = retrieval_output / retrieval_run_id / "events.jsonl"
        for sequence, key in enumerate(plan.execution_order, start=1):
            if key in completed:
                continue
            # A recovery authorization belongs to exactly one RunKey.  The
            # same invocation may successfully replay that key and then
            # continue until a *different* key fails.  Never carry the first
            # key's consumed retry budget forward to that later failure.
            recovery_for_key = (
                recovery
                if recovery is not None
                and recovery.get("retry_key") == key.to_dict()
                else None
            )
            key_failures = [
                item
                for item in active_failures
                if RunKey(item["condition_id"], item["question_id"]) == key
            ]
            if key_failures:
                if recovery_for_key is None:
                    raise EvidenceValidationError(
                        "Pending Model 2 retrieval key has no authorized retry"
                    )
                _append_event(
                    events,
                    {
                        "event": "model2_retrieval_retry_started",
                        "at": _now(),
                        "sequence": sequence,
                        "recovery_id": recovery_for_key["recovery_id"],
                        **key.to_dict(),
                        "prior_failure_id": key_failures[0]["failure_id"],
                    },
                )
            question = questions[key.question_id]
            method, store_id = dev.CONDITION_METHODS[key.condition_id]
            _append_event(
                events,
                {"event": "model2_episode_started", "at": _now(), "sequence": sequence, **key.to_dict()},
            )
            failure_cursor = gated.failure_cursor()
            usage_cursor = gated.usage_cursor()
            prior_failure_ids = {
                str(item["failure_id"])
                for item in failures
                if RunKey(item["condition_id"], item["question_id"]) == key
            }
            try:
                if method == "r1":
                    result = execute_r1_question(
                        repo_root=root,
                        output_root=retrieval_output,
                        run_id=retrieval_run_id,
                        cell_id=key.condition_id,
                        question=question,
                        provider=gated,
                        requested_model=MODEL2_REQUESTED_MODEL_ALIAS,
                        budget_unit="characters",
                        budget_limit=16_000,
                        loaded_store=stores[store_id],
                    )
                elif method == "r2":
                    result = execute_r2_question(
                        repo_root=root,
                        output_root=retrieval_output,
                        run_id=retrieval_run_id,
                        cell_id=key.condition_id,
                        question=question,
                        provider=gated,
                        requested_model=MODEL2_REQUESTED_MODEL_ALIAS,
                        budget_unit="characters",
                        budget_limit=16_000,
                        corpus=r2_corpora[store_id],
                    )
                else:
                    result = execute_r3_question(
                        repo_root=root,
                        output_root=retrieval_output,
                        run_id=retrieval_run_id,
                        question=question,
                        provider=gated,
                        requested_model=MODEL2_REQUESTED_MODEL_ALIAS,
                        budget_unit="characters",
                        budget_limit=16_000,
                        corpus=r3_corpus,
                    )
            except Exception as error:
                _raise_and_seal_identity_drift(
                    pilot_root=pilot_root, manifest=manifest, provider=gated
                )
                retry_collision = recovery_for_key is not None and (
                    (
                        isinstance(error, EvidenceValidationError)
                        and str(error) == "R1 failure artifact already exists"
                    )
                    or isinstance(error, FileExistsError)
                )
                if retry_collision:
                    outcome = _publish_retry_collision_outcome(
                        pilot_root=pilot_root,
                        recovery=recovery_for_key,
                        provider=gated,
                        usage_cursor=usage_cursor,
                        error=error,
                    )
                    _append_event(
                        pilot_root / "events.jsonl",
                        {
                            "event": "model2_retrieval_retry_exhausted",
                            "at": _now(),
                            "retry_outcome_id": outcome["retry_outcome_id"],
                            **key.to_dict(),
                        },
                    )
                    dev.write_status(
                        repo_root=root,
                        output_root=retrieval_output,
                        run_id=retrieval_run_id,
                    )
                    write_model2_pilot_status(
                        repo_root=root,
                        output_root=output_root,
                        pilot_id=pilot_id,
                    )
                    return {
                        "status": "failed",
                        "retry_exhausted": True,
                        "retry_outcome_id": outcome["retry_outcome_id"],
                        **key.to_dict(),
                    }
                failure = {
                    "schema_version": 1,
                    "protocol_version": MODEL2_PILOT_PIPELINE_PROTOCOL_VERSION,
                    "run_id": retrieval_run_id,
                    "sequence": sequence,
                    **key.to_dict(),
                    "error_type": type(error).__name__,
                    "message": dev._safe_error(error, gated),
                    "at": _now(),
                }
                dev._write_atomic(
                    retrieval_output / retrieval_run_id / "driver-failure.json", failure
                )
                dev.write_status(
                    repo_root=root, output_root=retrieval_output, run_id=retrieval_run_id
                )
                raise
            _raise_and_seal_identity_drift(
                pilot_root=pilot_root, manifest=manifest, provider=gated
            )
            if result.status == "failed":
                completed_after, failures_after, _, _ = dev._scan(
                    repo_root=root,
                    output_root=retrieval_output,
                    run_id=retrieval_run_id,
                )
                new_failures = [
                    item
                    for item in failures_after
                    if RunKey(item["condition_id"], item["question_id"]) == key
                    and str(item["failure_id"]) not in prior_failure_ids
                ]
                if key in completed_after or len(new_failures) != 1:
                    raise EvidenceValidationError(
                        "Model 2 retrieval failed attempt artifact differs"
                    )
                _publish_retrieval_failure_evidence(
                    pilot_root=pilot_root,
                    manifest=manifest,
                    failure=new_failures[0],
                    provider=gated,
                    failure_cursor=failure_cursor,
                    usage_cursor=usage_cursor,
                )
                dev.write_status(
                    repo_root=root, output_root=retrieval_output, run_id=retrieval_run_id
                )
                write_model2_pilot_status(
                    repo_root=root,
                    output_root=output_root,
                    pilot_id=pilot_id,
                )
                return {
                    "status": "failed",
                    "retry_exhausted": recovery_for_key is not None,
                    **key.to_dict(),
                }
            bundle = dev._verify_success(
                repo_root=root,
                artifact=result.artifact_path,
                condition_id=key.condition_id,
                cache={f"store-{store_id}": stores[store_id], "r3-corpus": r3_corpus},
            )
            if set(bundle.model["served_models"]) != {
                manifest["deployment"]["required_served_model"]
            }:
                raise EvidenceValidationError("Published retrieval bundle model drifted")
            completed[key] = bundle
            _append_event(
                events,
                {
                    "event": "model2_episode_verified",
                    "at": _now(),
                    "sequence": sequence,
                    **key.to_dict(),
                    "bundle_id": bundle.bundle_id,
                },
            )
            dev.write_status(
                repo_root=root, output_root=retrieval_output, run_id=retrieval_run_id
            )
        summary = _build_no_gold_retrieval_summary(
            repo_root=root,
            retrieval_output=retrieval_output,
            retrieval_run_id=retrieval_run_id,
            required_served_model=manifest["deployment"]["required_served_model"],
        )
        _append_event(
            pilot_root / "events.jsonl",
            {"event": "model2_retrieval_completed_no_gold", "at": _now(), "summary_id": summary["summary_id"]},
        )
        write_model2_pilot_status(repo_root=root, output_root=output_root, pilot_id=pilot_id)
        return summary


def _answer_pending_order(store: Any) -> tuple[RunKey, ...]:
    """Mirror the frozen legacy pilot order without modifying that runner."""
    primary = tuple(
        key
        for key in store.plan.execution_order
        if key.condition_id != "E7" and store.load_completed(key) is None
    )
    fusion = tuple(
        key
        for key in store.plan.execution_order
        if key.condition_id == "E7" and store.load_completed(key) is None
    )
    return primary + fusion


def _active_answer_failure(
    store: Any,
) -> tuple[RunKey, tuple[Any, ...]] | None:
    pending = _answer_pending_order(store)
    active = [
        (key, store.failure_attempts(key))
        for key in pending
        if store.failure_attempts(key)
    ]
    if not active:
        return None
    if len(active) != 1 or active[0][0] != pending[0]:
        raise EvidenceValidationError(
            "Model 2 answer failures do not match the next frozen answer key"
        )
    return active[0]


def _answer_failure_evidence_path(pilot_root: Path, failure_id: str) -> Path:
    return pilot_root / "recovery" / f"answer-failure-evidence-{failure_id}.json"


def _answer_record_usage(records: list[Any]) -> dict[str, int]:
    request_count = sum(
        int(record.answer_metrics["provider_request_attempts"])
        for record in records
    )
    response_count = sum(
        int(record.answer_metrics["model_calls"]) for record in records
    )
    return {
        "request_count": request_count,
        "response_count": response_count,
        "usage_unavailable_count": request_count - response_count,
        "prompt_tokens": sum(int(record.answer_metrics["prompt_tokens"]) for record in records),
        "completion_tokens": sum(
            int(record.answer_metrics["completion_tokens"]) for record in records
        ),
        "total_tokens": sum(int(record.answer_metrics["total_tokens"]) for record in records),
    }


def _publish_answer_failure_evidence(
    *,
    pilot_root: Path,
    manifest: Mapping[str, Any],
    store: Any,
    key: RunKey,
    provider: _PilotProvider,
    failure_cursor: int,
    usage_cursor: int,
    successful_usage_during_invocation: Mapping[str, int],
) -> dict[str, Any]:
    attempts = store.failure_attempts(key)
    if not attempts:
        raise EvidenceValidationError("Answer failure record is missing")
    failure = attempts[-1]
    provider_failures = provider.failures_since(failure_cursor)
    invocation_usage = provider.usage_since(usage_cursor)
    required_usage_fields = {
        "request_count",
        "response_count",
        "usage_unavailable_count",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    }
    if set(successful_usage_during_invocation) != required_usage_fields:
        raise EvidenceValidationError(
            "Model 2 successful answer usage offset fields differ"
        )
    failed_attempt_usage = {
        name: int(invocation_usage[name])
        - int(successful_usage_during_invocation[name])
        for name in sorted(required_usage_fields)
    }
    if (
        any(value < 0 for value in failed_attempt_usage.values())
        or failed_attempt_usage["request_count"]
        != failed_attempt_usage["response_count"]
        + failed_attempt_usage["usage_unavailable_count"]
        or failed_attempt_usage["total_tokens"]
        != failed_attempt_usage["prompt_tokens"]
        + failed_attempt_usage["completion_tokens"]
    ):
        raise EvidenceValidationError(
            "Model 2 answer failed-attempt usage subtraction differs"
        )
    if failure.stage == "answer_schema":
        eligible = True
        classification = "bounded-answer-schema-error"
    elif failure.stage == "provider":
        eligible = bool(provider_failures) and all(
            row.get("classification") == "transient-provider-error"
            and row.get("retryable") is True
            and row.get("kind") in {"timeout", "http"}
            and (
                row.get("kind") == "timeout"
                or row.get("http_status") in {408, 429, 500, 502, 503, 504}
            )
            for row in provider_failures
        )
        classification = (
            "transient-provider-retries-exhausted"
            if eligible
            else "non-transient-provider-error"
        )
    else:
        eligible = False
        classification = "non-retryable-answer-stage"
    body = {
        "schema_version": 1,
        "protocol_version": MODEL2_PILOT_RECOVERY_PROTOCOL_VERSION,
        "pilot_pipeline_manifest_id": manifest["pilot_pipeline_manifest_id"],
        "answer_plan_id": store.plan.plan_id,
        "answer_run_id": store.plan.run_id,
        "failure_id": failure.failure_id,
        "failure_attempt": failure.attempt,
        "failure_stage": failure.stage,
        "retry_key": key.to_dict(),
        "classification": classification,
        "eligible": eligible,
        "provider_failure_evidence": list(provider_failures),
        "invocation_usage": invocation_usage,
        "successful_usage_offset": dict(successful_usage_during_invocation),
        "failed_attempt_usage": failed_attempt_usage,
        "required_served_model": manifest["deployment"]["required_served_model"],
        "observed_served_model": provider.observed_served_model,
    }
    evidence = {
        "answer_failure_evidence_id": "model2-answer-failure-evidence-"
        + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    _publish_json(
        _answer_failure_evidence_path(pilot_root, failure.failure_id), evidence
    )
    return evidence


def _load_answer_failure_evidence(
    *, pilot_root: Path, manifest: Mapping[str, Any], store: Any, failure: Any
) -> dict[str, Any]:
    evidence = _read_json(
        _answer_failure_evidence_path(pilot_root, failure.failure_id)
    )
    identity = evidence.get("answer_failure_evidence_id")
    body = {
        key: value
        for key, value in evidence.items()
        if key != "answer_failure_evidence_id"
    }
    if identity != "model2-answer-failure-evidence-" + sha256_bytes(
        canonical_json_bytes(body)
    ):
        raise EvidenceValidationError("Model 2 answer failure evidence hash differs")
    usage_fields = {
        "request_count",
        "response_count",
        "usage_unavailable_count",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    }

    def valid_usage(value: Any) -> bool:
        return (
            isinstance(value, Mapping)
            and set(value) == usage_fields
            and all(
                isinstance(value.get(name), int)
                and not isinstance(value.get(name), bool)
                and value.get(name, -1) >= 0
                for name in usage_fields
            )
            and value.get("total_tokens")
            == value.get("prompt_tokens", -1) + value.get("completion_tokens", -1)
            and value.get("request_count")
            == value.get("response_count", -1)
            + value.get("usage_unavailable_count", -1)
        )

    usage = evidence.get("failed_attempt_usage")
    invocation_usage = evidence.get("invocation_usage")
    successful_offset = evidence.get("successful_usage_offset")
    usage_valid = (
        valid_usage(usage)
        and valid_usage(invocation_usage)
        and valid_usage(successful_offset)
        and all(
            invocation_usage[name] == successful_offset[name] + usage[name]
            for name in usage_fields
        )
    )
    if (
        evidence.get("pilot_pipeline_manifest_id")
        != manifest["pilot_pipeline_manifest_id"]
        or evidence.get("answer_plan_id") != store.plan.plan_id
        or evidence.get("answer_run_id") != store.plan.run_id
        or evidence.get("failure_id") != failure.failure_id
        or evidence.get("failure_attempt") != failure.attempt
        or evidence.get("failure_stage") != failure.stage
        or evidence.get("retry_key") != failure.key.to_dict()
        or evidence.get("eligible") is not True
        or evidence.get("classification")
        not in {
            "transient-provider-retries-exhausted",
            "bounded-answer-schema-error",
        }
        or not usage_valid
    ):
        raise EvidenceValidationError(
            "Model 2 answer failure lacks retry-eligible companion evidence"
        )
    return evidence


def authorize_model2_pilot_answer_retry(
    *, repo_root: Path, output_root: Path, pilot_id: str
) -> Path:
    """Authorize one same-protocol Answerer retry for the current failed key."""
    root = Path(repo_root).resolve()
    pilot_root, manifest, paths = _open_pipeline(
        repo_root=root, output_root=output_root, pilot_id=pilot_id
    )
    _assert_no_identity_drift(pilot_root)
    answer_output = Path(paths["answer_output"])
    answer_run_id = str(paths["answer_run_id"])
    store, _ = verify_run_store(answer_output, answer_run_id)
    pilot_manifest = _read_json(store.run_root / "pilot-manifest.json")
    active = _active_answer_failure(store)
    if active is None:
        raise EvidenceValidationError("Model 2 answer retry has no active failure")
    key, attempts = active
    if len(attempts) != 1:
        raise EvidenceValidationError("Model 2 answer retry limit is exhausted")
    failure = attempts[0]
    if failure.stage not in ANSWER_RETRYABLE_FAILURE_STAGES:
        raise EvidenceValidationError("Model 2 answer failure is not eligible for retry")
    retry_evidence = _load_answer_failure_evidence(
        pilot_root=pilot_root,
        manifest=manifest,
        store=store,
        failure=failure,
    )
    body = {
        "schema_version": 1,
        "protocol_version": MODEL2_PILOT_RECOVERY_PROTOCOL_VERSION,
        "pilot_id": pilot_id,
        "pilot_pipeline_manifest_id": manifest["pilot_pipeline_manifest_id"],
        "answer_run_id": answer_run_id,
        "answer_plan_id": store.plan.plan_id,
        "answer_pilot_manifest_id": pilot_manifest.get("pilot_manifest_id"),
        "retry_key": key.to_dict(),
        "prior_failure_id": failure.failure_id,
        "prior_failure_stage": failure.stage,
        "prior_failure_attempt": failure.attempt,
        "retry_eligibility_evidence_id": retry_evidence[
            "answer_failure_evidence_id"
        ],
        "maximum_whole_answer_retries": 1,
        "preserve_failure_artifact": True,
        "include_failed_attempt_cost_in_final_audit": True,
        "configuration_overrides": "forbidden",
        "authorization": "automatic-bounded-pilot-retry-after-stage-check",
    }
    policy = {
        "answer_recovery_id": "model2-pilot-answer-recovery-"
        + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    path = (
        pilot_root
        / "recovery"
        / f"{policy['answer_recovery_id']}.json"
    )
    consumed = (
        pilot_root
        / "recovery"
        / f"consumed-{policy['answer_recovery_id']}.json"
    )
    if consumed.exists() or consumed.is_symlink():
        raise EvidenceValidationError("Model 2 answer retry was already consumed")
    _publish_json(path, policy)
    _append_event(
        pilot_root / "events.jsonl",
        {
            "event": "model2_answer_retry_authorized",
            "at": _now(),
            "answer_recovery_id": policy["answer_recovery_id"],
            **key.to_dict(),
            "prior_failure_id": failure.failure_id,
            "prior_failure_stage": failure.stage,
        },
    )
    return path


def _load_authorized_answer_retry(
    *,
    pilot_root: Path,
    manifest: Mapping[str, Any],
    store: Any,
    pilot_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    active = _active_answer_failure(store)
    if active is None:
        raise EvidenceValidationError("Model 2 answer has no retry candidate")
    key, attempts = active
    if len(attempts) != 1:
        raise EvidenceValidationError("Model 2 answer retry limit is exhausted")
    failure = attempts[0]
    retry_evidence = _load_answer_failure_evidence(
        pilot_root=pilot_root,
        manifest=manifest,
        store=store,
        failure=failure,
    )
    candidates: list[dict[str, Any]] = []
    recovery_root = pilot_root / "recovery"
    if recovery_root.is_dir() and not recovery_root.is_symlink():
        for path in sorted(recovery_root.glob("model2-pilot-answer-recovery-*.json")):
            value = _read_json(path)
            identity = value.get("answer_recovery_id")
            body = {
                name: item
                for name, item in value.items()
                if name != "answer_recovery_id"
            }
            if identity != "model2-pilot-answer-recovery-" + sha256_bytes(
                canonical_json_bytes(body)
            ):
                raise EvidenceValidationError("Model 2 answer recovery hash differs")
            if (
                value.get("protocol_version")
                == MODEL2_PILOT_RECOVERY_PROTOCOL_VERSION
                and value.get("pilot_pipeline_manifest_id")
                == manifest["pilot_pipeline_manifest_id"]
                and value.get("answer_run_id") == store.plan.run_id
                and value.get("answer_plan_id") == store.plan.plan_id
                and value.get("answer_pilot_manifest_id")
                == pilot_manifest.get("pilot_manifest_id")
                and value.get("retry_key") == key.to_dict()
                and value.get("prior_failure_id") == failure.failure_id
                and value.get("prior_failure_stage") == failure.stage
                and value.get("prior_failure_attempt") == 1
                and value.get("retry_eligibility_evidence_id")
                == retry_evidence["answer_failure_evidence_id"]
                and value.get("prior_failure_stage")
                in ANSWER_RETRYABLE_FAILURE_STAGES
                and value.get("maximum_whole_answer_retries") == 1
                and value.get("preserve_failure_artifact") is True
                and value.get("include_failed_attempt_cost_in_final_audit") is True
                and value.get("configuration_overrides") == "forbidden"
            ):
                candidates.append(value)
    if len(candidates) != 1:
        raise EvidenceValidationError(
            "Model 2 answer failure lacks one exact retry authorization"
        )
    policy = candidates[0]
    consumed = (
        pilot_root
        / "recovery"
        / f"consumed-{policy['answer_recovery_id']}.json"
    )
    if consumed.exists() or consumed.is_symlink():
        raise EvidenceValidationError("Model 2 answer retry was already consumed")
    return policy


def _consume_answer_retry(
    *, pilot_root: Path, recovery: Mapping[str, Any]
) -> None:
    _publish_json(
        pilot_root
        / "recovery"
        / f"consumed-{recovery['answer_recovery_id']}.json",
        {
            "schema_version": 1,
            "protocol_version": MODEL2_PILOT_RECOVERY_PROTOCOL_VERSION,
            "status": "consumed",
            "answer_recovery_id": recovery["answer_recovery_id"],
            "pilot_pipeline_manifest_id": recovery[
                "pilot_pipeline_manifest_id"
            ],
            "retry_key": recovery["retry_key"],
            "prior_failure_id": recovery["prior_failure_id"],
        },
    )


def run_model2_pilot_answers(
    *, repo_root: Path, output_root: Path, pilot_id: str, provider: ChatProvider,
) -> dict[str, Any]:
    """Run/resume 42 answers; post-completion legacy pilot evaluation may load gold."""
    root = Path(repo_root).resolve()
    pilot_root, manifest, paths = _open_pipeline(
        repo_root=root, output_root=output_root, pilot_id=pilot_id
    )
    _assert_no_identity_drift(pilot_root)
    gated = _identity_provider(provider, manifest, pilot_root=pilot_root)
    retrieval_output = Path(paths["retrieval_output"])
    retrieval_run_id = str(paths["retrieval_run_id"])
    answer_output = Path(paths["answer_output"])
    answer_run_id = str(paths["answer_run_id"])
    summary = _read_json(retrieval_output / retrieval_run_id / RETRIEVAL_SUMMARY_NAME)
    if summary.get("status") != "completed" or summary.get("semantic_gold_loaded") is not False:
        raise EvidenceValidationError("Model 2 answer phase requires completed no-gold retrieval")
    if summary.get("served_models") != [manifest["deployment"]["required_served_model"]]:
        raise EvidenceValidationError("Model 2 retrieval summary model differs")
    with _pipeline_lock(pilot_root):
        legacy_pilot.prepare_pilot(
            repo_root=root,
            retrieval_output_root=retrieval_output,
            retrieval_run_id=retrieval_run_id,
            output_root=answer_output,
            run_id=answer_run_id,
            requested_model=MODEL2_REQUESTED_MODEL_ALIAS,
        )
        answer_store, _ = verify_run_store(answer_output, answer_run_id)
        answer_pilot_manifest = _read_json(
            answer_store.run_root / "pilot-manifest.json"
        )
        completed_before_invocation = {
            key
            for key in answer_store.plan.execution_order
            if answer_store.load_completed(key) is not None
        }
        active_answer_failure = _active_answer_failure(answer_store)
        if active_answer_failure is not None:
            recovery = _load_authorized_answer_retry(
                pilot_root=pilot_root,
                manifest=manifest,
                store=answer_store,
                pilot_manifest=answer_pilot_manifest,
            )
            _consume_answer_retry(pilot_root=pilot_root, recovery=recovery)
            _append_event(
                pilot_root / "events.jsonl",
                {
                    "event": "model2_answer_retry_started",
                    "at": _now(),
                    "answer_recovery_id": recovery["answer_recovery_id"],
                    **recovery["retry_key"],
                    "prior_failure_id": recovery["prior_failure_id"],
                },
            )
        answer_failure_cursor = gated.failure_cursor()
        answer_usage_cursor = gated.usage_cursor()
        result = legacy_pilot.run_pilot(
            repo_root=root, output_root=answer_output, run_id=answer_run_id, provider=gated
        )
        _raise_and_seal_identity_drift(
            pilot_root=pilot_root, manifest=manifest, provider=gated
        )
        if result.get("status") == "failed":
            failed_key = RunKey(
                str(result.get("condition_id")), str(result.get("question_id"))
            )
            refreshed_store, _ = verify_run_store(answer_output, answer_run_id)
            new_success_records = [
                record
                for key in refreshed_store.plan.execution_order
                if key not in completed_before_invocation
                and (record := refreshed_store.load_completed(key)) is not None
            ]
            _publish_answer_failure_evidence(
                pilot_root=pilot_root,
                manifest=manifest,
                store=refreshed_store,
                key=failed_key,
                provider=gated,
                failure_cursor=answer_failure_cursor,
                usage_cursor=answer_usage_cursor,
                successful_usage_during_invocation=_answer_record_usage(
                    new_success_records
                ),
            )
        write_model2_pilot_status(repo_root=root, output_root=output_root, pilot_id=pilot_id)
        if result.get("status") == "passed":
            return finalize_model2_pilot(
                repo_root=root, output_root=output_root, pilot_id=pilot_id
            )
        return result


def run_model2_pilot_all(
    *, repo_root: Path, output_root: Path, pilot_id: str, provider: ChatProvider,
) -> dict[str, Any]:
    """Run the complete dev-6 pilot with single-process bounded recovery.

    Every failed key gets at most one same-protocol retry and only when its
    recorded stage is on the frozen allowlist.  The launcher lock covers both
    phases, while each phase keeps its existing short critical-section lock.
    """
    root = Path(repo_root).resolve()
    pilot_root, _, _ = _open_pipeline(
        repo_root=root, output_root=output_root, pilot_id=pilot_id
    )
    _assert_no_identity_drift(pilot_root)
    with _launcher_lock(pilot_root):
        for _ in range(37):
            retrieval = run_model2_pilot_retrieval(
                repo_root=root,
                output_root=output_root,
                pilot_id=pilot_id,
                provider=provider,
            )
            if retrieval.get("status") == "completed":
                break
            if retrieval.get("retry_exhausted") is True:
                raise EvidenceValidationError(
                    "Model 2 retrieval retry limit is exhausted"
                )
            authorize_model2_pilot_retrieval_retry(
                repo_root=root, output_root=output_root, pilot_id=pilot_id
            )
        else:
            raise EvidenceValidationError(
                "Model 2 retrieval exceeded its bounded controller passes"
            )

        for _ in range(43):
            answer = run_model2_pilot_answers(
                repo_root=root,
                output_root=output_root,
                pilot_id=pilot_id,
                provider=provider,
            )
            if "model2_pilot_audit_id" in answer:
                if answer.get("status") != "passed":
                    raise EvidenceValidationError(
                        "Model 2 pilot completed but failed its frozen Go/No-Go audit"
                    )
                return answer
            if answer.get("status") != "failed":
                raise EvidenceValidationError(
                    "Model 2 answer phase returned an unexpected status"
                )
            authorize_model2_pilot_answer_retry(
                repo_root=root, output_root=output_root, pilot_id=pilot_id
            )
    raise EvidenceValidationError(
        "Model 2 answer phase exceeded its bounded controller passes"
    )


def write_model2_pilot_status(
    *, repo_root: Path, output_root: Path, pilot_id: str
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    pilot_root, manifest, paths = _open_pipeline(
        repo_root=root, output_root=output_root, pilot_id=pilot_id
    )
    completed, failures, retrieval_plan, _ = dev._scan(
        repo_root=root,
        output_root=Path(paths["retrieval_output"]),
        run_id=str(paths["retrieval_run_id"]),
    )
    retrieval_state = dev._state(
        completed=completed, failures=failures, plan=retrieval_plan
    )
    wrapper_retry_failures = _wrapper_retry_failure_outcomes(pilot_root)
    active_retrieval_failures = _active_retrieval_failures(
        completed=completed, failures=failures
    )
    active_retrieval_keys = {
        RunKey(item["condition_id"], item["question_id"])
        for item in active_retrieval_failures
    }
    retrieval_retry_exhausted = bool(wrapper_retry_failures) or any(
        sum(
            RunKey(item["condition_id"], item["question_id"]) == key
            for item in active_retrieval_failures
        )
        >= 2
        for key in active_retrieval_keys
    )
    answer_root = Path(paths["answer_output"])
    answer_run_id = str(paths["answer_run_id"])
    if (answer_root / answer_run_id / "plan.json").is_file():
        answer_store, answer_checkpoint = verify_run_store(answer_root, answer_run_id)
        answer_records = [
            record
            for key in answer_store.plan.execution_order
            if (record := answer_store.load_completed(key)) is not None
        ]
        answer_active_failed_keys = sum(
            bool(answer_store.failure_attempts(key))
            for key in _answer_pending_order(answer_store)
        )
        answer_retry_exhausted = any(
            len(answer_store.failure_attempts(key)) >= 2
            for key in _answer_pending_order(answer_store)
        )
    else:
        answer_records = []
        answer_active_failed_keys = 0
        answer_retry_exhausted = False
        answer_checkpoint = {
            "planned": PILOT_RECORD_COUNT,
            "completed": 0,
            "pending": PILOT_RECORD_COUNT,
            "failed_attempts": 0,
            "pending_keys": [],
        }
    required_served = manifest["deployment"]["required_served_model"]
    retrieval_identity_verified = all(
        bundle.model["requested_model"] == MODEL2_REQUESTED_MODEL_ALIAS
        and set(bundle.model["served_models"]) == {required_served}
        for bundle in completed.values()
    )
    answer_identity_verified = all(
        record.answer_result.requested_model == MODEL2_REQUESTED_MODEL_ALIAS
        and set(record.answer_result.served_models) == {required_served}
        for record in answer_records
    )
    if not retrieval_identity_verified or not answer_identity_verified:
        _publish_identity_drift_marker(
            pilot_root=pilot_root,
            manifest=manifest,
            observed_served_model=None,
            reason="verified pilot artifact violated the frozen model identity",
        )
        raise ModelIdentityError("Model 2 pilot artifact model identity differs")
    identity_drift = (pilot_root / PILOT_IDENTITY_DRIFT_NAME).is_file()
    status = (
        "halted-model-identity-drift"
        if identity_drift
        else "completed"
        if retrieval_state["verified_episode_count"] == 36
        and answer_checkpoint["completed"] == PILOT_RECORD_COUNT
        else "failed"
        if retrieval_state["status"] == "failed" or answer_checkpoint["failed_attempts"]
        else "pending"
    )
    body = {
        "schema_version": 1,
        "protocol_version": MODEL2_PILOT_PIPELINE_PROTOCOL_VERSION,
        "pilot_id": pilot_id,
        "pilot_pipeline_manifest_id": manifest["pilot_pipeline_manifest_id"],
        "status": status,
        "identity_drift_halted": identity_drift,
        "retrieval": {
            "planned": 36,
            "completed": retrieval_state["verified_episode_count"],
            "pending": retrieval_state["pending_episode_count"],
            "failure_attempts": retrieval_state["method_failure_attempt_count"]
            + len(wrapper_retry_failures),
            "active_failed_keys": len(active_retrieval_keys),
            "wrapper_retry_failure_attempts": len(wrapper_retry_failures),
            "retry_exhausted": retrieval_retry_exhausted,
            "identity_verified": retrieval_identity_verified,
            "next_key": retrieval_state["next_key"],
        },
        "answers": {
            "planned": PILOT_RECORD_COUNT,
            "completed": answer_checkpoint["completed"],
            "pending": answer_checkpoint["pending"],
            "failure_attempts": answer_checkpoint["failed_attempts"],
            "active_failed_keys": answer_active_failed_keys,
            "retry_exhausted": answer_retry_exhausted,
            "identity_verified": answer_identity_verified,
            "next_key": (
                answer_checkpoint["pending_keys"][0]
                if answer_checkpoint.get("pending_keys") else None
            ),
        },
        "updated_at": _now(),
    }
    _write_atomic(pilot_root / PILOT_STATUS_NAME, body)
    return body


def _trace_files_complete(retrieval_root: Path, plan: Any) -> bool:
    for key in plan.execution_order:
        path = retrieval_root / key.condition_id / key.question_id / "trace.jsonl"
        if path.is_symlink() or not path.is_file():
            return False
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                value = json.loads(line)
                if not isinstance(value, dict):
                    return False
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
    return True


def _answer_completion_precedes_finalize(answer_run_root: Path) -> bool:
    """Prove the post-completion gold evaluation boundary from append-only events."""
    events = answer_run_root / "events.jsonl"
    if events.is_symlink() or not events.is_file():
        return False
    verified: set[tuple[str, str]] = set()
    try:
        for line in events.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if not isinstance(row, dict):
                return False
            if row.get("event") == "answer_verified":
                condition = row.get("condition_id")
                question = row.get("question_id")
                if not isinstance(condition, str) or not isinstance(question, str):
                    return False
                verified.add((condition, question))
            if row.get("event") == "pilot_finalized":
                return len(verified) == PILOT_RECORD_COUNT
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return False


def _judge_artifacts_absent(*roots: Path) -> bool:
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if "judge" in path.name.casefold():
                return False
    return True


def _audit_retry_authorizations(
    *,
    pilot_root: Path,
    manifest: Mapping[str, Any],
    retrieval_failures: list[dict[str, Any]],
    answer_store: Any,
) -> dict[str, int]:
    """Re-derive every consumed retry decision from immutable failure evidence."""
    recovery_root = pilot_root / "recovery"
    if not recovery_root.exists():
        if retrieval_failures or any(
            answer_store.failure_attempts(key)
            for key in answer_store.plan.execution_order
        ):
            raise EvidenceValidationError(
                "Model 2 failures exist without recovery evidence"
            )
        return {
            "retrieval_authorizations": 0,
            "answer_authorizations": 0,
            "retrieval_failed_attempt_tokens": 0,
            "retrieval_failed_usage_unavailable_calls": 0,
            "answer_failed_attempt_prompt_tokens": 0,
            "answer_failed_attempt_completion_tokens": 0,
            "answer_failed_attempt_total_tokens": 0,
            "answer_failed_usage_unavailable_calls": 0,
        }
    if recovery_root.is_symlink() or not recovery_root.is_dir():
        raise EvidenceValidationError("Model 2 recovery directory is unsafe")

    retrieval_by_id = {
        str(item["failure_id"]): item for item in retrieval_failures
    }
    retrieval_covered: set[str] = set()
    retrieval_policies = 0
    retrieval_failed_usage_unavailable_calls = 0
    for path in sorted(recovery_root.glob("model2-pilot-recovery-*.json")):
        policy = _read_json(path)
        identity = policy.get("recovery_id")
        body = {
            key: value for key, value in policy.items() if key != "recovery_id"
        }
        if identity != "model2-pilot-recovery-" + sha256_bytes(
            canonical_json_bytes(body)
        ):
            raise EvidenceValidationError("Model 2 recovery hash differs")
        failure = retrieval_by_id.get(str(policy.get("prior_failure_id")))
        if failure is None:
            raise EvidenceValidationError(
                "Model 2 retrieval recovery references an unknown failure"
            )
        companion = _load_retrieval_failure_evidence(
            pilot_root=pilot_root,
            manifest=manifest,
            failure=failure,
        )
        evidence = _retrieval_retry_evidence(failure, companion)
        if (
            policy.get("pilot_pipeline_manifest_id")
            != manifest["pilot_pipeline_manifest_id"]
            or policy.get("retry_key")
            != {
                "condition_id": failure["condition_id"],
                "question_id": failure["question_id"],
            }
            or policy.get("prior_failure_kind") != failure["failure_kind"]
            or policy.get("retry_eligibility_evidence") != evidence
            or evidence.get("eligible") is not True
            or policy.get("maximum_whole_episode_retries") != 1
            or policy.get("preserve_failure_artifact") is not True
            or policy.get("include_failed_attempt_cost_in_final_audit") is not True
            or policy.get("configuration_overrides") != "forbidden"
            or policy.get("authorization")
            != "automatic-bounded-retry-after-frozen-evidence-check"
        ):
            raise EvidenceValidationError(
                "Model 2 retrieval recovery evidence is inconsistent"
            )
        consumed = _read_json(
            recovery_root / f"consumed-{identity}.json"
        )
        if (
            consumed.get("status") != "consumed"
            or consumed.get("recovery_id") != identity
            or consumed.get("pilot_pipeline_manifest_id")
            != manifest["pilot_pipeline_manifest_id"]
            or consumed.get("retry_key") != policy.get("retry_key")
            or consumed.get("prior_failure_id") != policy.get("prior_failure_id")
        ):
            raise EvidenceValidationError(
                "Model 2 retrieval recovery consumption differs"
            )
        failure_id = str(policy["prior_failure_id"])
        if failure_id in retrieval_covered:
            raise EvidenceValidationError(
                "Model 2 retrieval failure has duplicate retry authorization"
            )
        retrieval_covered.add(failure_id)
        retrieval_policies += 1
        retrieval_failed_usage_unavailable_calls += int(
            companion["failed_attempt_usage"]["usage_unavailable_count"]
        )

    answer_failures = {
        failure.failure_id: failure
        for key in answer_store.plan.execution_order
        for failure in answer_store.failure_attempts(key)
    }
    answer_covered: set[str] = set()
    answer_policies = 0
    answer_failed_prompt_tokens = 0
    answer_failed_completion_tokens = 0
    answer_failed_total_tokens = 0
    answer_failed_usage_unavailable_calls = 0
    for path in sorted(recovery_root.glob("model2-pilot-answer-recovery-*.json")):
        policy = _read_json(path)
        identity = policy.get("answer_recovery_id")
        body = {
            key: value
            for key, value in policy.items()
            if key != "answer_recovery_id"
        }
        if identity != "model2-pilot-answer-recovery-" + sha256_bytes(
            canonical_json_bytes(body)
        ):
            raise EvidenceValidationError("Model 2 answer recovery hash differs")
        failure = answer_failures.get(str(policy.get("prior_failure_id")))
        if failure is None:
            raise EvidenceValidationError(
                "Model 2 answer recovery references an unknown failure"
            )
        evidence = _load_answer_failure_evidence(
            pilot_root=pilot_root,
            manifest=manifest,
            store=answer_store,
            failure=failure,
        )
        if (
            policy.get("pilot_pipeline_manifest_id")
            != manifest["pilot_pipeline_manifest_id"]
            or policy.get("retry_key") != failure.key.to_dict()
            or policy.get("prior_failure_stage") != failure.stage
            or policy.get("prior_failure_attempt") != failure.attempt
            or policy.get("retry_eligibility_evidence_id")
            != evidence["answer_failure_evidence_id"]
            or policy.get("maximum_whole_answer_retries") != 1
            or policy.get("preserve_failure_artifact") is not True
            or policy.get("include_failed_attempt_cost_in_final_audit") is not True
            or policy.get("configuration_overrides") != "forbidden"
        ):
            raise EvidenceValidationError(
                "Model 2 answer recovery evidence is inconsistent"
            )
        consumed = _read_json(
            recovery_root / f"consumed-{identity}.json"
        )
        if (
            consumed.get("status") != "consumed"
            or consumed.get("answer_recovery_id") != identity
            or consumed.get("pilot_pipeline_manifest_id")
            != manifest["pilot_pipeline_manifest_id"]
            or consumed.get("retry_key") != policy.get("retry_key")
            or consumed.get("prior_failure_id") != policy.get("prior_failure_id")
        ):
            raise EvidenceValidationError(
                "Model 2 answer recovery consumption differs"
            )
        failure_id = str(policy["prior_failure_id"])
        if failure_id in answer_covered:
            raise EvidenceValidationError(
                "Model 2 answer failure has duplicate retry authorization"
            )
        answer_covered.add(failure_id)
        answer_policies += 1
        failed_usage = evidence["failed_attempt_usage"]
        answer_failed_prompt_tokens += int(failed_usage["prompt_tokens"])
        answer_failed_completion_tokens += int(failed_usage["completion_tokens"])
        answer_failed_total_tokens += int(failed_usage["total_tokens"])
        answer_failed_usage_unavailable_calls += int(
            failed_usage["usage_unavailable_count"]
        )

    if retrieval_covered != set(retrieval_by_id):
        raise EvidenceValidationError(
            "Model 2 retrieval failure/recovery coverage differs"
        )
    if answer_covered != set(answer_failures):
        raise EvidenceValidationError(
            "Model 2 answer failure/recovery coverage differs"
        )
    if _wrapper_retry_failure_outcomes(pilot_root):
        raise EvidenceValidationError(
            "A retry-exhausted Model 2 pilot cannot pass final audit"
        )
    companion_paths = sorted(
        recovery_root.glob("answer-failure-evidence-*.json")
    )
    if len(companion_paths) != len(answer_failures):
        raise EvidenceValidationError(
            "Model 2 answer companion evidence count differs"
        )
    retrieval_companion_paths = sorted(
        recovery_root.glob("retrieval-failure-evidence-*.json")
    )
    if len(retrieval_companion_paths) != len(retrieval_failures):
        raise EvidenceValidationError(
            "Model 2 retrieval companion evidence count differs"
        )
    return {
        "retrieval_authorizations": retrieval_policies,
        "answer_authorizations": answer_policies,
        "retrieval_failed_attempt_tokens": sum(
            int(item["total_tokens"]) for item in retrieval_failures
        ),
        "retrieval_failed_usage_unavailable_calls": (
            retrieval_failed_usage_unavailable_calls
        ),
        "answer_failed_attempt_prompt_tokens": answer_failed_prompt_tokens,
        "answer_failed_attempt_completion_tokens": answer_failed_completion_tokens,
        "answer_failed_attempt_total_tokens": answer_failed_total_tokens,
        "answer_failed_usage_unavailable_calls": answer_failed_usage_unavailable_calls,
    }


def finalize_model2_pilot(
    *, repo_root: Path, output_root: Path, pilot_id: str
) -> dict[str, Any]:
    """Run strict Model 2 identity/operational audit after the 42-record boundary."""
    root = Path(repo_root).resolve()
    pilot_root, manifest, paths = _open_pipeline(
        repo_root=root, output_root=output_root, pilot_id=pilot_id
    )
    _assert_no_identity_drift(pilot_root)
    retrieval_output = Path(paths["retrieval_output"])
    retrieval_run_id = str(paths["retrieval_run_id"])
    answer_output = Path(paths["answer_output"])
    answer_run_id = str(paths["answer_run_id"])
    completed, failures, retrieval_plan, retrieval_manifest = dev._scan(
        repo_root=root, output_root=retrieval_output, run_id=retrieval_run_id
    )
    answer_store, answer_checkpoint = verify_run_store(answer_output, answer_run_id)
    if len(completed) != 36 or answer_checkpoint["completed"] != 42 or answer_checkpoint["pending"]:
        raise EvidenceValidationError("Cannot finalize incomplete Model 2 pilot")
    records = [answer_store.load_completed(key) for key in answer_store.plan.execution_order]
    if any(record is None for record in records):
        raise EvidenceValidationError("Model 2 pilot answer record disappeared")
    answer_records = [record for record in records if record is not None]
    required_served = manifest["deployment"]["required_served_model"]
    retrieval_bundles = [completed[key] for key in retrieval_plan.execution_order]
    retrieval_models = {
        model for bundle in retrieval_bundles for model in bundle.model["served_models"]
    }
    answer_models = {
        model for record in answer_records for model in record.answer_result.served_models
    }
    requested_aliases = {
        *(bundle.model["requested_model"] for bundle in retrieval_bundles),
        *(record.answer_result.requested_model for record in answer_records),
    }
    citation_valid = all(
        set(record.answer_result.citations)
        <= {item.evidence_id for item in record.evidence_bundle.evidence_items}
        for record in answer_records
    )
    stores_unchanged = all(
        bundle.integrity.get("verified") is True
        and bundle.integrity.get("store_unchanged") is True
        for bundle in retrieval_bundles
    )
    source = legacy_pilot.load_retrieval_source(
        repo_root=root,
        retrieval_output_root=retrieval_output,
        retrieval_run_id=retrieval_run_id,
    )
    rank_invariant = all(
        legacy_pilot._r2_first_rank_backend_invariant(source, condition, question_id)
        for question_id in answer_store.plan.question_ids
        for condition in ("E2", "E4")
    )
    e7_records = [record for record in answer_records if record.key.condition_id == "E7"]
    e7_no_retrieval = all(
        isinstance(record.evidence_bundle, FusionEvidenceBundle)
        and record.evidence_bundle.retrieval_metrics.get("search_calls") == 0
        and record.evidence_bundle.retrieval_metrics.get("reused_upstream_retrieval") is True
        for record in e7_records
    )
    e7_cost_exact = True
    e7_source_models_exact = True
    for e7 in e7_records:
        e2 = answer_store.load_completed(RunKey("E2", e7.key.question_id))
        e6 = answer_store.load_completed(RunKey("E6", e7.key.question_id))
        if e2 is None or e6 is None:
            e7_cost_exact = False
            e7_source_models_exact = False
            continue
        expected_retrieval_tokens = int(e2.retrieval_metrics["total_tokens"]) + int(
            e6.retrieval_metrics["total_tokens"]
        )
        e7_cost_exact &= (
            int(e7.retrieval_metrics["total_tokens"]) == expected_retrieval_tokens
            and int(e7.deployment_metrics["total_tokens"])
            == expected_retrieval_tokens + int(e7.answer_metrics["total_tokens"])
        )
        source_models = {
            *e2.answer_result.served_models,
            *e6.answer_result.served_models,
            *e7.answer_result.served_models,
        }
        e7_source_models_exact &= source_models == {required_served}

    retrieval_failures = len(failures)
    answer_failures = sum(
        len(answer_store.failure_attempts(key)) for key in answer_store.plan.execution_order
    )
    retry_audit = _audit_retry_authorizations(
        pilot_root=pilot_root,
        manifest=manifest,
        retrieval_failures=failures,
        answer_store=answer_store,
    )
    retrieval_attempts = 36 + retrieval_failures
    answer_attempts = 42 + answer_failures
    retrieval_failure_rate = retrieval_failures / retrieval_attempts
    answer_failure_rate = answer_failures / answer_attempts
    skipped_episodes = sum(bundle.budget.skipped_items > 0 for bundle in retrieval_bundles)
    skip_fraction = skipped_episodes / 36
    max_successful_retrieval_tokens = max(
        int(bundle.metrics["total_tokens"]) for bundle in retrieval_bundles
    )
    max_failed_retrieval_tokens = max(
        (int(item["total_tokens"]) for item in failures), default=0
    )
    max_tokens = max(max_successful_retrieval_tokens, max_failed_retrieval_tokens)
    answer_repair_metrics_complete = all(
        isinstance(record.answer_result.format_repairs, int)
        and 0 <= record.answer_result.format_repairs <= 1
        for record in answer_records
    )
    cap_metrics_complete = all(
        isinstance(bundle.metrics.get("provider_rounds"), int)
        and isinstance(bundle.stop.hit_cap, bool)
        for bundle in retrieval_bundles
    )
    trace_complete = _trace_files_complete(
        retrieval_output / retrieval_run_id, retrieval_plan
    )
    answer_run_root = answer_output / answer_run_id
    conditions = {
        condition: sum(record.key.condition_id == condition for record in answer_records)
        for condition in CONDITION_IDS
    }
    expected_deployment = {
        "endpoint": MODEL2_CHAT_ENDPOINT,
        "api_style": MODEL2_API_STYLE,
        "request_timeout_seconds": MODEL2_REQUEST_TIMEOUT_SECONDS,
        "max_response_bytes": MODEL2_MAX_RESPONSE_BYTES,
        "context_limit": MODEL2_CONTEXT_LIMIT,
        "concurrency": MODEL2_CONCURRENCY,
    }
    deployment_contract_exact = all(
        manifest["deployment"].get(key) == value
        for key, value in expected_deployment.items()
    )
    successful_retrieval_tokens = sum(
        int(bundle.metrics["total_tokens"]) for bundle in retrieval_bundles
    )
    successful_answer_tokens = sum(
        int(record.answer_metrics["total_tokens"]) for record in answer_records
    )
    failed_attempt_tokens = (
        retry_audit["retrieval_failed_attempt_tokens"]
        + retry_audit["answer_failed_attempt_total_tokens"]
    )
    known_model_tokens_including_failed_attempts = (
        successful_retrieval_tokens
        + successful_answer_tokens
        + failed_attempt_tokens
    )
    usage_unavailable_call_count = (
        retry_audit["retrieval_failed_usage_unavailable_calls"]
        + retry_audit["answer_failed_usage_unavailable_calls"]
    )
    checks = {
        "records_42_complete": len(answer_records) == 42 and answer_checkpoint["pending"] == 0,
        "conditions_6_each": set(conditions.values()) == {6},
        "no_active_failures": all(
            answer_store.load_completed(key) is not None
            for key in answer_store.plan.execution_order
        ),
        "requested_alias_exact": requested_aliases == {MODEL2_REQUESTED_MODEL_ALIAS},
        "served_model_exact": retrieval_models == answer_models == {required_served},
        "deployment_contract_exact": deployment_contract_exact,
        "retry_authorization_evidence_exact": (
            retry_audit["retrieval_authorizations"] == retrieval_failures
            and retry_audit["answer_authorizations"] == answer_failures
        ),
        "failed_attempt_cost_accounting_explicit": (
            known_model_tokens_including_failed_attempts
            == successful_retrieval_tokens
            + successful_answer_tokens
            + retry_audit["retrieval_failed_attempt_tokens"]
            + retry_audit["answer_failed_attempt_total_tokens"]
            and usage_unavailable_call_count >= 0
        ),
        "retrieval_failure_rate_lt_5_percent": retrieval_failure_rate
        < SYSTEM_FAILURE_RATE_LIMIT,
        "answer_failure_rate_lt_5_percent": answer_failure_rate
        < SYSTEM_FAILURE_RATE_LIMIT,
        "citations_valid": citation_valid,
        "stores_unchanged": stores_unchanged,
        "e2_e4_top5_backend_invariant": rank_invariant,
        "budget_skip_fraction_lt_20_percent": skip_fraction
        < BUDGET_SKIP_EPISODE_FRACTION_LIMIT,
        "no_empty_evidence_bundles": all(bundle.evidence_items for bundle in retrieval_bundles),
        "token_safety_fuse_not_hit": (
            max_tokens < TOKEN_SAFETY_FUSE_LIMIT
            and retry_audit["retrieval_failed_usage_unavailable_calls"] == 0
        ),
        "caps_exact": manifest["caps"]
        == {
            "r1_round_cap_by_condition": R1_ROUND_CAP_BY_CONDITION,
            "r2_action_cap": R2_ACTION_CAP,
            "r3_action_cap": R3_ACTION_CAP,
        },
        "runtime_metrics_complete": cap_metrics_complete
        and trace_complete
        and answer_repair_metrics_complete,
        "whole_item_budget_only": all(
            bundle.budget.unit == "characters"
            and bundle.budget.limit == 16_000
            and bundle.budget.truncated is False
            for bundle in retrieval_bundles
        )
        and manifest["evidence_budget"]
        == {
            "unit": "characters",
            "single_source_limit": 16_000,
            "whole_items_only": True,
            "e7_per_source_limit": 16_000,
            "e7_total_limit": 32_000,
        },
        "e7_no_retrieval": len(e7_records) == 6 and e7_no_retrieval,
        "e7_budget_and_cost_exact": all(
            isinstance(record.evidence_bundle, FusionEvidenceBundle)
            and record.evidence_bundle.budget.per_source_limit == 16_000
            and record.evidence_bundle.budget.total_limit == 32_000
            for record in e7_records
        )
        and e7_cost_exact,
        "e7_source_models_exact": e7_source_models_exact,
        "gold_loaded_only_after_42": (
            (answer_run_root / "evaluation.json").is_file()
            and answer_checkpoint["completed"] == 42
            and _answer_completion_precedes_finalize(answer_run_root)
        ),
        "judge_not_called": manifest.get("judge_policy") == "forbidden"
        and _judge_artifacts_absent(pilot_root, retrieval_output, answer_output),
    }
    body = {
        "schema_version": 1,
        "protocol_version": MODEL2_PILOT_PIPELINE_PROTOCOL_VERSION,
        "pilot_id": pilot_id,
        "pilot_pipeline_manifest_id": manifest["pilot_pipeline_manifest_id"],
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "metrics": {
            "completed_by_condition": conditions,
            "retrieval_system_failure_attempts": retrieval_failures,
            "retrieval_system_failure_rate": retrieval_failure_rate,
            "answer_system_failure_attempts": answer_failures,
            "answer_system_failure_rate": answer_failure_rate,
            "retry_authorizations": {
                "retrieval": retry_audit["retrieval_authorizations"],
                "answers": retry_audit["answer_authorizations"],
            },
            "token_cost_accounting": {
                "successful_retrieval_tokens": successful_retrieval_tokens,
                "successful_answer_tokens": successful_answer_tokens,
                "failed_retrieval_attempt_tokens": retry_audit[
                    "retrieval_failed_attempt_tokens"
                ],
                "failed_answer_attempt_prompt_tokens": retry_audit[
                    "answer_failed_attempt_prompt_tokens"
                ],
                "failed_answer_attempt_completion_tokens": retry_audit[
                    "answer_failed_attempt_completion_tokens"
                ],
                "failed_answer_attempt_total_tokens": retry_audit[
                    "answer_failed_attempt_total_tokens"
                ],
                "retrieval_failed_usage_unavailable_calls": retry_audit[
                    "retrieval_failed_usage_unavailable_calls"
                ],
                "answer_failed_usage_unavailable_calls": retry_audit[
                    "answer_failed_usage_unavailable_calls"
                ],
                "usage_unavailable_call_count": usage_unavailable_call_count,
                "known_total_model_tokens": (
                    known_model_tokens_including_failed_attempts
                ),
                "completeness": (
                    "complete"
                    if usage_unavailable_call_count == 0
                    else "partial-known-token-lower-bound"
                ),
            },
            "budget_skipped_episode_count": skipped_episodes,
            "budget_skipped_episode_fraction": skip_fraction,
            "empty_evidence_bundles": sum(not bundle.evidence_items for bundle in retrieval_bundles),
            "max_retrieval_episode_total_tokens": max_tokens,
            "max_successful_retrieval_episode_total_tokens": (
                max_successful_retrieval_tokens
            ),
            "max_failed_retrieval_episode_total_tokens": (
                max_failed_retrieval_tokens
            ),
            "served_models": sorted(retrieval_models | answer_models),
            "deployment_contract": expected_deployment,
        },
        "legacy_post_completion_audit_path": str(
            answer_output / answer_run_id / "audit.json"
        ),
        "legacy_post_completion_evaluation_path": str(
            answer_output / answer_run_id / "evaluation.json"
        ),
        "evaluated_at": _now(),
    }
    audit = {
        "model2_pilot_audit_id": "model2-pilot-audit-"
        + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    _publish_json(pilot_root / PILOT_FINAL_AUDIT_NAME, audit)
    if audit["status"] == "passed":
        _publish_json(
            pilot_root / PILOT_PASSED_MARKER_NAME,
            {
                "status": "passed",
                "pilot_id": pilot_id,
                "model2_pilot_audit_id": audit["model2_pilot_audit_id"],
            },
        )
    write_model2_pilot_status(repo_root=root, output_root=output_root, pilot_id=pilot_id)
    return audit
