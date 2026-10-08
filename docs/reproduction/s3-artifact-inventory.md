# S3 artifact inventory

This inventory records the complete meaningful S3 asset set uploaded with the repository as of 2026-10-08.

| Class | Repository path | Count/status |
| --- | --- | --- |
| Frozen chunk inputs | `experiments/locomo-conv50-v1/streams/s3-management-v1/` | 85 text chunks |
| Stream contract | `experiments/locomo-conv50-v1/manifests/s3-management-stream.json` | tracked |
| Prompt contract | `experiments/locomo-conv50-v1/manifests/s3-management-prompt.json` | tracked |
| Runtime contract | `experiments/locomo-conv50-v1/manifests/s3-management-runtime.json` | tracked |
| Formal store | `experiments/locomo-conv50-v1/stores/s3-curated/` | `calvin.md`, `dave.md` |
| Publication manifest | `experiments/locomo-conv50-v1/manifests/s3-curated.json` | verified |
| Commit marker | `experiments/locomo-conv50-v1/manifests/s3-curated.COMMITTED` | verified |
| Formal build trace | `experiments/locomo-conv50-v1/traces/s3-management/` | 85 episodes + `events.jsonl` + `index.json` |
| Earlier failure/smoke summaries | `experiments/locomo-conv50-v1/traces/s3-*.json` | tracked |
| S3 implementation | `fs_memory_lab/s3_chunks.py`, `s3_protocol.py`, `s3_runtime.py`, `s3_runner.py` | tracked |
| CLI integration | `fs_memory_lab/cli.py` | tracked |
| Tests | `tests/test_s3_chunks.py`, `test_s3_prompt.py`, `test_s3_runner.py` | tracked |
| Research plan and progress | `docs/plans/`, `docs/progress/`, `docs/reproduction/` | tracked |
| Local operational history | `docs/reproduction/s3-operational-history/` | archived from ignored `local-runs/` |

Generated Python bytecode, macOS `.DS_Store`, empty directories, and live/stale process-control state are not scientific artifacts. Any such exclusions are explicitly documented in `s3-operational-history/README.md`; the historical PID/pointer files themselves were nevertheless copied into the archive for completeness.

The authoritative offline checks are:

```bash
python3 -m fs_memory_lab.cli --project . verify-s3
python3 -m fs_memory_lab.r1_cli --repo-root . preflight
```
