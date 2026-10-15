"""Local MCP client smoke test against the development site configured in `.env`.

Starts the server over stdio exactly as an MCP client would, then performs read-only calls.
Prints identifiers and counts only - never credentials, `.env` values or field values.

    uv run python scripts/smoke_mcp_client.py
"""

import asyncio
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

from frappe_enterprise_mcp.config import Settings

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_TOOLS = ["frappe_get_current_user", "frappe_get_document", "frappe_list_documents"]


def failed(step, result) -> int:
    error = (result.structured_content or {}).get("error", {})
    print(f"FAIL {step}: {error.get('category')} (correlation_id {error.get('correlation_id')})")
    return 1


async def smoke() -> int:
    doctypes = Settings(_env_file=ROOT / ".env").mcp_allowed_doctypes
    if not doctypes:
        print("FAIL: MCP_ALLOWED_DOCTYPES is empty")
        return 1
    server = StdioServerParameters(
        command=sys.executable, args=["-m", "frappe_enterprise_mcp"], cwd=ROOT
    )
    async with Client(server) as client:
        info = client.server_info
        print(f"server: {info.name} {info.version}, MCP protocol {client.protocol_version}")
        tools = sorted(tool.name for tool in (await client.list_tools()).tools)
        print(f"tools: {', '.join(tools)}")
        if tools != EXPECTED_TOOLS:
            print("FAIL: unexpected tool list")
            return 1

        me = await client.call_tool("frappe_get_current_user", {})
        if me.is_error:
            return failed("frappe_get_current_user", me)
        print(f"user: {me.structured_content['user']}")

        page = await client.call_tool("frappe_list_documents", {"doctype": doctypes[0], "limit": 5})
        if page.is_error:
            return failed("frappe_list_documents", page)
        records = page.structured_content["records"]
        print(f"allowed DocType #1: {len(records)} record(s) on page 1")
        if records:
            name = records[0]["name"]
            doc = await client.call_tool(
                "frappe_get_document", {"doctype": doctypes[0], "name": name}
            )
            if doc.is_error:
                return failed("frappe_get_document", doc)
            print(f"document read with {len(doc.structured_content['document'])} allowed field(s)")

        denied = await client.call_tool("frappe_list_documents", {"doctype": "MCP Smoke Denied"})
        print(f"non-allowlisted DocType -> {denied.structured_content['error']['category']}")
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(smoke()))
