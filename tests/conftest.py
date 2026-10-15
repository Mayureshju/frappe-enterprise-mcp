import contextlib
import os

import pytest
import respx
from mcp import Client

from frappe_enterprise_mcp.config import Settings
from frappe_enterprise_mcp.frappe_client import FrappeClient
from frappe_enterprise_mcp.server import build_server

SITE = "http://127.0.0.1:8000"
API_KEY = "unitkey00000001"
API_SECRET = "unitsecret00002"
USER_PATH = "/api/method/frappe.auth.get_logged_user"


@pytest.fixture(autouse=True)
def _isolated_env(request, monkeypatch, tmp_path):
    """Unit tests never see the developer's real `.env` or FRAPPE_*/MCP_* variables."""
    if request.node.get_closest_marker("integration"):
        return
    for key in list(os.environ):
        if key.startswith(("FRAPPE_", "MCP_")):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def make_settings():
    def make(**overrides):
        values = {
            "frappe_url": SITE,
            "frappe_api_key": API_KEY,
            "frappe_api_secret": API_SECRET,
            "mcp_allowed_doctypes": "ToDo,Note",
            "mcp_allowed_fields": {"ToDo": ["status", "priority"]},
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    return make


@pytest.fixture
def frappe():
    """Mock of every outbound HTTP request; unmatched requests are still recorded."""
    with respx.mock(assert_all_called=False, assert_all_mocked=False) as router:
        yield router


@pytest.fixture
def user_route(frappe):
    return frappe.get(SITE + USER_PATH).respond(200, json={"message": "mcp.reader@example.com"})


@pytest.fixture
def connect(make_settings):
    """In-process MCP client session. Used as `async with connect() as mcp:` inside the test,
    because the SDK's anyio task group must be entered and exited in the same task."""

    @contextlib.asynccontextmanager
    async def connect(**overrides):
        settings = make_settings(**overrides)
        async with (
            FrappeClient(settings) as client,
            Client(build_server(settings, client)) as session,
        ):
            yield session

    return connect
