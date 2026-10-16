# formal-v2 Model 2 main-60 candidate-02

Public, credential-free archive of the completed Model 2 main-60 run.

- Requested model alias: `x-test-2`
- Required and observed served model: `deepseek-v4.1-flash`
- Questions: 60
- Conditions: E1–E7
- Final records: 420/420
- Batch audits: 12/12 passed
- Continuation pre-gold verification: passed
- Formal eligibility: `not-eligible-mixed-protocol`

The run first reached the original 1,000,000-token R1 safety fuse at 88/420. A
content-addressed user authorization preserved those records and raised the fuse to
2,000,000. At 238/420, a second authorization preserved all records and raised the fuse to
4,000,000. No inherited record was deleted, rewritten, or rebound. The only disclosed
protocol changes are the two fuse transitions and exact bypass of the two authorized fuse
failures. All other data, prompts, stores, budgets, caps, ordering, timeout, and concurrency
remained frozen.

`run/continuation-pre-gold-verify.json` is the authoritative final verification. The archive
also contains the two child answer runs, records, bundles, traces, failure attempts, batch
audits, policies, deterministic LoCoMo P/R/F1 output, and the frozen continuation runner.

Runtime locks, PID files, Python caches, macOS metadata, credentials, and shell history are
excluded. `SHA256SUMS` records every archived file except itself.
