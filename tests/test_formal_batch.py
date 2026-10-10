import tempfile
import unittest
from pathlib import Path

from fs_memory_lab.evidence import EvidenceValidationError
from fs_memory_lab.formal_batch import (
    FORMAL_PLANNED_RECORDS,
    dry_run_formal,
    prepare_formal_run,
    write_formal_status,
)


ROOT = Path(__file__).resolve().parents[1]
FAKE_COMMIT = "2" * 40


class FormalBatchTests(unittest.TestCase):
    def test_prepare_and_real_input_dry_run_are_no_api_and_exact(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            output = Path(folder)
            run_id = "formal-v1-test"
            path = prepare_formal_run(
                repo_root=ROOT,
                output_root=output,
                run_id=run_id,
                orchestrator_commit=FAKE_COMMIT,
            )
            self.assertTrue(path.is_file())
            report = dry_run_formal(
                repo_root=ROOT, output_root=output, run_id=run_id
            )
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["planned_records"], FORMAL_PLANNED_RECORDS)
            self.assertEqual(report["condition_counts"], {f"E{i}": 40 for i in range(1, 8)})
            self.assertTrue(report["checks"]["api_provider_not_constructed"])
            self.assertTrue(report["checks"]["semantic_gold_not_loaded"])
            status = write_formal_status(
                repo_root=ROOT, output_root=output, run_id=run_id
            )
            self.assertEqual(status["status"], "pending")
            self.assertEqual(status["completed_records"], 0)
            self.assertEqual(status["pending_records"], 280)

    def test_prepare_rejects_bad_commit_and_run_id(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            with self.assertRaises(EvidenceValidationError):
                prepare_formal_run(
                    repo_root=ROOT,
                    output_root=Path(folder),
                    run_id="bad/run",
                    orchestrator_commit=FAKE_COMMIT,
                )
            with self.assertRaises(EvidenceValidationError):
                prepare_formal_run(
                    repo_root=ROOT,
                    output_root=Path(folder),
                    run_id="safe-run",
                    orchestrator_commit="short",
                )


if __name__ == "__main__":
    unittest.main()
