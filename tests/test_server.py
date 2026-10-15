import asyncio
import json
import logging
import sys
import time

import httpx
import pytest
from conftest import API_KEY, API_SECRET, SITE, USER_PATH

from frappe_enterprise_mcp.frappe_client import FrappeClient
from frappe_enterprise_mcp.server import _configure_logging

TOOLS = {"frappe_get_current_user", "frappe_list_documents", "frappe_get_document"}
TODO = f"{SITE}/api/resource/ToDo"
LIST = "frappe_list_documents"
GET = "frappe_get_document"


def category(result):
    assert result.is_error
    assert set(result.structured_content["error"]) == {"category", "message", "correlation_id"}
    return result.structured_content["error"]["category"]


def audit_events(caplog):
    return [json.loads(r.getMessage()) for r in caplog.records if r.name.endswith(".audit")]


# --- discovery -----------------------------------------------------------------------


async def test_exactly_three_read_only_tools(connect):
    async with connect() as mcp:
        tools = (await mcp.list_tools()).tools
        capabilities = mcp.server_capabilities
    assert len(tools) == 3 and {tool.name for tool in tools} == TOOLS
    for tool in tools:
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.input_schema["additionalProperties"] is False
        assert tool.output_schema["type"] == "object"
    assert capabilities.resources is None and capabilities.prompts is None


async def test_unknown_tools_are_rejected_without_outbound_calls(connect, frappe):
    async with connect() as mcp:
        for name in ("frappe_delete_document", "frappe_run_sql", "frappe_call_method", "run"):
            assert category(await mcp.call_tool(name, {})) == "unknown_tool"
    assert frappe.calls.call_count == 0


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        (LIST, {}),
        (LIST, {"doctype": "ToDo", "limit": 0}),
        (LIST, {"doctype": "ToDo", "limit": 51}),
        (LIST, {"doctype": "ToDo", "limit": "5"}),
        (LIST, {"doctype": "ToDo", "limit": True}),
        (LIST, {"doctype": "ToDo", "limit": 2.5}),
        (LIST, {"doctype": "ToDo", "offset": -1}),
        (LIST, {"doctype": "ToDo", "offset": 10_001}),
        (LIST, {"doctype": 5}),
        (LIST, {"doctype": "ToDo", "filters": {"owner": "x"}}),
        (LIST, {"doctype": "ToDo", "fields": ["*"]}),
        (LIST, {"doctype": "ToDo", "order_by": "name"}),
        (GET, {"doctype": "ToDo"}),
        (GET, {"doctype": "ToDo", "name": ""}),
        (GET, {"doctype": "ToDo", "name": None}),
        ("frappe_get_current_user", {"user": "Administrator"}),
    ],
)
async def test_invalid_arguments_make_no_outbound_calls(connect, frappe, tool, args):
    async with connect() as mcp:
        assert category(await mcp.call_tool(tool, args)) == "invalid_arguments"
    assert frappe.calls.call_count == 0


# --- frappe_get_current_user ---------------------------------------------------------


async def test_current_user_returns_non_admin_identity(connect, user_route):
    async with connect() as mcp:
        result = await mcp.call_tool("frappe_get_current_user", {})
    assert not result.is_error
    expected = {"site_id": "default", "user": "mcp.reader@example.com", "authenticated": True}
    assert result.structured_content == expected
    assert json.loads(result.content[0].text) == expected


@pytest.mark.parametrize(
    ("user", "expected"),
    [("Guest", "authentication_failed"), ("Administrator", "identity_not_permitted")],
)
async def test_current_user_rejects_guest_and_administrator(connect, frappe, user, expected):
    frappe.get(SITE + USER_PATH).respond(200, json={"message": user})
    async with connect() as mcp:
        assert category(await mcp.call_tool("frappe_get_current_user", {})) == expected


async def test_invalid_credentials_are_reported_without_secrets(connect, frappe):
    body = {"exc_type": "AuthenticationError", "exc": "Traceback (most recent call last)"}
    frappe.get(SITE + USER_PATH).respond(401, json=body)
    async with connect() as mcp:
        result = await mcp.call_tool("frappe_get_current_user", {})
    assert category(result) == "authentication_failed"
    for leaked in (API_KEY, API_SECRET, "Traceback", "127.0.0.1"):
        assert leaked not in result.content[0].text


