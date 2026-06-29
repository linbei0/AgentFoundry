# TUI Model Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> 历史说明：本文是 2026-06-28 的模型中心实施计划。当前产品决策已更新为无子命令 `haagent` 默认进入 TUI，旧 `haagent tui` 只保留迁移提示；本文中“保持 `haagent tui` 显式入口”的约束不再适用。

**Goal:** Build a TUI model center that can discover models from Models.dev, configure provider profiles with safe credential handling, switch the current TUI session model, set the default profile, and run explicit connection tests through `ModelGateway`.

**Architecture:** Add a catalog layer for Models.dev, a gateway registry for runnable capability, service-layer APIs for profile/session/default/test operations, and Textual modal screens for model selection and setup. Runtime switching stays behind `AssistantService` and `AgentSession`; secrets stay inside credential stores and in-memory gateway construction.

**Tech Stack:** Python 3.11+, Textual >= 0.80.0, pytest, urllib-based HTTP transports, keyring, existing HaAgent `ModelGateway`, `AssistantService`, and `AgentSession`.

## Global Constraints

- Current rule: TUI is the default ordinary HaAgent entry point via plain `haagent`; do not reintroduce alternate interactive CLI flows.
- Model calls must go through `ModelGateway`.
- TUI must not bypass `AssistantService`, `AgentSession`, or provider profile services.
- Real API keys must not be written to profile/settings/session/episode/transcript/tool trace/TUI text.
- TUI API key input must be masked; default credential storage is keyring.
- `Enter` switches the current TUI session profile/model only.
- `p` sets the default active profile only.
- Catalog refresh and connection test must not block the Textual event loop.
- All behavior changes require pytest coverage before implementation code.
- Use `apply_patch` for source edits.
- Project git rule overrides plan boilerplate: do not commit unless the user explicitly asks for commits.

---

## File Structure

- Create `src/haagent/models/catalog.py`
  - Fetch, parse, cache, and search Models.dev catalog data.
- Create `src/haagent/models/gateway_registry.py`
  - Map profile/catalog provider data to runnable gateway capabilities and gateway constructors.
- Modify `src/haagent/models/provider_profile.py`
  - Add list/status/save helpers needed by TUI and service APIs.
- Modify `src/haagent/app/assistant_service.py`
  - Add model profile list/configure/switch/default/test APIs.
- Modify `src/haagent/runtime/chat_session.py`
  - Add explicit current-session model switch semantics and non-sensitive metadata.
- Create `src/haagent/tui/models.py`
  - Textual modal screens and state objects for model center and setup wizard.
- Modify `src/haagent/tui/app.py`
  - Wire slash commands to model center.
- Modify `src/haagent/tui/commands.py`
  - Add `/model` and `/models`.
- Modify `tests/test_model_gateway.py`
  - Add gateway registry and native adapter tests.
- Create `tests/test_model_catalog.py`
  - Catalog parsing, cache, and failure tests.
- Modify `tests/test_credentials.py`
  - Add save/status redaction coverage if provider-profile tests do not fully cover it.
- Modify `tests/test_assistant_service.py`
  - Service API, switch semantics, and connection test coverage.
- Modify `tests/test_tui_app.py`
  - TUI slash command, overlay, wizard, worker, and secret display tests.

---

### Task 1: Models.dev Catalog Layer

**Files:**
- Create: `src/haagent/models/catalog.py`
- Create: `tests/test_model_catalog.py`

**Interfaces:**
- Produces:
  - `ModelCatalogError(Exception)`
  - `ModelCatalogProvider`
  - `ModelCatalogModel`
  - `CatalogFetchResult`
  - `fetch_model_catalog(*, cache_path: Path | None = None, transport: CatalogTransport | None = None) -> CatalogFetchResult`
  - `search_catalog(result: CatalogFetchResult, query: str) -> list[ModelCatalogProvider]`

- [ ] **Step 1: Write failing catalog parse test**

Add to `tests/test_model_catalog.py`:

```python
from pathlib import Path

import pytest

from haagent.models.catalog import fetch_model_catalog, search_catalog, ModelCatalogError


def test_models_dev_catalog_parses_provider_model_and_cache(tmp_path: Path) -> None:
    payload = {
        "requesty": {
            "id": "requesty",
            "name": "Requesty",
            "env": ["REQUESTY_API_KEY"],
            "api": "https://router.requesty.ai/v1",
            "npm": "@ai-sdk/openai-compatible",
            "doc": "https://requesty.ai/models",
            "models": {
                "openai/gpt-5.2-chat": {
                    "id": "openai/gpt-5.2-chat",
                    "name": "GPT 5.2 Chat",
                    "family": "gpt",
                    "tool_call": True,
                    "reasoning": True,
                    "modalities": {"input": ["text"], "output": ["text"]},
                    "limit": {"context": 128000, "output": 16000},
                    "cost": {"input": 1.25, "output": 10},
                    "release_date": "2026-01-01",
                    "last_updated": "2026-01-10",
                }
            },
        }
    }

    def transport() -> dict[str, object]:
        return payload

    result = fetch_model_catalog(
        cache_path=tmp_path / "models_catalog_cache.json",
        transport=transport,
    )

    provider = result.providers[0]
    assert result.used_cache is False
    assert provider.id == "requesty"
    assert provider.api_base_url == "https://router.requesty.ai/v1"
    assert provider.env_names == ["REQUESTY_API_KEY"]
    assert provider.provider_package == "@ai-sdk/openai-compatible"
    assert provider.models[0].id == "openai/gpt-5.2-chat"
    assert provider.models[0].supports_tool_call is True

    matches = search_catalog(result, "gpt 5.2")
    assert [item.id for item in matches] == ["requesty"]
```

- [ ] **Step 2: Write failing cache fallback tests**

Add:

