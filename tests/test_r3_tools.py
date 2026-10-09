import unittest
from pathlib import Path

from fs_memory_lab.r3_index import R3CuratedIndex
from fs_memory_lab.r3_inputs import load_r3_corpus
from fs_memory_lab.r3_prompts import r3_prompt_hashes, verify_r3_prompts
from fs_memory_lab.r3_tools import (
    FROZEN_R3_ACTION_CONTRACT_SHA256,
    R3ActionError,
    format_r3_search_observation,
    parse_r3_action,
    r3_action_contract_sha256,
    verify_r3_action_contract,
)


ROOT = Path(__file__).resolve().parents[1]


class R3ToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = R3CuratedIndex(load_r3_corpus(ROOT))

    def test_prompt_and_action_contracts_are_frozen(self) -> None:
        verify_r3_prompts()
        verify_r3_action_contract()
        self.assertEqual(
            r3_action_contract_sha256(), FROZEN_R3_ACTION_CONTRACT_SHA256
        )
        self.assertTrue(all(len(value) == 64 for value in r3_prompt_hashes().values()))

    def test_strict_actions_use_compatible_wire_names(self) -> None:
        action = parse_r3_action(
            'Thought: Search the curated facts.\nAction: search_chatrecord\n'
            'Action Input: {"keywords":["octopus","guitar"],"top_k":5}'
        )
        self.assertEqual(action.name, "search_chatrecord")
        self.assertEqual(action.arguments["keywords"], ("octopus", "guitar"))
        note = parse_r3_action(
            'Thought: Save both.\nAction: take_note\nAction Input: {"indices":[1,2]}'
        )
        self.assertEqual(note.arguments["indices"], (1, 2))

    def test_bad_format_top_k_date_and_duplicate_indices_fail(self) -> None:
        with self.assertRaises(R3ActionError):
            parse_r3_action('Action: finish_search\nAction Input: {}')
        with self.assertRaises(R3ActionError):
            parse_r3_action(
                'Thought: x\nAction: search_chatrecord\n'
                'Action Input: {"keywords":["x"],"top_k":4}'
            )
        with self.assertRaises(R3ActionError):
            parse_r3_action(
                'Thought: x\nAction: search_chatrecord\n'
                'Action Input: {"keywords":["x"],"top_k":5,"date_from":"2023-01-01"}'
            )
        with self.assertRaises(R3ActionError):
            parse_r3_action(
                'Thought: x\nAction: take_note\nAction Input: {"indices":[1,1]}'
            )

    def test_observation_exposes_curated_provenance_and_exact_text(self) -> None:
        result = self.index.search(["octopus", "guitar"])
        rendered = format_r3_search_observation(result)
        first = result.hits[0]
        self.assertIn("path=/memories/", rendered)
        self.assertIn("topic=", rendered)
        self.assertIn("source_dates=", rendered)
        self.assertIn("matched_dates=", rendered)
        self.assertIn("unit_bm25=", rendered)
        self.assertIn("group_score=", rendered)
        self.assertIn("[MATCH]", rendered)
        self.assertIn(first.anchor.exact_markdown_text, rendered)
        self.assertIn(first.anchor.source_locators[0], rendered)
        self.assertIn(first.anchor.dia_ids[0], rendered)


if __name__ == "__main__":
    unittest.main()
