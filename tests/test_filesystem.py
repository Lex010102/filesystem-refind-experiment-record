import io
import json
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from fs_memory_lab.agent import AgentRunner, CompatibleChatProvider, TOOL_DEFINITIONS
from fs_memory_lab.cli import chunk_lines, main, validate_locomo_turns
from fs_memory_lab.filesystem import MemoryFS, ToolError
from fs_memory_lab.paper_config import MANAGEMENT, SEARCH
from fs_memory_lab.paper_prompts import MANAGEMENT_PROMPT, SEARCH_PROMPT
from fs_memory_lab.paper_tools import MANAGEMENT_PROFILE, SEARCH_PROFILE


FILE = "---\nname: alice\ndescription: Alice's diet.\n---\n\n# Diet\n- Vegetarian since May 2026 [S6T5]\n## Past\n- Previously liked yakiniku [S1T1]\n"


class FakeProvider:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.tool_names = []

    def complete(self, messages, tools, config):
        self.tool_names.append({tool["function"]["name"] for tool in tools})
        self.last_messages = messages
        self.last_tools = tools
        self.last_config = config
        return {"message": next(self.responses), "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


class FilesystemTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.fs = MemoryFS(self.base / "memories", self.base / "trash")

    def tearDown(self):
        self.temp.cleanup()

    def test_create_view_grep_toc_section_and_edit(self):
        self.fs.create("/memories/people/alice.md", FILE)
        self.assertIn("Alice's diet.", self.fs.view("/memories"))
        self.assertIn("L7", self.fs.grep("vegetarian"))
        self.assertIn("# Diet", self.fs.toc("/memories/people/alice.md"))
        self.assertIn("Previously liked", self.fs.section_read("/memories/people/alice.md", "# Diet > ## Past"))
        self.fs.str_replace("/memories/people/alice.md", "Alice's diet.", "Alice's diet history.")
        self.fs.insert("/memories/people/alice.md", 6, "- Likes tofu [S6T6]")
        self.assertIn("tofu", self.fs.view("/memories/people/alice.md"))

    def test_rename_requires_name_followup(self):
        self.fs.create("/memories/people/alice.md", FILE)
        result = self.fs.rename("/memories/people/alice.md", "/memories/people/alice-diet.md")
        self.assertIn("may need editing", result)
        self.fs.str_replace("/memories/people/alice-diet.md", "name: alice", "name: alice-diet")
        self.assertIn("name: alice-diet", self.fs.view("/memories/people/alice-diet.md"))

    def test_roles_and_root_boundary(self):
        with self.assertRaises(ToolError):
            self.fs.call("search", "create", {"path": "/memories/a.md", "file_text": FILE})
        with self.assertRaises(ToolError):
            self.fs.create("/memories/../outside.md", FILE)
        with self.assertRaises(ToolError):
            self.fs.delete("/memories")
        outside = self.base / "outside.md"
        outside.write_text("secret", encoding="utf-8")
        (self.fs.root / "link.md").symlink_to(outside)
        with self.assertRaises(ToolError):
            self.fs.view("/memories/link.md")

    def test_delete_is_recoverable(self):
        self.fs.create("/memories/people/alice.md", FILE)
        observation = self.fs.delete("/memories/people/alice.md")
        self.assertEqual(observation, "Deleted /memories/people/alice.md")
        self.assertFalse((self.fs.root / "people/alice.md").exists())
        self.assertEqual(len(list((self.base / "trash").rglob("alice.md"))), 1)

    def test_agent_loop_and_tool_profile(self):
        call = {"id": "call_1", "type": "function", "function": {"name": "view", "arguments": json.dumps({"path": "/memories"})}}
        provider = FakeProvider([{"role": "assistant", "content": None, "tool_calls": [call]},
                                 {"role": "assistant", "content": "No memory yet."}])
        result = AgentRunner(self.fs, provider).run("search", "What is remembered?")
        self.assertEqual(result.rounds, 2)
        self.assertEqual(result.tool_calls, 1)
        self.assertNotIn("create", provider.tool_names[0])
        self.assertIn("section_read", provider.tool_names[0])
        self.assertEqual(set(TOOL_DEFINITIONS), MemoryFS.management_tools | MemoryFS.search_tools)
        self.assertEqual(provider.last_config, SEARCH)
        self.assertEqual(provider.last_messages[0]["content"], SEARCH_PROMPT)
        self.assertEqual(provider.last_tools, [TOOL_DEFINITIONS[name] for name in SEARCH_PROFILE])

    def test_management_loop_can_create_but_search_cannot(self):
        view_call = {"id": "call_1", "type": "function", "function": {"name": "view", "arguments": '{"path":"/memories"}'}}
        create_call = {"id": "call_2", "type": "function", "function": {
            "name": "create", "arguments": json.dumps({"path": "/memories/people/alice.md", "file_text": FILE})}}
        provider = FakeProvider([
            {"role": "assistant", "content": None, "tool_calls": [view_call]},
            {"role": "assistant", "content": None, "tool_calls": [create_call]},
            {"role": "assistant", "content": "Created Alice memory."},
        ])
        result = AgentRunner(self.fs, provider).run("management", "Integrate [S6T5]")
        self.assertEqual((result.rounds, result.tool_calls), (3, 2))
        self.assertIn("create", provider.tool_names[0])
        self.assertIn("Vegetarian", self.fs.view("/memories/people/alice.md"))
        self.assertEqual(provider.last_config, MANAGEMENT)
        self.assertEqual(provider.last_messages[0]["content"], MANAGEMENT_PROMPT)
        self.assertEqual(provider.last_tools, [TOOL_DEFINITIONS[name] for name in MANAGEMENT_PROFILE])

    def test_rejects_bad_frontmatter_and_ambiguous_replace(self):
        with self.assertRaises(ToolError):
            self.fs.create("/memories/people/alice.md", "# Missing YAML\n")
        repeated = FILE + "- Vegetarian since May 2026 [S6T5]\n"
        self.fs.create("/memories/people/alice.md", repeated)
        with self.assertRaises(ToolError):
            self.fs.str_replace("/memories/people/alice.md", "Vegetarian since May 2026", "Vegan")
        self.assertIn("Vegetarian", self.fs.view("/memories/people/alice.md"))

    def test_chunking(self):
        self.assertEqual(len(chunk_lines("\n".join(str(i) for i in range(17)))), 3)
        self.assertEqual(len(chunk_lines("a" * 2000 + "\n" + "b" * 2000)), 2)
        validate_locomo_turns("Alice: I like tea. [S1T2]\nBob: Good. [S1T3]")
        with self.assertRaises(ValueError):
            validate_locomo_turns("Alice: I like tea.")

    def test_compatible_api_adapter_without_network(self):
        provider = CompatibleChatProvider("https://api.example.test/v1", "model-with-tools", "test-key")
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"message": {"role": "assistant", "content": "Done."}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 3},
        }).encode("utf-8")
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            result = provider.complete([{"role": "user", "content": "hello"}], [], SEARCH)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.example.test/v1/chat/completions")
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], "model-with-tools")
        self.assertEqual(payload["reasoning_effort"], "high")
        self.assertEqual(payload["max_completion_tokens"], 8192)
        self.assertNotIn("temperature", payload)
        self.assertNotIn("seed", payload)
        self.assertEqual(result["message"]["content"], "Done.")
        with self.assertRaises(ValueError):
            CompatibleChatProvider("http://remote.example/v1", "model", "key")

    def test_portable_api_style_omits_provider_specific_fields(self):
        provider = CompatibleChatProvider("https://api.example.test/v1", "coding", "test-key",
                                          api_style="portable")
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"message": {"role": "assistant", "content": None,
                                     "tool_calls": [{"id": "call_1", "type": "function",
                                                     "function": {"name": "view", "arguments": '{"path":"/memories"}'}}]}}],
        }).encode("utf-8")
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            result = provider.complete([{"role": "user", "content": "call view"}],
                                       [TOOL_DEFINITIONS["view"]], SEARCH)
        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(payload["model"], "coding")
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertNotIn("reasoning_effort", payload)
        self.assertNotIn("max_completion_tokens", payload)
        self.assertEqual(result["message"]["tool_calls"][0]["function"]["name"], "view")

    def test_http_error_reports_parameter_but_redacts_key(self):
        secret = "test-api-key-not-a-real-secret"
        provider = CompatibleChatProvider("https://api.example.test/v1", "coding", secret,
                                          api_style="portable")
        error = urllib.error.HTTPError("https://api.example.test/v1/chat/completions", 400,
                                       "Bad Request", {}, io.BytesIO(json.dumps({
                                           "error": {"param": "tools", "message": f"Rejected {secret}"}
                                       }).encode("utf-8")))
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "HTTP 400.*param=tools") as raised:
                provider.complete([{"role": "user", "content": "hello"}],
                                  [TOOL_DEFINITIONS["view"]], SEARCH)
        self.assertNotIn(secret, str(raised.exception))

    def test_check_api_is_read_only_and_requires_function_call(self):
        provider = MagicMock()
        provider.model = "coding"
        provider.complete.return_value = {
            "message": {"tool_calls": [{"function": {"name": "view", "arguments": '{"path":"/memories"}'}}]},
            "served_model": "coding",
        }
        argv = ["fs-memory-lab", "--project", str(self.base / "probe-project"), "check-api"]
        with patch("sys.argv", argv), patch("fs_memory_lab.cli.CompatibleChatProvider.from_environment",
                                           return_value=provider), redirect_stdout(io.StringIO()) as output:
            main()
        self.assertIn("function calling OK", output.getvalue())
        self.assertFalse((self.base / "probe-project").exists())
        provider.complete.return_value = {"message": {"content": "I cannot call tools."}}
        with patch("sys.argv", argv), patch("fs_memory_lab.cli.CompatibleChatProvider.from_environment",
                                           return_value=provider), self.assertRaisesRegex(RuntimeError, "did not call view"):
            main()

    def test_completion_cap_is_not_accepted_as_an_answer(self):
        class LimitedProvider(FakeProvider):
            def complete(self, messages, tools, config):
                result = super().complete(messages, tools, config)
                result["finish_reason"] = "length"
                return result
        with self.assertRaisesRegex(RuntimeError, "completion cap"):
            AgentRunner(self.fs, LimitedProvider([{"role": "assistant", "content": "Partial"}])).run("search", "Question")

    def test_published_prompt_and_schema_surfaces(self):
        self.assertIn("Then maintain", MANAGEMENT_PROMPT)
        self.assertIn("[S5T3][S12T2]", MANAGEMENT_PROMPT)
        self.assertIn("## Citation Format", SEARCH_PROMPT)
        self.assertEqual(MANAGEMENT.max_rounds, 60)
        self.assertEqual(SEARCH.max_rounds, 40)
        self.assertEqual(TOOL_DEFINITIONS["view"]["function"]["parameters"]["required"], ["path"])
        self.assertEqual(TOOL_DEFINITIONS["section_read"]["function"]["parameters"]["required"], ["path", "section_path"])

    def test_compaction_keeps_summary_and_recent_rounds(self):
        calls = [{"role": "assistant", "content": None, "tool_calls": [
            {"id": f"call_{i}", "type": "function", "function": {
                "name": "view", "arguments": '{"path":"/memories"}'}}]} for i in range(4)]
        class CompactProvider(FakeProvider):
            def complete(self, messages, tools, config):
                result = super().complete(messages, tools, config)
                if len(self.tool_names) == 4:
                    result["usage"]["prompt_tokens"] = 97001
                return result
        provider = CompactProvider(calls + [
            {"role": "assistant", "content": "Earlier survey found no memory."},
            {"role": "assistant", "content": "No memory found."},
        ])
        result = AgentRunner(self.fs, provider).run("search", "What is stored?")
        self.assertTrue(any(item.get("compaction") for item in result.trace))
        self.assertTrue(any(item.get("compaction") for item in result.usage))
        self.assertIn("Running summary", provider.last_messages[2]["content"])
        self.assertEqual(result.rounds, 5)


if __name__ == "__main__":
    unittest.main()
