"""Offline LoCoMo, evidence, citation, cost, and anonymous-judge evaluation.

Gold data is loaded only in this module, after retrieval and answering have produced
content-addressed RunRecords.  The deterministic F1 follows the official LoCoMo
``task_eval/evaluation.py`` at the pinned data commit, including NLTK 3.8.1 Porter
stemming and the category-specific multi-answer rule.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import string
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from .agent import ChatProvider, TransientProviderError
from .evidence import EvidenceValidationError, canonical_json_bytes, sha256_bytes
from .run_records import RunRecord, verify_run_store
from .vendor.locomo_porter import PorterStemmer


LOCOMO_EVALUATOR_REPOSITORY = "https://github.com/snap-research/locomo"
LOCOMO_EVALUATOR_COMMIT = "cbfbc1dba6bc53d00625212a0f22d55ffee7c1fc"
LOCOMO_EVALUATOR_PATH = "task_eval/evaluation.py"
LOCOMO_EVALUATOR_SHA256 = "8e3be5d57ff2ff9ec5cd05939592f468c5f3f1fd95d13e431932bdf6bf0fd6fd"
LOCOMO_NLTK_VERSION = "3.8.1"
EVALUATION_PROTOCOL_VERSION = "locomo-e1-e7-evaluation-v1"
RELIABLE_POOL_CATEGORY_COUNTS = MappingProxyType({1: 30, 2: 32, 3: 7, 4: 85})

JUDGE_PROTOCOL_VERSION = "anonymous-correctness-judge-v1"
JUDGE_PROMPT_ID = "project-defined-anonymous-correctness-judge-v1"
JUDGE_SYSTEM_PROMPT = """Evaluate a candidate answer against a reference answer.

Use semantic equivalence: concise paraphrases are acceptable. Label `correct` only
when the candidate conveys all information required by the reference without a
material contradiction. Label `partial` when it contains some correct required
information but is incomplete or mixed with a material unsupported claim. Otherwise
label `incorrect`.

Return exactly one JSON object with exactly these keys:
{"label":"correct|partial|incorrect","binary_correct":0_or_1,
 "short_reason":string,"confidence":"high|medium|low"}
