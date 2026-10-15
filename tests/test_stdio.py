"""Runs the real server process over stdio with the SDK's client."""

import sys

from mcp import Client, StdioServerParameters

SECRET = "stdiosecret0002"


async def test_stdio_server_initializes_lists_tools_and_fails_safely(tmp_path):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "frappe_enterprise_mcp"],
        cwd=tmp_path,  # no .env here
        env={
            "FRAPPE_URL": "http://127.0.0.1:9",  # nothing listens: a real network failure
            "FRAPPE_API_KEY": "stdiokey0000001",
            "FRAPPE_API_SECRET": SECRET,
            "MCP_ALLOWED_DOCTYPES": "ToDo",
        },
    )
    async with Client(params) as client:
        assert client.server_info.name == "frappe-enterprise-mcp"
        tools = (await client.list_tools()).tools
        assert sorted(tool.name for tool in tools) == [
            "frappe_get_current_user",
            "frappe_get_document",
            "frappe_list_documents",
        ]
        denied = await client.call_tool("frappe_list_documents", {"doctype": "User"})
        unreachable = await client.call_tool("frappe_get_current_user", {})

    assert denied.structured_content["error"]["category"] == "doctype_not_allowed"
    assert unreachable.structured_content["error"]["category"] == "upstream_unavailable"
    assert (
        SECRET not in unreachable.content[0].text and "127.0.0.1" not in unreachable.content[0].text
    )
