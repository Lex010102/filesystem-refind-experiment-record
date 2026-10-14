# LoCoMo conv-50 main-60-v2

This is an append-only composite test set. Positions 1--40 remain in the frozen `locomo-conv50-main40-v1` files in `../question-sets/`; positions 41--60 come from the independent `locomo-conv50-extension20-v2` files in this directory.

- `extension-20-input.jsonl`: safe online input for the 20 new questions.
- `extension-20-gold.jsonl`: offline-only gold answers and evidence.
- `main-60-composition.json`: global positions 1--60 and source-set identity.
- `main-60-audit.md`: human-readable audit table.
- `manifest.json` and `verification.json`: frozen provenance and checks.

Do not rewrite the original 40 rows with a new question-set ID; doing so would invalidate the existing formal-v1 records. Regenerate with `python3 -m fs_memory_lab.question_sets_v2` and verify with `python3 -m fs_memory_lab.question_sets_v2 --verify-only`.