@pytest.mark.parametrize("user", ["Administrator", "Guest"])
async def test_documents_are_never_read_as_administrator_or_guest(connect, frappe, user):
    frappe.get(SITE + USER_PATH).respond(200, json={"message": user})
    todo = frappe.get(url__startswith=TODO).respond(200, json={"data": [{"name": "t1"}]})
    async with connect() as mcp:
        for tool, args in ((LIST, {"doctype": "ToDo"}), (GET, {"doctype": "ToDo", "name": "t1"})):
            result = await mcp.call_tool(tool, args)
            assert category(result) in {"identity_not_permitted", "authentication_failed"}
    assert not todo.called


async def test_identity_is_verified_once_per_process(connect, frappe, user_route):
    frappe.get(TODO).respond(200, json={"data": []})
    async with connect() as mcp:
        await mcp.call_tool(LIST, {"doctype": "ToDo"})
        await mcp.call_tool(LIST, {"doctype": "ToDo"})
    assert user_route.call_count == 1


# --- frappe_list_documents -----------------------------------------------------------


async def test_list_requests_and_returns_only_policy_fields(connect, frappe, user_route):
    row = {"name": "t1", "status": "Open", "priority": "High", "description": "secret plan"}
    route = frappe.get(TODO).respond(200, json={"data": [row | {"_assign": "[]"}]})
    async with connect() as mcp:
        result = await mcp.call_tool(LIST, {"doctype": "ToDo", "limit": 5})
    assert json.loads(route.calls.last.request.url.params["fields"]) == [
        "name",
        "status",
        "priority",
    ]
    assert result.structured_content == {
        "doctype": "ToDo",
        "records": [{"name": "t1", "status": "Open", "priority": "High"}],
        "count": 1,
        "next_offset": None,
    }
    assert "secret plan" not in result.content[0].text


async def test_doctype_without_field_policy_returns_name_only(connect, frappe, user_route):
    rows = [{"name": "n1", "title": "x", "content": "y"}]
    route = frappe.get(f"{SITE}/api/resource/Note").respond(200, json={"data": rows})
    async with connect() as mcp:
        result = await mcp.call_tool(LIST, {"doctype": "Note"})
    assert json.loads(route.calls.last.request.url.params["fields"]) == ["name"]
    assert result.structured_content["records"] == [{"name": "n1"}]


async def test_empty_list_and_default_page_size(connect, frappe, user_route):
    route = frappe.get(TODO).respond(200, json={"data": []})
    async with connect() as mcp:
        result = await mcp.call_tool(LIST, {"doctype": "ToDo"})
    expected = {"doctype": "ToDo", "records": [], "count": 0, "next_offset": None}
    assert result.structured_content == expected
    params = route.calls.last.request.url.params
    assert (params["limit_start"], params["limit_page_length"]) == ("0", "21")  # default 20 + 1


@pytest.mark.parametrize(
    ("offset", "limit", "rows", "next_offset"),
    [
        (0, 2, 3, 2),  # the extra row means another page exists
        (40, 20, 21, 60),
        (0, 2, 2, None),  # exactly one page
        (0, 50, 60, 50),  # an over-long upstream page is truncated
        (9_990, 10, 11, 10_000),
        (10_000, 1, 2, None),  # the next page would exceed the offset cap
    ],
)
async def test_pagination(connect, frappe, user_route, offset, limit, rows, next_offset):
    data = [{"name": f"t{i}"} for i in range(rows)]
    route = frappe.get(TODO).respond(200, json={"data": data})
    async with connect() as mcp:
        result = await mcp.call_tool(LIST, {"doctype": "ToDo", "limit": limit, "offset": offset})
    params = route.calls.last.request.url.params
    assert (params["limit_start"], params["limit_page_length"]) == (str(offset), str(limit + 1))
    assert result.structured_content["count"] == min(rows, limit)
    assert result.structured_content["next_offset"] == next_offset


async def test_list_denied_by_frappe(connect, frappe, user_route):
    frappe.get(TODO).respond(403, json={"exc_type": "PermissionError"})
    async with connect() as mcp:
        assert category(await mcp.call_tool(LIST, {"doctype": "ToDo"})) == "access_denied"


