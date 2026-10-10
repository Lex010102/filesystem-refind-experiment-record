"""No-API command line interface for preparing and verifying formal-v1."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .formal_v1 import verify_formal_manifest, write_formal_manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Freeze or verify formal-v1; never calls API")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="write the content-addressed manifest once")
    prepare.add_argument("--implementation-commit", required=True)
    verify = sub.add_parser("verify", help="recompute and verify every frozen field")
    verify.add_argument("--manifest", type=Path)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    root = args.repo_root.resolve()
    if args.command == "prepare":
        path = write_formal_manifest(
            root, implementation_commit=args.implementation_commit
        )
        result = {"status": "prepared", "manifest": str(path)}
    else:
        result = verify_formal_manifest(root, args.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
