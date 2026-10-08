"""Safe single-question and sequential-batch execution for formal R1 cells."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .agent import ChatProvider
from .evidence import (
    EvidenceValidationError,
    QuestionInput,
    canonical_json_bytes,
    sha256_bytes,
)
from .r1_agent import R1AgentError, R1ResearchAgent
from .r1_artifacts import (
    R1EpisodeWorkspace,
    build_r1_evidence_bundle,
    build_r1_failure_artifact,
    verify_r1_episode_artifact,
    verify_r1_failure_artifact,
)
from .r1_inputs import LoadedR1Store, load_r1_store
from .r1_prompts import R1_PROMPT_PROFILES


R1_RUNNER_PROTOCOL_VERSION = "r1-evidence-runner-v1"


@dataclass(frozen=True)
class R1RunResult:
    status: str
    cell_id: str
    question_id: str
    artifact_id: str
    artifact_path: Path

    def __post_init__(self) -> None:
        if self.status not in {"completed", "capped", "failed"}:
            raise EvidenceValidationError("R1 run result status is invalid")
        if self.cell_id not in R1_PROMPT_PROFILES:
            raise EvidenceValidationError("R1 run result cell is invalid")
        if not self.artifact_id or not self.artifact_path.is_absolute():
            raise EvidenceValidationError("R1 run result artifact is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "cell_id": self.cell_id,
            "question_id": self.question_id,
            "artifact_id": self.artifact_id,
            "artifact_path": str(self.artifact_path),
        }


def execute_r1_question(
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
    loaded_store: LoadedR1Store | None = None,
    sleeper=None,
) -> R1RunResult:
    """Run exactly one isolated episode and atomically publish its result."""
    if cell_id not in R1_PROMPT_PROFILES:
        raise EvidenceValidationError("R1 cell_id must be E1, E3, or E5")
    profile = R1_PROMPT_PROFILES[cell_id]
    store = loaded_store or load_r1_store(repo_root, profile.store_id)
    if store.snapshot.store_id != profile.store_id.casefold():
        raise EvidenceValidationError("R1 loaded store does not match the cell")
    workspace = R1EpisodeWorkspace.create(
        output_root=Path(output_root).resolve(),
        run_id=run_id,
        cell_id=cell_id,
        question_id=question.question_id,
    )
    options: dict[str, Any] = {}
    if sleeper is not None:
        options["sleeper"] = sleeper
    agent = R1ResearchAgent(
        root=store.root,
        catalog=store.catalog,
        verified_manifest=store.verified_manifest,
        snapshot=store.snapshot,
        provider=provider,
        requested_model=requested_model,
        budget_unit=budget_unit,
        budget_limit=budget_limit,
        event_sink=workspace.sink,
        private_checkpoint_path=workspace.private_checkpoint_path,
        **options,
    )
    try:
        outcome = agent.run(cell_id=cell_id, question=question)
    except R1AgentError as error:
        failure = build_r1_failure_artifact(
            error,
            cell_id=cell_id,
            question=question,
            loaded_store=store,
            requested_model=requested_model,
            budget_unit=budget_unit,
            budget_limit=budget_limit,
        )
        published = workspace.publish_failure(artifact=failure)
        verified = verify_r1_failure_artifact(published)
        return R1RunResult(
            status="failed",
            cell_id=cell_id,
            question_id=question.question_id,
            artifact_id=verified.failure_id,
            artifact_path=published.resolve(),
        )
    bundle = build_r1_evidence_bundle(outcome, loaded_store=store)
    published = workspace.publish_success(bundle=bundle, outcome=outcome)
    verified = verify_r1_episode_artifact(published, loaded_store=store)
    return R1RunResult(
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
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short R1 batch-summary write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def execute_r1_batch(
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
) -> tuple[R1RunResult, ...]:
    """Run a deterministic cell-major batch sequentially.

    Sequential execution is intentional for the local study: it makes stop and
    cost accounting unambiguous. Parallelism can be introduced only as a new,
    separately frozen runtime condition.
    """
    cells = tuple(cell_ids)
    items = tuple(questions)
    if not cells or len(set(cells)) != len(cells):
        raise EvidenceValidationError("R1 batch cells must be nonempty and unique")
    if any(cell not in R1_PROMPT_PROFILES for cell in cells):
        raise EvidenceValidationError("R1 batch contains an unknown cell")
    if not items or len({item.question_id for item in items}) != len(items):
        raise EvidenceValidationError("R1 batch questions must be nonempty and unique")
    stores = {
        cell: load_r1_store(repo_root, R1_PROMPT_PROFILES[cell].store_id)
        for cell in cells
    }
    results: list[R1RunResult] = []
    halted = False
    for cell_id in cells:
        for question in items:
            result = execute_r1_question(
                repo_root=repo_root,
                output_root=output_root,
                run_id=run_id,
                cell_id=cell_id,
                question=question,
                provider=provider,
                requested_model=requested_model,
                budget_unit=budget_unit,
                budget_limit=budget_limit,
                loaded_store=stores[cell_id],
                sleeper=sleeper,
            )
            results.append(result)
            if result.status == "failed" and stop_on_failure:
                halted = True
                break
        if halted:
            break
    body = {
        "protocol_version": R1_RUNNER_PROTOCOL_VERSION,
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
    _write_exclusive(
        run_root / "batch-summary.json", canonical_json_bytes(body) + b"\n"
    )
    return tuple(results)


def verify_r1_batch_summary(path: Path, *, repo_root: Path) -> tuple[R1RunResult, ...]:
    """Verify the summary hash, deterministic order, and every episode artifact."""
    summary_path = Path(path)
    if summary_path.is_symlink() or not summary_path.is_file():
        raise EvidenceValidationError("R1 batch summary is not a regular file")
    try:
        value = json.loads(summary_path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError("R1 batch summary is unreadable") from exc
    required = {
        "protocol_version",
        "run_id",
        "cell_ids",
        "question_ids",
        "planned_episode_count",
        "completed_episode_count",
        "stop_on_failure",
        "halted_on_failure",
        "results",
        "summary_sha256",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise EvidenceValidationError("R1 batch summary fields are invalid")
    digest = value.pop("summary_sha256")
    if value.get(
        "protocol_version"
    ) != R1_RUNNER_PROTOCOL_VERSION or digest != sha256_bytes(
        canonical_json_bytes(value)
    ):
        raise EvidenceValidationError("R1 batch summary hash is invalid")
    cells = value["cell_ids"]
    questions = value["question_ids"]
    raw_results = value["results"]
    if (
        not isinstance(cells, list)
        or not cells
        or len(set(cells)) != len(cells)
        or any(cell not in R1_PROMPT_PROFILES for cell in cells)
        or not isinstance(questions, list)
        or not questions
        or len(set(questions)) != len(questions)
        or any(not isinstance(item, str) or not item for item in questions)
        or not isinstance(raw_results, list)
    ):
        raise EvidenceValidationError("R1 batch summary plan is invalid")
    planned = len(cells) * len(questions)
    if (
        value["planned_episode_count"] != planned
        or value["completed_episode_count"] != len(raw_results)
        or len(raw_results) > planned
        or not isinstance(value["stop_on_failure"], bool)
        or not isinstance(value["halted_on_failure"], bool)
        or (not value["halted_on_failure"] and len(raw_results) != planned)
        or (value["halted_on_failure"] and not value["stop_on_failure"])
    ):
        raise EvidenceValidationError("R1 batch summary counts are invalid")
    expected_order = [(cell, question) for cell in cells for question in questions][
        : len(raw_results)
    ]
    stores: dict[str, LoadedR1Store] = {}
    results: list[R1RunResult] = []
    run_root = summary_path.parent.resolve()
    if value["run_id"] != run_root.name:
        raise EvidenceValidationError("R1 batch summary run identity is invalid")
    for raw, (expected_cell, expected_question) in zip(raw_results, expected_order):
        if not isinstance(raw, dict) or set(raw) != {
            "status",
            "cell_id",
            "question_id",
            "artifact_id",
            "artifact_path",
        }:
            raise EvidenceValidationError("R1 batch result fields are invalid")
        result = R1RunResult(
            status=raw["status"],
            cell_id=raw["cell_id"],
            question_id=raw["question_id"],
            artifact_id=raw["artifact_id"],
            artifact_path=Path(raw["artifact_path"]),
        )
        if (result.cell_id, result.question_id) != (
            expected_cell,
            expected_question,
        ):
            raise EvidenceValidationError("R1 batch execution order is invalid")
        try:
            result.artifact_path.resolve().relative_to(run_root)
        except ValueError as exc:
            raise EvidenceValidationError(
                "R1 batch artifact escapes its run directory"
            ) from exc
        if result.cell_id not in stores:
            stores[result.cell_id] = load_r1_store(
                repo_root, R1_PROMPT_PROFILES[result.cell_id].store_id
            )
        if result.status == "failed":
            artifact = verify_r1_failure_artifact(result.artifact_path)
            if (
                artifact.failure_id != result.artifact_id
                or artifact.store_snapshot != stores[result.cell_id].snapshot
            ):
                raise EvidenceValidationError("R1 batch failure identity differs")
        else:
            bundle = verify_r1_episode_artifact(
                result.artifact_path, loaded_store=stores[result.cell_id]
            )
            if bundle.bundle_id != result.artifact_id:
                raise EvidenceValidationError("R1 batch bundle identity differs")
        results.append(result)
    if value["halted_on_failure"] and (not results or results[-1].status != "failed"):
        raise EvidenceValidationError("R1 batch halt lacks a terminal failure")
    return tuple(results)
