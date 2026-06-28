"""
haagent/models/gateway.py - 统一模型网关接口

上层只依赖 ModelGateway 协议；真实 provider 失败必须显式暴露。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

class ModelCallError(RuntimeError):
    """Raised when a model provider fails explicitly."""


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]
    id: str = ""


@dataclass(frozen=True)
class ModelResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)


class ModelGateway(Protocol):
    provider_name: str

    def generate(
        self,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
    ) -> ModelResponse:
        """Generate a model response given a conversation messages list."""


Transport = Callable[[dict[str, object], str], dict[str, object]]
AnthropicTransport = Callable[[dict[str, object], str, str], dict[str, object]]
GoogleGeminiTransport = Callable[[dict[str, object], str, str], dict[str, object]]
DEFAULT_RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses"
DEFAULT_CHAT_COMPLETIONS_ENDPOINT = "https://api.openai.com/v1/chat/completions"
DEFAULT_ANTHROPIC_MESSAGES_ENDPOINT = "https://api.anthropic.com/v1/messages"
DEFAULT_GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class OpenAIResponsesGateway:
    provider_name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4.1-mini",
        base_url: str | None = None,
        transport: Transport | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._model = model
        configured_base_url = (
            base_url
            if base_url is not None
            else os.environ.get("OPENAI_BASE_URL")
        )
        self._responses_endpoint = _normalize_responses_endpoint(configured_base_url)
        self._transport = transport or (
            lambda payload, api_key: _responses_transport(
                payload,
                api_key,
                self._responses_endpoint,
            )
        )

    @property
    def responses_endpoint(self) -> str:
        """返回本次 gateway 会请求的 Responses API endpoint，便于审计和测试。"""
        return self._responses_endpoint

    def generate(
        self,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
    ) -> ModelResponse:
        """调用 OpenAI Responses API，并把 provider 输出收敛成统一 ModelResponse。"""
        if not self._api_key:
            raise ModelCallError("OPENAI_API_KEY is required for OpenAIResponsesGateway")

        # Responses API uses "input" — convert messages to input format
        payload: dict[str, object] = {
            "model": self._model,
            "input": _messages_to_responses_input(messages),
        }
        if tool_schemas:
            payload["tools"] = tool_schemas
        try:
            response = self._transport(payload, self._api_key)
        except Exception as error:
            raise ModelCallError(str(error)) from error

        output_text = response.get("output_text")
        if not isinstance(output_text, str):
            raise ModelCallError("OpenAI response did not include output_text")
        return ModelResponse(content=output_text, tool_calls=_parse_tool_calls(response))


class OpenAIChatCompletionsGateway:
    provider_name = "openai-chat"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4.1-mini",
        base_url: str | None = None,
        transport: Transport | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._model = model
        self._chat_completions_endpoint = _normalize_chat_completions_endpoint(base_url)
        self._transport = transport or (
            lambda payload, api_key: _chat_completions_transport(
                payload,
                api_key,
                self._chat_completions_endpoint,
            )
        )

    @property
    def chat_completions_endpoint(self) -> str:
        """返回本次 gateway 会请求的 Chat Completions endpoint，便于审计和测试。"""
        return self._chat_completions_endpoint

    def generate(
        self,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
    ) -> ModelResponse:
        """调用 OpenAI Chat Completions 兼容 API，并归一化为 ModelResponse。"""
        if not self._api_key:
            raise ModelCallError(
                "OPENAI_API_KEY is required for OpenAIChatCompletionsGateway",
            )

        payload: dict[str, object] = {
            "model": self._model,
            "messages": messages,
        }
        if tool_schemas:
            payload["tools"] = _chat_tool_schemas(tool_schemas)
        try:
            response = self._transport(payload, self._api_key)
        except Exception as error:
            raise ModelCallError(str(error)) from error
        return _parse_chat_completion_response(response)


class AnthropicMessagesGateway:
    provider_name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-5",
        base_url: str | None = None,
        transport: AnthropicTransport | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._model = model
        self._messages_endpoint = _normalize_anthropic_messages_endpoint(base_url)
        self._transport = transport or _anthropic_transport

    @property
    def messages_endpoint(self) -> str:
        """返回本次 gateway 会请求的 Anthropic Messages endpoint，便于审计和测试。"""
        return self._messages_endpoint

    def generate(
        self,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
    ) -> ModelResponse:
        """调用 Anthropic Messages API，并归一化为统一 ModelResponse。"""
        if not self._api_key:
            raise ModelCallError("ANTHROPIC_API_KEY is required for AnthropicMessagesGateway")

        system, anthropic_messages = _anthropic_messages(messages)
        payload: dict[str, object] = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": anthropic_messages,
        }
        if system:
            payload["system"] = system
        if tool_schemas:
            payload["tools"] = _anthropic_tool_schemas(tool_schemas)
        try:
            response = self._transport(payload, self._api_key, self._messages_endpoint)
        except Exception as error:
            raise ModelCallError(str(error)) from error
        return _parse_anthropic_response(response)


class GoogleGeminiGateway:
    provider_name = "google"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-2.5-pro",
        base_url: str | None = None,
        transport: GoogleGeminiTransport | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self._model = model
        self._endpoint = _normalize_gemini_generate_content_endpoint(base_url, model)
        self._transport = transport or _google_gemini_transport

    @property
    def generate_content_endpoint(self) -> str:
        """返回本次 gateway 会请求的 Gemini generateContent endpoint，便于审计和测试。"""
        return self._endpoint

    def generate(
        self,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
    ) -> ModelResponse:
        """调用 Gemini generateContent API，并归一化为统一 ModelResponse。"""
        if not self._api_key:
            raise ModelCallError("GEMINI_API_KEY is required for GoogleGeminiGateway")

        system_instruction, contents = _gemini_contents(messages)
        payload: dict[str, object] = {
            "contents": contents,
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        if tool_schemas:
            payload["tools"] = _gemini_tool_schemas(tool_schemas)
        try:
            response = self._transport(payload, self._api_key, self._endpoint)
        except Exception as error:
            raise ModelCallError(str(error)) from error
        return _parse_gemini_response(response)


def _parse_tool_arguments(arguments: str) -> dict[str, Any]:
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError as error:
        raise ModelCallError("invalid tool arguments JSON") from error
    if not isinstance(parsed, dict):
        raise ModelCallError("tool arguments must be a JSON object")
    return parsed


def _parse_tool_calls(response: dict[str, object]) -> list[ToolCall]:
    output = response.get("output")
    if output is None:
        return []
    if not isinstance(output, list):
        raise ModelCallError("OpenAI output must be a list when present")

    tool_calls: list[ToolCall] = []
    for item in output:
        # 当前只支持 Responses API 的最小 function_call 结构，避免误吞 provider 新格式。
        if not isinstance(item, dict):
            raise ModelCallError("unsupported OpenAI output item")
        output_type = item.get("type")
        if output_type in {"message", "output_text", "text"}:
            continue
        if output_type != "function_call":
            raise ModelCallError(f"unsupported OpenAI output type: {output_type}")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise ModelCallError("missing tool name")
        arguments = item.get("arguments")
        if not isinstance(arguments, str):
            raise ModelCallError("missing tool arguments")
        call_id = str(item.get("call_id") or item.get("id") or "")
        tool_calls.append(ToolCall(name=name, args=_parse_tool_arguments(arguments), id=call_id))
    return tool_calls


def _chat_tool_schemas(tool_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把内部工具 schema 转成 Chat Completions 的 function tool 格式。"""
    return [
        {
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema.get("description", ""),
                "parameters": schema.get("parameters", {}),
            },
        }
        for schema in tool_schemas
    ]