async def test_slow_upstream_hits_the_deadline_inside_the_server(connect, frappe, user_route):
    async def stall(_request):
        await asyncio.sleep(10)
        return httpx.Response(200, json={"data": []})

    frappe.get(TODO).mock(side_effect=stall)
    started = time.perf_counter()
    async with connect(frappe_timeout_seconds=1) as mcp:
        result = await mcp.call_tool(LIST, {"doctype": "ToDo"})
    assert category(result) == "upstream_timeout"
    assert time.perf_counter() - started < 5


# --- frappe_get_document -------------------------------------------------------------


async def test_get_document_suppresses_sensitive_fields(connect, frappe, user_route):
    document = {
        "name": "t1",
        "status": "Open",
        "priority": None,
        "description": "<p>secret plan</p>",
        "allocated_to": "ceo@example.com",
        "password": "hunter2",
        "api_secret": "s3cr3t",
        "items": [{"name": "row1", "rate": 5}],
    }
    frappe.get(f"{TODO}/t1").respond(200, json={"data": document})
    async with connect() as mcp:
        result = await mcp.call_tool(GET, {"doctype": "ToDo", "name": "t1"})
    assert result.structured_content == {
        "doctype": "ToDo",
        "document": {"name": "t1", "status": "Open", "priority": None},
    }
    for leaked in ("secret plan", "ceo@example.com", "hunter2", "s3cr3t", "row1"):
        assert leaked not in result.content[0].text


async def test_child_tables_are_dropped_even_if_allowlisted(connect, frappe, user_route):
    document = {"name": "t1", "status": "Open", "items": [{"name": "r1", "secret": "s"}]}
    frappe.get(f"{TODO}/t1").respond(200, json={"data": document})
    async with connect(mcp_allowed_fields={"ToDo": ["items", "status"]}) as mcp:
        result = await mcp.call_tool(GET, {"doctype": "ToDo", "name": "t1"})
    assert result.structured_content["document"] == {"name": "t1", "status": "Open"}


@pytest.mark.parametrize(("status", "expected"), [(403, "access_denied"), (404, "not_found")])
async def test_forbidden_or_missing_record_returns_no_data(
    connect, frappe, user_route, status, expected
):
    body = {"exc": "Traceback", "data": {"name": "t9", "description": "classified"}}
    frappe.get(f"{TODO}/t9").respond(status, json=body)
    async with connect() as mcp:
        result = await mcp.call_tool(GET, {"doctype": "ToDo", "name": "t9"})
    assert category(result) == expected
    assert set(result.structured_content) == {"error"}
    assert "classified" not in result.content[0].text and "Traceback" not in result.content[0].text


async def test_unusual_names_stay_inside_one_path_segment(connect, frappe, user_route):
    route = frappe.get(url__startswith=TODO + "/").respond(200, json={"data": {"name": "a?b#c%d"}})
    async with connect() as mcp:
        result = await mcp.call_tool(GET, {"doctype": "ToDo", "name": "a?b#c%d"})
    assert not result.is_error
    url = route.calls.last.request.url
    assert (url.host, url.raw_path) == ("127.0.0.1", b"/api/resource/ToDo/a%3Fb%23c%25d")


# --- negative policy, injection and oversized input -----------------------------------


@pytest.mark.parametrize(
    "doctype",
    [
        "User",
        "todo",
        "ToDo ",
        "Sales Invoice",
        "*",
        "http://evil.example/api",
        "//evil.example",
        "ToDo/../User",
        "ToDo?x=1",
        "ToDo%2F..%2FUser",
    ],
)
async def test_forbidden_doctypes_make_zero_http_requests(connect, frappe, doctype):
    async with connect() as mcp:
        for tool, args in ((LIST, {"doctype": doctype}), (GET, {"doctype": doctype, "name": "x"})):
            assert category(await mcp.call_tool(tool, args)) == "doctype_not_allowed"
    assert frappe.calls.call_count == 0


@pytest.mark.parametrize(
    "name",
    [
        ".",
        "..",
        "...",
        "../User/Administrator",
        "a/b",
        "a\\b",
        "https://evil.example/x",
        "line\nbreak",
        "nul\x00",
        "‮direction",
        " padded",
    ],
)
async def test_path_changing_names_are_rejected(connect, frappe, name):
    async with connect() as mcp:
        result = await mcp.call_tool(GET, {"doctype": "ToDo", "name": name})
    assert category(result) == "invalid_arguments"
    assert frappe.calls.call_count == 0


