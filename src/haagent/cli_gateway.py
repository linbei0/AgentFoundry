"""
haagent/cli_gateway.py - CLI 模型网关构建

集中处理 CLI 参数、provider profile 与 ModelGateway adapter 的组装。
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from haagent.models.gateway import OpenAIChatCompletionsGateway, OpenAIResponsesGateway
from haagent.models.provider_profile import ProviderProfile, ProviderProfileError, load_provider_profile


def build_run_model_gateway(
    args: argparse.Namespace,
    *,
    responses_gateway_cls: type = OpenAIResponsesGateway,
    chat_gateway_cls: type = OpenAIChatCompletionsGateway,
) -> Any:
    if args.profile is not None:
        if args.provider != "fake" or args.model is not None or args.base_url is not None:
            raise ProviderProfileError(
                "--profile cannot be combined with --provider, --model, or --base-url",
            )
        return gateway_from_profile(
            load_provider_profile(args.profile),
            responses_gateway_cls=responses_gateway_cls,
            chat_gateway_cls=chat_gateway_cls,
        )

    if args.provider in {"openai", "openai-chat"}:
        gateway_kwargs = {}
        if args.model is not None:
            gateway_kwargs["model"] = args.model
        if args.base_url is not None:
            gateway_kwargs["base_url"] = args.base_url
        gateway_class = responses_gateway_cls if args.provider == "openai" else chat_gateway_cls
        return gateway_class(**gateway_kwargs)
    return None


def build_dogfood_model_gateway(
    args: argparse.Namespace,
    *,
    responses_gateway_cls: type = OpenAIResponsesGateway,
    chat_gateway_cls: type = OpenAIChatCompletionsGateway,
) -> Any:
    if args.profile is not None:
        if args.provider is not None or args.model is not None or args.base_url is not None:
            raise ProviderProfileError(
                "--profile cannot be combined with --provider, --model, or --base-url",
            )
        return gateway_from_profile(
            load_provider_profile(args.profile),
            responses_gateway_cls=responses_gateway_cls,
            chat_gateway_cls=chat_gateway_cls,
        )
    if args.provider is None:
        return None
    if not os.environ.get("OPENAI_API_KEY"):
        raise ProviderProfileError("OPENAI_API_KEY is not set; dogfood skipped")
    return build_run_model_gateway(
        args,
        responses_gateway_cls=responses_gateway_cls,
        chat_gateway_cls=chat_gateway_cls,
    )


def gateway_from_profile(
    profile: ProviderProfile,
    *,
    responses_gateway_cls: type = OpenAIResponsesGateway,
    chat_gateway_cls: type = OpenAIChatCompletionsGateway,
) -> Any:
    gateway_kwargs = {
        "api_key": profile.api_key,
        "model": profile.model,
        "base_url": profile.base_url,
    }
    if profile.provider == "openai":
        return responses_gateway_cls(**gateway_kwargs)
    if profile.provider == "openai-chat":
        return chat_gateway_cls(**gateway_kwargs)
    raise ProviderProfileError(f"unsupported provider in profile: {profile.provider}")
