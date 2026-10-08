import unittest
from types import SimpleNamespace

from fs_memory_lab.r2_cli import _validate_live_provider_contract
from fs_memory_lab.r2_prompts import (
    FROZEN_R2_PROMPT_SHA256,
    r2_prompt_hashes,
    render_r2_observation,
    render_r2_user_prompt,
    verify_r2_prompts,
)
from fs_memory_lab.r2_protocol import (
    FROZEN_R2_PROTOCOL_SHA256,
    r2_protocol_sha256,
    verify_r2_protocol,
)


class R2ProtocolTests(unittest.TestCase):
    def test_protocol_is_frozen(self) -> None:
        verify_r2_protocol()
        self.assertEqual(r2_protocol_sha256(), FROZEN_R2_PROTOCOL_SHA256)

    def test_prompts_are_frozen(self) -> None:
        verify_r2_prompts()
        self.assertEqual(r2_prompt_hashes(), dict(FROZEN_R2_PROMPT_SHA256))

    def test_renderers_do_not_change_contract(self) -> None:
        self.assertIn("What happened?", render_r2_user_prompt("What happened?"))
        rendered = render_r2_observation("No matches.")
        self.assertTrue(rendered.startswith("Observation: No matches."))
        self.assertIn("Thought + Action + Action Input ONLY", rendered)

    def test_formal_cli_rejects_wire_profile_or_model_drift(self) -> None:
        _validate_live_provider_contract(
            SimpleNamespace(api_style="portable", model="coding"), "coding"
        )
        with self.assertRaises(SystemExit):
            _validate_live_provider_contract(
                SimpleNamespace(api_style="paper", model="coding"), "coding"
            )
        with self.assertRaises(SystemExit):
            _validate_live_provider_contract(
                SimpleNamespace(api_style="portable", model="other"), "coding"
            )


if __name__ == "__main__":
    unittest.main()
