"""Safe single-question and sequential-batch execution for R2-Raw."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .agent import ChatProvider
from .evidence import EvidenceValidationError, QuestionInput, canonical_json_bytes, sha256_bytes
from .r1_inputs import load_r1_store
from .r2_agent import R2AgentError, R2RetrievalAgent
from .r2_artifacts import (
    R2EpisodeWorkspace,
    build_r2_evidence_bundle,
    build_r2_failure_artifact,
    verify_r2_episode_artifact,
    verify_r2_failure_artifact,
)
from .r2_index import R2RawIndex
from .r2_inputs import R2RawCorpus, build_r2_raw_corpus


R2_RUNNER_PROTOCOL_VERSION = "r2-raw-runner-v1"
R2_CELL_STORES = {"E2": "s1", "E4": "s2"}


@dataclass(frozen=True)
class R2RunResult:
    status: str
    cell_id: str
    question_id: str
    artifact_id: str
    artifact_path: Path

    def __post_init__(self) -> None:
        if self.status not in {"completed", "capped", "failed"}:
            raise EvidenceValidationError("R2 run result status is invalid")
        if self.cell_id not in R2_CELL_STORES:
            raise EvidenceValidationError("R2 run result cell is invalid")
        if not self.artifact_id or not self.artifact_path.is_absolute():
            raise EvidenceValidationError("R2 run result artifact is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "cell_id": self.cell_id,
            "question_id": self.question_id,
            "artifact_id": self.artifact_id,
            "artifact_path": str(self.artifact_path),
        }


def execute_r2_question(
    *,
    repo_root: Path,
    output_root: Path,
    run_id: str,
    cell_id: str,
    question: QuestionInput,
    provider: ChatProvider,
    requested_model: str,
    budget_unit: str,
    budget_limit: int,
    corpus: R2RawCorpus | None = None,
    sleeper=None,
) -> R2RunResult:
    try:
        store_id = R2_CELL_STORES[cell_id]
    except KeyError as exc:
        raise EvidenceValidationError("R2 cell_id must be E2 or E4") from exc
    loaded = corpus or build_r2_raw_corpus(repo_root, store_id)
    if loaded.store_id != store_id:
        raise EvidenceValidationError("R2 loaded corpus does not match the cell")
    workspace = R2EpisodeWorkspace.create(
        output_root=Path(output_root).resolve(),
        run_id=run_id,
        cell_id=cell_id,
        question_id=question.question_id,
    )
    options: dict[str, Any] = {}
    if sleeper is not None:
        options["sleeper"] = sleeper
    api_style = getattr(provider, "api_style", "portable")
    agent = R2RetrievalAgent(
        index=R2RawIndex(loaded),
        provider=provider,
        requested_model=requested_model,
        api_style=api_style,
        event_sink=workspace.sink,
        **options,
    )
    try:
        outcome = agent.run(cell_id=cell_id, question=question)
    except R2AgentError as error:
        failure = build_r2_failure_artifact(
            error,
            cell_id=cell_id,
            question=question,
            loaded_store=loaded.store,
            corpus_sha256=loaded.corpus_sha256,
            requested_model=requested_model,
            api_style=api_style,
            budget_unit=budget_unit,
            budget_limit=budget_limit,
        )
        published = workspace.publish_failure(failure)
        verified = verify_r2_failure_artifact(published)
        return R2RunResult(
            status="failed",
            cell_id=cell_id,
            question_id=question.question_id,
            artifact_id=verified.failure_id,
            artifact_path=published.resolve(),
        )
    bundle = build_r2_evidence_bundle(
        outcome,
        loaded_store=loaded.store,
        corpus_sha256=loaded.corpus_sha256,
        budget_unit=budget_unit,
        budget_limit=budget_limit,
    )
    published = workspace.publish_success(bundle)
    verified = verify_r2_episode_artifact(published, loaded_store=loaded.store)
    return R2RunResult(
        status=verified.status,
        cell_id=cell_id,
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
                raise OSError("short R2 batch-summary write")
            offset += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def execute_r2_batch(
    *,
    repo_root: Path,
    output_root: Path,
    run_id: str,
    cell_ids: Sequence[str],
    questions: Sequence[QuestionInput],
    provider: ChatProvider,
    requested_model: str,
    budget_unit: str,
    budget_limit: int,
    stop_on_failure: bool = True,
    sleeper=None,
) -> tuple[R2RunResult, ...]:
    cells = tuple(cell_ids)
    items = tuple(questions)
    if not cells or len(cells) != len(set(cells)) or any(cell not in R2_CELL_STORES for cell in cells):
        raise EvidenceValidationError("R2 batch cells must be unique E2/E4 values")
    if not items or len({item.question_id for item in items}) != len(items):
        raise EvidenceValidationError("R2 batch questions must be nonempty and unique")
    corpora = {
        cell: build_r2_raw_corpus(repo_root, R2_CELL_STORES[cell]) for cell in cells
    }
    results: list[R2RunResult] = []
    halted = False
    for cell_id in cells:
        for question in items:
            result = execute_r2_question(
                repo_root=repo_root,
                output_root=output_root,
                run_id=run_id,
                cell_id=cell_id,
                question=question,
                provider=provider,
                requested_model=requested_model,
                budget_unit=budget_unit,
                budget_limit=budget_limit,
                corpus=corpora[cell_id],
                sleeper=sleeper,
            )
            results.append(result)
            if result.status == "failed" and stop_on_failure:
                halted = True
                break
        if halted:
            break
    body = {
        "protocol_version": R2_RUNNER_PROTOCOL_VERSION,
        "run_id": run_id,
        "cell_ids": list(cells),
        "question_ids": [item.question_id for item in items],
        "planned_episode_count": len(cells) * len(items),
        "completed_episode_count": len(results),
        "stop_on_failure": stop_on_failure,
        "halted_on_failure": halted,
        "results": [item.to_dict() for item in results],
    }
    body["summary_sha256"] = sha256_bytes(canonical_json_bytes(body))
    run_root = Path(output_root).resolve() / run_id
    _write_exclusive(run_root / "batch-summary.json", canonical_json_bytes(body) + b"\n")
    return tuple(results)


def verify_r2_batch_summary(path: Path, *, repo_root: Path) -> tuple[R2RunResult, ...]:
    summary_path = Path(path)
    if summary_path.is_symlink() or not summary_path.is_file():
        raise EvidenceValidationError("R2 batch summary is not a regular file")
    try:
        value = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError("R2 batch summary is unreadable") from exc
    if not isinstance(value, dict):
        raise EvidenceValidationError("R2 batch summary must be an object")
    digest = value.pop("summary_sha256", None)
    if digest != sha256_bytes(canonical_json_bytes(value)):
        raise EvidenceValidationError("R2 batch summary hash is invalid")
    if value.get("protocol_version") != R2_RUNNER_PROTOCOL_VERSION:
        raise EvidenceValidationError("R2 batch summary protocol differs")
    cells = value.get("cell_ids")
    questions = value.get("question_ids")
    raw_results = value.get("results")
    if (
        not isinstance(cells, list)
        or not cells
        or any(cell not in R2_CELL_STORES for cell in cells)
        or len(cells) != len(set(cells))
        or not isinstance(questions, list)
        or not questions
        or len(questions) != len(set(questions))
        or not isinstance(raw_results, list)
    ):
        raise EvidenceValidationError("R2 batch summary plan is invalid")
    planned = len(cells) * len(questions)
    if value.get("planned_episode_count") != planned or value.get("completed_episode_count") != len(raw_results):
        raise EvidenceValidationError("R2 batch summary counts differ")
    expected_order = [(cell, question) for cell in cells for question in questions][: len(raw_results)]
    stores = {cell: load_r1_store(repo_root, R2_CELL_STORES[cell]) for cell in cells}
    results: list[R2RunResult] = []
    run_root = summary_path.parent.resolve()
    if value.get("run_id") != run_root.name:
        raise EvidenceValidationError("R2 batch run identity differs")
    for raw, expected in zip(raw_results, expected_order, strict=True):
        if not isinstance(raw, dict):
            raise EvidenceValidationError("R2 batch result is invalid")
        result = R2RunResult(
            status=raw["status"],
            cell_id=raw["cell_id"],
            question_id=raw["question_id"],
            artifact_id=raw["artifact_id"],
            artifact_path=Path(raw["artifact_path"]),
        )
        if (result.cell_id, result.question_id) != expected:
            raise EvidenceValidationError("R2 batch result order differs")
        try:
            result.artifact_path.resolve().relative_to(run_root)
        except ValueError as exc:
            raise EvidenceValidationError("R2 batch artifact escapes its run") from exc
        if result.status == "failed":
            artifact = verify_r2_failure_artifact(result.artifact_path)
            if artifact.failure_id != result.artifact_id:
                raise EvidenceValidationError("R2 batch failure ID differs")
        else:
            bundle = verify_r2_episode_artifact(
                result.artifact_path, loaded_store=stores[result.cell_id]
            )
            if bundle.bundle_id != result.artifact_id:
                raise EvidenceValidationError("R2 batch bundle ID differs")
        results.append(result)
    return tuple(results)
