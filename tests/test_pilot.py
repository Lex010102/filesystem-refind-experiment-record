from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fs_memory_lab.evidence import EvidenceValidationError
from fs_memory_lab.pilot import (
    RetrievalSource,
    _r2_first_rank_backend_invariant,
    _r2_first_rank_signature,
    load_retrieval_source,
)


ROOT = Path(__file__).resolve().parents[1]


class PilotTests(unittest.TestCase):
    def test_retrieval_source_requires_a_frozen_budget_gate(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            output = Path(temporary)
            run = output / "retrieval"
            run.mkdir()
            manifest = {
                "manifest_id": "manifest-test",
                "budget_unit": "characters",
                "budget_limit": 10000,
            }
            summary = {
                "status": "completed",
                "episode_count": 36,
                "manifest_id": "manifest-test",
                "budget_decision": {"decision": "adjust-and-rerun-all-dev6"},
            }
            (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (run / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                load_retrieval_source(
                    repo_root=ROOT,
                    retrieval_output_root=output,
                    retrieval_run_id="retrieval",
                )
            summary["budget_decision"]["decision"] = "freeze-candidate-10000"
            (run / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
            loaded = load_retrieval_source(
                repo_root=ROOT,
                retrieval_output_root=output,
                retrieval_run_id="retrieval",
            )
            self.assertEqual(loaded.budget_limit, 10000)

    def test_s1_s2_first_round_backend_ranking_is_identical(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            output = Path(temporary)
            run = output / "retrieval"
            arguments = {"keywords": ["Dave", "engine", "work"], "top_k": 5}
            event = {
                "event": "action",
                "action": "search_chatrecord",
                "arguments": arguments,
            }
            for condition in ("E2", "E4"):
                path = run / condition / "conv-50-q025"
                path.mkdir(parents=True)
                (path / "trace.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
            source = RetrievalSource(ROOT, output, "retrieval", {}, {})
            self.assertEqual(
                _r2_first_rank_signature(source, "E2", "conv-50-q025"),
                _r2_first_rank_signature(source, "E4", "conv-50-q025"),
            )
            self.assertTrue(
                _r2_first_rank_backend_invariant(
                    source, "E2", "conv-50-q025"
                )
            )
            self.assertTrue(
                _r2_first_rank_backend_invariant(
                    source, "E4", "conv-50-q025"
                )
            )


if __name__ == "__main__":
    unittest.main()
