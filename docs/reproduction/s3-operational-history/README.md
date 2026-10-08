# S3 local operational history archive

This directory preserves the meaningful S3 files that originally lived under the Git-ignored `local-runs/` tree. They are archived for auditability only and are not inputs to E5/E6.

## Archived mappings

- `background/`: exact copies of the background resume logs, `latest-log.path`, and the final stale PID marker from `local-runs/s3-background/`.
- `failed-formal-attempt-20261005/`: exact copy of run `20261005T191027554957Z-2715bad3`, including `run-state.json`, `events.jsonl`, `failure.json`, checkpoints, quarantine trace/store, and empty trash directory where representable.
- `smoke-20261005/`: exact copy of the successful isolated smoke run `20261005T185937697619Z-eac18b90`, including summary, trace, events, and its two temporary memory files.
- `scripts/`: exact copies of `s3-smoke-once.py`, `start-s3-resume.zsh`, and `start-s3-resume-background.zsh`.

The original ignored paths remain local. These archive copies do not alter any formal S3 hashes.

## Intentionally non-artifact local entries

- `local-runs/__pycache__/s3-smoke-once.cpython-313.pyc` is a regenerable interpreter cache and is not source, data, a model output, or an experiment record.
- `local-runs/s3-smoke-20261005T185810003598Z-c8ba8ea2/` was an empty directory and Git cannot represent empty directories; its existence is recorded here.
- Empty directories such as `failed-formal-attempt-20261005/checkpoints/chunk-001-before/`, its `trash/`, and the smoke run's `trash/` are described here because Git has no file to carry them.
- The copied PID and latest-log files are historical machine-state records. They must not be used to control a current process.

The authoritative successful 85-chunk run is not reconstructed from these local files. Its complete published artifacts are under:

- `experiments/locomo-conv50-v1/stores/s3-curated/`
- `experiments/locomo-conv50-v1/manifests/s3-curated.json`
- `experiments/locomo-conv50-v1/manifests/s3-curated.COMMITTED`
- `experiments/locomo-conv50-v1/traces/s3-management/`

The formal verifier is:

```bash
python3 -m fs_memory_lab.cli --project . verify-s3
```
