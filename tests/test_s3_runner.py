import copy
import json
import tempfile
import unittest
from pathlib import Path

from fs_memory_lab.management_prompt import MANAGEMENT_PROMPT
from fs_memory_lab.paper_config import MANAGEMENT
from fs_memory_lab.paper_tools import MANAGEMENT_PROFILE, TOOL_DEFINITIONS
from fs_memory_lab.s3_protocol import render_s3_user_message
from fs_memory_lab.s3_runner import (
    S3BuildError,
    build_s3_store,
    preflight_s3_build,
    validate_curated_store,
    verify_published_s3,
)
from fs_memory_lab.s3_runtime import (
    EXPECTED_S3_PROMPT_CONTRACT_SHA256,
    EXPECTED_S3_RUNTIME_CONTRACT_SHA256,
    EXPECTED_S3_STREAM_MANIFEST_SHA256,
    FROZEN_MANAGEMENT_RUNTIME_CONFIG_SHA256,
    FROZEN_MANAGEMENT_TOOL_PROFILE_SHA256,
    FROZEN_MANAGEMENT_TOOL_SCHEMA_SHA256,
    S3_RESOURCE_LIMITS,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = REPO_ROOT / "experiments" / "locomo-conv50-v1"
STREAM = EXPERIMENT / "streams" / "s3-management-v1"
STREAM_MANIFEST = EXPERIMENT / "manifests" / "s3-management-stream.json"
PROMPT_CONTRACT = EXPERIMENT / "manifests" / "s3-management-prompt.json"
RUNTIME_CONTRACT = EXPERIMENT / "manifests" / "s3-management-runtime.json"

EXPECTED_TOOLS = [TOOL_DEFINITIONS[name] for name in MANAGEMENT_PROFILE]
VALID_MEMORY = (
    "---\n"
    "name: alice\n"
    "description: A small test memory about Alice.\n"
    "---\n\n"
    "# Facts\n\n"
    "- Alice appears in the first source turn [S1T1].\n"
)
FUTURE_MEMORY = VALID_MEMORY.replace("[S1T1]", "[S30T1]")
MALFORMED_MEMORY = VALID_MEMORY.replace("[S1T1]", "[S11][S13][S15]")
REPAIRED_MEMORY = VALID_MEMORY.replace("[S1T1]", "[S1T1][S1T3][S1T5]")


def tool_call(call_id: str, name: str, **arguments) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments, ensure_ascii=False, sort_keys=True),
        },
    }


def tool_round(call: dict, *, served_model: str) -> dict:
    return {
        "message": {"role": "assistant", "content": None, "tool_calls": [call]},
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "finish_reason": "tool_calls",
        "response_id": "fake-tool-response",
        "served_model": served_model,
        "system_fingerprint": "fake-s3-fingerprint",
    }


def answer_round(episode: int, *, served_model: str) -> dict:
    return {
        "message": {
            "role": "assistant",
            "content": f"Episode {episode} integrated.",
        },
        "usage": {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11},
        "finish_reason": "stop",
        "response_id": f"fake-answer-{episode:03d}",
        "served_model": served_model,
        "system_fingerprint": "fake-s3-fingerprint",
    }


class RecordingS3Provider:
    endpoint = "https://soclaas-api.comp.nus.edu.sg/v1/chat/completions"
    api_style = "portable"
    model = "coding"
    timeout = 300
    max_response_bytes = 20_000_000

    def __init__(
        self,
        expected_user_messages: list[str],
        *,
        served_model: str = "qwen3.8:27b",
        fail_episode: int | None = None,
        first_memory: str = VALID_MEMORY,
    ):
        self.expected_user_messages = expected_user_messages
        self.served_model = served_model
        self.fail_episode = fail_episode
        self.first_memory = first_memory
        self.episode = 0
        self.calls = 0
        self.first_contexts: list[list[dict]] = []
        self.tool_profiles: list[list[str]] = []

    def complete(self, messages, tools, config):
        self.calls += 1
        self.assert_protocol(messages, tools, config)
        is_new_episode = len(messages) == 2
        if is_new_episode:
            self.episode += 1
            if self.episode > len(self.expected_user_messages):
                raise AssertionError("Runner started more than 85 S3 episodes")
            expected = self.expected_user_messages[self.episode - 1]
            if messages[1] != {"role": "user", "content": expected}:
                raise AssertionError(f"Unexpected S3 user message for episode {self.episode}")
            self.first_contexts.append(copy.deepcopy(messages))
            if self.fail_episode == self.episode:
                raise RuntimeError("gateway failed with clsk_TESTSECRET1234567890")
            if self.episode == 1:
                return tool_round(
                    tool_call(
                        "create-alice",
                        "create",
                        path="/memories/people/alice.md",
                        file_text=self.first_memory,
                    ),
                    served_model=self.served_model,
                )
        return answer_round(self.episode, served_model=self.served_model)

    def assert_protocol(self, messages, tools, config):
        if not messages or messages[0] != {"role": "system", "content": MANAGEMENT_PROMPT}:
            raise AssertionError("Runner did not send the frozen Management system prompt")
        if tools != EXPECTED_TOOLS:
            raise AssertionError("Runner did not send the exact ordered seven-tool schema")
        if config != MANAGEMENT:
            raise AssertionError("Runner did not use the frozen paper management role config")
        names = [tool["function"]["name"] for tool in tools]
        self.tool_profiles.append(names)


