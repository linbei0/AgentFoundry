# Skill Marketplace v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a full v1 skill marketplace integration using only `skills_sh` and `skillsmp`.

**Architecture:** Marketplace HTTP integration lives in `haagent.skills.marketplace` and exposes typed search/install operations. Model-visible discovery is a read-only `skill_market_search` ToolRouter tool. User-triggered install is handled by `AssistantService` and TUI slash commands so remote skill installation stays behind explicit user action.

**Tech Stack:** Python 3.11, httpx, pytest, Textual TUI, existing HaAgent ToolRouter and local skills loader.

## Global Constraints

- Only marketplace providers are `skills_sh` and `skillsmp`.
- Do not connect GenericAgent 105K search, OpenClaw, GitHub Code Search, or other providers.
- Do not inject remote search results into default model context.
- Do not expose marketplace install as a normal model tool.
- All model-visible marketplace search calls must go through `ToolRouter` and write `tool-calls.jsonl`.
- Remote text is external data, not trusted instruction.
- Install must be user-triggered and must not overwrite an existing local skill directory.
- Implement the whole v1 surface, not a client-only stub.

---

## File Structure

- Create `src/haagent/skills/marketplace.py`: provider clients, normalized cards, install helpers.
- Create `src/haagent/tools/skill_market.py`: ToolRouter handler for read-only marketplace search.
- Modify `src/haagent/tools/registry.py`: add `skill_market_search` schema.
- Modify `src/haagent/tools/router.py`: route `skill_market_search`.
- Modify `src/haagent/runtime/chat_session.py`: allow marketplace search in chat when web is enabled.
- Modify `src/haagent/app/assistant_service.py`: user-facing search cache and install method.
- Modify `src/haagent/tui/app.py`: `/skills search` and `/skills install`.
- Modify `src/haagent/tui/commands.py`: command description.
- Test `tests/test_skill_marketplace.py`: client and install behavior.
- Test `tests/test_tool_registry.py`: schema export and registry validation.
- Test `tests/test_tool_router.py`: search dispatch and trace.
- Test `tests/test_assistant_service.py`: service search/install boundaries.
- Test `tests/test_tui_app.py`: slash command behavior.

## Task 1: Marketplace Client

**Files:**
- Create: `src/haagent/skills/marketplace.py`
- Test: `tests/test_skill_marketplace.py`

**Interfaces:**
- Produces: `MarketplaceProvider`, `MarketplaceSkillCard`, `MarketplaceSearchResult`, `search_marketplace(...)`, `install_skills_sh_skill(...)`.

- [x] Write failing tests for provider normalization, partial failure warnings, invalid providers, and install no-overwrite behavior.
- [x] Run: `uv run pytest tests/test_skill_marketplace.py -q`; expected failures reference missing module.
- [x] Implement dataclasses, provider request functions, normalization helpers, and install helpers.
- [x] Run: `uv run pytest tests/test_skill_marketplace.py -q`; expected pass.

## Task 2: ToolRouter Search Tool

**Files:**
- Create: `src/haagent/tools/skill_market.py`
- Modify: `src/haagent/tools/registry.py`
- Modify: `src/haagent/tools/router.py`
- Test: `tests/test_tool_registry.py`
- Test: `tests/test_tool_router.py`

**Interfaces:**
- Consumes: `search_marketplace(args...)`.
- Produces: `skill_market_search(args) -> dict[str, object]`.

- [x] Write failing schema and dispatch tests.
- [x] Run focused tests; expected failures reference unknown `skill_market_search`.
- [x] Implement schema and router handler.
- [x] Run focused tests; expected pass.

## Task 3: Chat Tool Availability

**Files:**
- Modify: `src/haagent/runtime/chat_session.py`
- Test: `tests/test_cli_personal_assistant.py`

**Interfaces:**
- Consumes: Tool registry entry `skill_market_search`.
- Produces: chat task includes marketplace search only when web tools are enabled.

- [x] Write failing tests proving marketplace search is absent by default and present with explicit web enablement.
- [x] Run focused tests; expected failure for missing tool.
- [x] Add marketplace search to web-enabled chat tools.
- [x] Run focused tests; expected pass.

## Task 4: AssistantService Search And Install

**Files:**
- Modify: `src/haagent/app/assistant_service.py`
- Test: `tests/test_assistant_service.py`

**Interfaces:**
- Consumes: marketplace client functions.
- Produces: `search_skill_marketplace(query, ...)` and `install_marketplace_skill(result_id)`.

- [x] Write failing service tests for merged search cache, rejecting unknown ids, rejecting `skillsmp`, and installing `skills_sh`.
- [x] Run focused tests; expected failures reference missing service methods.
- [x] Add dataclasses for service-facing marketplace results and implement cache/install.
- [x] Run focused tests; expected pass.

## Task 5: TUI Slash Commands

**Files:**
- Modify: `src/haagent/tui/app.py`
- Modify: `src/haagent/tui/commands.py`
- Test: `tests/test_tui_app.py`

**Interfaces:**
- Consumes: AssistantService marketplace methods.
- Produces: `/skills search <query>` and `/skills install <result-id>`.

- [x] Write failing TUI tests for search display, install success, and install rejection text.
- [x] Run focused tests; expected failures reference old `/skills` usage.
- [x] Extend slash command handling and output formatting.
- [x] Run focused tests; expected pass.

## Task 6: Regression And Quality Gate

**Files:**
- Existing tests only, no production code unless failures reveal missed behavior.

- [ ] Run marketplace, tool, service, and TUI focused tests.
- [ ] Run `uv run pytest -m "not slow" -q`.
- [ ] Run `uv run haagent check`.
- [ ] Inspect `git diff` for unrelated churn.
