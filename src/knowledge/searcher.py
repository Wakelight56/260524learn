"""网络搜索工具 — 检测"xxx是什么"类问题并搜索"""

import logging
import re

logger = logging.getLogger("autochat.knowledge.searcher")

SEARCH_PATTERNS: list[tuple[str, str]] = [
    (r"什么是(.+)", "cn"),
    (r"(.+)是什么", "cn"),
    (r"(.+)是什么意思", "cn"),
    (r"(.+)是啥", "cn"),
    (r"(.+)指的是什么", "cn"),
    (r"(.+)是指什么", "cn"),
    (r"(.+)是什么东西", "cn"),
    (r"(.+)是什么玩意", "cn"),
    (r"what(?: is|'s| are)\s+(.+)", "en"),
    (r"what(?: is|'s| are)\s+an?\s+(.+)", "en"),
    (r"what(?: is|'s| are)\s+the\s+(.+)", "en"),
    (r"tell\s+me\s+about\s+(.+)", "en"),
    (r"(.+)って何", "jp"),
    (r"(.+)とは", "jp"),
]


def extract_query(text: str) -> str | None:
    """从消息中提取搜索关键词。不匹配则返回 None。"""
    for pattern, _lang in SEARCH_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            q = m.group(1).strip()
            if q and len(q) >= 2:
                return q
    return None


async def web_search(query: str) -> str:
    """搜索网络（Wikipedia），返回格式化文本或空字符串。"""
    # 优先中文 Wikipedia
    result = await _search_wiki(query, "zh.wikipedia.org")
    if result:
        return result

    # 英文备选
    result = await _search_wiki(query, "en.wikipedia.org")
    if result:
        return result

    return ""


async def _search_wiki(query: str, host: str) -> str:
    """查询 Wikipedia API"""
    import httpx

    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json",
        "srlimit": 3,
        "srprop": "snippet|titlesnippet",
    }
    headers = {"User-Agent": "AutoChat/1.0 (bot)"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://{host}/w/api.php",
                params=params, headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            return _format_wiki(data, host)
    except Exception as e:
        logger.debug("Wikipedia 搜索失败 (%s): %s", host, e)
        return ""


def _format_wiki(data: dict, host: str) -> str:
    """格式化 Wikipedia 结果为纯文本"""
    search = data.get("query", {}).get("search", [])
    if not search:
        return ""

    lines = ["【网络搜索结果】"]
    for item in search[:3]:
        title = item.get("title", "")
        snippet = re.sub(r"<[^>]+>", "", item.get("snippet", ""))
        snippet = re.sub(r"\s+", " ", snippet).strip()
        lines.append(f"\n• {title}: {snippet[:200]}")

    lines.append("\n（以上信息来自网络搜索，仅供参考）")
    return "\n".join(lines)