class WrongProfileProvider(RecordingS3Provider):
    model = "not-coding"


class RepairingLocatorProvider(RecordingS3Provider):
    def __init__(self, expected_user_messages: list[str]):
        super().__init__(expected_user_messages, first_memory=MALFORMED_MEMORY)
        self.repair_sent = False
        self.feedback = ""

    def complete(self, messages, tools, config):
        if self.episode == 1 and len(messages) > 2 and not self.repair_sent:
            self.calls += 1
            self.assert_protocol(messages, tools, config)
            tool_messages = [message for message in messages if message.get("role") == "tool"]
            self.assert_first_feedback(tool_messages)
            self.repair_sent = True
            return tool_round(
                tool_call(
                    "repair-alice",
                    "str_replace",
                    path="/memories/people/alice.md",
                    old_str="[S11][S13][S15]",
                    new_str="[S1T1][S1T3][S1T5]",
                ),
                served_model=self.served_model,
            )
        return super().complete(messages, tools, config)

    def assert_first_feedback(self, tool_messages: list[dict]) -> None:
        if len(tool_messages) != 1 or tool_messages[0].get("tool_call_id") != "create-alice":
            raise AssertionError("Malformed write did not produce one immediate tool result")
        self.feedback = str(tool_messages[0].get("content", ""))
        required = (
            "POST-TOOL VALIDATION ERROR",
            "the tool action was applied",
            "people/alice.md:L8",
            "[S11]",
            "[S13]",
            "[S15]",
        )
        if any(value not in self.feedback for value in required):
            raise AssertionError(f"Incomplete locator repair feedback: {self.feedback}")


class TooManyCallsProvider(RecordingS3Provider):
    def complete(self, messages, tools, config):
        self.calls += 1
        self.assert_protocol(messages, tools, config)
        calls = [
            tool_call(f"view-{index}", "view", path="/memories")
            for index in range(S3_RESOURCE_LIMITS["max_tool_calls_per_response"] + 1)
        ]
        return {
            "message": {"role": "assistant", "content": None, "tool_calls": calls},
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "finish_reason": "tool_calls",
            "served_model": "qwen3.8:27b",
        }


class OversizedRawArgumentsProvider(RecordingS3Provider):
    def complete(self, messages, tools, config):
        self.calls += 1
        self.assert_protocol(messages, tools, config)
        arguments = (
            " " * S3_RESOURCE_LIMITS["max_tool_arguments_bytes"]
            + '{"path":"/memories"}'
        )
        return {
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "oversized-raw",
                    "type": "function",
                    "function": {"name": "view", "arguments": arguments},
                }],
            },
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "finish_reason": "tool_calls",
            "served_model": "qwen3.8:27b",
        }


