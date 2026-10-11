# formal-v1 main-40 run 02

This directory is the public, credential-free archive of the completed
`formal-v1-main40-run-02` experiment.

## Completion state

- 40 frozen LoCoMo `conv-50` questions
- 7 conditions (`E1`--`E7`)
- 280/280 final RunRecords
- 40 final records per condition
- 8/8 batch audits passed
- pre-gold audit passed
- no active failed keys
- requested model alias: `coding`
- served model: `qwen3.8:27b`

The authoritative final outputs are under `run/records/E1` through
`run/records/E7`. Each JSON file contains the online question, final answer,
citations, EvidenceBundle, retrieval metrics, Answerer metrics, and combined
deployment cost.

`run/E1` through `run/E6` preserve the successful retrieval artifacts and
traces. `run/failures` and the `.failed-*` directories preserve failed attempts
for recovery analysis; they are not part of the 280 final records. E7 is a
fusion condition and therefore has final RunRecords but no independent
retrieval episode directory.

`control/` contains the eight batch logs, checkpoint snapshots, audits, PASSED
markers, and the final pre-gold verification report.

## Deliberate exclusions

The local-only `episode-secret.json` files contain per-episode MAC secrets used
to authenticate read receipts while the run is active. They are not API keys,
are not scientific inputs or outputs, and are intentionally excluded from the
public archive. Runtime lock files, PID files, and unpublished `.in-progress-*`
directories are also excluded. No API key or authorization header is included.

`SHA256SUMS` records the SHA-256 digest of every archived file except itself.
The deterministic post-run evaluation will add `evaluation.json` and
`final-audit.json` after the pre-gold archive commit.
