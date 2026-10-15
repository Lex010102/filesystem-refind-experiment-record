# formal-v2 Qwen extension-20 run 01

This directory is the public, credential-free archive of the completed
`formal-v2-qwen-extension20-run-01` answer run.

## Completion state

- 20 frozen LoCoMo `conv-50` extension questions
- 7 conditions (`E1`--`E7`)
- 140/140 final RunRecords
- 20 final records per condition
- 4/4 batch audits passed
- pre-gold verification passed
- no active failed keys
- 11 historical failed attempts were preserved for recovery/cost analysis
- requested model alias: `coding`
- required and verified served model: `qwen3.8:27b`
- no token-F1 evaluation and no LLM Judge were run for this extension archive

The authoritative final outputs are under `run/records/E1` through
`run/records/E7`. `run/E1` through `run/E6` preserve successful retrieval
artifacts and traces. E7 reuses upstream evidence and therefore has final
RunRecords but no independent retrieval episode directory. Failed retrieval
attempts are retained under `run/failures` and `.failed-*` directories; they
are not counted among the 140 final records.

`control/` contains the four batch logs, status snapshots, audits, PASSED
markers, the read-only pre-gold verification report, and the
`ANSWER-RUN-COMPLETED-NO-JUDGE` marker.

## Deliberate exclusions

The local-only `episode-secret.json` files are excluded. Runtime locks, PID
files, unpublished in-progress state, launch scripts, Keychain integration,
caches, and API credentials or authorization headers are also excluded. The
source run under `local-runs/` was not modified.

`SHA256SUMS` records the SHA-256 digest of every archived file except itself.
