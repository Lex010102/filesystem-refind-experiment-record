# formal-v2 Model 2 dev-6 pilot run 02

This directory is the public, credential-free archive of the completed
`formal-v2-model2-dev6-pilot-run-02` compatibility pilot.

## Completion state

- 6 frozen LoCoMo `conv-50` development questions
- 7 conditions (`E1`--`E7`)
- 36/36 retrieval episodes completed (`E1`--`E6`)
- 42/42 answer records completed (6 per condition)
- final Model 2 audit passed and `MODEL2-PILOT-42.PASSED` was created
- no active failed keys and no model-identity drift
- one retrieval failure was recovered and retained for failure/cost analysis
- requested model alias: `x-test-2`
- verified served model: `deepseek-v4.1-flash`
- evidence budget: 16,000 characters per single-source condition
- R1 caps: 20 rounds for E1/E3 and 40 rounds for E5
- R2/R3 action cap: 4
- E7 reused E2 and E6 evidence and performed no independent retrieval
- no LLM Judge was called

The authoritative pilot answer records are under
`run/children/answers/.../records/E1` through `E7`. Retrieval bundles,
episodes, traces, status, and the recovered failed attempt are under
`run/children/retrieval`. Top-level `run/status.json`,
`run/pilot-pipeline-manifest.json`, `run/model2-final-audit.json`, and the
PASSED marker bind the two child runs into one audited pilot.

The child `evaluation.json` is a post-completion dev-6 diagnostic. This is a
small compatibility pilot, not the formal 60-question/420-record Model 2
result, and it must not be reported as that formal result.

## Deliberate exclusions

The aborted run-01 is not copied or counted. Local-only
`episode-secret.json` files, runtime locks/PIDs, recovery authorization state,
temporary recovery evidence, background launcher state, Keychain launch
scripts and credential material, caches, API credentials, and authorization
headers are excluded. The manifest retains only non-secret credential-policy
metadata needed to explain the execution contract. The
source run under `local-runs/` was not modified.

`SHA256SUMS` records the SHA-256 digest of every archived file except itself.