@pytest.mark.parametrize("key", ["url", "site", "base_url", "host", "frappe_url", "headers"])
async def test_target_selecting_arguments_are_rejected(connect, frappe, key):
    async with connect() as mcp:
        for tool, args in ((LIST, {"doctype": "ToDo"}), (GET, {"doctype": "ToDo", "name": "t1"})):
            result = await mcp.call_tool(tool, args | {key: "https://evil.example"})
            assert category(result) == "invalid_arguments"
    assert frappe.calls.call_count == 0


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        (LIST, {"doctype": "T" * 141}),
        (GET, {"doctype": "ToDo", "name": "n" * 141}),
        (GET, {"doctype": "ToDo", "name": "n", "padding": "x" * 1_000_000}),
    ],
)
async def test_oversized_input_is_rejected_without_echo(connect, frappe, tool, args):
    async with connect() as mcp:
        result = await mcp.call_tool(tool, args)
    assert category(result) == "invalid_arguments"
    assert len(result.content[0].text) < 400
    assert frappe.calls.call_count == 0


# --- safe errors and audit -----------------------------------------------------------


async def test_upstream_server_error_is_sanitized_and_correlated(
    connect, frappe, user_route, caplog
):
    caplog.set_level(logging.INFO)
    frappe.get(TODO).respond(500, text="Traceback: OperationalError host=db.internal")
    async with connect() as mcp:
        result = await mcp.call_tool(LIST, {"doctype": "ToDo"})
    error = result.structured_content["error"]
    assert error["category"] == "upstream_error" and len(error["correlation_id"]) == 32
    assert "Traceback" not in result.content[0].text and "db.internal" not in result.content[0].text
    assert audit_events(caplog)[-1]["request_id"] == error["correlation_id"]


async def test_unexpected_exceptions_become_internal_error(
    connect, frappe, user_route, monkeypatch, caplog
):
    async def explode(*_args, **_kwargs):
        raise RuntimeError(f"boom {API_SECRET}")

    monkeypatch.setattr(FrappeClient, "list_documents", explode)
    async with connect() as mcp:
        result = await mcp.call_tool(LIST, {"doctype": "ToDo"})
    assert category(result) == "internal_error"
    assert "boom" not in result.content[0].text
    assert API_SECRET not in caplog.text and "RuntimeError" in caplog.text


async def test_audit_events_are_redacted(connect, frappe, user_route, caplog):
    caplog.set_level(logging.DEBUG)
    rows = [{"name": "t1", "status": "Open-Sentinel", "description": "Payload-Sentinel"}]
    frappe.get(TODO).respond(200, json={"data": rows})
    frappe.get(f"{TODO}/t2").respond(403, json={"exc": "Payload-Sentinel"})
    async with connect() as mcp:
        await mcp.call_tool(LIST, {"doctype": "ToDo"})
        await mcp.call_tool(GET, {"doctype": "ToDo", "name": "t2"})
        await mcp.call_tool(GET, {"doctype": "User", "name": "Administrator"})
    events = audit_events(caplog)
    assert [(e["tool"], e["outcome"], e["error_category"]) for e in events] == [
        (LIST, "ok", None),
        (GET, "error", "access_denied"),
        (GET, "error", "doctype_not_allowed"),
    ]
    assert all(len(e["request_id"]) == 32 and e["duration_ms"] >= 0 for e in events)
    assert events[0]["doctype"] == "ToDo" and events[1]["upstream_status"] == 403
    assert "doctype" not in events[2]  # rejected DocType strings are not logged
    ours = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("frappe_"))
    for leaked in ("Open-Sentinel", "Payload-Sentinel", "t2", "Administrator", "mcp.reader"):
        assert leaked not in ours
    for secret in (API_KEY, API_SECRET):
        assert secret not in caplog.text


def test_logging_goes_to_stderr_and_keeps_third_party_quiet():
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    try:
        _configure_logging("DEBUG")
        assert [getattr(h, "stream", None) for h in root.handlers] == [sys.stderr]
        assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING
        assert logging.getLogger("mcp").getEffectiveLevel() == logging.WARNING
        assert logging.getLogger("frappe_enterprise_mcp.audit").getEffectiveLevel() == logging.DEBUG
    finally:
        root.handlers[:], root.level = saved
        logging.getLogger("frappe_enterprise_mcp").setLevel(logging.NOTSET)