def _parse_chat_completion_response(response: dict[str, object]) -> ModelResponse:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelCallError("OpenAI chat response did not include choices")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ModelCallError("OpenAI chat choice must be an object")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise ModelCallError("OpenAI chat choice did not include message")
    content = message.get("content", "")
    if content is None:
        content = ""
    if not isinstance(content, str):
        raise ModelCallError("OpenAI chat message content must be a string")
    return ModelResponse(
        content=content,
        tool_calls=_parse_chat_tool_calls(message.get("tool_calls")),
    )


def _parse_chat_tool_calls(raw_tool_calls: object) -> list[ToolCall]:
    if raw_tool_calls is None:
        return []
    if not isinstance(raw_tool_calls, list):
        raise ModelCallError("OpenAI chat tool_calls must be a list when present")
    tool_calls: list[ToolCall] = []
    for item in raw_tool_calls:
        if not isinstance(item, dict):
            raise ModelCallError("unsupported OpenAI chat tool_call item")
        if item.get("type") != "function":
            raise ModelCallError(
                f"unsupported OpenAI chat tool_call type: {item.get('type')}",
            )
        function = item.get("function")
        if not isinstance(function, dict):
            raise ModelCallError("OpenAI chat tool_call missing function")
        name = function.get("name")
        if not isinstance(name, str) or not name:
            raise ModelCallError("missing tool name")
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            raise ModelCallError("missing tool arguments")
        tool_call_id = str(item.get("id") or "")
        tool_calls.append(ToolCall(name=name, args=_parse_tool_arguments(arguments), id=tool_call_id))
    return tool_calls


