"""Wspólne narzędzia HTTP (retry/backoff, obsługa timeoutów) dla providerów rejestrów."""

import asyncio
from typing import Any, Dict, Optional

import httpx

from src.config import APP_USER_AGENT, HTTP_TIMEOUT_SECONDS


async def http_request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
    max_retries: int = 2,
) -> httpx.Response:
    """
    Wykonuje zapytanie HTTP z krótkim exponential backoff dla błędów przejściowych (429/5xx/sieć).
    """
    merged_headers = {"User-Agent": APP_USER_AGENT, "Accept": "application/json"}
    if headers:
        merged_headers.update(headers)

    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            resp = await client.request(
                method=method,
                url=url,
                headers=merged_headers,
                json=json_body,
                timeout=timeout,
            )
            if resp.status_code in (429, 502, 503, 504) and attempt < max_retries:
                await asyncio.sleep(0.35 * (attempt + 1))
                continue
            return resp
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            if attempt < max_retries:
                await asyncio.sleep(0.35 * (attempt + 1))
                continue
            raise

    assert last_exc is not None
    raise last_exc
