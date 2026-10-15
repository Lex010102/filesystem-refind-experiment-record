"""Provider-free CLI for Model 2 suite validation.

This command intentionally has no provider/environment imports.  It only
inspects a prepared suite and its two bound, sanitized preflight copies, then
publishes the content-addressed ``dry-run.json`` gate consumed by the live
suite runner.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .model2_validation import run_prepared_suite_dry_run


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the offline Model 2 60-question/420-key suite audit"
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--suite-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_prepared_suite_dry_run(
        repo_root=args.repo_root.resolve(),
        output_root=args.output_root.resolve(),
        suite_id=args.suite_id,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
