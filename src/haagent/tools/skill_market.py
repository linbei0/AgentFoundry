"""
src/haagent/tools/skill_market.py - 远端 skill marketplace 搜索工具

把 marketplace 搜索封装为 ToolRouter 可审计的只读工具，并保持返回结果紧凑。
"""

from __future__ import annotations

from typing import Any

from haagent.skills.marketplace import MarketplaceError, search_marketplace
from haagent.tools.base import tool_error


def skill_market_search(args: dict[str, Any]) -> dict[str, Any]:
    """搜索允许的远端 skill marketplace，不返回完整 skill 正文。"""
    query = str(args.get("query", "")).strip()
    if not query:
        return tool_error("tool_argument_invalid", "query is required")
    providers = args.get("providers")
    if providers is not None and (
        not isinstance(providers, list) or not all(isinstance(item, str) for item in providers)
    ):
        return tool_error("tool_argument_invalid", "providers must be a list of strings")
    limit = args.get("limit", 10)
    if not isinstance(limit, int) or isinstance(limit, bool):
        return tool_error("tool_argument_invalid", "limit must be an integer")
    try:
        result = search_marketplace(query, providers=providers, limit=limit)
    except MarketplaceError as error:
        return tool_error("skill_market_search_failed", str(error))
    return {
        "status": result.status,
        "query": result.query,
        "results": [_card_result(card) for card in result.cards],
        "warnings": result.warnings,
    }


def _card_result(card) -> dict[str, Any]:
    return {
        "result_id": card.result_id,
        "provider": card.provider.value,
        "name": card.name,
        "source": card.source,
        "summary": card.summary,
        "detail_url": card.detail_url,
        "installable": card.installable,
        "quality": card.quality,
    }
