"""
haagent/cli_parser.py - CLI 参数解析器构建

集中定义 HaAgent 子命令参数，并将解析结果绑定到对应 command handler。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from haagent.cli_commands import (
    handle_check,
    handle_chat,
    handle_dogfood,
    handle_eval,
    handle_export_eval,
    handle_inspect,
    handle_run,
    handle_smoke,
)
from haagent.cli_runtime import CliRuntime


def build_cli_parser(runtime: CliRuntime) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="haagent", description="HaAgent runtime CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run a task.yaml file")
    run_parser.add_argument("task_yaml", nargs="?", type=Path, help="path to task.yaml")
    run_parser.add_argument("--goal", help="task goal used when task_yaml is omitted")
    run_parser.add_argument(
        "--workspace-root",
        type=Path,
        help="workspace root used when task_yaml is omitted",
    )
    run_parser.add_argument("--verify", help="verification command used when task_yaml is omitted")
    run_parser.add_argument(
        "--runs-root",
        type=Path,
        default=Path(".runs"),
        help="directory for episode packages (default: .runs)",
    )
    run_parser.add_argument(
        "--provider",
        choices=["fake", "openai", "openai-chat"],
        default="fake",
        help="model provider to use (default: fake)",
    )
    run_parser.add_argument("--profile", help="provider profile name from .haagent/providers.json")
    run_parser.add_argument("--model", help="OpenAI model name; only used when --provider openai")
    run_parser.add_argument(
        "--base-url",
        help="OpenAI-compatible Responses API base URL; only used when --provider openai",
    )
    run_parser.add_argument(
        "--max-turns",
        type=_positive_int,
        default=3,
        help="maximum model/tool turns before failing the run (default: 3)",
    )
    run_parser.set_defaults(handler=lambda args: handle_run(args, runtime))

    chat_parser = subparsers.add_parser("chat", help="run a natural language request")
    chat_parser.add_argument(
        "request",
        nargs="?",
        help="natural language request to run in the workspace; omit to enter REPL",
    )
    chat_parser.add_argument(
        "--workspace-root",
        type=Path,
        help="workspace root for the chat request (default: current directory)",
    )
    chat_parser.add_argument("--resume", help="resume a chat session by session id or session package path")
    chat_parser.add_argument(
        "--provider",
        choices=["fake", "openai", "openai-chat"],
        default="fake",
        help="model provider to use (default: fake)",
    )
    chat_parser.add_argument("--profile", help="provider profile name from .haagent/providers.json")
    chat_parser.add_argument("--model", help="OpenAI model name; only used when --provider openai")
    chat_parser.add_argument(
        "--base-url",
        help="OpenAI-compatible Responses API base URL; only used when --provider openai",
    )
    chat_parser.set_defaults(handler=lambda args: handle_chat(args, runtime))

    smoke_parser = subparsers.add_parser("smoke", help="run the minimal HaAgent smoke suite")
    smoke_parser.add_argument(
        "--runs-root",
        type=Path,
        default=Path(".runs"),
        help="directory for episode packages (default: .runs)",
    )
    smoke_parser.add_argument("--profile", help="real provider profile name from .haagent/providers.json")
    smoke_parser.add_argument(
        "--max-turns",
        type=_positive_int,
        default=12,
        help="maximum model/tool turns per smoke task (default: 12)",
    )
    smoke_parser.set_defaults(handler=lambda args: handle_smoke(args, runtime))

    dogfood_parser = subparsers.add_parser(
        "dogfood",
        help="run manual real-model dogfood tasks outside default CI",
    )
    dogfood_parser.add_argument(
        "--runs-root",
        type=Path,
        help="directory for dogfood episode packages; defaults to a temporary directory",
    )
    dogfood_parser.add_argument("--profile", help="real provider profile name from .haagent/providers.json")
    dogfood_parser.add_argument(
        "--provider",
        choices=["openai", "openai-chat"],
        help="real provider to use when --profile is omitted",
    )
    dogfood_parser.add_argument("--model", help="model name for --provider dogfood runs")
    dogfood_parser.add_argument("--base-url", help="OpenAI-compatible base URL for --provider dogfood runs")
    dogfood_parser.add_argument(
        "--max-turns",
        type=_positive_int,
        default=16,
        help="maximum model/tool turns per dogfood task (default: 16)",
    )
    dogfood_parser.add_argument(
        "--no-auto-approve",
        action="store_true",
        help="deny high-risk tool approvals instead of auto-granting them",
    )
    dogfood_parser.set_defaults(handler=lambda args: handle_dogfood(args, runtime))

    inspect_parser = subparsers.add_parser("inspect", help="inspect an episode package")
    inspect_parser.add_argument("episode_path", type=Path, help="path to an episode directory")
    inspect_parser.set_defaults(handler=lambda args: handle_inspect(args))

    export_eval_parser = subparsers.add_parser("export-eval", help="export an eval case JSON")
    export_eval_parser.add_argument(
        "episode_paths",
        nargs="+",
        type=Path,
        help="path to one or more episode directories",
    )
    export_eval_parser.add_argument(
        "--output",
        type=Path,
        help="write eval case JSON to this file instead of stdout",
    )
    export_eval_parser.add_argument(
        "--output-dir",
        type=Path,
        help="write one eval case JSON file per episode into this existing directory",
    )
    export_eval_parser.set_defaults(handler=lambda args: handle_export_eval(args))

    eval_parser = subparsers.add_parser("eval", help="run exported eval case JSON locally")
    eval_parser.add_argument("eval_path", type=Path, help="eval case JSON, directory, or batch manifest")
    eval_parser.add_argument(
        "--output",
        type=Path,
        help="write eval report JSON to this file instead of only printing a summary",
    )
    eval_parser.add_argument(
        "--runs-root",
        type=Path,
        default=Path(".runs"),
        help="directory for eval run episode packages (default: .runs)",
    )
    eval_parser.add_argument(
        "--provider",
        choices=["fake", "openai", "openai-chat"],
        default="fake",
        help="model provider to use (default: fake)",
    )
    eval_parser.add_argument("--profile", help="provider profile name from .haagent/providers.json")
    eval_parser.add_argument("--model", help="OpenAI model name; only used when --provider openai")
    eval_parser.add_argument(
        "--base-url",
        help="OpenAI-compatible Responses API base URL; only used when --provider openai",
    )
    eval_parser.set_defaults(handler=lambda args: handle_eval(args, runtime))

    check_parser = subparsers.add_parser("check", help="run the local HaAgent quality gate")
    check_parser.add_argument(
        "--eval-path",
        type=Path,
        default=runtime.project_root / "examples" / "evals",
        help="eval suite path to run (default: examples/evals)",
    )
    check_parser.add_argument("--output", type=Path, help="write check report JSON to this file")
    check_parser.add_argument(
        "--runs-root",
        type=Path,
        default=Path(".runs"),
        help="directory for check episode packages (default: .runs)",
    )
    check_parser.add_argument(
        "--pytest",
        action="store_true",
        help="also run uv run pytest -q after the eval suite",
    )
    check_parser.add_argument(
        "--provider",
        choices=["fake", "openai", "openai-chat"],
        default="fake",
        help="model provider for eval replay (default: fake)",
    )
    check_parser.add_argument("--profile", help="provider profile name from .haagent/providers.json")
    check_parser.add_argument("--model", help="OpenAI model name; only used when --provider openai")
    check_parser.add_argument(
        "--base-url",
        help="OpenAI-compatible Responses API base URL; only used when --provider openai",
    )
    check_parser.set_defaults(handler=lambda args: handle_check(args, runtime))
    return parser


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("--max-turns must be a positive integer")
    return parsed
