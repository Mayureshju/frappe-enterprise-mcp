import pytest
from pydantic import ValidationError

from frappe_enterprise_mcp import main
from frappe_enterprise_mcp.config import Settings

SENTINEL = "Sentinel-Secret-Value-9"


def test_valid_settings_normalize_origin(make_settings):
    settings = make_settings(frappe_url=" http://127.0.0.1:8000/ ")
    assert settings.frappe_url == "http://127.0.0.1:8000"
    assert SENTINEL not in repr(make_settings(frappe_api_secret=SENTINEL))


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000",
        "http://site1.localhost:8000",
        "http://127.0.0.1",
        "http://[::1]:8000",
        "https://erp.example.com",
    ],
)
def test_accepted_site_urls(make_settings, url):
    assert make_settings(frappe_url=url).frappe_url == url


@pytest.mark.parametrize(
    "url",
    [
        "http://erp.example.com",  # plain HTTP off loopback
        "http://10.0.0.5:8000",
        "ftp://127.0.0.1",
        "127.0.0.1:8000",
        "https://",
        "https://user:pass@erp.example.com",
        "https://erp.example.com/app",
        "https://erp.example.com/?next=http://evil.example",
        "https://erp.example.com#fragment",
        "http://127.0.0.1:99999",
    ],
)
def test_rejected_site_urls(make_settings, url):
    with pytest.raises(ValidationError):
        make_settings(frappe_url=url)


@pytest.mark.parametrize(
    "secret",
    [
        "",
        "short",
        "replace-with-restricted-user-api-secret",
        "has space123",
        "colon:inside",
        "ünicode12",
    ],
)
def test_rejected_credentials(make_settings, secret):
    for field in ("frappe_api_key", "frappe_api_secret"):
        with pytest.raises(ValidationError):
            make_settings(**{field: secret})


def test_credentials_are_required():
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, frappe_url="http://127.0.0.1:8000")
    assert {e["loc"][0] for e in caught.value.errors()} == {"frappe_api_key", "frappe_api_secret"}


def test_doctype_allowlist_parsing(make_settings):
    assert make_settings(
        mcp_allowed_doctypes=" ToDo, Sales Invoice,ToDo ,"
    ).mcp_allowed_doctypes == (
        "ToDo",
        "Sales Invoice",
    )
    assert make_settings(mcp_allowed_doctypes="", mcp_allowed_fields={}).mcp_allowed_doctypes == ()


@pytest.mark.parametrize(
    "doctypes", ["ToDo;DROP TABLE", "../User", "ToDo,*", ",".join(f"D{i}" for i in range(21))]
)
def test_rejected_doctype_allowlists(make_settings, doctypes):
    with pytest.raises(ValidationError):
        make_settings(mcp_allowed_doctypes=doctypes, mcp_allowed_fields={})


@pytest.mark.parametrize(
    "fields",
    [
        {"User": ["email"]},  # DocType not allowlisted
        {"ToDo": ["*"]},
        {"ToDo": ["Status"]},
        {"ToDo": ["api_key"]},
        {"ToDo": ["new_password"]},
        {"ToDo": ["reset_token"]},
        {"ToDo": [f"f{i}" for i in range(21)]},
    ],
)
def test_rejected_field_policies(make_settings, fields):
    with pytest.raises(ValidationError):
        make_settings(mcp_allowed_fields=fields)


def test_field_policy_defaults_to_name_only(make_settings):
    settings = make_settings(mcp_allowed_fields={"ToDo": ["status", "name", "status"]})
    assert settings.fields_for("ToDo") == ("name", "status")
    assert settings.fields_for("Note") == ("name",)


@pytest.mark.parametrize("timeout", [0.5, 61, "slow"])
def test_timeout_is_bounded(make_settings, timeout):
    with pytest.raises(ValidationError):
        make_settings(frappe_timeout_seconds=timeout)


def test_startup_fails_on_invalid_config_without_leaking_or_calling(monkeypatch, capsys, frappe):
    monkeypatch.setenv("FRAPPE_URL", "http://erp.example.com")
    monkeypatch.setenv("FRAPPE_API_KEY", "unitkey00000001")
    monkeypatch.setenv("FRAPPE_API_SECRET", f"{SENTINEL} with space")
    with pytest.raises(SystemExit) as exited:
        main()
    assert exited.value.code == 2
    err = capsys.readouterr().err
    assert "FRAPPE_URL" in err and "FRAPPE_API_SECRET" in err
    assert SENTINEL not in err and "unitkey00000001" not in err
    assert frappe.calls.call_count == 0


def test_startup_fails_without_config(capsys):
    with pytest.raises(SystemExit) as exited:
        main()
    assert exited.value.code == 2
    assert "FRAPPE_URL: Field required" in capsys.readouterr().err


def test_startup_reports_unparseable_json_setting(monkeypatch, capsys):
    monkeypatch.setenv("FRAPPE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("FRAPPE_API_KEY", "unitkey00000001")
    monkeypatch.setenv("FRAPPE_API_SECRET", "unitsecret00002")
    monkeypatch.setenv("MCP_ALLOWED_FIELDS", '{"ToDo": [' + SENTINEL)
    with pytest.raises(SystemExit):
        main()
    err = capsys.readouterr().err
    assert "mcp_allowed_fields" in err and SENTINEL not in err
