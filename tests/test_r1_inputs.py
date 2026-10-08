from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from fs_memory_lab.evidence import EvidenceValidationError
from fs_memory_lab.r1_inputs import (
    FROZEN_R1_INPUT_CONTRACT_SHA256,
    QUESTION_INPUTS,
    R1_STORE_SPECS,
    load_question_inputs,
    load_r1_store,
    r1_input_contract_sha256,
    verify_r1_input_contract,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_ROOT = Path("/Users/wangwenqi/Desktop/memory bench")


class R1InputsTest(unittest.TestCase):
    def test_s1_s2_and_question_sets_are_hash_pinned(self):
        s1 = load_r1_store(REPO_ROOT, "s1")
        s2 = load_r1_store(REPO_ROOT, "S2")
        self.assertEqual(s1.snapshot.store_id, "s1")
        self.assertEqual(s1.snapshot.file_count, 30)
        self.assertEqual(s2.snapshot.store_id, "s2")
        self.assertEqual(s2.snapshot.file_count, 30)
        self.assertNotEqual(s1.snapshot.tree_sha256, s2.snapshot.tree_sha256)
        dev = load_question_inputs(REPO_ROOT, "dev-6")
        main = load_question_inputs(REPO_ROOT, "main-40")
        self.assertEqual(len(dev), 6)
        self.assertEqual(len(main), 40)
        self.assertFalse(
            {item.question_id for item in dev} & {x.question_id for x in main}
        )
        self.assertRegex(r1_input_contract_sha256(), r"^[0-9a-f]{64}$")
        self.assertEqual(r1_input_contract_sha256(), FROZEN_R1_INPUT_CONTRACT_SHA256)
        verify_r1_input_contract()

    def test_checked_in_worktree_contains_verified_published_s3(self):
        self.assertTrue(
            (REPO_ROOT / R1_STORE_SPECS["s3"].store_relative_path).is_dir()
        )
        loaded = load_r1_store(REPO_ROOT, "s3")
        self.assertEqual(loaded.snapshot.store_id, "s3")
        self.assertEqual(loaded.snapshot.file_count, 2)

    def test_completed_main_s3_passes_formal_publication_gate(self):
        marker = MAIN_ROOT / R1_STORE_SPECS["s3"].marker_relative_path
        if not marker.exists():
            self.skipTest("formal S3 publication is not present on this host")
        loaded = load_r1_store(MAIN_ROOT, "s3")
        self.assertEqual(loaded.snapshot.store_id, "s3")
        self.assertEqual(loaded.snapshot.source_kind, "curated")
        self.assertEqual(loaded.snapshot.file_count, 2)
        self.assertEqual(
            loaded.snapshot.tree_sha256,
            "983238fddc77a88ef4ae3d06b50bcfd25a429f497e89c6af4d9477cefca9cad2",
        )
        self.assertEqual(
            loaded.snapshot.attribution_index_sha256,
            "98109144a5a23da7a5b89634be2c543ea2366f2abe85f1f3f8a3df64a5e92ce2",
        )

    def test_staging_copy_and_tampered_question_file_are_rejected(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            root = Path(temporary) / "repo"
            shutil.copytree(REPO_ROOT, root, ignore=shutil.ignore_patterns(".git"))
            question_path = root / QUESTION_INPUTS["dev-6"]["relative_path"]
            question_path.write_text(
                question_path.read_text(encoding="utf-8") + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(EvidenceValidationError, "frozen hash"):
                load_question_inputs(root, "dev-6")

            fake_s3 = root / R1_STORE_SPECS["s3"].store_relative_path
            shutil.copyfile(
                root / "experiments/locomo-conv50-v1/stores/s1-flat/session-01.md",
                fake_s3 / "calvin.md",
            )
            with self.assertRaises(EvidenceValidationError):
                load_r1_store(root, "s3")


if __name__ == "__main__":
    unittest.main()
