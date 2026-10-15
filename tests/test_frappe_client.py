import asyncio
import json
import logging

import httpx
import pytest
from conftest import API_KEY, API_SECRET, SITE, USER_PATH

from frappe_enterprise_mcp.frappe_client import MAX_RESPONSE_BYTES, FrappeClient, SafeError

LEAKY_BODY = {
    "exc": "Traceback (most recent call last): db_password=hunter2",
    "_server_messages": "x",
}


@pytest.fixture
async def client(make_settings):
    async with FrappeClient(make_settings()) as frappe_client:
        yield frappe_client


async def failure(coro) -> SafeError:
    with pytest.raises(SafeError) as caught:
        await coro
    return caught.value


async def test_current_user_request_shape(client, frappe):
    route = frappe.get(SITE + USER_PATH).respond(200, json={"message": "reader@example.com"})
    assert await client.get_logged_user() == "reader@example.com"
    request = route.calls.last.request
    assert request.method == "GET"
    assert request.headers["authorization"] == f"token {API_KEY}:{API_SECRET}"
    assert request.headers["accept"] == "application/json"


async def test_list_request_uses_explicit_fields_and_bounds(client, frappe):
    route = frappe.get(f"{SITE}/api/resource/Sales%20Invoice").respond(200, json={"data": []})
    await client.list_documents("Sales Invoice", ("name", "status"), limit=21, offset=40)
    params = route.calls.last.request.url.params
    assert json.loads(params["fields"]) == ["name", "status"]
    assert params["limit_page_length"] == "21" and params["limit_start"] == "40"
    assert set(params) == {"fields", "limit_page_length", "limit_start"}


async def test_document_name_is_one_encoded_path_segment(client, frappe):
    route = frappe.get(url__regex=r".*").respond(200, json={"data": {"name": "a b?c#d%e"}})
    await client.get_document("ToDo", "a b?c#d%e")
    url = route.calls.last.request.url
    assert url.host == "127.0.0.1" and url.port == 8000
    assert url.raw_path == b"/api/resource/ToDo/a%20b%3Fc%23d%25e"


async def test_transport_defaults_are_strict(client, make_settings):
    http = client._http
    assert http.follow_redirects is False
    assert http.trust_env is False
    assert http.timeout == httpx.Timeout(make_settings().frappe_timeout_seconds)
    assert "token" not in repr(http.headers)  # httpx masks Authorization in reprs


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (401, "authentication_failed"),
        (403, "access_denied"),
        (404, "not_found"),
        (429, "rate_limited"),
        (400, "upstream_rejected"),
        (417, "upstream_rejected"),
        (500, "upstream_error"),
        (502, "upstream_error"),
        (503, "upstream_error"),
    ],
)
async def test_status_codes_map_to_safe_categories(client, frappe, status, category):
    frappe.get(SITE + USER_PATH).respond(status, json=LEAKY_BODY)
    error = await failure(client.get_logged_user())
    assert (error.category, error.status) == (category, status)
    assert "hunter2" not in repr(error) + error.detail


@pytest.mark.parametrize("status", [301, 302, 307, 308])
async def test_redirects_are_rejected_not_followed(client, frappe, status):
    frappe.get(SITE + USER_PATH).respond(status, headers={"Location": "https://evil.example/x"})
    evil = frappe.get(url__startswith="https://evil.example").respond(200, json={"message": "x"})
    error = await failure(client.get_logged_user())
    assert error.category == "redirect_rejected"
    assert not evil.called


@pytest.mark.parametrize(
    ("exception", "category"),
    [
        (httpx.ConnectTimeout, "upstream_timeout"),
        (httpx.ReadTimeout, "upstream_timeout"),
        (httpx.PoolTimeout, "upstream_timeout"),
        (httpx.ConnectError, "upstream_unavailable"),
        (httpx.RemoteProtocolError, "upstream_unavailable"),
    ],
)
async def test_network_failures(client, frappe, exception, category):
    frappe.get(SITE + USER_PATH).mock(side_effect=exception(f"boom {API_SECRET}"))
    error = await failure(client.get_logged_user())
    assert error.category == category
    assert API_SECRET not in repr(error) and error.__cause__ is None