class S3SafeRunnerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.paths = {
            "store": self.base / "stores" / "s3-curated",
            "manifest": self.base / "manifests" / "s3-curated.json",
            "trace": self.base / "traces" / "s3-management",
            "marker": self.base / "manifests" / "s3-curated.COMMITTED",
            "work": self.base / "local-runs" / "s3-management",
        }
        stream_document = json.loads(STREAM_MANIFEST.read_text(encoding="utf-8"))
        self.chunks = stream_document["chunks"]
        self.user_messages = [
            render_s3_user_message((STREAM / chunk["filename"]).read_text(encoding="utf-8"))
            for chunk in self.chunks
        ]

    def tearDown(self):
        self.temporary.cleanup()

    def preflight(self):
        return preflight_s3_build(
            STREAM,
            STREAM_MANIFEST,
            PROMPT_CONTRACT,
            RUNTIME_CONTRACT,
            self.paths["store"],
            self.paths["manifest"],
            self.paths["trace"],
            self.paths["marker"],
        )

    def build(self, provider):
        return build_s3_store(
            STREAM,
            STREAM_MANIFEST,
            PROMPT_CONTRACT,
            RUNTIME_CONTRACT,
            self.paths["store"],
            self.paths["manifest"],
            self.paths["trace"],
            self.paths["marker"],
            self.paths["work"],
            provider,
            code_revision="test-s3-runner",
            code_dirty=False,
            test_mode=True,
        )

    def verify(self):
        return verify_published_s3(
            STREAM,
            STREAM_MANIFEST,
            PROMPT_CONTRACT,
            RUNTIME_CONTRACT,
            self.paths["store"],
            self.paths["manifest"],
            self.paths["trace"],
            self.paths["marker"],
            allow_test_artifact=True,
        )

    def assert_no_formal_outputs(self):
        for name in ("store", "manifest", "trace", "marker"):
            self.assertFalse(self.paths[name].exists(), name)

    def test_real_frozen_stream_and_contracts_pass_preflight(self):
        result = self.preflight()
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["chunks"], 85)
        self.assertEqual(result["source_turns"], 568)
        self.assertEqual(
            result["stream_manifest_sha256"], EXPECTED_S3_STREAM_MANIFEST_SHA256
        )
        self.assertEqual(
            result["prompt_contract_sha256"], EXPECTED_S3_PROMPT_CONTRACT_SHA256
        )
        self.assertEqual(
            result["runtime_contract_sha256"], EXPECTED_S3_RUNTIME_CONTRACT_SHA256
        )
        self.assertEqual(
            result["tool_profile_sha256"], FROZEN_MANAGEMENT_TOOL_PROFILE_SHA256
        )
        self.assertEqual(
            result["tool_schema_sha256"], FROZEN_MANAGEMENT_TOOL_SCHEMA_SHA256
        )
        self.assertEqual(
            result["runtime_config_sha256"], FROZEN_MANAGEMENT_RUNTIME_CONFIG_SHA256
        )
        self.assert_no_formal_outputs()

    def test_success_runs_85_fresh_episodes_and_detects_tampering(self):
        provider = RecordingS3Provider(self.user_messages)
        result = self.build(provider)
        self.assertEqual(result["status"], "published")
        self.assertEqual(result["chunks"], 85)
        self.assertEqual(result["served_models"], ["qwen3.8:27b"])
        self.assertEqual(provider.episode, 85)
        self.assertEqual(len(provider.first_contexts), 85)
        self.assertEqual(provider.calls, 86)
        self.assertTrue(
            all(len(context) == 2 for context in provider.first_contexts),
            "Every chunk must start from a fresh two-message context",
        )
        self.assertTrue(
            all(profile == list(MANAGEMENT_PROFILE) for profile in provider.tool_profiles)
        )
        self.assertEqual(len(list(self.paths["trace"].glob("episode-*.json"))), 85)
        with self.assertRaisesRegex(S3BuildError, "test S3 artifact"):
            verify_published_s3(
                STREAM,
                STREAM_MANIFEST,
                PROMPT_CONTRACT,
                RUNTIME_CONTRACT,
                self.paths["store"],
                self.paths["manifest"],
                self.paths["trace"],
                self.paths["marker"],
            )
        verified = self.verify()
        self.assertEqual(verified["status"], "verified")

        memory_path = self.paths["store"] / "people" / "alice.md"
        original_memory = memory_path.read_bytes()
        memory_path.write_bytes(original_memory + b"\nTAMPERED\n")
        with self.assertRaises(S3BuildError):
            self.verify()
        memory_path.write_bytes(original_memory)
        self.assertEqual(self.verify()["status"], "verified")

        episode_path = self.paths["trace"] / "episode-001.json"
        original_episode = episode_path.read_bytes()
        episode_path.write_bytes(original_episode + b" ")
        with self.assertRaises(S3BuildError):
            self.verify()
        episode_path.write_bytes(original_episode)
        self.assertEqual(self.verify()["status"], "verified")

        marker_path = self.paths["marker"]
        original_marker = marker_path.read_bytes()
        marker = json.loads(original_marker)
        marker["run_id"] = "tampered"
        marker_path.write_text(json.dumps(marker), encoding="utf-8")
        with self.assertRaises(S3BuildError):
            self.verify()
        marker_path.write_bytes(original_marker)
        self.assertEqual(self.verify()["status"], "verified")

    def test_provider_profile_mismatch_fails_before_any_call(self):
        provider = WrongProfileProvider(self.user_messages)
        with self.assertRaisesRegex(S3BuildError, "Provider profile"):
            self.build(provider)
        self.assertEqual(provider.calls, 0)
        self.assert_no_formal_outputs()

    def test_formal_mode_refuses_test_revision_and_fake_provider(self):
        provider = RecordingS3Provider(self.user_messages)
        with self.assertRaisesRegex(S3BuildError, "Formal S3 build requires"):
            build_s3_store(
                STREAM,
                STREAM_MANIFEST,
                PROMPT_CONTRACT,
                RUNTIME_CONTRACT,
                self.paths["store"],
                self.paths["manifest"],
                self.paths["trace"],
                self.paths["marker"],
                self.paths["work"],
                provider,
                code_revision="test-cannot-be-formal",
                code_dirty=False,
            )
        self.assertEqual(provider.calls, 0)
        self.assert_no_formal_outputs()

    def test_unexpected_served_model_is_rejected_without_publication(self):
        provider = RecordingS3Provider(
            self.user_messages, served_model="unexpected-backend"
        )
        with self.assertRaises(S3BuildError):
            self.build(provider)
        self.assert_no_formal_outputs()

    def test_incremental_locator_feedback_allows_same_episode_repair(self):
        provider = RepairingLocatorProvider(self.user_messages)
        result = self.build(provider)
        self.assertEqual(result["status"], "published")
        self.assertEqual(provider.episode, 85)
        self.assertEqual(provider.calls, 87)
        self.assertTrue(provider.repair_sent)
        self.assertIn("[S11]", provider.feedback)
        memory_path = self.paths["store"] / "people" / "alice.md"
        self.assertEqual(memory_path.read_text(encoding="utf-8"), REPAIRED_MEMORY)

        episode = json.loads(
            (self.paths["trace"] / "episode-001.json").read_text(encoding="utf-8")
        )
        tool_events = [event for event in episode["result"]["trace"] if "tool" in event]
        self.assertEqual(
            [(event["round"], event["tool"], event["ok"]) for event in tool_events],
            [(1, "create", False), (2, "str_replace", True)],
        )
        self.assertIn("POST-TOOL VALIDATION ERROR", tool_events[0]["observation"])
        self.assertEqual(episode["result"]["rounds"], 3)
        self.assertEqual(episode["result"]["tool_calls"], 2)
        self.assertEqual(self.verify()["status"], "verified")

    def test_unrepaired_malformed_locator_still_fails_final_gate(self):
        provider = RecordingS3Provider(
            self.user_messages, first_memory=MALFORMED_MEMORY
        )
        with self.assertRaises(S3BuildError):
            self.build(provider)
        self.assert_no_formal_outputs()
        run_dir = next(path for path in self.paths["work"].iterdir() if path.is_dir())
        failure = json.loads((run_dir / "failure.json").read_text(encoding="utf-8"))
        self.assertEqual(failure["current_chunk"], 1)
        self.assertIn("Malformed source locator", failure["error"]["message"])
        quarantined = run_dir / "quarantine" / "store" / "people" / "alice.md"
        self.assertEqual(quarantined.read_text(encoding="utf-8"), MALFORMED_MEMORY)

    def test_tool_call_count_and_raw_argument_limits_fail_closed(self):
        for provider_type in (TooManyCallsProvider, OversizedRawArgumentsProvider):
            with self.subTest(provider=provider_type.__name__):
                isolated = Path(tempfile.mkdtemp(dir=self.base))
                self.paths = {
                    "store": isolated / "stores" / "s3-curated",
                    "manifest": isolated / "manifests" / "s3-curated.json",
                    "trace": isolated / "traces" / "s3-management",
                    "marker": isolated / "manifests" / "s3-curated.COMMITTED",
                    "work": isolated / "local-runs" / "s3-management",
                }
                provider = provider_type(self.user_messages)
                with self.assertRaises(S3BuildError):
                    self.build(provider)
                self.assert_no_formal_outputs()

    def test_provider_failure_keeps_checkpoint_and_quarantine_only(self):
        provider = RecordingS3Provider(self.user_messages, fail_episode=2)
        with self.assertRaises(S3BuildError):
            self.build(provider)
        self.assert_no_formal_outputs()
        run_dirs = [path for path in self.paths["work"].iterdir() if path.is_dir()]
        self.assertEqual(len(run_dirs), 1)
        run_dir = run_dirs[0]
        failure_text = (run_dir / "failure.json").read_text(encoding="utf-8")
        failure = json.loads(failure_text)
        self.assertEqual(failure["status"], "failed")
        self.assertEqual(failure["current_chunk"], 2)
        self.assertTrue(failure["checkpoints_retained"])
        self.assertNotIn("clsk_TESTSECRET1234567890", failure_text)
        self.assertIn("[REDACTED_KEY]", failure_text)
        checkpoint = run_dir / "checkpoints" / "chunk-002-before" / "people" / "alice.md"
        self.assertEqual(checkpoint.read_text(encoding="utf-8"), VALID_MEMORY)
        quarantined = run_dir / "quarantine" / "store" / "people" / "alice.md"
        self.assertEqual(quarantined.read_text(encoding="utf-8"), VALID_MEMORY)
        self.assertTrue((run_dir / "quarantine" / "trace" / "episode-001.json").is_file())

    def test_future_locator_from_model_is_caught_by_episode_gate(self):
        provider = RecordingS3Provider(self.user_messages, first_memory=FUTURE_MEMORY)
        with self.assertRaises(S3BuildError):
            self.build(provider)
        self.assert_no_formal_outputs()
        run_dir = next(path for path in self.paths["work"].iterdir() if path.is_dir())
        failure = json.loads((run_dir / "failure.json").read_text(encoding="utf-8"))
        self.assertEqual(failure["current_chunk"], 1)
        self.assertIn("future source locator", failure["error"]["message"])
        rows = [
            json.loads(line)
            for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        tool_events = [event for event in rows if event.get("tool") == "create"]
        self.assertEqual(len(tool_events), 1)
        self.assertFalse(tool_events[0]["ok"])
        self.assertIn(
            "unknown or future source locator [S30T1]",
            tool_events[0]["observation"],
        )

    def test_store_gate_rejects_future_locator_and_bad_frontmatter(self):
        allowed = {"[S1T1]"}
        future = self.base / "future-store"
        (future / "people").mkdir(parents=True)
        (future / "people" / "alice.md").write_text(FUTURE_MEMORY, encoding="utf-8")
        with self.assertRaisesRegex(S3BuildError, "future source locator"):
            validate_curated_store(future, allowed)

        invalid = self.base / "invalid-store"
        invalid.mkdir()
        (invalid / "alice.md").write_text(
            VALID_MEMORY.replace("name: alice", "name: wrong-name"), encoding="utf-8"
        )
        with self.assertRaisesRegex(S3BuildError, "frontmatter|invalid"):
            validate_curated_store(invalid, allowed)

    def test_plain_markdown_brackets_are_not_treated_as_source_locators(self):
        store = self.base / "ordinary-brackets"
        store.mkdir()
        (store / "notes.md").write_text(
            "---\n"
            "name: notes\n"
            "description: Notes containing an ordinary Markdown link label.\n"
            "---\n\n"
            "# Notes\n\n"
            "Read [Setup guide] before using the tool. Source: [S1T1].\n",
            encoding="utf-8",
        )
        gate = validate_curated_store(store, {"[S1T1]"})
        self.assertEqual(gate.unique_locators, 1)
        self.assertEqual(gate.locator_mentions, 1)
        self.assertEqual(list(gate.source_index), ["[S1T1]"])

    def test_section_cross_reference_must_resolve_to_an_existing_heading(self):
        store = self.base / "section-references"
        (store / "topics").mkdir(parents=True)
        target = (
            "---\n"
            "name: target\n"
            "description: Target file for section-link validation.\n"
            "---\n\n"
            "# Overview\n\n"
            "The referenced content is here [S1T1].\n"
        )
        source_template = (
            "---\n"
            "name: index\n"
            "description: Index linking to a precise memory section.\n"
            "---\n\n"
            "# Index\n\n"
            "- See /memories/topics/target.md > {section} [S1T1]\n"
        )
        (store / "topics" / "target.md").write_text(target, encoding="utf-8")
        source_path = store / "index.md"
        source_path.write_text(
            source_template.format(section="# Overview"), encoding="utf-8"
        )
        gate = validate_curated_store(store, {"[S1T1]"})
        self.assertEqual(
            gate.files["index.md"]["section_cross_references"],
            ["/memories/topics/target.md > # Overview"],
        )

        source_path.write_text(
            source_template.format(section="# Missing heading"), encoding="utf-8"
        )
        with self.assertRaisesRegex(S3BuildError, "Broken or ambiguous section cross-reference"):
            validate_curated_store(store, {"[S1T1]"})

    def test_section_links_handle_punctuation_and_reject_ambiguous_shorthand(self):
        store = self.base / "section-reference-edge-cases"
        store.mkdir()
        target = (
            "---\nname: target\ndescription: Headings with punctuation and duplicates.\n---\n\n"
            "# U.S. travel\n\nA fact [S1T1].\n"
            "# Alice\n\n## Music\n\nAlice fact.\n"
            "# Bob\n\n## Music\n\nBob fact.\n"
        )
        (store / "target.md").write_text(target, encoding="utf-8")
        source = store / "index.md"
        prefix = "---\nname: index\ndescription: Section reference edge cases.\n---\n\n# Index\n\n"
        source.write_text(
            prefix + "See /memories/target.md > # U.S. travel. [S1T1]\n",
            encoding="utf-8",
        )
        validate_curated_store(store, {"[S1T1]"})
        source.write_text(
            prefix + "See /memories/target.md > # Alice > ## Music. [S1T1]\n",
            encoding="utf-8",
        )
        validate_curated_store(store, {"[S1T1]"})
        source.write_text(
            prefix + "See /memories/target.md > ## Music. [S1T1]\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(S3BuildError, "ambiguous section cross-reference"):
            validate_curated_store(store, {"[S1T1]"})

    def test_unicode_cross_reference_and_malformed_locator_are_not_silently_ignored(self):
        store = self.base / "invalid-reference-tokens"
        store.mkdir()
        path = store / "notes.md"
        prefix = "---\nname: notes\ndescription: Invalid reference tests.\n---\n\n# Notes\n\n"
        path.write_text(prefix + "See /memories/人物/missing.md [S1T1].\n", encoding="utf-8")
        with self.assertRaisesRegex(S3BuildError, "Broken cross-reference"):
            validate_curated_store(store, {"[S1T1]"})
        path.write_text(prefix + "Malformed source [SxT1].\n", encoding="utf-8")
        with self.assertRaisesRegex(S3BuildError, "Malformed source locator"):
            validate_curated_store(store, {"[S1T1]"})

    def test_store_gate_rejects_a_file_over_the_frozen_size_limit(self):
        store = self.base / "oversized-store"
        store.mkdir()
        prefix = (
            "---\n"
            "name: oversized\n"
            "description: Deliberately oversized file for the safety gate.\n"
            "---\n\n"
            "# Data\n\n"
        )
        target_size = S3_RESOURCE_LIMITS["max_file_bytes"] + 1
        payload = prefix + ("x" * (target_size - len(prefix.encode("utf-8"))))
        (store / "oversized.md").write_text(payload, encoding="utf-8")
        self.assertGreater(
            (store / "oversized.md").stat().st_size,
            S3_RESOURCE_LIMITS["max_file_bytes"],
        )
        with self.assertRaisesRegex(S3BuildError, "resource limit exceeded: max_file_bytes"):
            validate_curated_store(store, set())

    def test_store_gate_rejects_an_uncited_list_fact_candidate(self):
        store = self.base / "uncited-list-fact"
        store.mkdir()
        (store / "notes.md").write_text(
            "---\nname: notes\ndescription: A deliberately uncited fact.\n---\n\n"
            "# Facts\n\n- Alice likes cats.\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(S3BuildError, "Uncited list/table fact"):
            validate_curated_store(store, {"[S1T1]"})

    def test_store_gate_counts_empty_directory_depth(self):
        store = self.base / "deep-empty-directories"
        current = store
        for index in range(S3_RESOURCE_LIMITS["max_directory_depth"] + 1):
            current = current / f"level-{index}"
        current.mkdir(parents=True)
        with self.assertRaisesRegex(S3BuildError, "max_directory_depth"):
            validate_curated_store(store, set(), allow_empty=True)


if __name__ == "__main__":
    unittest.main()
