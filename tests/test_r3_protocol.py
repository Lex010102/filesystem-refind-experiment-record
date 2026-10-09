import json
import unittest
from pathlib import Path

from fs_memory_lab.r3_protocol import (
    FROZEN_R3_PROTOCOL_SHA256,
    R3_INPUT_IDENTITY,
    R3_PARAMETERS,
    r3_protocol_sha256,
    verify_r3_protocol,
)


ROOT = Path(__file__).resolve().parents[1]


class R3ProtocolTests(unittest.TestCase):
    def test_protocol_is_frozen(self) -> None:
        verify_r3_protocol()
        self.assertEqual(r3_protocol_sha256(), FROZEN_R3_PROTOCOL_SHA256)

    def test_formal_shape_is_fact_to_h2(self) -> None:
        self.assertEqual(R3_INPUT_IDENTITY["expected_fact_units"], 390)
        self.assertEqual(R3_INPUT_IDENTITY["expected_h2_groups"], 35)
        self.assertEqual(R3_PARAMETERS["unit"], "locator-bearing-markdown-list-item")
        self.assertEqual(R3_PARAMETERS["group"], "relative-path-plus-h2-ordinal")
        self.assertEqual(R3_PARAMETERS["multi_date_semantics"], "source-date-set-overlap")

    def test_manifest_agrees_with_code(self) -> None:
        manifest = json.loads(
            (ROOT / "docs/reproduction/r3-protocol-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["protocol_sha256"], r3_protocol_sha256())
        self.assertFalse(manifest["api_called"])
        self.assertFalse(manifest["experimental_results_created"])


if __name__ == "__main__":
    unittest.main()
