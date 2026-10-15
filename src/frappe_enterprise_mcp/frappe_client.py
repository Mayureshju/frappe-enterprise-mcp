"""Restricted async client for the three Frappe REST v1 read endpoints this server uses."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any, TypeGuard
from urllib.parse import quote

import httpx

from frappe_enterprise_mcp.config import Settings

MAX_RESPONSE_BYTES = 1024 * 1024
MAX_CONNECTIONS = 4

_STATUS_CATEGORIES = {
    401: "authentication_failed",
    403: "access_denied",
    404: "not_found",
    429: "rate_limited",
}


class SafeError(Exception):
    """A failure whose fields are safe to show MCP clients; never carries upstream bodies."""

    def __init__(self, category: str, *, status: int | None = None, detail: str = "") -> None:
        super().__init__(category)
        self.category = category
        self.status = status
        self.detail = detail


def _category_for(status: int) -> str:
    if 300 <= status < 400:
        return "redirect_rejected"
    if status >= 500:
        return "upstream_error"
    return _STATUS_CATEGORIES.get(status, "upstream_rejected")


def _is_record(value: object) -> TypeGuard[dict[str, Any]]:
    return isinstance(value, dict) and isinstance(value.get("name"), str)


class FrappeClient:
    """GET-only client bound to the configured site origin; never follows redirects."""

    def __init__(self, settings: Settings) -> None:
        key = settings.frappe_api_key.get_secret_value()
        secret = settings.frappe_api_secret.get_secret_value()
        self._timeout = settings.frappe_timeout_seconds
        self._http = httpx.AsyncClient(
            base_url=settings.frappe_url,
            headers={
                "Authorization": f"token {key}:{secret}",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
            timeout=httpx.Timeout(self._timeout),
            limits=httpx.Limits(
                max_connections=MAX_CONNECTIONS, max_keepalive_connections=MAX_CONNECTIONS
            ),
            follow_redirects=False,
            verify=True,
            trust_env=False,  # no proxy/netrc from the environment
        )
        base = self._http.base_url
        self._origin = (base.scheme, base.host, base.port)

    async def __aenter__(self) -> FrappeClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._http.aclose()

    async def get_logged_user(self) -> str:
        payload = await self._get_json("/api/method/frappe.auth.get_logged_user")
        user = payload.get("message")
        if not isinstance(user, str) or not 0 < len(user) <= 140:
            raise SafeError("invalid_upstream_response")
        return user

    async def list_documents(
        self, doctype: str, fields: Sequence[str], *, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        payload = await self._get_json(
            f"/api/resource/{quote(doctype, safe='')}",
            params={
                "fields": json.dumps(list(fields)),
                "limit_start": offset,
                "limit_page_length": limit,
            },
        )
        rows = payload.get("data")
        if not isinstance(rows, list) or not all(_is_record(row) for row in rows):
            raise SafeError("invalid_upstream_response")
        return rows

    async def get_document(self, doctype: str, name: str) -> dict[str, Any]:
        payload = await self._get_json(
            f"/api/resource/{quote(doctype, safe='')}/{quote(name, safe='')}"
        )
        document = payload.get("data")
        if not _is_record(document):
            raise SafeError("invalid_upstream_response")
        return document

    async def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request = self._http.build_request("GET", path, params=params)
        if (request.url.scheme, request.url.host, request.url.port) != self._origin:
            raise SafeError("internal_error")  # credentials only ever go to the configured site
        try:
            async with asyncio.timeout(self._timeout):
                response = await self._http.send(request, stream=True)
                try:
                    if response.status_code != 200:
                        category = _category_for(response.status_code)
                        raise SafeError(category, status=response.status_code)
                    body = await _read_limited(response)
                finally:
                    await response.aclose()
        except (TimeoutError, httpx.TimeoutException):
            raise SafeError("upstream_timeout") from None
        except httpx.HTTPError:
            raise SafeError("upstream_unavailable") from None
        try:
            payload = json.loads(body)
        except ValueError:
            raise SafeError("invalid_upstream_response") from None
        if not isinstance(payload, dict):
            raise SafeError("invalid_upstream_response")
        return payload


async def _read_limited(response: httpx.Response) -> bytes:
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
        raise SafeError("response_too_large")
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body += chunk
        if len(body) > MAX_RESPONSE_BYTES:
            raise SafeError("response_too_large")
    return bytes(body)
