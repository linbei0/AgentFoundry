# AGENTS.md

## Project Overview

HaAgent is a harness-first Agent Runtime MVP written in Python.
The current runtime loads `task.yaml`, runs a small orchestrator state machine, routes local tools, records model/tool traces, and writes episode packages.

## Project Reference Documents

Before making non-trivial changes, consult the relevant project documents:

- `docs/harness-requirements.md` defines the product direction, current stage, non-goals, and the two baseline constraints:
  - do not increase user mental burden;
  - do not increase model input token usage.
- `docs/unresolved-risks-and-roadmap.md` defines the current unresolved risks and near-term roadmap. It must stay aligned with `docs/harness-requirements.md`; if they conflict, the requirements document wins.
- `docs/code-governance.md` defines code ownership boundaries, unique runtime entry points, change categories, verification expectations, and refactoring guardrails.

Use these documents as decision inputs, not as permission to expand scope. For small mechanical edits, read only the directly relevant document. For feature, contract, runtime, context, episode, tool, provider, or CLI behavior changes, read the relevant sections before editing.

## Document Precedence

- `AGENTS.md` defines the active working rules for coding agents.
- `docs/harness-requirements.md` defines product and engineering direction.
- `docs/code-governance.md` defines code organization and change discipline.
- `docs/unresolved-risks-and-roadmap.md` defines current priorities and known risks.

If documents disagree, prefer the narrower and more current rule. Do not silently choose one; mention the conflict and update the stale document when the task scope includes documentation.

## Setup Commands

- Install dependencies: `uv sync`
- Run all tests: `uv run pytest`
- Run a focused test file: `uv run pytest tests/test_tool_router.py -q`

## Development Workflow

- Use `uv` for virtual environment and dependency management.
- Keep the package in `src/haagent`.
- Keep tests in `tests`.
- Prefer `apply_patch` for file edits to avoid PowerShell encoding issues.
- Do not add UI, browser automation, multi-agent behavior, or long-term memory unless explicitly requested.

## Compatibility Policy

- HaAgent is currently a pre-user, pre-1.0 development project.
- Do not preserve compatibility for historical `.runs`, old episode schemas, old context manifests, old eval cases, or old internal test interfaces unless explicitly requested.
- Do not add legacy paths, fallback behavior, old-field support, old-status support, or silent degradation just to keep development artifacts readable.
- Schema and trace format changes may break old local run artifacts; new runs must remain explicit, validated, inspectable, and covered by tests.
- Compatibility is allowed only for current real needs:
  - external provider differences, such as OpenAI Responses and OpenAI-compatible Chat Completions;
  - task authoring ergonomics, such as omitted `policy` or `workspace_root`;
  - real partial-failure states, such as a run failing before verification files are written.
- If compatibility seems necessary, state who depends on it, what real failure it prevents, and why fail-fast behavior is not better.

## Testing Instructions

- Add or update pytest coverage for every behavior change.
- For bug fixes and new behavior, write the failing test first, then implement the smallest code that passes.
- Run `uv run pytest` before claiming completion.

## Code Style

- Responses and code comments should use Simplified Chinese when explaining project-specific behavior.
- Every Python file must start with a module docstring in this style:

  ```python
  """
  path/to/file.py - 简短职责说明

  说明该文件在 HaAgent 中负责什么。
  """
  ```

- Add concise comments for complex workflows, failure boundaries, provider/tool behavior, or security-sensitive checks.
- Do not comment obvious assignments or one-line boilerplate.
- Keep comments current when changing behavior.

## Runtime Rules

- Model calls must go through the `ModelGateway` interface.
- Tool calls must go through `ToolRouter`.
- Every tool call must append a record to `tool-calls.jsonl`.
- Model calls and responses must append records to `transcript.jsonl`.
- Failures must be explicit and structured; do not add silent fallbacks or simulated success paths.
- Path-mutating tools must stay inside the configured workspace root.