```python
def test_model_catalog_uses_cache_when_refresh_fails(tmp_path: Path) -> None:
    cache_path = tmp_path / "models_catalog_cache.json"

    def first_transport() -> dict[str, object]:
        return {
            "openrouter": {
                "id": "openrouter",
                "name": "OpenRouter",
                "env": ["OPENROUTER_API_KEY"],
                "api": "https://openrouter.ai/api/v1",
                "npm": "@openrouter/ai-sdk-provider",
                "models": {"anthropic/claude-sonnet": {"id": "anthropic/claude-sonnet"}},
            }
        }

    fetch_model_catalog(cache_path=cache_path, transport=first_transport)

    def failing_transport() -> dict[str, object]:
        raise OSError("network down")

    result = fetch_model_catalog(cache_path=cache_path, transport=failing_transport)

    assert result.used_cache is True
    assert result.error == "network down"
    assert result.providers[0].id == "openrouter"


def test_model_catalog_fails_explicitly_without_cache(tmp_path: Path) -> None:
    def failing_transport() -> dict[str, object]:
        raise OSError("network down")

    with pytest.raises(ModelCatalogError, match="network down"):
        fetch_model_catalog(
            cache_path=tmp_path / "missing_cache.json",
            transport=failing_transport,
        )
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```powershell
uv run pytest tests/test_model_catalog.py -q
```

Expected: FAIL because `haagent.models.catalog` does not exist.

- [ ] **Step 4: Implement catalog layer**

Create `src/haagent/models/catalog.py` with module docstring and dataclasses. Use `urllib.request` for default transport, JSON for cache, and explicit `ModelCatalogError`.

Key implementation shape:

```python
"""
src/haagent/models/catalog.py - 模型目录发现与缓存

负责从 Models.dev 读取公开 provider/model 元数据，并提供非敏感的搜索结果。
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from haagent.models.provider_profile import user_config_dir

MODELS_DEV_URL = "https://models.dev/api.json"
MODEL_CATALOG_CACHE_FILE = "models_catalog_cache.json"
CatalogTransport = Callable[[], dict[str, object]]


class ModelCatalogError(Exception):
    """模型目录读取失败。"""


@dataclass(frozen=True)
class ModelCatalogModel:
    id: str
    name: str
    family: str | None = None
    supports_tool_call: bool = False
    supports_reasoning: bool = False
    modalities: dict[str, object] = field(default_factory=dict)
    limits: dict[str, object] = field(default_factory=dict)
    cost: dict[str, object] = field(default_factory=dict)
    release_date: str | None = None
    last_updated: str | None = None


@dataclass(frozen=True)
class ModelCatalogProvider:
    id: str
    name: str
    env_names: list[str]
    api_base_url: str | None
    provider_package: str | None
    documentation_url: str | None
    models: list[ModelCatalogModel]


@dataclass(frozen=True)
class CatalogFetchResult:
    providers: list[ModelCatalogProvider]
    source: str
    fetched_at: str
    used_cache: bool = False
    error: str | None = None
```

- [ ] **Step 5: Run catalog tests**

Run:

```powershell
uv run pytest tests/test_model_catalog.py -q
```

Expected: PASS.

- [ ] **Step 6: Review checkpoint**

Confirm:

```powershell
git diff -- src/haagent/models/catalog.py tests/test_model_catalog.py
```

Expected: only catalog layer and tests changed.

---

### Task 2: Provider Profile Listing and Safe Save APIs

**Files:**
- Modify: `src/haagent/models/provider_profile.py`
- Modify: `tests/test_model_gateway.py`
- Modify: `tests/test_credentials.py`

**Interfaces:**
- Consumes: existing `ProviderProfileRecord`, `CredentialStore`, `credential_status`.
- Produces:
  - `list_provider_profile_records(*, config_path: Path | None = None) -> list[ProviderProfileRecord]`
  - `provider_profile_credential_status(name: str, *, environ: Mapping[str, str] | None = None, credential_store: CredentialStore | None = None, config_dir: Path | None = None) -> CredentialStatus`
  - `save_provider_profile_with_key(record: ProviderProfileRecord, api_key: str | None, *, credential_store: CredentialStore | None = None, config_dir: Path | None = None) -> Path`

- [ ] **Step 1: Write failing profile list/status tests**

Add to `tests/test_model_gateway.py`:

```python
from haagent.models.provider_profile import (
    ProviderProfileRecord,
    list_provider_profile_records,
    provider_profile_credential_status,
    save_provider_profile,
)


def test_provider_profiles_can_be_listed_without_secrets(tmp_path: Path) -> None:
    save_provider_profile(
        ProviderProfileRecord(
            name="router",
            provider="openai-chat",
            base_url="https://openrouter.ai/api/v1",
            model="openai/gpt-5.2-chat",
            api_key_env="OPENROUTER_API_KEY",
            credential_source="keyring",
        ),
        config_dir=tmp_path,
    )

    records = list_provider_profile_records(config_path=tmp_path / "providers.json")

    assert [record.name for record in records] == ["router"]
    assert records[0].model == "openai/gpt-5.2-chat"
    assert "secret" not in records[0].to_dict()


def test_provider_profile_credential_status_for_named_profile(tmp_path: Path) -> None:
    save_provider_profile(
        ProviderProfileRecord(
            name="router",
            provider="openai-chat",
            base_url="https://openrouter.ai/api/v1",
            model="openai/gpt-5.2-chat",
            api_key_env="OPENROUTER_API_KEY",
            credential_source="keyring",
        ),
        config_dir=tmp_path,
    )

    status = provider_profile_credential_status(
        "router",
        config_dir=tmp_path,
        credential_store=FakeCredentialStore({"haagent:router": "sk-test-secret"}),
    )

    assert status.available is True
    assert status.source_used == "keyring"
    assert "sk-test-secret" not in repr(status)
```

- [ ] **Step 2: Write failing save-with-key test**

Add to `tests/test_credentials.py`:

```python
from haagent.models.provider_profile import (
    ProviderProfileRecord,
    load_provider_profile_record,
    save_provider_profile_with_key,
)


def test_save_provider_profile_with_keyring_key_does_not_write_secret(tmp_path: Path) -> None:
    store = FakeCredentialStore()
    record = ProviderProfileRecord(
        name="router",
        provider="openai-chat",
        base_url="https://openrouter.ai/api/v1",
        model="openai/gpt-5.2-chat",
        api_key_env="OPENROUTER_API_KEY",
        credential_source="keyring",
    )

    save_provider_profile_with_key(
        record,
        "sk-test-secret",
        credential_store=store,
        config_dir=tmp_path,
    )

    saved = load_provider_profile_record(
        "router",
        config_path=tmp_path / "providers.json",
    )
    assert saved.name == "router"
    assert store.values["haagent:router"] == "sk-test-secret"
    assert "sk-test-secret" not in (tmp_path / "providers.json").read_text(encoding="utf-8")
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```powershell
uv run pytest tests/test_model_gateway.py::test_provider_profiles_can_be_listed_without_secrets tests/test_model_gateway.py::test_provider_profile_credential_status_for_named_profile tests/test_credentials.py::test_save_provider_profile_with_keyring_key_does_not_write_secret -q
```

Expected: FAIL because helper functions do not exist.

- [ ] **Step 4: Implement profile helpers**

Modify `src/haagent/models/provider_profile.py`:

```python
def list_provider_profile_records(*, config_path: Path | None = None) -> list[ProviderProfileRecord]:
    path = config_path or user_provider_profile_path()
    records = _load_profile_records(path) if path.exists() else []
    return [
        ProviderProfileRecord(
            name=_required_string(record, "name"),
            provider=_required_provider(record),
            base_url=_required_string(record, "base_url"),
            model=_required_string(record, "model"),
            api_key_env=_required_string(record, "api_key_env"),
            credential_source=_credential_source(record),
        )
        for record in records
    ]


def provider_profile_credential_status(
    name: str,
    *,
    environ: Mapping[str, str] | None = None,
    credential_store: CredentialStore | None = None,
    config_dir: Path | None = None,
):
    config_path = (config_dir / USER_PROVIDERS_FILE) if config_dir is not None else None
    record = load_provider_profile_record(name, config_path=config_path)
    return credential_status(
        CredentialRecord(
            profile_name=record.name,
            api_key_env=record.api_key_env,
            credential_source=record.credential_source,
        ),
        environ=environ,
        credential_store=credential_store,
        config_dir=config_dir,
    )
```

Implement `save_provider_profile_with_key` by calling `save_provider_profile`, then `save_keyring_api_key` only when `credential_source == "keyring"` and `api_key` is not empty. For `env`, reject non-empty `api_key` with `ProviderProfileError`. For `insecure_file`, call existing `save_insecure_api_key`.

- [ ] **Step 5: Run profile tests**

Run:

```powershell
uv run pytest tests/test_model_gateway.py tests/test_credentials.py -q
```

Expected: PASS.

- [ ] **Step 6: Review checkpoint**

Confirm:

```powershell
git diff -- src/haagent/models/provider_profile.py tests/test_model_gateway.py tests/test_credentials.py
```

Expected: profile helpers and targeted tests only.

---

### Task 3: Gateway Registry and Capability Mapping

**Files:**
- Create: `src/haagent/models/gateway_registry.py`
- Modify: `src/haagent/app/assistant_service.py`
- Modify: `tests/test_model_gateway.py`

**Interfaces:**
- Consumes: `ProviderProfile`, catalog provider metadata, existing OpenAI gateways.
- Produces:
  - `GatewayCapability`
  - `GatewayRegistryError`
  - `gateway_capability_for_profile(record: ProviderProfileRecord) -> GatewayCapability`
  - `catalog_provider_capability(provider: ModelCatalogProvider) -> GatewayCapability`
  - `gateway_from_profile(profile: ProviderProfile) -> ModelGateway`

- [ ] **Step 1: Write failing registry tests**

Add to `tests/test_model_gateway.py`:

```python
from haagent.models.catalog import ModelCatalogProvider
from haagent.models.gateway_registry import (
    catalog_provider_capability,
    gateway_capability_for_profile,
    gateway_from_profile,
)
from haagent.models.provider_profile import ProviderProfile, ProviderProfileRecord


def test_gateway_registry_maps_openai_chat_profile_to_runnable_gateway() -> None:
    record = ProviderProfileRecord(
        name="router",
        provider="openai-chat",
        base_url="https://openrouter.ai/api/v1",
        model="openai/gpt-5.2-chat",
        api_key_env="OPENROUTER_API_KEY",
    )

    capability = gateway_capability_for_profile(record)

    assert capability.status == "runnable"
    assert capability.gateway_provider == "openai-chat"


def test_gateway_registry_marks_native_catalog_provider_adapter_required() -> None:
    provider = ModelCatalogProvider(
        id="anthropic",
        name="Anthropic",
        env_names=["ANTHROPIC_API_KEY"],
        api_base_url=None,
        provider_package="@ai-sdk/anthropic",
        documentation_url="https://docs.anthropic.com/",
        models=[],
    )

    capability = catalog_provider_capability(provider)

    assert capability.status == "adapter_required"
    assert capability.reason == "native provider adapter is not available"


def test_gateway_registry_builds_existing_openai_chat_gateway() -> None:
    gateway = gateway_from_profile(
        ProviderProfile(
            name="router",
            provider="openai-chat",
            base_url="https://openrouter.ai/api/v1",
            model="openai/gpt-5.2-chat",
            api_key="sk-test",
        )
    )

    assert isinstance(gateway, OpenAIChatCompletionsGateway)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
uv run pytest tests/test_model_gateway.py::test_gateway_registry_maps_openai_chat_profile_to_runnable_gateway tests/test_model_gateway.py::test_gateway_registry_marks_native_catalog_provider_adapter_required tests/test_model_gateway.py::test_gateway_registry_builds_existing_openai_chat_gateway -q
```

Expected: FAIL because `gateway_registry.py` does not exist.

- [ ] **Step 3: Implement registry**

Create `src/haagent/models/gateway_registry.py`:

```python
"""
src/haagent/models/gateway_registry.py - 模型网关能力映射

