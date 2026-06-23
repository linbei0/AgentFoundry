"""
haagent/cli.py - HaAgent CLI 入口

提供 run、smoke、inspect 和 export-eval 命令的参数解析与输出展示。
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from haagent.cli_commands import (
    SmokeDefinition,
    SmokeResult,
    export_single_eval_case,
    handle_check,
    handle_chat,
    handle_dogfood,
    handle_eval,
    handle_export_eval,
    handle_inspect,
    handle_run,
    handle_smoke,
    run_failure_summary,
    run_smoke_definition,
    run_task_path,
    smoke_definitions,
    write_eval_case_file,
    write_eval_dataset_manifest,
    write_authoring_task_yaml,
)
from haagent.cli_gateway import (
    build_dogfood_model_gateway,
    build_run_model_gateway,
    gateway_from_profile,
)
from haagent.cli_render import (
    excerpt,
    format_event_mapping,
    last_model_response,
    print_chat_event,
    print_chat_turn_result,
    print_check_summary,
    print_eval_summary,
    print_run_summary,
    print_session_status,
    print_smoke_result,
    read_chat_interaction,
    run_chat_repl,
    run_final_response,
    shell_token,
    summary_provider,
    summary_value,
)
from haagent.models.gateway import OpenAIChatCompletionsGateway, OpenAIResponsesGateway
from haagent.models.provider_profile import ProviderProfile
from haagent.runtime.chat_session import AgentSession
from haagent.runtime.orchestrator import RunOrchestrator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SMOKE_DEFINITIONS = smoke_definitions(PROJECT_ROOT)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="haagent", description="HaAgent runtime CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run a task.yaml file")
    run_parser.add_argument("task_yaml", nargs="?", type=Path, help="path to task.yaml")
    run_parser.add_argument(
        "--goal",
        help="task goal used when task_yaml is omitted",
    )
    run_parser.add_argument(
        "--workspace-root",
        type=Path,
        help="workspace root used when task_yaml is omitted",
    )
    run_parser.add_argument(
        "--verify",
        help="verification command used when task_yaml is omitted",
    )
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
    run_parser.add_argument(
        "--profile",
        help="provider profile name from .haagent/providers.json",
    )
    run_parser.add_argument(
        "--model",
        help="OpenAI model name; only used when --provider openai",
    )
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
    run_parser.set_defaults(handler=_handle_run)

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
    chat_parser.add_argument(
        "--resume",
        help="resume a chat session by session id or session package path",
    )
    chat_parser.add_argument(
        "--provider",
        choices=["fake", "openai", "openai-chat"],
        default="fake",
        help="model provider to use (default: fake)",
    )
    chat_parser.add_argument(
        "--profile",
        help="provider profile name from .haagent/providers.json",
    )
    chat_parser.add_argument(
        "--model",
        help="OpenAI model name; only used when --provider openai",
    )
    chat_parser.add_argument(
        "--base-url",
        help="OpenAI-compatible Responses API base URL; only used when --provider openai",
    )
    chat_parser.set_defaults(handler=_handle_chat)

    smoke_parser = subparsers.add_parser(
        "smoke",
        help="run the minimal HaAgent smoke suite",
    )
    smoke_parser.add_argument(
        "--runs-root",
        type=Path,
        default=Path(".runs"),
        help="directory for episode packages (default: .runs)",
    )
    smoke_parser.add_argument(
        "--profile",
        help="real provider profile name from .haagent/providers.json",
    )
    smoke_parser.add_argument(
        "--max-turns",
        type=_positive_int,
        default=12,
        help="maximum model/tool turns per smoke task (default: 12)",
    )
    smoke_parser.set_defaults(handler=_handle_smoke)

    dogfood_parser = subparsers.add_parser(
        "dogfood",
        help="run manual real-model dogfood tasks outside default CI",
    )
    dogfood_parser.add_argument(
        "--runs-root",
        type=Path,
        help="directory for dogfood episode packages; defaults to a temporary directory",
    )
    dogfood_parser.add_argument(
        "--profile",
        help="real provider profile name from .haagent/providers.json",
    )
    dogfood_parser.add_argument(
        "--provider",
        choices=["openai", "openai-chat"],
        help="real provider to use when --profile is omitted",
    )
    dogfood_parser.add_argument(
        "--model",
        help="model name for --provider dogfood runs",
    )
    dogfood_parser.add_argument(
        "--base-url",
        help="OpenAI-compatible base URL for --provider dogfood runs",
    )
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
    dogfood_parser.set_defaults(handler=_handle_dogfood)

    inspect_parser = subparsers.add_parser("inspect", help="inspect an episode package")
    inspect_parser.add_argument("episode_path", type=Path, help="path to an episode directory")
    inspect_parser.set_defaults(handler=_handle_inspect)

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
    export_eval_parser.set_defaults(handler=_handle_export_eval)

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
    eval_parser.add_argument(
        "--profile",
        help="provider profile name from .haagent/providers.json",
    )
    eval_parser.add_argument(
        "--model",
        help="OpenAI model name; only used when --provider openai",
    )
    eval_parser.add_argument(
        "--base-url",
        help="OpenAI-compatible Responses API base URL; only used when --provider openai",
    )
    eval_parser.set_defaults(handler=_handle_eval)

    check_parser = subparsers.add_parser("check", help="run the local HaAgent quality gate")
    check_parser.add_argument(
        "--eval-path",
        type=Path,
        default=PROJECT_ROOT / "examples" / "evals",
        help="eval suite path to run (default: examples/evals)",
    )
    check_parser.add_argument(
        "--output",
        type=Path,
        help="write check report JSON to this file",
    )
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
    check_parser.add_argument(
        "--profile",
        help="provider profile name from .haagent/providers.json",
    )
    check_parser.add_argument(
        "--model",
        help="OpenAI model name; only used when --provider openai",
    )
    check_parser.add_argument(
        "--base-url",
        help="OpenAI-compatible Responses API base URL; only used when --provider openai",
    )
    check_parser.set_defaults(handler=_handle_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    """解析 CLI 参数，运行 orchestrator，并输出机器可读的最小结果。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)