def _anthropic_messages(messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    system_parts: list[str] = []
    normalized: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content", "")
        if not isinstance(content, str):
            raise ModelCallError("Anthropic message content must be a string")
        if role == "system":
            if content:
                system_parts.append(content)
            continue
        if role == "user":
            normalized.append({"role": "user", "content": content})
            continue
        if role == "assistant":
            normalized.append(_anthropic_assistant_message(content, message.get("tool_calls")))
            continue
        if role == "tool":
            tool_result_block = _anthropic_tool_result_block(message)
            if _is_anthropic_tool_result_message(normalized[-1] if normalized else None):
                normalized[-1]["content"].append(tool_result_block)
            else:
                normalized.append({"role": "user", "content": [tool_result_block]})
            continue
        raise ModelCallError(f"unsupported Anthropic message role: {role}")
    system = "\n\n".join(system_parts) if system_parts else None
    return system, normalized


def _anthropic_assistant_message(content: str, raw_tool_calls: object) -> dict[str, Any]:
    if raw_tool_calls is None:
        return {"role": "assistant", "content": content}
    if not isinstance(raw_tool_calls, list):
        raise ModelCallError("Anthropic assistant tool_calls must be a list when present")
    blocks: list[dict[str, Any]] = []
    if content:
        blocks.append({"type": "text", "text": content})
    for item in raw_tool_calls:
        if not isinstance(item, dict):
            raise ModelCallError("unsupported Anthropic assistant tool_call item")
        if item.get("type") != "function":
            raise ModelCallError(
                f"unsupported Anthropic assistant tool_call type: {item.get('type')}",
            )
        function = item.get("function")
        if not isinstance(function, dict):
            raise ModelCallError("Anthropic assistant tool_call missing function")
        name = function.get("name")
        if not isinstance(name, str) or not name:
            raise ModelCallError("missing tool name")
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            raise ModelCallError("missing tool arguments")
        blocks.append({
            "type": "tool_use",
            "id": str(item.get("id") or ""),
            "name": name,
            "input": _parse_tool_arguments(arguments),
        })
    return {"role": "assistant", "content": blocks}


def _anthropic_tool_result_block(message: dict[str, Any]) -> dict[str, Any]:
    tool_call_id = message.get("tool_call_id")
    if not isinstance(tool_call_id, str) or not tool_call_id:
        raise ModelCallError("Anthropic tool result missing tool_call_id")
    content = message.get("content", "")
    if not isinstance(content, str):
        raise ModelCallError("Anthropic tool result content must be a string")
    return {
        "type": "tool_result",
        "tool_use_id": tool_call_id,
        "content": content,
    }


def _is_anthropic_tool_result_message(message: object) -> bool:
    if not isinstance(message, dict) or message.get("role") != "user":
        return False
    content = message.get("content")
    if not isinstance(content, list) or not content:
        return False
    return all(isinstance(item, dict) and item.get("type") == "tool_result" for item in content)


def _anthropic_tool_schemas(tool_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": schema["name"],
            "description": schema.get("description", ""),
            "input_schema": schema.get("parameters", {}),
        }
        for schema in tool_schemas
    ]


def _parse_anthropic_response(response: dict[str, object]) -> ModelResponse:
    content_blocks = response.get("content")
    if not isinstance(content_blocks, list):
        raise ModelCallError("Anthropic response did not include content blocks")

    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in content_blocks:
        if not isinstance(block, dict):
            raise ModelCallError("Anthropic content block must be an object")
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if not isinstance(text, str):
                raise ModelCallError("Anthropic text block must include text")
            text_parts.append(text)
            continue
        if block_type == "tool_use":
            name = block.get("name")
            if not isinstance(name, str) or not name:
                raise ModelCallError("Anthropic tool_use block missing name")
            raw_input = block.get("input")
            if not isinstance(raw_input, dict):
                raise ModelCallError("Anthropic tool_use block input must be an object")
            tool_id = str(block.get("id") or "")
            tool_calls.append(ToolCall(name=name, args=raw_input, id=tool_id))
            continue
        raise ModelCallError(f"unsupported Anthropic content block type: {block_type}")
    return ModelResponse(content="".join(text_parts), tool_calls=tool_calls)


