import unittest
from unittest.mock import patch

from fs_memory_lab.evidence import EvidenceValidationError
from fs_memory_lab.r1_tools import (
    FROZEN_R1_FILESYSTEM_TOOL_PROFILE_SHA256,
    FROZEN_R1_FILESYSTEM_TOOL_SCHEMA_SHA256,
    FROZEN_R1_FILESYSTEM_TOOL_WIRE_SHA256,
    FROZEN_R1_PROJECT_DEFAULTS_SHA256,
    R1_FILESYSTEM_PROTOCOL_VERSION,
    R1_FILESYSTEM_TOOL_NAMES,
    R1_PROJECT_DEFAULTS,
    r1_filesystem_tool_profile_sha256,
    r1_filesystem_tool_schema_sha256,
    r1_filesystem_tool_schemas,
    r1_filesystem_tool_wire_sha256,
    r1_project_defaults_sha256,
    verify_r1_filesystem_tool_freeze,
)


class R1ToolSchemaTest(unittest.TestCase):
    def test_exact_order_names_required_fields_and_frozen_hash(self):
        schemas = r1_filesystem_tool_schemas()
        self.assertEqual(R1_FILESYSTEM_PROTOCOL_VERSION, "center-table12-readonly-v1")
        self.assertEqual(
            tuple(schema["function"]["name"] for schema in schemas),
            R1_FILESYSTEM_TOOL_NAMES,
        )
        self.assertEqual(
            r1_filesystem_tool_schema_sha256(),
            FROZEN_R1_FILESYSTEM_TOOL_SCHEMA_SHA256,
        )
        self.assertEqual(
            r1_filesystem_tool_profile_sha256(),
            FROZEN_R1_FILESYSTEM_TOOL_PROFILE_SHA256,
        )
        self.assertEqual(
            r1_filesystem_tool_wire_sha256(),
            FROZEN_R1_FILESYSTEM_TOOL_WIRE_SHA256,
        )
        self.assertEqual(
            r1_project_defaults_sha256(), FROZEN_R1_PROJECT_DEFAULTS_SHA256
        )
        verify_r1_filesystem_tool_freeze()
        required = {
            "view": ["path"],
            "grep": ["pattern"],
            "toc": ["path"],
            "section_read": ["path", "section_path"],
        }
        for schema in schemas:
            function = schema["function"]
            parameters = function["parameters"]
            self.assertFalse(parameters["additionalProperties"])
            self.assertEqual(parameters["required"], required[function["name"]])

    def test_schema_return_is_detached_and_mutation_is_detected(self):
        first = r1_filesystem_tool_schemas()
        first[0]["function"]["description"] = "caller mutation"
        self.assertNotEqual(
            first[0]["function"]["description"],
            r1_filesystem_tool_schemas()[0]["function"]["description"],
        )
        with patch.dict(
            "fs_memory_lab.r1_tools.TOOL_DEFINITIONS",
            {"view": {"type": "function"}},
            clear=True,
        ):
            with self.assertRaises(EvidenceValidationError):
                r1_filesystem_tool_schemas()

    def test_project_defaults_are_separate_from_paper_schema(self):
        schemas = r1_filesystem_tool_schemas()
        self.assertEqual(R1_PROJECT_DEFAULTS["view"], {"start_line": 1, "end_line": -1})
        self.assertEqual(
            R1_PROJECT_DEFAULTS["grep"],
            {"path": "/memories", "case_sensitive": False, "max_results": 100},
        )
        for schema in schemas:
            for field in schema["function"]["parameters"]["properties"].values():
                self.assertNotIn("default", field)


if __name__ == "__main__":
    unittest.main()
