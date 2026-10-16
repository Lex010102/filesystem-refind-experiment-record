# Unified anonymous LLM-as-Judge for both main-60 systems

This directory archives two independent 420-record Judge runs:

- `llm-judge-x-test1-model1-main60-run-01/`
- `llm-judge-x-test1-model2-main60-run-01/`

Both runs use the frozen anonymous `judge-v1` rubric and prompt. The Judge sees only the
question, reference answer, and candidate answer. It does not see model/system identity,
condition, storage or retrieval method, traces, cost, or token-F1.

- Requested Judge alias: `x-test-1`
- Observed served model: `glm-5.3-flash`
- Prompt SHA-256: `f5992f035a32f819858781ccd87221937124c3a924942db7449c75d75574df1a`
- Labels: `correct`, `partial`, `incorrect`
- Strict mapping: 1, 0, 0
- Soft mapping: 1, 0.5, 0
- Total judgments: 840/840
- Batch audits: 12/12 passed for each system
- Verification and final audit: passed for both systems
- Format repairs: 0

Runtime locks, PID files, credentials, and shell history are excluded. Individual Judge
artifacts intentionally retain labels and short reasons for scientific audit. `SHA256SUMS`
records every archived file except itself.
