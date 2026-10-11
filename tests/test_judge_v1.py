import json
import unittest

from fs_memory_lab.judge_v1 import (
    _COMMIT,
    JUDGE_PROMPT_SHA256,
    JUDGE_REQUIRED_SERVED_MODEL,
    SemanticJudge,
    parse_judge_output,
    render_judge_user_prompt,
)


class Provider:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, messages, tools, config):
        self.calls.append((json.loads(json.dumps(messages)), tools, config))
        return self.replies.pop(0)


def reply(content):
    return {
        "message": {"role": "assistant", "content": content},
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "served_model": JUDGE_REQUIRED_SERVED_MODEL,
        "response_id": "response-1",
    }


class JudgeV1Tests(unittest.TestCase):
    def test_git_commit_identity_is_40_hex(self):
        self.assertIsNotNone(_COMMIT.fullmatch("a" * 40))
        self.assertIsNone(_COMMIT.fullmatch("a" * 64))

    def test_prompt_is_anonymous_and_semantic(self):
        prompt = render_judge_user_prompt(
            question="Where did Alice go?",
            reference_answer="Tokyo",
            candidate_answer="She travelled to Tokyo.",
        )
        self.assertNotIn("E1", prompt)
        self.assertNotIn("retrieval", prompt.lower())
        self.assertNotIn("storage", prompt.lower())
        self.assertEqual(len(JUDGE_PROMPT_SHA256), 64)

    def test_parse_requires_exact_three_field_json(self):
        parsed = parse_judge_output(json.dumps({
            "label": "partial", "short_reason": "One required fact is missing.",
            "confidence": "high",
        }))
        self.assertEqual(parsed["label"], "partial")
        with self.assertRaises(Exception):
            parse_judge_output(json.dumps({**parsed, "score": 0.5}))

    def test_single_judge_derives_strict_and_soft_scores(self):
        provider = Provider([reply(json.dumps({
            "label": "partial", "short_reason": "One required fact is missing.",
            "confidence": "medium",
        }))])
        result = SemanticJudge(provider=provider, sleeper=lambda _: None).run(
            question="What did Alice buy?", reference_answer="tea and cake",
            candidate_answer="tea",
        )
        self.assertEqual(result["strict_score"], 0.0)
        self.assertEqual(result["soft_score"], 0.5)
        self.assertEqual(result["model_calls"], 1)
        self.assertEqual(len(provider.calls), 1)

    def test_one_format_repair_is_recorded(self):
        provider = Provider([
            reply("partial"),
            reply(json.dumps({
                "label": "partial", "short_reason": "Incomplete.",
                "confidence": "low",
            })),
        ])
        result = SemanticJudge(provider=provider, sleeper=lambda _: None).run(
            question="Q", reference_answer="A and B", candidate_answer="A",
        )
        self.assertEqual(result["format_repairs"], 1)
        self.assertEqual(result["model_calls"], 2)
        self.assertEqual(result["provider_request_attempts"], 2)

    def test_served_model_drift_fails_closed(self):
        row = reply(json.dumps({
            "label": "correct", "short_reason": "Equivalent.",
            "confidence": "high",
        }))
        row["served_model"] = "different-model"
        with self.assertRaises(Exception):
            SemanticJudge(provider=Provider([row]), sleeper=lambda _: None).run(
                question="Q", reference_answer="A", candidate_answer="A",
            )


if __name__ == "__main__":
    unittest.main()
