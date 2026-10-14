import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from fs_memory_lab.formal_v2_extension import (
    PLANNED_RECORDS,
    _execution_order,
    _load_extension_questions,
    dry_run,
    prepare_run,
    write_status,
)
from fs_memory_lab.formal_v2_extension_cli import _parser


ROOT = Path(__file__).resolve().parents[1]
FAKE_COMMIT = "4" * 40


class FormalV2ExtensionTests(unittest.TestCase):
    def test_extension_order_continues_main60_rotation(self):
        questions = _load_extension_questions(ROOT)
        order = _execution_order(tuple(item.question_id for item in questions))
        self.assertEqual(len(order), 140)
        self.assertEqual(order[0].condition_id, "E5")
        self.assertEqual(order[0].question_id, "conv-50-q147")
        for question in questions:
            cells = [key.condition_id for key in order if key.question_id == question.question_id]
            self.assertEqual(len(cells), 7)
            self.assertEqual(cells[-1], "E7")
            self.assertLess(cells.index("E2"), cells.index("E7"))
            self.assertLess(cells.index("E6"), cells.index("E7"))

    def test_prepare_and_dry_run_are_no_api_and_exact(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            output = Path(folder)
            run_id = "formal-v2-extension-test"
            path = prepare_run(
                repo_root=ROOT,
                output_root=output,
                run_id=run_id,
                implementation_commit=FAKE_COMMIT,
            )
            self.assertTrue(path.is_file())
            report = dry_run(repo_root=ROOT, output_root=output, run_id=run_id)
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["planned_records"], PLANNED_RECORDS)
            self.assertEqual(
                report["condition_counts"], {f"E{i}": 20 for i in range(1, 8)}
            )
            self.assertTrue(report["checks"]["api_provider_not_constructed"])
            self.assertTrue(report["checks"]["semantic_gold_not_loaded"])
            self.assertTrue(report["checks"]["judge_not_constructed"])
            status = write_status(
                repo_root=ROOT, output_root=output, run_id=run_id
            )
            self.assertEqual(status["completed_records"], 0)
            self.assertEqual(status["pending_records"], 140)

    def test_cli_requires_explicit_valid_batch_boundary(self):
        parser = _parser()
        base = [
            "--output-root",
            "/private/tmp/formal-v2-extension-test",
            "--run-id",
            "formal-v2-extension-test",
            "run",
        ]
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(base)
        self.assertEqual(
            parser.parse_args([*base, "--through-block", "4"]).through_block, 4
        )
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parser.parse_args([*base, "--through-block", "5"])


if __name__ == "__main__":
    unittest.main()