binary_correct must be 1 only for label=correct. Return JSON only and do not reveal
hidden reasoning."""
JUDGE_PROMPT_SHA256 = sha256_bytes(JUDGE_SYSTEM_PROMPT.encode("utf-8"))


_STEMMER = PorterStemmer()
_GOLD_KEYS = frozenset(
    {
        "schema_version",
        "question_set_id",
        "question_id",
        "source_qa_index",
        "non_adversarial_order",
        "category",
        "category_name",
        "answer",
        "gold_evidence_dia_ids_official",
        "gold_evidence_dia_ids",
        "gold_evidence_locators",
        "gold_evidence_sessions",
        "has_caption_evidence",
    }
)


def normalize_answer(value: str) -> str:
    """Official LoCoMo normalization without the third-party ``regex`` package."""
    if not isinstance(value, str):
        raise EvidenceValidationError("LoCoMo answer must be a string")
    value = value.replace(",", "").lower()
    value = "".join(character for character in value if character not in set(string.punctuation))
    value = re.sub(r"\b(a|an|the|and)\b", " ", value)
    return " ".join(value.split())


def locomo_f1_score(prediction: str, ground_truth: str) -> float:
    prediction_tokens = [_STEMMER.stem(word) for word in normalize_answer(prediction).split()]
    truth_tokens = [_STEMMER.stem(word) for word in normalize_answer(ground_truth).split()]
    common = Counter(prediction_tokens) & Counter(truth_tokens)
    same = sum(common.values())
    if same == 0:
        return 0.0
    precision = same / len(prediction_tokens)
    recall = same / len(truth_tokens)
    return (2 * precision * recall) / (precision + recall)


def locomo_multi_answer_f1(prediction: str, ground_truth: str) -> float:
    predictions = [part.strip() for part in prediction.split(",")]
    truths = [part.strip() for part in ground_truth.split(",")]
    return sum(
        max(locomo_f1_score(candidate, truth) for candidate in predictions)
        for truth in truths
    ) / len(truths)


def locomo_category_f1(prediction: str, ground_truth: str, category: int) -> float:
    if category == 1:
        return locomo_multi_answer_f1(prediction, ground_truth)
    if category == 3:
        ground_truth = ground_truth.split(";")[0].strip()
    if category in {2, 3, 4}:
        return locomo_f1_score(prediction, ground_truth)
    raise EvidenceValidationError("Only non-adversarial LoCoMo categories 1-4 are supported")


@dataclass(frozen=True)
class GoldRecord:
    schema_version: int
    question_set_id: str
    question_id: str
    source_qa_index: int
    non_adversarial_order: int
    category: int
    category_name: str
    answer: str
    gold_evidence_dia_ids_official: tuple[str, ...]
    gold_evidence_dia_ids: tuple[str, ...]
    gold_evidence_locators: tuple[str, ...]
    gold_evidence_sessions: tuple[int, ...]
    has_caption_evidence: bool

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise EvidenceValidationError("Gold schema version must be 1")
        for value, label in (
            (self.question_set_id, "question_set_id"),
            (self.question_id, "question_id"),
            (self.category_name, "category_name"),
            (self.answer, "answer"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise EvidenceValidationError(f"Gold {label} is invalid")
        for value, label in (
            (self.source_qa_index, "source_qa_index"),
            (self.non_adversarial_order, "non_adversarial_order"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise EvidenceValidationError(f"Gold {label} is invalid")
        if self.category not in {1, 2, 3, 4}:
            raise EvidenceValidationError("Gold category must be 1-4")
        for name in (
            "gold_evidence_dia_ids_official",
            "gold_evidence_dia_ids",
            "gold_evidence_locators",
            "gold_evidence_sessions",
        ):
            value = tuple(getattr(self, name))
            object.__setattr__(self, name, value)
        for name in (
            "gold_evidence_dia_ids_official",
            "gold_evidence_dia_ids",
            "gold_evidence_locators",
        ):
            if any(not isinstance(item, str) or not item.strip() for item in getattr(self, name)):
                raise EvidenceValidationError(f"Gold {name} contains an invalid value")
        if any(
            isinstance(item, bool) or not isinstance(item, int) or item < 1
            for item in self.gold_evidence_sessions
        ):
            raise EvidenceValidationError("Gold evidence sessions contain an invalid value")
        if len(self.gold_evidence_dia_ids) != len(set(self.gold_evidence_dia_ids)):
            raise EvidenceValidationError("Gold canonical dia_ids repeat")
        if not isinstance(self.has_caption_evidence, bool):
            raise EvidenceValidationError("Gold caption flag must be boolean")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GoldRecord":
        if not isinstance(value, Mapping) or set(value) != _GOLD_KEYS:
            raise EvidenceValidationError("Gold record fields are invalid")
        data = dict(value)
        for key in (
            "gold_evidence_dia_ids_official",
            "gold_evidence_dia_ids",
            "gold_evidence_locators",
            "gold_evidence_sessions",
        ):
            data[key] = tuple(data[key])
        return cls(**data)


def load_gold_records(
    path: Path, *, expected_sha256: str | None = None
) -> tuple[GoldRecord, ...]:
    lexical_path = Path(path)
    if lexical_path.is_symlink():
        raise EvidenceValidationError("Gold path must not be a symbolic link")
    path = lexical_path.resolve()
    if not path.is_file():
        raise EvidenceValidationError("Gold path must be a regular file")
    payload = path.read_bytes()
    if expected_sha256 is not None and sha256_bytes(payload) != expected_sha256:
        raise EvidenceValidationError("Gold file hash differs")
    try:
        rows = [json.loads(line) for line in payload.decode("utf-8").splitlines() if line]
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError("Gold JSONL is unreadable") from exc
    records = tuple(GoldRecord.from_mapping(row) for row in rows)
    if not records or len({item.question_id for item in records}) != len(records):
        raise EvidenceValidationError("Gold records must be nonempty and unique")
    if len({item.question_set_id for item in records}) != 1:
        raise EvidenceValidationError("Gold records mix question sets")
    return records


@dataclass(frozen=True)
class JudgeConfig:
    model: str
    reasoning_effort: str = "high"
    max_completion_tokens: int = 1024
    max_rounds: int = 1
    temperature: int = 0


@dataclass(frozen=True)
class CorrectnessJudgeResult:
    label: str
    binary_correct: int
    short_reason: str
    confidence: str
    prompt_sha256: str
    requested_model: str
    served_models: tuple[str, ...]
    provider_request_attempts: int
    model_calls: int
    format_repairs: int
    usage: tuple[Mapping[str, int], ...]

    def __post_init__(self) -> None:
        if self.label not in {"correct", "partial", "incorrect"}:
            raise EvidenceValidationError("Judge label is invalid")
        if (
            isinstance(self.binary_correct, bool)
            or self.binary_correct not in {0, 1}
            or self.binary_correct != int(self.label == "correct")
        ):
            raise EvidenceValidationError("Judge binary label differs")
        if not isinstance(self.short_reason, str) or not self.short_reason.strip():
            raise EvidenceValidationError("Judge reason is empty")
        if self.confidence not in {"high", "medium", "low"}:
            raise EvidenceValidationError("Judge confidence is invalid")
        if self.prompt_sha256 != JUDGE_PROMPT_SHA256:
            raise EvidenceValidationError("Judge prompt hash differs")
        if not isinstance(self.requested_model, str) or not self.requested_model.strip():
            raise EvidenceValidationError("Judge requested model is invalid")
        served = tuple(self.served_models)
        if not served or any(not isinstance(value, str) or not value.strip() for value in served):
            raise EvidenceValidationError("Judge served models are invalid")
        if len(served) != len(set(served)):
            raise EvidenceValidationError("Judge served models repeat")
        for value, label in (
            (self.provider_request_attempts, "provider request attempts"),
            (self.model_calls, "model calls"),
            (self.format_repairs, "format repairs"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise EvidenceValidationError(f"Judge {label} is invalid")
        usage = tuple(MappingProxyType(dict(row)) for row in self.usage)
        if self.model_calls != len(usage) or self.provider_request_attempts < self.model_calls:
            raise EvidenceValidationError("Judge call counters differ")
        if self.format_repairs not in {0, 1} or self.model_calls != 1 + self.format_repairs:
            raise EvidenceValidationError("Judge format repair count differs")
        required_tokens = {"prompt_tokens", "completion_tokens", "total_tokens"}
        for row in usage:
            if set(row) != required_tokens:
                raise EvidenceValidationError("Judge usage fields differ")
            if any(isinstance(row[key], bool) or not isinstance(row[key], int) or row[key] < 0 for key in row):
                raise EvidenceValidationError("Judge usage value is invalid")
            if row["total_tokens"] != row["prompt_tokens"] + row["completion_tokens"]:
                raise EvidenceValidationError("Judge usage total differs")
        object.__setattr__(self, "served_models", served)
        object.__setattr__(self, "usage", usage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "binary_correct": self.binary_correct,
            "short_reason": self.short_reason,
            "confidence": self.confidence,
            "prompt_sha256": self.prompt_sha256,
            "requested_model": self.requested_model,
            "served_models": list(self.served_models),
            "provider_request_attempts": self.provider_request_attempts,
            "model_calls": self.model_calls,
            "format_repairs": self.format_repairs,
            "usage": [dict(row) for row in self.usage],
        }


class AnonymousCorrectnessJudge:
    def __init__(
        self,
        *,
        provider: ChatProvider,
        requested_model: str,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(requested_model, str) or not requested_model.strip():
            raise EvidenceValidationError("Judge model must be nonempty")
        self.provider = provider
        self.requested_model = requested_model
        self.sleeper = sleeper
        self.config = JudgeConfig(requested_model)

    def _complete(self, messages: list[dict[str, str]]) -> tuple[dict[str, Any], int]:
        attempts = 0
        while True:
            attempts += 1
            try:
                response = self.provider.complete(messages, [], self.config)
                if not isinstance(response, Mapping):
                    raise RuntimeError("Judge provider response must be an object")
                return dict(response), attempts
            except TransientProviderError as exc:
                maximum = 5 if exc.kind == "http" else 3
                backoff = (5, 15, 30, 60) if exc.kind == "http" else (2, 4)
                if attempts >= maximum:
                    raise
                self.sleeper(float(backoff[attempts - 1]))

    @staticmethod
    def _parse(content: str) -> dict[str, Any]:
        try:
            value = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("Judge output is not exact JSON") from exc
        required = {"label", "binary_correct", "short_reason", "confidence"}
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("Judge JSON fields differ")
        label = value["label"]
        binary = value["binary_correct"]
        reason = value["short_reason"]
        confidence = value["confidence"]
        if label not in {"correct", "partial", "incorrect"}:
            raise ValueError("Judge label is invalid")
        if isinstance(binary, bool) or binary not in {0, 1} or binary != int(label == "correct"):
            raise ValueError("Judge binary label differs")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Judge reason is empty")
        if confidence not in {"high", "medium", "low"}:
            raise ValueError("Judge confidence is invalid")
        return {
            "label": label,
            "binary_correct": binary,
            "short_reason": reason.strip(),
            "confidence": confidence,
        }

    def run(self, *, question: str, gold_answer: str, candidate_answer: str) -> CorrectnessJudgeResult:
        for value, label in (
            (question, "question"),
            (gold_answer, "gold answer"),
            (candidate_answer, "candidate answer"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise EvidenceValidationError(f"Judge {label} is invalid")
        original_prompt = (
            f"Question:\n{question}\n\nReference answer:\n{gold_answer}"
            f"\n\nCandidate answer:\n{candidate_answer}\n\nReturn the required JSON."
        )
        messages = [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": original_prompt},
        ]
        usages: list[Mapping[str, int]] = []
        served: list[str] = []
        request_attempts = 0
        repairs = 0
        while True:
            response, attempts = self._complete(messages)
            request_attempts += attempts
            message = response.get("message")
            if not isinstance(message, Mapping) or message.get("tool_calls") not in (None, []):
                raise EvidenceValidationError("Judge response message is invalid")
            content = message.get("content")
            usage = response.get("usage")
            model = response.get("served_model")
            if not isinstance(content, str) or not isinstance(usage, Mapping) or not isinstance(model, str) or not model:
                raise EvidenceValidationError("Judge provider response is incomplete")
            required_tokens = {"prompt_tokens", "completion_tokens", "total_tokens"}
            if not required_tokens.issubset(usage) or usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]:
                raise EvidenceValidationError("Judge usage is invalid")
            safe_usage = {key: int(usage[key]) for key in sorted(required_tokens)}
            usages.append(MappingProxyType(safe_usage))
            served.append(model)
            try:
                parsed = self._parse(content)
                break
            except (ValueError, EvidenceValidationError):
                if repairs >= 1:
                    raise EvidenceValidationError("Judge format repair failed")
                repairs += 1
                messages = [
                    {
                        "role": "system",
                        "content": "Reformat the candidate judgment into the exact required JSON. Do not change its decision.",
                    },
                    {"role": "user", "content": content},
                ]
        return CorrectnessJudgeResult(
            **parsed,
            prompt_sha256=JUDGE_PROMPT_SHA256,
            requested_model=self.requested_model,
            served_models=tuple(dict.fromkeys(served)),
            provider_request_attempts=request_attempts,
            model_calls=len(usages),
            format_repairs=repairs,
            usage=tuple(usages),
        )


@dataclass(frozen=True)
class EvaluationResult:
    schema_version: int
    protocol_version: str
    evaluation_id: str
    record_id: str
    run_id: str
    condition_id: str
    question_id: str
    category: int
    category_name: str
    locomo_f1: float
    evidence_eligible: bool
    gold_dia_ids: tuple[str, ...]
    retrieved_dia_ids: tuple[str, ...]
    evidence_recall: float | None
    evidence_any_hit: bool | None
    evidence_all_hit: bool | None
    citation_count: int
    valid_citation_count: int
    citation_validity: float
    cited_dia_ids: tuple[str, ...]
    judge: CorrectnessJudgeResult | None
    costs: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.protocol_version != EVALUATION_PROTOCOL_VERSION:
            raise EvidenceValidationError("EvaluationResult protocol differs")
        if not self.evaluation_id.startswith("eval-") or len(self.evaluation_id) != 69:
            raise EvidenceValidationError("EvaluationResult ID is invalid")
        if self.condition_id not in {"E1", "E2", "E3", "E4", "E5", "E6", "E7"}:
            raise EvidenceValidationError("Evaluation condition is invalid")
        if self.category not in {1, 2, 3, 4} or not 0 <= self.locomo_f1 <= 1:
            raise EvidenceValidationError("Evaluation category or F1 is invalid")
        if self.evidence_eligible:
            if self.evidence_recall is None or self.evidence_any_hit is None or self.evidence_all_hit is None:
                raise EvidenceValidationError("Eligible evidence metrics are missing")
        elif any(value is not None for value in (self.evidence_recall, self.evidence_any_hit, self.evidence_all_hit)):
            raise EvidenceValidationError("Ineligible evidence metrics must be null")
        if self.citation_count < 0 or not 0 <= self.valid_citation_count <= self.citation_count:
            raise EvidenceValidationError("Citation counts are invalid")
        if not 0 <= self.citation_validity <= 1:
            raise EvidenceValidationError("Citation validity is invalid")
        object.__setattr__(self, "costs", MappingProxyType(dict(self.costs)))

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "protocol_version": self.protocol_version,
            "record_id": self.record_id,
            "run_id": self.run_id,
            "condition_id": self.condition_id,
            "question_id": self.question_id,
            "category": self.category,
            "category_name": self.category_name,
            "locomo_f1": self.locomo_f1,
            "evidence_eligible": self.evidence_eligible,
            "gold_dia_ids": list(self.gold_dia_ids),
            "retrieved_dia_ids": list(self.retrieved_dia_ids),
            "evidence_recall": self.evidence_recall,
            "evidence_any_hit": self.evidence_any_hit,
            "evidence_all_hit": self.evidence_all_hit,
            "citation_count": self.citation_count,
            "valid_citation_count": self.valid_citation_count,
            "citation_validity": self.citation_validity,
            "cited_dia_ids": list(self.cited_dia_ids),
            "judge": self.judge.to_dict() if self.judge else None,
            "costs": dict(self.costs),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"evaluation_id": self.evaluation_id, **self._body()}


def evaluate_run_record(
    record: RunRecord,
    gold: GoldRecord,
    *,
    judge: AnonymousCorrectnessJudge | None = None,
) -> EvaluationResult:
    if record.question.question_id != gold.question_id or record.question.question_set_id != gold.question_set_id:
        raise EvidenceValidationError("RunRecord and gold identity differ")
    answer = record.answer_result
    items = tuple(record.evidence_bundle.evidence_items)
    item_by_id = {item.evidence_id: item for item in items}
    retrieved = tuple(dict.fromkeys(dia for item in items for dia in item.dia_ids))
    cited_items = [item_by_id[value] for value in answer.citations if value in item_by_id]
    cited_dia_ids = tuple(dict.fromkeys(dia for item in cited_items for dia in item.dia_ids))
    valid_count = sum(value in item_by_id for value in answer.citations)
    citation_count = len(answer.citations)
    citation_validity = valid_count / citation_count if citation_count else 1.0
    gold_ids = tuple(gold.gold_evidence_dia_ids)
    eligible = bool(gold_ids)
    overlap = set(gold_ids) & set(retrieved)
    judge_result = (
        judge.run(
            question=record.question.question,
            gold_answer=gold.answer,
            candidate_answer=answer.answer,
        )
        if judge is not None
        else None
    )
    values = {
        "schema_version": 1,
        "protocol_version": EVALUATION_PROTOCOL_VERSION,
        "record_id": record.record_id,
        "run_id": record.run_id,
        "condition_id": record.key.condition_id,
        "question_id": gold.question_id,
        "category": gold.category,
        "category_name": gold.category_name,
        "locomo_f1": locomo_category_f1(answer.answer, gold.answer, gold.category),
        "evidence_eligible": eligible,
        "gold_dia_ids": gold_ids,
        "retrieved_dia_ids": retrieved,
        "evidence_recall": len(overlap) / len(gold_ids) if eligible else None,
        "evidence_any_hit": bool(overlap) if eligible else None,
        "evidence_all_hit": set(gold_ids).issubset(retrieved) if eligible else None,
        "citation_count": citation_count,
        "valid_citation_count": valid_count,
        "citation_validity": citation_validity,
        "cited_dia_ids": cited_dia_ids,
        "judge": judge_result,
        "costs": dict(record.deployment_metrics),
    }
    placeholder = EvaluationResult(evaluation_id="eval-" + "0" * 64, **values)
    evaluation_id = "eval-" + sha256_bytes(canonical_json_bytes(placeholder._body()))
    return EvaluationResult(**{**placeholder.__dict__, "evaluation_id": evaluation_id})


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def aggregate_evaluations(results: Sequence[EvaluationResult]) -> dict[str, Any]:
    rows = tuple(results)
    if not rows or len({(row.condition_id, row.question_id) for row in rows}) != len(rows):
        raise EvidenceValidationError("Evaluation rows must be nonempty and unique")
    output: dict[str, Any] = {}
    for condition in sorted({row.condition_id for row in rows}):
        members = [row for row in rows if row.condition_id == condition]
        by_category = {
            str(category): _mean([row.locomo_f1 for row in members if row.category == category])
            for category in (1, 2, 3, 4)
        }
        present = [value for value in by_category.values() if value is not None]
        post_stratified = None
        if all(by_category[str(category)] is not None for category in (1, 2, 3, 4)):
            denominator = sum(RELIABLE_POOL_CATEGORY_COUNTS.values())
            post_stratified = sum(
                float(by_category[str(category)]) * RELIABLE_POOL_CATEGORY_COUNTS[category]
                for category in (1, 2, 3, 4)
            ) / denominator
        evidence_members = [row for row in members if row.evidence_eligible]
        judged = [row for row in members if row.judge is not None]
        token_values = [
            int(row.costs["total_tokens"])
            for row in members
            if isinstance(row.costs.get("total_tokens"), int)
        ]
        judge_token_values = [
            sum(item["total_tokens"] for item in row.judge.usage)
            for row in judged
        ]
        output[condition] = {
            "count": len(members),
            "micro_f1": _mean([row.locomo_f1 for row in members]),
            "category_f1": by_category,
            "category_macro_f1": _mean(present),
            "post_stratified_f1": post_stratified,
            "evidence_eligible_count": len(evidence_members),
            "mean_evidence_recall": _mean([float(row.evidence_recall) for row in evidence_members]),
            "any_hit_rate": _mean([float(row.evidence_any_hit) for row in evidence_members]),
            "all_hit_rate": _mean([float(row.evidence_all_hit) for row in evidence_members]),
            "citation_validity": _mean([row.citation_validity for row in members]),
            "judge_binary_accuracy": _mean([float(row.judge.binary_correct) for row in judged]),
            "judge_partial_rate": _mean([float(row.judge.label == "partial") for row in judged]),
            "judge_total_tokens": sum(judge_token_values),
            "mean_judge_total_tokens": _mean(judge_token_values),
            "mean_total_tokens": _mean(token_values),
        }
    body = {
        "schema_version": 1,
        "protocol_version": EVALUATION_PROTOCOL_VERSION,
        "row_count": len(rows),
        "conditions": output,
        "official_evaluator": {
            "repository": LOCOMO_EVALUATOR_REPOSITORY,
            "commit": LOCOMO_EVALUATOR_COMMIT,
            "path": LOCOMO_EVALUATOR_PATH,
            "sha256": LOCOMO_EVALUATOR_SHA256,
            "nltk_version": LOCOMO_NLTK_VERSION,
        },
    }
    return {**body, "summary_sha256": sha256_bytes(canonical_json_bytes(body))}


def evaluate_run_store(
    *,
    run_root: Path,
    run_id: str,
    gold_path: Path,
    expected_gold_sha256: str,
    judge: AnonymousCorrectnessJudge | None = None,
) -> tuple[EvaluationResult, ...]:
    """Verify and evaluate every completed key in one frozen experiment run.

    The function fails closed when the run is incomplete, when the gold hash is not
    explicitly pinned, or when question-set membership differs.  Gold is never read
    by retrieval or answering code; this is the post-run boundary.
    """
    if not isinstance(expected_gold_sha256, str) or re.fullmatch(
        r"[0-9a-f]{64}", expected_gold_sha256
    ) is None:
        raise EvidenceValidationError("A lowercase pinned gold SHA-256 is required")
    store, checkpoint = verify_run_store(run_root, run_id)
    if checkpoint["pending"] != 0 or checkpoint["completed"] != checkpoint["planned"]:
        raise EvidenceValidationError("Run store is incomplete and cannot be evaluated")
    gold_records = load_gold_records(
        gold_path, expected_sha256=expected_gold_sha256
    )
    gold_by_question = {record.question_id: record for record in gold_records}
    if (
        {record.question_set_id for record in gold_records}
        != {store.plan.question_set_id}
        or set(gold_by_question) != set(store.plan.question_ids)
    ):
        raise EvidenceValidationError("Frozen plan and gold question set differ")
    results: list[EvaluationResult] = []
    for key in store.plan.execution_order:
        record = store.load_completed(key)
        if record is None:  # Defensive: checkpoint already established completeness.
            raise EvidenceValidationError("Run record disappeared during evaluation")
        results.append(evaluate_run_record(record, gold_by_question[key.question_id], judge=judge))
    return tuple(results)


def write_evaluation_report(
    path: Path,
    results: Sequence[EvaluationResult],
) -> Path:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise EvidenceValidationError("Evaluation report already exists")
    body = {
        "summary": aggregate_evaluations(results),
        "results": [row.to_dict() for row in results],
    }
    payload = canonical_json_bytes(body) + b"\n"
    staging = path.parent / f".{path.name}.in-progress-{secrets.token_hex(8)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(staging, flags, 0o600)
    try:
        offset = 0
        while offset < len(payload):
            count = os.write(descriptor, payload[offset:])
            if count <= 0:
                raise OSError("short evaluation report write")
            offset += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        # Same-directory hard linking publishes atomically without overwriting.
        os.link(staging, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        staging.unlink(missing_ok=True)
    return path