def _gemini_contents(messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    for message in messages:
        raw_role = message.get("role")
        content = message.get("content", "")
        if not isinstance(content, str):
            raise ModelCallError("Gemini message content must be a string")
        if raw_role == "system":
            if content:
                system_parts.append(content)
            continue
        if raw_role == "user":
            contents.append({"role": "user", "parts": [{"text": content}]})
            continue
        if raw_role == "assistant":
            contents.append(_gemini_assistant_content(content, message.get("tool_calls")))
            continue
        if raw_role == "model":
            contents.append({"role": "model", "parts": [{"text": content}]})
            continue
        if raw_role == "tool":
            contents.append(_gemini_tool_result_content(message))
            continue
        raise ModelCallError(f"unsupported Gemini message role: {raw_role}")
    system = "\n\n".join(system_parts) if system_parts else None
    return system, contents


def _gemini_assistant_content(content: str, raw_tool_calls: object) -> dict[str, Any]:
    if raw_tool_calls is None:
        return {"role": "model", "parts": [{"text": content}]}
    if not isinstance(raw_tool_calls, list):
        raise ModelCallError("Gemini assistant tool_calls must be a list when present")
    parts: list[dict[str, Any]] = []
    if content:
        parts.append({"text": content})
    for item in raw_tool_calls:
        if not isinstance(item, dict):
            raise ModelCallError("unsupported Gemini assistant tool_call item")
        if item.get("type") != "function":
            raise ModelCallError(
                f"unsupported Gemini assistant tool_call type: {item.get('type')}",
            )
        function = item.get("function")
        if not isinstance(function, dict):
            raise ModelCallError("Gemini assistant tool_call missing function")
        name = function.get("name")
        if not isinstance(name, str) or not name:
            raise ModelCallError("missing tool name")
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            raise ModelCallError("missing tool arguments")
        parts.append({
            "functionCall": {
                "name": name,
                "args": _parse_tool_arguments(arguments),
            }
        })
    return {"role": "model", "parts": parts}


def _gemini_tool_result_content(message: dict[str, Any]) -> dict[str, Any]:
    name = message.get("name")
    if not isinstance(name, str) or not name:
        raise ModelCallError("Gemini tool result missing name")
    content = message.get("content", "")
    if not isinstance(content, str):
        raise ModelCallError("Gemini tool result content must be a string")
    return {
        "role": "user",
        "parts": [
            {
                "functionResponse": {
                    "name": name,
                    "response": {"content": content},
                }
            }
        ],
    }


def _gemini_tool_schemas(tool_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "functionDeclarations": [
                {
                    "name": schema["name"],
                    "description": schema.get("description", ""),
                    "parameters": schema.get("parameters", {}),
                }
            ]
        }
        for schema in tool_schemas
    ]


def _parse_gemini_response(response: dict[str, object]) -> ModelResponse:
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ModelCallError("Gemini response did not include candidates")
    first_candidate = candidates[0]
    if not isinstance(first_candidate, dict):
        raise ModelCallError("Gemini candidate must be an object")
    content = first_candidate.get("content")
    if not isinstance(content, dict):
        raise ModelCallError("Gemini candidate did not include content")
    parts = content.get("parts")
    if not isinstance(parts, list):
        raise ModelCallError("Gemini content did not include parts")

    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for part in parts:
        if not isinstance(part, dict):
            raise ModelCallError("Gemini part must be an object")
        if "text" in part:
            text = part["text"]
            if not isinstance(text, str):
                raise ModelCallError("Gemini text part must be a string")
            text_parts.append(text)
            continue
        if "functionCall" in part:
            function_call = part["functionCall"]
            if not isinstance(function_call, dict):
                raise ModelCallError("Gemini functionCall must be an object")
            name = function_call.get("name")
            if not isinstance(name, str) or not name:
                raise ModelCallError("Gemini functionCall missing name")
            args = function_call.get("args", {})
            if not isinstance(args, dict):
                raise ModelCallError("Gemini functionCall args must be an object")
            tool_calls.append(ToolCall(name=name, args=args))
            continue
        raise ModelCallError("unsupported Gemini part")
    return ModelResponse(content="".join(text_parts), tool_calls=tool_calls)


