import hashlib
import json
import unittest
from pathlib import Path

from fs_memory_lab.management_prompt import (BUILDER_BASE,
                                             FROZEN_BUILDER_PROMPT_SHA256,
                                             FROZEN_LOCOMO_ATTRIBUTION_SHA256,
                                             FROZEN_MANAGEMENT_PROMPT_SHA256,
                                             LOCOMO_ATTRIBUTION,
                                             MANAGEMENT_PROMPT)
from fs_memory_lab.paper_tools import MANAGEMENT_PROFILE
from fs_memory_lab.s3_protocol import (FROZEN_S3_USER_INSTRUCTION_SHA256,
                                       FROZEN_S3_USER_TEMPLATE_SHA256,
                                       S3_USER_INSTRUCTION,
                                       S3_USER_TEMPLATE,
                                       render_s3_user_message)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT
    / "experiments"
    / "locomo-conv50-v1"
    / "manifests"
    / "s3-management-prompt.json"
)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class S3PromptTest(unittest.TestCase):
    def test_published_components_and_combined_prompt_are_frozen(self):
        self.assertEqual(sha256(BUILDER_BASE), FROZEN_BUILDER_PROMPT_SHA256)
        self.assertEqual(sha256(LOCOMO_ATTRIBUTION), FROZEN_LOCOMO_ATTRIBUTION_SHA256)
        self.assertEqual(MANAGEMENT_PROMPT, BUILDER_BASE + "\n" + LOCOMO_ATTRIBUTION)
        self.assertEqual(sha256(MANAGEMENT_PROMPT), FROZEN_MANAGEMENT_PROMPT_SHA256)
        self.assertEqual(
            (len(BUILDER_BASE), len(BUILDER_BASE.encode("utf-8"))),
            (12521, 12663),
        )
        self.assertEqual(
            (len(LOCOMO_ATTRIBUTION), len(LOCOMO_ATTRIBUTION.encode("utf-8"))),
            (872, 874),
        )

    def test_local_wrapper_is_separate_and_preserves_payload_exactly(self):
        self.assertEqual(sha256(S3_USER_INSTRUCTION), FROZEN_S3_USER_INSTRUCTION_SHA256)
        self.assertEqual(sha256(S3_USER_TEMPLATE), FROZEN_S3_USER_TEMPLATE_SHA256)
        payload = "Session 1 · 2023-01-01\n\nDave: line 1\nline 2\n[S1T1] (dia_id: D1:1)"
        self.assertEqual(
            render_s3_user_message(payload),
            S3_USER_INSTRUCTION + "\n\n" + payload,
        )
        with self.assertRaises(ValueError):
            render_s3_user_message("")

    def test_machine_readable_contract_matches_runtime(self):
        manifest = json.loads(CONTRACT.read_text(encoding="utf-8"))
        prompt = manifest["system_prompt"]
        self.assertEqual(manifest["schema_version"], "s3-management-prompt-contract-v1")
        self.assertEqual(manifest["paper_source"]["arxiv_id"], "2607.26637v1")
        self.assertEqual(
            manifest["paper_source"]["official_tex_archive_sha256"],
            "ef77cd11a986a0dbb40501469474b61e28e91481209530be5c20e9b85b29cb3e",
        )
        self.assertEqual(prompt["builder_prompt_1"]["sha256"], sha256(BUILDER_BASE))
        self.assertEqual(prompt["builder_prompt_1"]["characters"], len(BUILDER_BASE))
        self.assertEqual(
            prompt["builder_prompt_1"]["utf8_bytes"], len(BUILDER_BASE.encode("utf-8"))
        )
        self.assertEqual(prompt["locomo_prompt_2"]["sha256"], sha256(LOCOMO_ATTRIBUTION))
        self.assertEqual(prompt["locomo_prompt_2"]["characters"], len(LOCOMO_ATTRIBUTION))
        self.assertEqual(
            prompt["locomo_prompt_2"]["utf8_bytes"],
            len(LOCOMO_ATTRIBUTION.encode("utf-8")),
        )
        self.assertEqual(prompt["combined"]["sha256"], sha256(MANAGEMENT_PROMPT))
        self.assertEqual(prompt["combined"]["characters"], len(MANAGEMENT_PROMPT))
        self.assertEqual(
            prompt["combined"]["utf8_bytes"], len(MANAGEMENT_PROMPT.encode("utf-8"))
        )
        self.assertEqual(manifest["user_wrapper"]["instruction"], S3_USER_INSTRUCTION)
        self.assertEqual(manifest["user_wrapper"]["template"], S3_USER_TEMPLATE)
        self.assertEqual(
            manifest["user_wrapper"]["instruction_sha256"],
            sha256(S3_USER_INSTRUCTION),
        )
        self.assertEqual(
            manifest["user_wrapper"]["template_sha256"],
            sha256(S3_USER_TEMPLATE),
        )
        self.assertEqual(tuple(manifest["management_tool_profile"]), MANAGEMENT_PROFILE)
        self.assertEqual(manifest["construction_cost"]["llm_calls"], 0)


if __name__ == "__main__":
    unittest.main()