async def test_overall_deadline_bounds_slow_responses(client, frappe):
    async def stall(request):
        await asyncio.sleep(5)
        return httpx.Response(200, json={"message": "late"})

    frappe.get(SITE + USER_PATH).mock(side_effect=stall)
    client._timeout = 0.05
    assert (await failure(client.get_logged_user())).category == "upstream_timeout"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>login</html>"),
        httpx.Response(200, text="not json"),
        httpx.Response(200, content=b"\xff\xfe"),
        httpx.Response(200, json=["array"]),
        httpx.Response(200, json={"message": 7}),
        httpx.Response(200, json={"message": ""}),
        httpx.Response(200, json={"message": "u" * 141}),
        httpx.Response(200, json={}),
    ],
)
async def test_malformed_current_user(client, frappe, response):
    frappe.get(SITE + USER_PATH).mock(return_value=response)
    assert (await failure(client.get_logged_user())).category == "invalid_upstream_response"


@pytest.mark.parametrize(
    "payload",
    [{}, {"data": {}}, {"data": "rows"}, {"data": [1]}, {"data": [{"title": "no name"}]}],
)
async def test_malformed_list(client, frappe, payload):
    frappe.get(f"{SITE}/api/resource/ToDo").respond(200, json=payload)
    error = await failure(client.list_documents("ToDo", ("name",), limit=1, offset=0))
    assert error.category == "invalid_upstream_response"


@pytest.mark.parametrize("payload", [{}, {"data": []}, {"data": {"name": 5}}, {"data": None}])
async def test_malformed_document(client, frappe, payload):
    frappe.get(f"{SITE}/api/resource/ToDo/abc").respond(200, json=payload)
    error = await failure(client.get_document("ToDo", "abc"))
    assert error.category == "invalid_upstream_response"


async def test_oversized_streamed_response_is_rejected(client, frappe):
    async def chunks():  # no Content-Length, so the streaming cap must catch it
        for _ in range(3):
            yield b"x" * (MAX_RESPONSE_BYTES // 2)

    frappe.get(SITE + USER_PATH).mock(return_value=httpx.Response(200, content=chunks()))
    assert (await failure(client.get_logged_user())).category == "response_too_large"


async def test_declared_oversized_response_is_rejected_before_reading(client, frappe):
    headers = {"Content-Length": str(MAX_RESPONSE_BYTES + 1)}
    frappe.get(SITE + USER_PATH).respond(200, headers=headers, content=b"{}")
    assert (await failure(client.get_logged_user())).category == "response_too_large"


async def test_requests_never_leave_the_configured_origin(client, frappe):
    client._origin = ("https", "evil.example", None)
    assert (await failure(client.get_logged_user())).category == "internal_error"
    assert frappe.calls.call_count == 0


async def test_no_secret_in_errors_or_logs(client, frappe, caplog):
    caplog.set_level(logging.DEBUG)
    responses = [httpx.Response(s, json=LEAKY_BODY) for s in (401, 403, 404, 429, 500)]
    responses += [httpx.Response(302, headers={"Location": "http://evil.example"})]
    route = frappe.get(SITE + USER_PATH)
    seen = []
    for response in responses:
        route.mock(return_value=response)
        seen.append(await failure(client.get_logged_user()))
    for exc in (httpx.ConnectError("x"), httpx.ReadTimeout("x")):
        route.mock(side_effect=exc)
        seen.append(await failure(client.get_logged_user()))
    text = caplog.text + " ".join(f"{e!r} {e} {e.detail}" for e in seen)
    for secret in (API_KEY, API_SECRET, "hunter2", "Traceback"):
        assert secret not in text
