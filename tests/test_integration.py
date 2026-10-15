"""Read-only checks against the development site in `.env`, using its restricted API user.

Skipped unless FRAPPE_INTEGRATION=1. Optional fixtures, prepared on the site by an admin:
  FRAPPE_IT_DENIED_NAME       record in the first allowed DocType the API user cannot read
  FRAPPE_IT_RESTRICTED_FIELD  permlevel>0 field of that DocType the API user cannot read
  FRAPPE_IT_RESTRICTED_NAME   readable record whose restricted field holds a value
"""

import os
import sys
import uuid
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from frappe_enterprise_mcp.config import Settings
from frappe_enterprise_mcp.frappe_client import FrappeClient
from frappe_enterprise_mcp.server import build_server

ROOT = Path(__file__).resolve().parent.parent
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("FRAPPE_INTEGRATION") != "1", reason="set FRAPPE_INTEGRATION=1"
    ),
]
DENIED_NAME = os.environ.get("FRAPPE_IT_DENIED_NAME")
RESTRICTED_FIELD = os.environ.get("FRAPPE_IT_RESTRICTED_FIELD")
RESTRICTED_NAME = os.environ.get("FRAPPE_IT_RESTRICTED_NAME")


@pytest.fixture
def settings():
    settings = Settings(_env_file=ROOT / ".env")
    assert settings.mcp_allowed_doctypes, "MCP_ALLOWED_DOCTYPES must name a test DocType"
    return settings


def error_category(result):
    assert result.is_error
    return result.structured_content["error"]["category"]


async def test_report_frappe_version(settings):
    """For the compatibility matrix only; the MCP server itself never calls this method."""
    async with FrappeClient(settings) as frappe:
        payload = await frappe._get_json("/api/method/frappe.utils.change_log.get_versions")
    apps = payload["message"]
    print(f"frappe {apps['frappe']['version']}, erpnext {apps.get('erpnext', {}).get('version')}")


async def test_restricted_user_reads_one_allowed_document_over_stdio(settings):
    doctype = settings.mcp_allowed_doctypes[0]
    server = StdioServerParameters(
        command=sys.executable, args=["-m", "frappe_enterprise_mcp"], cwd=ROOT
    )
    async with Client(server) as client:
        me = await client.call_tool("frappe_get_current_user", {})
        page = await client.call_tool("frappe_list_documents", {"doctype": doctype, "limit": 3})
        assert not me.is_error and not page.is_error
        records = page.structured_content["records"]
        if not records:
            pytest.skip("the allowed DocType has no records readable by the API user")
        doc = await client.call_tool(
            "frappe_get_document", {"doctype": doctype, "name": records[0]["name"]}
        )
    assert me.structured_content["user"] not in {"Guest", "Administrator"}
    assert me.structured_content["authenticated"] is True
    allowed = set(settings.fields_for(doctype))
    assert all(set(record) <= allowed and "name" in record for record in records)
    assert not doc.is_error
    assert doc.structured_content["document"]["name"] == records[0]["name"]
    assert set(doc.structured_content["document"]) <= allowed


async def test_unauthorized_requests_reveal_nothing(settings):
    doctype = settings.mcp_allowed_doctypes[0]
    missing = f"mcp-it-missing-{uuid.uuid4().hex}"
    async with FrappeClient(settings) as frappe, Client(build_server(settings, frappe)) as client:
        forbidden = await client.call_tool("frappe_list_documents", {"doctype": "MCP IT Denied"})
        absent = await client.call_tool(
            "frappe_get_document", {"doctype": doctype, "name": missing}
        )
    assert error_category(forbidden) == "doctype_not_allowed"
    assert error_category(absent) == "not_found"
    assert set(absent.structured_content) == {"error"}


@pytest.mark.skipif(not DENIED_NAME, reason="set FRAPPE_IT_DENIED_NAME")
async def test_record_denied_by_frappe_reveals_nothing(settings):
    doctype = settings.mcp_allowed_doctypes[0]
    async with FrappeClient(settings) as frappe, Client(build_server(settings, frappe)) as client:
        result = await client.call_tool(
            "frappe_get_document", {"doctype": doctype, "name": DENIED_NAME}
        )
        page = await client.call_tool("frappe_list_documents", {"doctype": doctype, "limit": 50})
    assert error_category(result) == "access_denied"
    assert set(result.structured_content) == {"error"}
    assert DENIED_NAME not in {record["name"] for record in page.structured_content["records"]}


@pytest.mark.skipif(
    not (RESTRICTED_FIELD and RESTRICTED_NAME),
    reason="set FRAPPE_IT_RESTRICTED_FIELD and FRAPPE_IT_RESTRICTED_NAME",
)
async def test_permlevel_restricted_field_is_not_disclosed(settings):
    doctype = settings.mcp_allowed_doctypes[0]
    # Deliberately put the restricted field in the gateway policy: Frappe must still withhold it.
    widened = settings.model_copy(update={"mcp_allowed_fields": {doctype: (RESTRICTED_FIELD,)}})
    async with FrappeClient(widened) as frappe, Client(build_server(widened, frappe)) as client:
        doc = await client.call_tool(
            "frappe_get_document", {"doctype": doctype, "name": RESTRICTED_NAME}
        )
        page = await client.call_tool("frappe_list_documents", {"doctype": doctype, "limit": 50})
    assert not doc.is_error
    assert doc.structured_content["document"].get(RESTRICTED_FIELD) in (None, "")
    if not page.is_error:  # some versions reject the whole list instead, which is also safe
        assert all(
            r.get(RESTRICTED_FIELD) in (None, "") for r in page.structured_content["records"]
        )
