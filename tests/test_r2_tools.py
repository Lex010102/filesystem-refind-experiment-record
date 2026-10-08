import unittest
from pathlib import Path

from fs_memory_lab.r2_index import R2RawIndex
from fs_memory_lab.r2_inputs import build_r2_raw_corpus
from fs_memory_lab.r2_tools import (
    FROZEN_R2_ACTION_CONTRACT_SHA256,
    R2ActionError,
    format_r2_search_observation,
    parse_r2_action,
    r2_action_contract_sha256,
    verify_r2_action_contract,
)


ROOT = Path(__file__).resolve().parents[1]


class R2ToolTests(unittest.TestCase):
    def test_action_contract_is_frozen(self) -> None:
        verify_r2_action_contract()
        self.assertEqual(
            r2_action_contract_sha256(), FROZEN_R2_ACTION_CONTRACT_SHA256
        )

    def test_strict_search_parse(self) -> None:
        action = parse_r2_action(
            'Thought: Search broadly.\nAction: search_chatrecord\n'
            'Action Input: {"keywords":["Japan","music"],"top_k":5}'
        )
        self.assertEqual(action.name, "search_chatrecord")
        self.assertEqual(action.arguments["keywords"], ("Japan", "music"))

    def test_bad_format_top_k_and_date_fail(self) -> None:
        with self.assertRaises(R2ActionError):
            parse_r2_action('Action: finish_search\nAction Input: {}')
        with self.assertRaises(R2ActionError):
            parse_r2_action(
                'Thought: x\nAction: search_chatrecord\n'
                'Action Input: {"keywords":["x"],"top_k":4}'
            )
        with self.assertRaises(R2ActionError):
            parse_r2_action(
                'Thought: x\nAction: search_chatrecord\n'
                'Action Input: {"keywords":["x"],"top_k":5,"date_from":"2023-01-01"}'
            )

    def test_observation_shows_path_but_preserves_source(self) -> None:
        index = R2RawIndex(build_r2_raw_corpus(ROOT, "s2"))
        result = index.search(["Japan"])
        rendered = format_r2_search_observation(result)
        self.assertIn("path=/memories/", rendered)
        self.assertIn("[MATCH]", rendered)
        self.assertIn(result.hits[0].anchor.locators[0], rendered)


if __name__ == "__main__":
    unittest.main()
