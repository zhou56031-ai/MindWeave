"""Tavily/Serper 外部搜索，失败返回空证据。"""

import hashlib

import httpx

from app.core.settings import settings
from app.schemas.models import RetrievalHit


def _enabled() -> bool:
    return bool(
        settings.WEB_SEARCH_ENABLED
        and settings.WEB_SEARCH_PROVIDER
        and settings.WEB_SEARCH_API_KEY.get_secret_value()
    )


async def search_web(query: str, max_results: int = 5) -> list[RetrievalHit]:
    if not _enabled():
        return []
    key = settings.WEB_SEARCH_API_KEY.get_secret_value()
    provider = settings.WEB_SEARCH_PROVIDER.lower()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if provider == "tavily":
                response = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": key,
                        "query": query,
                        "max_results": max_results,
                    },
                )
            elif provider == "serper":
                response = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": key},
                    json={"q": query, "num": max_results},
                )
            else:
                return []
        response.raise_for_status()
        payload = response.json()
        rows = (
            payload.get("results")
            if provider == "tavily"
            else payload.get("organic")
        )
    except Exception:
        return []

    hits = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("link") or "")
        title = str(item.get("title") or "Web result")
        text = str(item.get("content") or item.get("snippet") or "")
        source_id = "web-" + hashlib.sha256(
            (url + title).encode()
        ).hexdigest()[:16]
        hits.append(RetrievalHit(
            source_kind="web",
            source_id=source_id,
            title=title,
            snippet=text,
            score=500,
            url=url if url.startswith(("https://", "http://")) else None,
        ))
    return hits
