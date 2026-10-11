# llm-judge-v1 main-40 run 01

This directory is the public, credential-free archive of the supplemental semantic evaluation for `formal-v1-main40-run-02`.

## Completion state

- 280/280 judgments completed;
- 40 judgments per condition for E1–E7;
- 8/8 batch audits passed;
- 0 active failed keys;
- verification passed;
- final audit passed;
- requested model alias: `coding`;
- served model: `qwen3.8:27b`;
- 182,951 Judge tokens;
- labels: 168 correct, 57 partial, 55 incorrect.

`run/records/E1` through `run/records/E7` contain the 280 content-addressed judgment records. Each record stores input hashes, source record identity, the three-way label, strict/soft score, a short reason, confidence, served model and token usage. Raw questions, reference answers and candidate answers are not duplicated in this archive; their hashes link each decision to the frozen source run.

`run/results.json` contains all judgment rows and summaries by condition and LoCoMo category. `run/verification.json` and `run/final-audit.json` record the passed integrity gates. `control/` contains all eight batch logs, audit reports and PASSED markers.

See `SCORING.md` for the compact scoring table and metric definitions.

## Deliberate exclusions

Runtime `run.lock`, `launcher.pid`, the empty launcher log and empty failure directories are not scientific outputs and are excluded. No API key, authorization header, shell history or other credential is included.

`SHA256SUMS` records the SHA-256 digest of every archived file except itself.
