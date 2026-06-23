"""
haagent/cli.py - HaAgent CLI 公开入口

保留 console script 入口，并把参数定义和运行期依赖交给专门的 CLI Module。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from haagent.cli_parser import build_cli_parser
from haagent.cli_runtime import CliRuntime


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME = CliRuntime(project_root=PROJECT_ROOT)


def build_parser() -> argparse.ArgumentParser:
    return build_cli_parser(DEFAULT_RUNTIME)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
