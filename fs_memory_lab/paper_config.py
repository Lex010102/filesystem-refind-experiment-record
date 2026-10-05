"""Resolved default Center/Agent-curated settings from Appendix C.1 Table 11."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RoleConfig:
    model: str
    reasoning_effort: str
    max_completion_tokens: int
    max_rounds: int


MANAGEMENT = RoleConfig("gpt-5.4-mini", "high", 32768, 60)
# The paper fixes the foldering model/effort and general build round cap, but does
# not print a separate Foldered-sessions completion cap.  We use the main build
# cap locally and record it as a reconstruction choice.
FOLDERING = RoleConfig("gpt-5.4-mini", "high", 32768, 60)
SEARCH = RoleConfig("gpt-5.4-mini", "high", 8192, 40)
RANDOM_SEED = 42
CHUNK_MAX_TURNS = 8
CHUNK_MAX_CHARS = 3000
CONTEXT_COMPACTION_TRIGGER = 96000
CONTEXT_COMPACTION_KEEP_ROUNDS = 3
SEARCH_CONCURRENCY = 8  # Table 11 batch-evaluation setting; single-question CLI does not use it.
