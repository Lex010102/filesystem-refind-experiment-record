"""Safe single-question and sequential-batch execution for E6/R3."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .agent import ChatProvider
from .evidence import EvidenceValidationError, QuestionInput, canonical_json_bytes, sha256_bytes
from .r3_agent import R3AgentError, R3RetrievalAgent
from .r3_artifacts import (
    R3EpisodeWorkspace,
    build_r3_evidence_bundle,
    build_r3_failure_artifact,
    verify_r3_episode_artifact,
    verify_r3_failure_artifact,
)
from .r3_index import R3CuratedIndex
from .r3_inputs import R3CuratedCorpus, load_r3_corpus


R3_RUNNER_PROTOCOL_VERSION = "r3-curated-runner-v1"


@dataclass(frozen=True)
class R3RunResult:
    status: str
    cell_id: str
    question_id: str
    artifact_id: str
    artifact_path: Path

    def __post_init__(self) -> None:
        if self.status not in {"completed", "capped", "failed"}:
            raise EvidenceValidationError("R3 run result status is invalid")
        if self.cell_id != "E6":
            raise EvidenceValidationError("R3 run result cell must be E6")
        if not self.artifact_id or not self.artifact_path.is_absolute():
            raise EvidenceValidationError("R3 run result artifact is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "cell_id": self.cell_id,
            "question_id": self.question_id,
            "artifact_id": self.artifact_id,
            "artifact_path": str(self.artifact_path),
        }


def execute_r3_question(
    *,
    repo_root: Path,
    output_root: Path,
    run_id: str,
    question: QuestionInput,
    provider: ChatProvider,
    requested_model: str,
    budget_unit: str,
    budget_limit: int,
    corpus: R3CuratedCorpus | None = None,
    sleeper=None,
) -> R3RunResult:
    loaded = corpus or load_r3_corpus(repo_root)
    workspace = R3EpisodeWorkspace.create(
        output_root=Path(output_root).resolve(),
        run_id=run_id,
        question_id=question.question_id,
    )
    options: dict[str, Any] = {}
    if sleeper is not None:
        options["sleeper"] = sleeper
    api_style = getattr(provider, "api_style", "portable")
    agent = R3RetrievalAgent(
        index=R3CuratedIndex(loaded),
        provider=provider,
        requested_model=requested_model,
        api_style=api_style,
        event_sink=workspace.sink,
        **options,
    )
    try:
        outcome = agent.run(cell_id="E6", question=question)
    except R3AgentError as error:
        failure = build_r3_failure_artifact(
            error,
            question=question,
            corpus=loaded,
            requested_model=requested_model,
            api_style=api_style,
            budget_unit=budget_unit,
            budget_limit=budget_limit,
        )
        published = workspace.publish_failure(failure)
        verified = verify_r3_failure_artifact(published)
        return R3RunResult(
            status="failed",
            cell_id="E6",
            question_id=question.question_id,
            artifact_id=verified.failure_id,
            artifact_path=published.resolve(),
        )
    bundle = build_r3_evidence_bundle(
        outcome,
        corpus=loaded,
        budget_unit=budget_unit,
        budget_limit=budget_limit,
    )
    published = workspace.publish_success(bundle)
    verified = verify_r3_episode_artifact(published, corpus=loaded)
    return R3RunResult(
        status=verified.status,
        cell_id="E6",
        question_id=question.question_id,
        artifact_id=verified.bundle_id,
        artifact_path=published.resolve(),
    )


def _write_exclusive(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o644)
    try:
        offset = 0
        while offset < len(payload):
            count = os.write(descriptor, payload[offset:])
            if count <= 0:
                raise OSError("short R3 batch-summary write")
            offset += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def execute_r3_batch(
    *,
    repo_root: Path,
    output_root: Path,
    run_id: str,
    questions: Sequence[QuestionInput],
    provider: ChatProvider,
    requested_model: str,
    budget_unit: str,
    budget_limit: int,
    stop_on_failure: bool = True,
    sleeper=None,
) -> tuple[R3RunResult, ...]:
    items = tuple(questions)
    if not items or len({item.question_id for item in items}) != len(items):
        raise EvidenceValidationError("R3 batch questions must be nonempty and unique")
    corpus = load_r3_corpus(repo_root)
    results: list[R3RunResult] = []
    halted = False
    for question in items:
        result = execute_r3_question(
            repo_root=repo_root,
            output_root=output_root,
            run_id=run_id,
            question=question,
            provider=provider,
            requested_model=requested_model,
            budget_unit=budget_unit,
            budget_limit=budget_limit,
            corpus=corpus,
            sleeper=sleeper,
        )
        results.append(result)
        if result.status == "failed" and stop_on_failure:
            halted = True
            break
    body = {
        "protocol_version": R3_RUNNER_PROTOCOL_VERSION,
        "run_id": run_id,
        "cell_id": "E6",
        "question_ids": [item.question_id for item in items],
        "planned_episode_count": len(items),
        "completed_episode_count": len(results),
        "stop_on_failure": stop_on_failure,
        "halted_on_failure": halted,
        "results": [item.to_dict() for item in results],
    }
    body["summary_sha256"] = sha256_bytes(canonical_json_bytes(body))
    run_root = Path(output_root).resolve() / run_id
    _write_exclusive(run_root / "batch-summary.json", canonical_json_bytes(body) + b"\n")
    return tuple(results)


def verify_r3_batch_summary(path: Path, *, repo_root: Path) -> tuple[R3RunResult, ...]:
    summary_path = Path(path)
    if summary_path.is_symlink() or not summary_path.is_file():
        raise EvidenceValidationError("R3 batch summary is not a regular file")
    try:
        value = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError("R3 batch summary is unreadable") from exc
    if not isinstance(value, dict):
        raise EvidenceValidationError("R3 batch summary must be an object")
    digest = value.pop("summary_sha256", None)
    if digest != sha256_bytes(canonical_json_bytes(value)):
        raise EvidenceValidationError("R3 batch summary hash is invalid")
    questions = value.get("question_ids")
    raw_results = value.get("results")
    if (
        value.get("protocol_version") != R3_RUNNER_PROTOCOL_VERSION
        or value.get("cell_id") != "E6"
        or not isinstance(questions, list)
        or not questions
        or len(questions) != len(set(questions))
        or not isinstance(raw_results, list)
        or value.get("planned_episode_count") != len(questions)
        or value.get("completed_episode_count") != len(raw_results)
    ):
        raise EvidenceValidationError("R3 batch summary plan is invalid")
    stop_on_failure = value.get("stop_on_failure")
    halted = value.get("halted_on_failure")
    if not isinstance(stop_on_failure, bool) or not isinstance(halted, bool):
        raise EvidenceValidationError("R3 batch stop flags are invalid")
    if halted:
        if not stop_on_failure or not raw_results or raw_results[-1].get("status") != "failed":
            raise EvidenceValidationError("R3 halted batch lacks a terminal failure")
    elif len(raw_results) != len(questions):
        raise EvidenceValidationError("R3 non-halted batch is incomplete")
    corpus = load_r3_corpus(repo_root)
    results: list[R3RunResult] = []
    run_root = summary_path.parent.resolve()
    if value.get("run_id") != run_root.name:
        raise EvidenceValidationError("R3 batch run identity differs")
    for raw, expected_question in zip(raw_results, questions, strict=False):
        if not isinstance(raw, dict):
            raise EvidenceValidationError("R3 batch result is invalid")
        result = R3RunResult(
            status=raw["status"],
            cell_id=raw["cell_id"],
            question_id=raw["question_id"],
            artifact_id=raw["artifact_id"],
            artifact_path=Path(raw["artifact_path"]),
        )
        if result.question_id != expected_question:
            raise EvidenceValidationError("R3 batch result order differs")
        try:
            result.artifact_path.resolve().relative_to(run_root)
        except ValueError as exc:
            raise EvidenceValidationError("R3 batch artifact escapes its run") from exc
        if result.status == "failed":
            artifact = verify_r3_failure_artifact(result.artifact_path)
            if artifact.failure_id != result.artifact_id:
                raise EvidenceValidationError("R3 batch failure ID differs")
        else:
            bundle = verify_r3_episode_artifact(result.artifact_path, corpus=corpus)
            if bundle.bundle_id != result.artifact_id:
                raise EvidenceValidationError("R3 batch bundle ID differs")
        results.append(result)
    return tuple(results)