def _handle_run(args: argparse.Namespace) -> int:
    return handle_run(args, build_gateway=_build_run_model_gateway, orchestrator_cls=RunOrchestrator)


def _handle_chat(args: argparse.Namespace) -> int:
    return handle_chat(args, build_gateway=_build_run_model_gateway, session_cls=AgentSession)


def _handle_smoke(args: argparse.Namespace) -> int:
    return handle_smoke(
        args,
        definitions=SMOKE_DEFINITIONS,
        gateway_from_profile=_gateway_from_profile,
        orchestrator_cls=RunOrchestrator,
    )


def _handle_dogfood(args: argparse.Namespace) -> int:
    return handle_dogfood(args, build_dogfood_gateway=_build_dogfood_model_gateway)


def _handle_inspect(args: argparse.Namespace) -> int:
    return handle_inspect(args)


def _handle_eval(args: argparse.Namespace) -> int:
    return handle_eval(args, build_gateway=_build_run_model_gateway)


def _handle_check(args: argparse.Namespace) -> int:
    return handle_check(args, build_gateway=_build_run_model_gateway)


def _handle_export_eval(args: argparse.Namespace) -> int:
    return handle_export_eval(args.episode_paths, args.output, args.output_dir)


def _run_task_path(
    args: argparse.Namespace,
) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    return run_task_path(args)


def _write_authoring_task_yaml(
    path: Path,
    *,
    goal: str,
    workspace_root: Path,
    verification_command: str,
) -> None:
    write_authoring_task_yaml(
        path,
        goal=goal,
        workspace_root=workspace_root,
        verification_command=verification_command,
    )


def _build_dogfood_model_gateway(args: argparse.Namespace):
    return build_dogfood_model_gateway(
        args,
        responses_gateway_cls=OpenAIResponsesGateway,
        chat_gateway_cls=OpenAIChatCompletionsGateway,
    )


def _run_smoke_definition(definition: SmokeDefinition, args: argparse.Namespace) -> SmokeResult:
    return run_smoke_definition(
        definition,
        args,
        gateway_from_profile=_gateway_from_profile,
        orchestrator_cls=RunOrchestrator,
    )


def _run_failure_summary(episode_path: Path) -> tuple[str, str, str]:
    return run_failure_summary(episode_path)


def _print_smoke_result(result: SmokeResult) -> None:
    print_smoke_result(result)


def _build_run_model_gateway(args: argparse.Namespace):
    return build_run_model_gateway(
        args,
        responses_gateway_cls=OpenAIResponsesGateway,
        chat_gateway_cls=OpenAIChatCompletionsGateway,
    )


def _gateway_from_profile(profile: ProviderProfile):
    return gateway_from_profile(
        profile,
        responses_gateway_cls=OpenAIResponsesGateway,
        chat_gateway_cls=OpenAIChatCompletionsGateway,
    )


def _print_run_summary(result) -> None:
    print_run_summary(result)


def _run_chat_repl(session: AgentSession) -> int:
    return run_chat_repl(session)


def _print_session_status(session: AgentSession) -> None:
    print_session_status(session)


def _print_chat_turn_result(result) -> None:
    print_chat_turn_result(result)


def _print_chat_event(event) -> None:
    print_chat_event(event)


def _read_chat_interaction(request):
    return read_chat_interaction(request)


def _format_event_mapping(value: object) -> str:
    return format_event_mapping(value)


def _shell_token(value: str) -> str:
    return shell_token(value)


def _run_final_response(transcript: list[dict[str, object]]) -> str:
    return run_final_response(transcript)


def _summary_provider(episode_metadata: dict[str, object]) -> str:
    return summary_provider(episode_metadata)


def _last_model_response(transcript: list[dict[str, object]]) -> dict[str, object] | None:
    return last_model_response(transcript)


def _excerpt(content: str, limit: int = 500) -> str:
    return excerpt(content, limit)


def _summary_value(value: str, limit: int = 300) -> str:
    return summary_value(value, limit)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("--max-turns must be a positive integer")
    return parsed


def _print_check_summary(report: dict[str, object]) -> None:
    print_check_summary(report)


def _print_eval_summary(report: dict[str, object]) -> None:
    print_eval_summary(report)


def _export_single_eval_case(
    episode_path: Path,
    output_path: Path | None,
    output_dir: Path | None,
) -> int:
    return export_single_eval_case(episode_path, output_path, output_dir)


def _write_eval_case_file(episode_path: Path, output_path: Path) -> None:
    write_eval_case_file(episode_path, output_path)


def _write_eval_dataset_manifest(output_dir: Path, records: list[dict[str, object]]) -> None:
    write_eval_dataset_manifest(output_dir, records)


if __name__ == "__main__":
    raise SystemExit(main())
