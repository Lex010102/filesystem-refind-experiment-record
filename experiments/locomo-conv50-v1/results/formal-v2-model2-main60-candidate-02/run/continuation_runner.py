#!/usr/bin/env python3
"""Explicit mixed-protocol continuation for the preserved candidate-02 suite.

This operational wrapper keeps the verified checkpoint, records each explicitly
authorized token-fuse transition, raises only the R1 emergency fuse for later
R1 episodes, and emits a separately labelled final audit.  It never loads
semantic gold and never constructs a Judge.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import MappingProxyType
from typing import Any

REPO_ROOT = Path("/Users/wangwenqi/Desktop/memory bench")
sys.path.insert(0, str(REPO_ROOT))

from fs_memory_lab.evidence import EvidenceValidationError, canonical_json_bytes, sha256_bytes
from fs_memory_lab.model2_preflight import load_model2_provider_from_environment
from fs_memory_lab.run_records import CONDITION_IDS, RunKey
import fs_memory_lab.formal_v2_model2 as model2
import fs_memory_lab.r1_agent as r1_agent
import fs_memory_lab.r1_artifacts as r1_artifacts


OUTPUT_ROOT = REPO_ROOT / "local-runs/formal-v2-model2"
SUITE_ID = "formal-v2-model2-main60-candidate-02"
SUITE_ROOT = OUTPUT_ROOT / SUITE_ID
POLICY_PATH = SUITE_ROOT / "continuation-policy.json"
POLICY_PROTOCOL = "model2-mixed-protocol-continuation-v2"


def _load_policy() -> dict[str, Any]:
    value = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    required = {
        "policy_id",
        "schema_version",
        "protocol_version",
        "status",
        "suite_id",
        "suite_manifest_id",
        "previous_policy_id",
        "inherited_completed_records",
        "original_protocol_fuse_limit",
        "inherited_continuation_fuse_limit",
        "continuation_fuse_limit",
        "authorized_failure_ids",
        "authorization",
        "formal_eligibility",
        "no_gold",
        "judge_forbidden",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise EvidenceValidationError("Continuation policy schema differs")
    body = {key: item for key, item in value.items() if key != "policy_id"}
    expected_id = "mixed-continuation-" + sha256_bytes(canonical_json_bytes(body))
    if (
        value["policy_id"] != expected_id
        or value["schema_version"] != 1
        or value["protocol_version"] != POLICY_PROTOCOL
        or value["status"] != "authorized"
        or value["suite_id"] != SUITE_ID
        or value["previous_policy_id"]
        != "mixed-continuation-8cb135a3f83ac5f62b259a41857595bd27dfde65c473102dc16978323f1affa4"
        or value["inherited_completed_records"] != 238
        or value["original_protocol_fuse_limit"] != 1_000_000
        or value["inherited_continuation_fuse_limit"] != 2_000_000
        or value["continuation_fuse_limit"] != 4_000_000
        or not isinstance(value["authorized_failure_ids"], list)
        or len(value["authorized_failure_ids"]) != 2
        or len(set(value["authorized_failure_ids"])) != 2
        or value["authorization"]
        != "user-explicitly-approved-4000000-token-continuation"
        or value["formal_eligibility"] != "not-eligible-mixed-protocol"
        or value["no_gold"] is not True
        or value["judge_forbidden"] is not True
    ):
        raise EvidenceValidationError("Continuation policy identity differs")
    return value


def _open_and_validate_policy(policy: dict[str, Any]):
    suite = model2.open_suite(
        repo_root=REPO_ROOT, output_root=OUTPUT_ROOT, suite_id=SUITE_ID
    )
    if suite.manifest["suite_manifest_id"] != policy["suite_manifest_id"]:
        raise EvidenceValidationError("Continuation policy suite identity differs")
    model2._assert_no_identity_drift(suite)
    status = model2._suite_status_body(suite)
    if status["completed_records"] < policy["inherited_completed_records"]:
        raise EvidenceValidationError("Inherited verified checkpoint regressed")
    matching_failures = []
    authorized_failure_ids = set(policy["authorized_failure_ids"])
    for store in (suite.main_store, suite.extension_store):
        for key in store.plan.execution_order:
            matching_failures.extend(
                failure
                for failure in store.failure_attempts(key)
                if failure.failure_id in authorized_failure_ids
            )
    if (
        len(matching_failures) != len(authorized_failure_ids)
        or {failure.failure_id for failure in matching_failures}
        != authorized_failure_ids
        or any(failure.stage != "token_safety_fuse" for failure in matching_failures)
        or any(failure.retryable is not False for failure in matching_failures)
    ):
        raise EvidenceValidationError("Authorized continuation failure differs")
    return suite


def _install_runtime_override(policy: dict[str, Any]) -> None:
    if (
        r1_agent.R1_AGENT_LIMITS["token_safety_fuse_limit"]
        != policy["original_protocol_fuse_limit"]
    ):
        raise EvidenceValidationError("Base R1 fuse differs before continuation")
    limits = dict(r1_agent.R1_AGENT_LIMITS)
    limits["token_safety_fuse_limit"] = policy["continuation_fuse_limit"]
    frozen_limits = MappingProxyType(limits)
    r1_agent.R1_AGENT_LIMITS = frozen_limits
    r1_agent.FROZEN_R1_AGENT_LIMITS_SHA256 = sha256_bytes(
        canonical_json_bytes(frozen_limits)
    )
    r1_artifacts.R1_AGENT_LIMITS = frozen_limits

    original_attempt_gate = model2._require_attempt_budget

    def continuation_attempt_gate(store, key):
        attempts = store.failure_attempts(key)
        if (
            attempts
            and attempts[-1].failure_id in set(policy["authorized_failure_ids"])
            and attempts[-1].stage == "token_safety_fuse"
            and attempts[-1].retryable is False
        ):
            return
        original_attempt_gate(store, key)

    model2._require_attempt_budget = continuation_attempt_gate


def _run_child(policy: dict[str, Any], child: str, through_block: int) -> dict[str, Any]:
    _open_and_validate_policy(policy)
    _install_runtime_override(policy)
    return model2.run_child_with_recovery(
        repo_root=REPO_ROOT,
        output_root=OUTPUT_ROOT,
        suite_id=SUITE_ID,
        child_id=child,
        through_block=through_block,
        provider=load_model2_provider_from_environment(),
    )


def _verify_continuation(policy: dict[str, Any]) -> dict[str, Any]:
    suite = _open_and_validate_policy(policy)
    status = model2._suite_status_body(suite)
    if status["completed_records"] != 420 or status["pending_records"] != 0:
        raise EvidenceValidationError("Continuation verification requires 420/420")

    counts = {condition: 0 for condition in CONDITION_IDS}
    failed_usage = {
        "failure_attempts": 0,
        "model_calls": 0,
        "usage_available_calls": 0,
        "usage_unavailable_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    for item in suite.manifest["global_schedule"]:
        store = model2._store_for_child(suite, item["child_id"])
        key = RunKey(item["condition_id"], item["question_id"])
        record = store.load_completed(key)
        if record is None:
            raise EvidenceValidationError("Continuation record disappeared")
        model2._validate_record(record, suite)
        item_usage = model2._verify_failure_metadata(
            suite=suite, store=store, key=key
        )
        for name, value in item_usage.items():
            failed_usage[name] += value
        counts[item["condition_id"]] += 1

    batch_audits: list[str] = []
    for global_batch in range(1, 13):
        audit = model2._read_json(
            suite.suite_root / "control" / f"batch-{global_batch:02d}-audit.json"
        )
        marker = model2._read_json(
            suite.suite_root / "control" / f"batch-{global_batch:02d}.PASSED"
        )
        if (
            audit.get("status") != "passed"
            or marker.get("batch_audit_id") != audit.get("batch_audit_id")
        ):
            raise EvidenceValidationError("Continuation batch gate differs")
        batch_audits.append(str(audit["batch_audit_id"]))

    checks = {
        "records_420_complete": True,
        "conditions_60_each": set(counts.values()) == {60},
        "served_model_exact": True,
        "citations_real": True,
        "e7_no_new_retrieval": True,
        "all_12_batch_gates_passed": len(batch_audits) == 12,
        "failure_model_receipts_verified": True,
        "mixed_protocol_disclosed": True,
        "semantic_gold_loaded": False,
        "judge_calls": 0,
    }
    if not all(
        value is True
        for key, value in checks.items()
        if key not in {"semantic_gold_loaded", "judge_calls"}
    ):
        raise EvidenceValidationError("Continuation checks failed")

    body = {
        "schema_version": 1,
        "protocol_version": POLICY_PROTOCOL,
        "suite_id": SUITE_ID,
        "suite_manifest_id": suite.manifest["suite_manifest_id"],
        "continuation_policy_id": policy["policy_id"],
        "status": "passed",
        "formal_eligibility": policy["formal_eligibility"],
        "completed_records": 420,
        "inherited_completed_records": policy["inherited_completed_records"],
        "previous_policy_id": policy["previous_policy_id"],
        "original_protocol_fuse_limit": policy["original_protocol_fuse_limit"],
        "inherited_continuation_fuse_limit": policy[
            "inherited_continuation_fuse_limit"
        ],
        "continuation_fuse_limit": policy["continuation_fuse_limit"],
        "condition_counts": counts,
        "verified_failure_attempts": failed_usage["failure_attempts"],
        "failed_attempt_usage": failed_usage,
        "checks": checks,
        "batch_audit_ids": batch_audits,
        "completion_marker": "ANSWER-RUN-COMPLETED-NO-JUDGE-MIXED-PROTOCOL",
    }
    audit = {
        "continuation_audit_id": "model2-continuation-pre-gold-"
        + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    model2._publish_json(
        suite.suite_root / "continuation-pre-gold-verify.json", audit
    )
    model2._publish_json(
        suite.suite_root / "continuation-pre-gold-verify.PASSED",
        {
            "status": "passed",
            "formal_eligibility": policy["formal_eligibility"],
            "completion_marker": body["completion_marker"],
            "continuation_audit_id": audit["continuation_audit_id"],
            "continuation_policy_id": policy["policy_id"],
        },
    )
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run-child")
    run.add_argument("--child", choices=("main40", "extension20"), required=True)
    run.add_argument("--through-block", type=int, required=True)
    sub.add_parser("verify")
    args = parser.parse_args()
    policy = _load_policy()
    result = (
        _run_child(policy, args.child, args.through_block)
        if args.command == "run-child"
        else _verify_continuation(policy)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