负责把 profile 和公开模型目录映射为 HaAgent 当前可运行的 ModelGateway 能力。
"""

from __future__ import annotations

from dataclasses import dataclass

from haagent.models.catalog import ModelCatalogProvider
from haagent.models.gateway import (
    ModelGateway,
    OpenAIChatCompletionsGateway,
    OpenAIResponsesGateway,
)
from haagent.models.provider_profile import ProviderProfile, ProviderProfileError, ProviderProfileRecord


@dataclass(frozen=True)
class GatewayCapability:
    status: str
    gateway_provider: str | None
    reason: str | None = None


class GatewayRegistryError(Exception):
    """网关能力映射失败。"""


def gateway_capability_for_profile(record: ProviderProfileRecord) -> GatewayCapability:
    if record.provider in {"openai", "openai-chat"}:
        return GatewayCapability(status="runnable", gateway_provider=record.provider)
    return GatewayCapability(
        status="adapter_required",
        gateway_provider=None,
        reason="native provider adapter is not available",
    )
```

Move `_gateway_from_profile` logic from `assistant_service.py` into `gateway_from_profile`, then update `assistant_service.py` to import it.

- [ ] **Step 4: Run registry tests**

Run:

```powershell
uv run pytest tests/test_model_gateway.py -q
```

Expected: PASS.

- [ ] **Step 5: Review checkpoint**

Confirm:

```powershell
git diff -- src/haagent/models/gateway_registry.py src/haagent/app/assistant_service.py tests/test_model_gateway.py
```

Expected: gateway creation centralized; no runtime behavior change beyond import path.

---

### Task 4: AssistantService Model APIs

**Files:**
- Modify: `src/haagent/app/assistant_service.py`
- Modify: `tests/test_assistant_service.py`

**Interfaces:**
- Consumes: catalog, provider profile helpers, gateway registry.
- Produces:
  - `AssistantModelProfile`
  - `AssistantModelTestResult`
  - `AssistantService.list_model_profiles()`
  - `AssistantService.configure_model_profile(request)`
  - `AssistantService.set_default_model_profile(profile_name: str)`
  - `AssistantService.test_model_profile(profile_name: str)`

- [ ] **Step 1: Write failing list/default/test service tests**

Add to `tests/test_assistant_service.py`:

```python
from haagent.models.provider_profile import ProviderProfileRecord, save_active_profile, save_provider_profile


def test_service_lists_model_profiles_with_active_and_credential_status(tmp_path: Path) -> None:
    save_provider_profile(
        ProviderProfileRecord(
            name="router",
            provider="openai-chat",
            base_url="https://openrouter.ai/api/v1",
            model="openai/gpt-5.2-chat",
            api_key_env="OPENROUTER_API_KEY",
        ),
        config_dir=tmp_path / ".haagent",
    )
    save_active_profile("router", config_dir=tmp_path / ".haagent")
    service = _service(tmp_path, config_dir=tmp_path / ".haagent")

    profiles = service.list_model_profiles()

    assert len(profiles) == 1
    assert profiles[0].name == "router"
    assert profiles[0].active is True
    assert profiles[0].capability.status == "runnable"


def test_service_sets_default_model_profile_without_switching_current_session(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.set_default_model_profile("router")

    assert service.current_session() is None
```

In this task, update the local `_service(...)` test helper in `tests/test_assistant_service.py` so it accepts:

```python
def _service(
    tmp_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    gateway_factory=None,
    config_dir: Path | None = None,
    block_until_released: bool = False,
):
    ...
```

Use `config_dir` to point profile/settings reads at a temporary user config directory for tests.

- [ ] **Step 2: Write failing connection test service test**

Add:

```python
def test_service_connection_test_uses_gateway_factory_and_redacts_secret(tmp_path: Path) -> None:
    calls = []

    class RecordingGateway:
        provider_name = "openai-chat"

        def generate(self, messages, tool_schemas):
            calls.append((messages, tool_schemas))
            return ModelResponse(content="OK")

    def gateway_factory(profile):
        assert profile.api_key == "sk-test-secret"
        return RecordingGateway()

    service = _service(
        tmp_path,
        gateway_factory=gateway_factory,
        environ={"OPENROUTER_API_KEY": "sk-test-secret"},
    )

    result = service.test_model_profile("router")

    assert result.ok is True
    assert result.message == "OK"
    assert calls
    assert "sk-test-secret" not in repr(result)
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```powershell
uv run pytest tests/test_assistant_service.py::test_service_lists_model_profiles_with_active_and_credential_status tests/test_assistant_service.py::test_service_sets_default_model_profile_without_switching_current_session tests/test_assistant_service.py::test_service_connection_test_uses_gateway_factory_and_redacts_secret -q
```

Expected: FAIL because service APIs do not exist.

- [ ] **Step 4: Implement service dataclasses and APIs**

Add dataclasses to `assistant_service.py`:

```python
@dataclass(frozen=True)
class AssistantModelProfile:
    name: str
    provider: str
    base_url: str
    model: str
    api_key_env: str
    credential_source: str
    active: bool
    credential_available: bool
    credential_source_used: str | None
    capability: GatewayCapability


@dataclass(frozen=True)
class AssistantModelTestResult:
    ok: bool
    profile_name: str
    provider: str
    model: str
    message: str
```

Add methods that call profile helpers and registry. For `test_model_profile`, build a gateway from the named profile and call:

```python
gateway.generate(
    [{"role": "user", "content": "Reply with OK."}],
    [],
)
```

Catch `ProviderProfileError`, `CredentialError`, and `ModelCallError`; return `AssistantModelTestResult(ok=False, message=str(error))` after redacting common secret-bearing fields if needed.

- [ ] **Step 5: Run service tests**

Run:

```powershell
uv run pytest tests/test_assistant_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Review checkpoint**

Confirm:

```powershell
git diff -- src/haagent/app/assistant_service.py tests/test_assistant_service.py
```

Expected: service API only; no TUI code yet.

---

### Task 5: Current Session Model Switching

**Files:**
- Modify: `src/haagent/runtime/chat_session.py`
- Modify: `src/haagent/app/assistant_service.py`
- Modify: `tests/test_assistant_service.py`

**Interfaces:**
- Consumes: `gateway_from_profile`, current session status.
- Produces:
  - `AgentSession.switch_model_gateway(profile_name: str, provider: str, model: str, base_url: str, gateway: ModelGateway) -> None`
  - `AssistantService.switch_current_session_model(profile_name: str) -> AssistantSessionStatus`

- [ ] **Step 1: Write failing switch test for existing session**

Add to `tests/test_assistant_service.py`:

```python
def test_service_switches_current_session_model_without_changing_default(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create_session()

    status = service.switch_current_session_model("router")

    assert status.model_profile_name == "router"
    assert service.current_session().model_profile_name == "router"
```

Add `model_profile_name: str | None` to `AssistantSessionStatus` in the test expectation.

- [ ] **Step 2: Write failing switch-denied-while-running test**

Add:

```python
def test_service_rejects_model_switch_while_current_run_is_active(tmp_path: Path) -> None:
    service = _service(tmp_path, block_until_released=True)
    service.create_session()
    thread = threading.Thread(target=lambda: service.run_prompt_events("hello"))
    thread.start()

    try:
        with pytest.raises(AssistantServiceError, match="current task is running"):
            service.switch_current_session_model("router")
    finally:
        service.cancel_current_run()
        thread.join(timeout=2)
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```powershell
uv run pytest tests/test_assistant_service.py::test_service_switches_current_session_model_without_changing_default tests/test_assistant_service.py::test_service_rejects_model_switch_while_current_run_is_active -q
```

Expected: FAIL because switch APIs and status fields do not exist.

- [ ] **Step 4: Implement AgentSession switch method**

Modify `AgentSession`:

```python
    def switch_model_gateway(
        self,
        *,
        profile_name: str,
        provider: str,
        model: str,
        base_url: str,
        gateway: ModelGateway,
    ) -> None:
        if self._current_cancellation is not None:
            raise ChatSessionError("current task is running")
        self.model_gateway = gateway
        self._model_profile_name = profile_name
        self._model_provider = provider
        self._model_name = model
        self._model_base_url = base_url
        self._write_session_metadata()
```

Update `__init__`, `resume`, `status`, and `_write_session_metadata` so metadata records non-sensitive model info.

- [ ] **Step 5: Implement AssistantService switch**

Add `self._pending_model_profile_name: str | None = None`. In `create_session`, if pending profile exists, build that gateway instead of active default. Implement `switch_current_session_model`:

```python
    def switch_current_session_model(self, profile_name: str) -> AssistantSessionStatus:
        profile = load_provider_profile(profile_name, environ=self._environ)
        gateway = self._gateway_factory(profile)
        if self._session is None:
            self._pending_model_profile_name = profile_name
            return AssistantSessionStatus(
                session_id="pending",
                session_path=self._runs_root,
                workspace_root=self._workspace_root,
                provider=profile.provider,
                model_profile_name=profile_name,
            )
        try:
            self._session.switch_model_gateway(
                profile_name=profile_name,
                provider=profile.provider,
                model=profile.model,
                base_url=profile.base_url,
                gateway=gateway,
            )
        except ChatSessionError as error:
            raise AssistantServiceError(str(error)) from error
        return _session_status(self._session)
```

Adjust exact constructor fields to match the final `AssistantSessionStatus` dataclass.

- [ ] **Step 6: Run switch tests**

Run:

```powershell
uv run pytest tests/test_assistant_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Review checkpoint**

Confirm:

```powershell
git diff -- src/haagent/runtime/chat_session.py src/haagent/app/assistant_service.py tests/test_assistant_service.py
```

Expected: explicit switch semantics, no secret metadata.

---

### Task 6: TUI Model Center Overlay

**Files:**
- Create: `src/haagent/tui/models.py`
- Modify: `src/haagent/tui/commands.py`
- Modify: `src/haagent/tui/app.py`
- Modify: `tests/test_tui_app.py`

**Interfaces:**
- Consumes: `AssistantService.list_model_profiles`, `switch_current_session_model`, `set_default_model_profile`.
- Produces:
  - `ModelCenterOverlay`
  - `ModelCenterResult(action: str, profile_name: str | None)`
  - `/model` and `/models` actions.

- [ ] **Step 1: Write failing slash command registry test**

Update existing `test_tui_slash_command_registry_parses_known_and_unknown_commands`:

```python
model = parse_slash_command("/model", registry)
models = parse_slash_command("/models", registry)
assert model.command.action == "open_models"
assert models.command.action == "open_models"
```

- [ ] **Step 2: Write failing overlay test**

Add to `tests/test_tui_app.py`:

```python
def test_tui_model_overlay_switches_session_and_sets_default(tmp_path: Path) -> None:
    service = FakeAssistantService(workspace_root=tmp_path)
    service.model_profiles = [
        SimpleNamespace(
            name="router",
            provider="openai-chat",
            model="openai/gpt-5.2-chat",
            active=False,
            credential_available=True,
            capability=SimpleNamespace(status="runnable"),
        )
    ]

    async def run() -> None:
        app = HaAgentTuiApp(service)
        async with app.run_test() as pilot:
            await pilot.press("/")
            await pilot.press("m", "o", "d", "e", "l", "enter")
            assert "router" in _all_text(app)
            await pilot.press("enter")
            assert service.switched_model_profile == "router"
            await pilot.press("/")
            await pilot.press("m", "o", "d", "e", "l", "enter")
            await pilot.press("p")
            assert service.default_model_profile == "router"

    asyncio.run(run())
```

Extend `FakeAssistantService` with model profile methods and tracking fields.

- [ ] **Step 3: Run tests and verify they fail**

Run:

```powershell
uv run pytest tests/test_tui_app.py::test_tui_slash_command_registry_parses_known_and_unknown_commands tests/test_tui_app.py::test_tui_model_overlay_switches_session_and_sets_default -q
```

Expected: FAIL because commands and overlay do not exist.

- [ ] **Step 4: Implement commands and overlay**

Add command entries:

```python
SlashCommand("model", "打开模型中心", "open_models"),
SlashCommand("models", "搜索和切换模型", "open_models"),
```

Create `ModelCenterOverlay(ModalScreen[ModelCenterResult | None])`. Use a `DataTable` or focused list with rows showing active marker, profile name, provider/model, credential status, and capability.

Wire `HaAgentTuiApp.action_open_models`:

```python
    def action_open_models(self) -> None:
        self.push_screen(ModelCenterOverlay(self._service), self._handle_model_center_result)
```

Handle result:

```python
    def _handle_model_center_result(self, result: ModelCenterResult | None) -> None:
        if result is None or result.profile_name is None:
            self._restore_prompt_focus()
            return
        if result.action == "switch_session":
            status = self._service.switch_current_session_model(result.profile_name)
            self._append_line(f"模型已切换到当前会话：{status.model_profile_name}")
        elif result.action == "set_default":
            self._service.set_default_model_profile(result.profile_name)
            self._append_line(f"默认模型 profile 已设为：{result.profile_name}")
        self._refresh()
```

- [ ] **Step 5: Run TUI overlay tests**

Run:

```powershell
uv run pytest tests/test_tui_app.py::test_tui_slash_command_registry_parses_known_and_unknown_commands tests/test_tui_app.py::test_tui_model_overlay_switches_session_and_sets_default -q
```

Expected: PASS.

- [ ] **Step 6: Review checkpoint**

Confirm:

```powershell
git diff -- src/haagent/tui/models.py src/haagent/tui/commands.py src/haagent/tui/app.py tests/test_tui_app.py
```

Expected: no catalog wizard yet; only existing profile switch/default overlay.

---

### Task 7: Model Setup Wizard, Catalog Refresh, and Connection Test Workers

**Files:**
- Modify: `src/haagent/tui/models.py`
- Modify: `src/haagent/tui/app.py`
- Modify: `tests/test_tui_app.py`

**Interfaces:**
- Consumes: catalog service APIs, profile configure API, connection test API.
- Produces:
  - `ModelSetupWizard`
  - worker-backed catalog refresh
  - worker-backed connection test
  - masked API key input.

- [ ] **Step 1: Write failing masked-key wizard test**

Add to `tests/test_tui_app.py`:

```python
def test_tui_model_setup_wizard_masks_key_and_saves_keyring_profile(tmp_path: Path) -> None:
    service = FakeAssistantService(workspace_root=tmp_path)
    service.catalog_providers = [
        SimpleNamespace(
            id="requesty",
            name="Requesty",
            env_names=["REQUESTY_API_KEY"],
            api_base_url="https://router.requesty.ai/v1",
            models=[SimpleNamespace(id="openai/gpt-5.2-chat", name="GPT 5.2 Chat")],
        )
    ]

    async def run() -> None:
        app = HaAgentTuiApp(service)
        async with app.run_test() as pilot:
            await pilot.press("/")
            await pilot.press("m", "o", "d", "e", "l", "enter")
            await pilot.press("n")
            await pilot.press("enter")
            await pilot.press("enter")
            await pilot.press("s", "k", "-", "t", "e", "s", "t", "-", "s", "e", "c", "r", "e", "t")
            assert "sk-test-secret" not in _all_text(app)
            await pilot.press("enter")
            assert service.configured_model_profile.name == "requesty-openai-gpt-5-2-chat"
            assert service.configured_api_key == "sk-test-secret"

    asyncio.run(run())
```

- [ ] **Step 2: Write failing connection test worker test**

Add:

```python
def test_tui_model_overlay_runs_connection_test_without_showing_secret(tmp_path: Path) -> None:
    service = FakeAssistantService(workspace_root=tmp_path)
    service.connection_test_result = SimpleNamespace(
        ok=True,
        profile_name="router",
        provider="openai-chat",
        model="openai/gpt-5.2-chat",
        message="OK",
    )

    async def run() -> None:
        app = HaAgentTuiApp(service)
        async with app.run_test() as pilot:
            await pilot.press("/")
            await pilot.press("m", "o", "d", "e", "l", "enter")
            await pilot.press("t")
            await pilot.pause()
            assert service.tested_model_profile == "router"
            assert "OK" in _all_text(app)
            assert "sk-test-secret" not in _all_text(app)

    asyncio.run(run())
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```powershell
uv run pytest tests/test_tui_app.py::test_tui_model_setup_wizard_masks_key_and_saves_keyring_profile tests/test_tui_app.py::test_tui_model_overlay_runs_connection_test_without_showing_secret -q
```

Expected: FAIL because wizard and worker actions do not exist.

- [ ] **Step 4: Implement wizard**

In `src/haagent/tui/models.py`, add a `ModelSetupWizard(ModalScreen[ModelSetupResult | None])` using `Input(password=True)` for API key. Keep staged values in attributes, not conversation log.

For env credential mode, do not mount the API key input. Show only the env var name from catalog provider.

Use service call shape:

```python
self._service.configure_model_profile(
    ModelProfileConfigureRequest(
        name=profile_name,
        provider=gateway_provider,
        base_url=base_url,
        model=model_id,
        api_key_env=api_key_env,
        credential_source=credential_source,
        api_key=api_key_or_none,
    )
)
```

`ModelProfileConfigureRequest` is required in `src/haagent/app/assistant_service.py` for this task set. Define it there as:

```python
@dataclass(frozen=True)
class ModelProfileConfigureRequest:
    name: str
    provider: str
    base_url: str
    model: str
    api_key_env: str
    credential_source: str
    api_key: str | None = None
```

- [ ] **Step 5: Implement workers**

Use Textual worker APIs:

```python
@work(exclusive=True)
async def action_refresh_catalog(self) -> None:
    result = self._service.refresh_model_catalog()
    self._catalog_result = result
    self.refresh()


@work(exclusive=True)
async def action_test_selected_profile(self) -> None:
    result = self._service.test_model_profile(self.selected_profile_name)
    self._test_result = result
    self.refresh()
```

If the service calls are sync, wrap them in `self.run_worker(..., thread=True)` or use `@work(thread=True, exclusive=True)` and update UI via messages or `call_from_thread`.

- [ ] **Step 6: Run TUI wizard/worker tests**

Run:

```powershell
uv run pytest tests/test_tui_app.py::test_tui_model_setup_wizard_masks_key_and_saves_keyring_profile tests/test_tui_app.py::test_tui_model_overlay_runs_connection_test_without_showing_secret -q
```

Expected: PASS.

- [ ] **Step 7: Run broader TUI tests**

Run:

```powershell
uv run pytest tests/test_tui_app.py -q
```

Expected: PASS.

- [ ] **Step 8: Review checkpoint**

Confirm:

```powershell
git diff -- src/haagent/tui/models.py src/haagent/tui/app.py src/haagent/app/assistant_service.py tests/test_tui_app.py
```

Expected: wizard and worker changes only; no secret values in snapshots or strings.

---

### Task 8: Anthropic Native Gateway Adapter Slice

**Files:**
- Modify: `src/haagent/models/gateway.py`
- Modify: `src/haagent/models/gateway_registry.py`
- Modify: `tests/test_model_gateway.py`

**Interfaces:**
- Produces:
  - `AnthropicMessagesGateway`
  - Registry support for profile provider `anthropic`.

Use Anthropic official Messages API and tool-use documentation during implementation. The adapter must normalize HaAgent `ModelResponse` and `ToolCall`.

- [ ] **Step 1: Write failing Anthropic text response test**

Add to `tests/test_model_gateway.py`:

```python
from haagent.models.gateway import AnthropicMessagesGateway


def test_anthropic_gateway_text_response_uses_messages_payload() -> None:
    captured = {}

    def transport(payload: dict[str, object], api_key: str, endpoint: str) -> dict[str, object]:
        captured["payload"] = payload
        captured["api_key"] = api_key
        captured["endpoint"] = endpoint
        return {
            "content": [{"type": "text", "text": "hello"}],
            "stop_reason": "end_turn",
        }

    gateway = AnthropicMessagesGateway(
        api_key="sk-ant-test",
        model="claude-sonnet-4-5",
        transport=transport,
    )

    result = gateway.generate([{"role": "user", "content": "hi"}], [])

    assert result.content == "hello"
    assert captured["payload"]["model"] == "claude-sonnet-4-5"
    assert captured["payload"]["messages"] == [{"role": "user", "content": "hi"}]
    assert captured["api_key"] == "sk-ant-test"
```

- [ ] **Step 2: Write failing Anthropic tool-call normalization test**

Add:

```python
def test_anthropic_gateway_normalizes_tool_use_blocks() -> None:
    def transport(payload: dict[str, object], api_key: str, endpoint: str) -> dict[str, object]:
        assert payload["tools"] == [
            {
                "name": "file_read",
                "description": "Read a file",
                "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
            }
        ]
        return {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_123",
                    "name": "file_read",
                    "input": {"path": "README.md"},
                }
            ],
            "stop_reason": "tool_use",
        }

    gateway = AnthropicMessagesGateway(
        api_key="sk-ant-test",
        model="claude-sonnet-4-5",
        transport=transport,
    )

    result = gateway.generate(
        [{"role": "user", "content": "read"}],
        [{"name": "file_read", "description": "Read a file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}],
    )

    assert result.tool_calls == [ToolCall(id="toolu_123", name="file_read", arguments={"path": "README.md"})]
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```powershell
uv run pytest tests/test_model_gateway.py::test_anthropic_gateway_text_response_uses_messages_payload tests/test_model_gateway.py::test_anthropic_gateway_normalizes_tool_use_blocks -q
```

Expected: FAIL because `AnthropicMessagesGateway` does not exist.

- [ ] **Step 4: Implement Anthropic adapter**

Add `AnthropicMessagesGateway` with transport injection. Convert internal tool schemas to Anthropic tools using `input_schema`. Parse `content` blocks:

```python
class AnthropicMessagesGateway(ModelGateway):
    provider_name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-5",
        base_url: str | None = None,
        transport: AnthropicTransport | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ModelCallError("ANTHROPIC_API_KEY is required")
        self.model = model
        self.endpoint = _normalize_anthropic_endpoint(base_url)
        self.transport = transport or _anthropic_transport
```

Implement `_anthropic_transport` with headers `x-api-key`, `anthropic-version`, and JSON body. Do not log headers.

- [ ] **Step 5: Register Anthropic**

In `gateway_registry.py`, map profile provider `anthropic` to `AnthropicMessagesGateway` and mark catalog provider package `@ai-sdk/anthropic` as runnable with gateway provider `anthropic`.

- [ ] **Step 6: Run gateway tests**

Run:

```powershell
uv run pytest tests/test_model_gateway.py -q
```

Expected: PASS.

- [ ] **Step 7: Review checkpoint**

Confirm:

```powershell
git diff -- src/haagent/models/gateway.py src/haagent/models/gateway_registry.py tests/test_model_gateway.py
```

Expected: Anthropic adapter only; no Google changes yet.

---

### Task 9: Google Gemini Native Gateway Adapter Slice

**Files:**
- Modify: `src/haagent/models/gateway.py`
- Modify: `src/haagent/models/gateway_registry.py`
- Modify: `tests/test_model_gateway.py`

**Interfaces:**
- Produces:
  - `GoogleGeminiGateway`
  - Registry support for profile provider `google`.

Use Google Gemini API official `generateContent` and function calling documentation during implementation. The adapter must normalize HaAgent `ModelResponse` and `ToolCall`.

- [ ] **Step 1: Write failing Gemini text response test**

Add to `tests/test_model_gateway.py`:

```python
from haagent.models.gateway import GoogleGeminiGateway


def test_google_gemini_gateway_text_response_uses_generate_content_payload() -> None:
    captured = {}

    def transport(payload: dict[str, object], api_key: str, endpoint: str) -> dict[str, object]:
        captured["payload"] = payload
        captured["api_key"] = api_key
        captured["endpoint"] = endpoint
        return {
            "candidates": [
                {"content": {"parts": [{"text": "hello"}], "role": "model"}}
            ]
        }

    gateway = GoogleGeminiGateway(
        api_key="gemini-test-key",
        model="gemini-2.5-pro",
        transport=transport,
    )

    result = gateway.generate([{"role": "user", "content": "hi"}], [])

    assert result.content == "hello"
    assert captured["payload"]["contents"] == [
        {"role": "user", "parts": [{"text": "hi"}]}
    ]
    assert captured["api_key"] == "gemini-test-key"
```

- [ ] **Step 2: Write failing Gemini function-call normalization test**

Add:

```python
def test_google_gemini_gateway_normalizes_function_calls() -> None:
    def transport(payload: dict[str, object], api_key: str, endpoint: str) -> dict[str, object]:
        assert payload["tools"][0]["functionDeclarations"][0]["name"] == "file_read"
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "file_read",
                                    "args": {"path": "README.md"},
                                }
                            }
                        ],
                        "role": "model",
                    }
                }
            ]
        }

    gateway = GoogleGeminiGateway(
        api_key="gemini-test-key",
        model="gemini-2.5-pro",
        transport=transport,
    )

    result = gateway.generate(
        [{"role": "user", "content": "read"}],
        [{"name": "file_read", "description": "Read a file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}],
    )

    assert result.tool_calls == [ToolCall(id="file_read:0", name="file_read", arguments={"path": "README.md"})]
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```powershell
uv run pytest tests/test_model_gateway.py::test_google_gemini_gateway_text_response_uses_generate_content_payload tests/test_model_gateway.py::test_google_gemini_gateway_normalizes_function_calls -q
```

Expected: FAIL because `GoogleGeminiGateway` does not exist.

- [ ] **Step 4: Implement Gemini adapter**

Add `GoogleGeminiGateway` with transport injection. Normalize messages to `contents`, convert tool schemas to `functionDeclarations`, and parse candidate parts. Use generated synthetic ids for function calls because Gemini function calls do not expose OpenAI-style ids in the basic response shape.

Endpoint shape:

```python
https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
```

Pass the API key as query parameter or header according to current official docs; keep the key out of error strings and tests.

- [ ] **Step 5: Register Google**

In `gateway_registry.py`, map profile provider `google` to `GoogleGeminiGateway` and catalog package `@ai-sdk/google` to runnable with gateway provider `google`.

- [ ] **Step 6: Run gateway tests**

Run:

```powershell
uv run pytest tests/test_model_gateway.py -q
```

Expected: PASS.

- [ ] **Step 7: Review checkpoint**

Confirm:

```powershell
git diff -- src/haagent/models/gateway.py src/haagent/models/gateway_registry.py tests/test_model_gateway.py
```

Expected: Google adapter only; no TUI or service changes unless registry signatures required it.

---

### Task 10: Full Integration and Documentation Pass

**Files:**
- Modify: `docs/superpowers/specs/2026-06-28-tui-model-center-design.md` only if implementation changes a documented contract.
- Modify: tests touched by previous tasks only for final consistency.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: verified implementation ready for handoff.

- [ ] **Step 1: Run focused model/profile/service/TUI tests**

Run:

```powershell
uv run pytest tests/test_model_catalog.py tests/test_model_gateway.py tests/test_credentials.py tests/test_assistant_service.py tests/test_tui_app.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run:

```powershell
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 3: Run HaAgent quality gate**

Run:

```powershell
uv run haagent check
```

Expected: command exits 0. If it runs pytest internally, capture only failing summaries if any.

- [ ] **Step 4: Secret scan of changed code and tests**

Run:

```powershell
git diff
```

Expected:

- No real API key values.
- Test fake secrets only use obvious dummy strings such as `sk-test-secret`.
- No Authorization header or key value appears in error display assertions.
- No TUI text renders typed key values.

- [ ] **Step 5: Final capability check**

Manually verify from tests and code:

- `/model` and `/models` open the model center.
- `Enter` calls session switch only.
- `p` calls default profile save only.
- `n` opens setup wizard.
- `r` refreshes catalog through worker.
- `t` runs connection test through `ModelGateway`.
- OpenAI/OpenAI-compatible providers are runnable.
- Anthropic and Google are runnable if Tasks 8 and 9 pass; otherwise they remain `adapter_required` with explicit handoff note.

- [ ] **Step 6: Handoff summary**

Prepare final response with:

- Files changed.
- Tests run and exact result.
- Any provider adapter limitations.
- Confirmation that no git commit was made unless the user explicitly requested it.