def _messages_to_responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Chat Completions messages to Responses API input format."""
    result = []
    for msg in messages:
        role = msg.get("role")
        if role == "system":
            result.append({"role": "system", "content": msg.get("content", "")})
        elif role == "user":
            result.append({"role": "user", "content": msg.get("content", "")})
        elif role == "assistant":
            item: dict[str, Any] = {"role": "assistant", "content": msg.get("content", "")}
            for tc in msg.get("tool_calls", []):
                result.append({
                    "type": "function_call",
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                    "call_id": tc.get("id", ""),
                })
            if item["content"]:
                result.append(item)
        elif role == "tool":
            result.append({
                "type": "function_call_output",
                "call_id": msg.get("tool_call_id", ""),
                "output": msg.get("content", ""),
            })
    return result


def _normalize_responses_endpoint(base_url: str | None) -> str:
    """把裸域名或 /v1 base URL 规范化为 Responses API endpoint。"""
    if base_url is None or not base_url.strip():
        return DEFAULT_RESPONSES_ENDPOINT
    endpoint = base_url.strip().rstrip("/")
    if "://" not in endpoint:
        endpoint = f"https://{endpoint}"
    if endpoint.endswith("/v1/responses"):
        return endpoint
    if endpoint.endswith("/v1"):
        return f"{endpoint}/responses"
    return f"{endpoint}/v1/responses"


def _normalize_chat_completions_endpoint(base_url: str | None) -> str:
    """把裸域名或 /v1 base URL 规范化为 Chat Completions endpoint。"""
    if base_url is None or not base_url.strip():
        return DEFAULT_CHAT_COMPLETIONS_ENDPOINT
    endpoint = base_url.strip().rstrip("/")
    if "://" not in endpoint:
        endpoint = f"https://{endpoint}"
    if endpoint.endswith("/v1/chat/completions"):
        return endpoint
    if endpoint.endswith("/v1"):
        return f"{endpoint}/chat/completions"
    return f"{endpoint}/v1/chat/completions"


def _normalize_anthropic_messages_endpoint(base_url: str | None) -> str:
    """把裸域名或 /v1 base URL 规范化为 Anthropic Messages endpoint。"""
    if base_url is None or not base_url.strip():
        return DEFAULT_ANTHROPIC_MESSAGES_ENDPOINT
    endpoint = base_url.strip().rstrip("/")
    if "://" not in endpoint:
        endpoint = f"https://{endpoint}"
    if endpoint.endswith("/v1/messages"):
        return endpoint
    if endpoint.endswith("/v1"):
        return f"{endpoint}/messages"
    return f"{endpoint}/v1/messages"


def _normalize_gemini_generate_content_endpoint(base_url: str | None, model: str) -> str:
    """把 Gemini base URL 规范化为指定 model 的 generateContent endpoint。"""
    model_path = model if model.startswith("models/") else f"models/{model}"
    if base_url is None or not base_url.strip():
        base = DEFAULT_GEMINI_API_BASE_URL
    else:
        base = base_url.strip().rstrip("/")
        if "://" not in base:
            base = f"https://{base}"
    if base.endswith(":generateContent"):
        return base
    return f"{base}/{model_path}:generateContent"


def _responses_transport(
    payload: dict[str, object],
    api_key: str,
    endpoint: str = DEFAULT_RESPONSES_ENDPOINT,
) -> dict[str, object]:
    """执行真实 HTTP 请求；保持为函数便于测试注入替身 transport。"""
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise ModelCallError(f"OpenAI request failed with HTTP {error.code}: {detail}") from error
    return json.loads(body)


def _chat_completions_transport(
    payload: dict[str, object],
    api_key: str,
    endpoint: str = DEFAULT_CHAT_COMPLETIONS_ENDPOINT,
) -> dict[str, object]:
    """执行真实 Chat Completions HTTP 请求；测试中通过 transport 注入替身。"""
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise ModelCallError(
            f"OpenAI chat request failed with HTTP {error.code}: {detail}",
        ) from error
    return json.loads(body)


def _anthropic_transport(
    payload: dict[str, object],
    api_key: str,
    endpoint: str = DEFAULT_ANTHROPIC_MESSAGES_ENDPOINT,
) -> dict[str, object]:
    """执行真实 Anthropic Messages HTTP 请求；测试中通过 transport 注入替身。"""
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise ModelCallError(
            f"Anthropic request failed with HTTP {error.code}: {detail}",
        ) from error
    return json.loads(body)


def _google_gemini_transport(
    payload: dict[str, object],
    api_key: str,
    endpoint: str,
) -> dict[str, object]:
    """执行真实 Gemini generateContent HTTP 请求；测试中通过 transport 注入替身。"""
    separator = "&" if "?" in endpoint else "?"
    request = urllib.request.Request(
        f"{endpoint}{separator}key={api_key}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise ModelCallError(
            f"Gemini request failed with HTTP {error.code}: {detail}",
        ) from error
    return json.loads(body)
