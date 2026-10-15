"""Process configuration, validated once at startup from the environment and `.env`."""

from __future__ import annotations

import ipaddress
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

MAX_ALLOWED_DOCTYPES = 20
MAX_EXTRA_FIELDS = 20

_DOCTYPE = re.compile(r"[A-Za-z][A-Za-z0-9 _-]{0,60}")
_FIELDNAME = re.compile(r"[a-z][a-z0-9_]{0,61}")
_SITE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")
# Never exposable, even if listed in MCP_ALLOWED_FIELDS.
_DENIED_FIELD_PARTS = ("password", "secret", "api_key", "token")


def _is_loopback(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class Settings(BaseSettings):
    """All configuration. Secrets stay in `SecretStr` and are never echoed in errors."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", frozen=True
    )

    frappe_url: str
    frappe_api_key: SecretStr
    frappe_api_secret: SecretStr
    frappe_timeout_seconds: float = Field(default=15.0, ge=1.0, le=60.0)
    mcp_allowed_doctypes: Annotated[tuple[str, ...], NoDecode] = ()
    mcp_allowed_fields: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    mcp_site_id: str = "default"
    mcp_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("frappe_url")
    @classmethod
    def _site_origin(cls, value: str) -> str:
        parts = urlsplit(value.strip())
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("must be an absolute http(s) URL")
        if parts.username is not None or parts.password is not None:
            raise ValueError("must not embed credentials")
        if parts.path not in ("", "/") or parts.query or parts.fragment:
            raise ValueError("must be the bare site origin, without path, query or fragment")
        try:
            _ = parts.port
        except ValueError:
            raise ValueError("has an invalid port") from None
        if parts.scheme == "http" and not _is_loopback(parts.hostname):
            raise ValueError("must use https unless the host is loopback (local development)")
        return f"{parts.scheme}://{parts.netloc}"

    @field_validator("frappe_api_key", "frappe_api_secret")
    @classmethod
    def _credential(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if raw.lower().startswith("replace-with"):
            raise ValueError("is still the .env.example placeholder")
        if not (8 <= len(raw) <= 256 and raw.isascii() and raw.isprintable()):
            raise ValueError("must be 8-256 printable ASCII characters")
        if any(char.isspace() or char == ":" for char in raw):
            raise ValueError("must not contain whitespace or ':'")
        return value

    @field_validator("mcp_allowed_doctypes", mode="before")
    @classmethod
    def _split_doctypes(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @field_validator("mcp_allowed_doctypes")
    @classmethod
    def _doctypes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > MAX_ALLOWED_DOCTYPES:
            raise ValueError(f"allows at most {MAX_ALLOWED_DOCTYPES} DocTypes")
        if not all(_DOCTYPE.fullmatch(doctype) for doctype in value):
            raise ValueError("entries must be DocType names (letters, digits, space, '_' or '-')")
        return tuple(dict.fromkeys(value))

    @field_validator("mcp_site_id")
    @classmethod
    def _site_id(cls, value: str) -> str:
        if not _SITE_ID.fullmatch(value):
            raise ValueError("must be 1-63 lowercase letters, digits, '_' or '-'")
        return value

    @model_validator(mode="after")
    def _field_policy(self) -> Settings:
        for doctype, fields in self.mcp_allowed_fields.items():
            if doctype not in self.mcp_allowed_doctypes:
                raise ValueError(
                    "MCP_ALLOWED_FIELDS may only name DocTypes in MCP_ALLOWED_DOCTYPES"
                )
            if len(fields) > MAX_EXTRA_FIELDS:
                raise ValueError(
                    f"MCP_ALLOWED_FIELDS allows at most {MAX_EXTRA_FIELDS} per DocType"
                )
            for field in fields:
                if not _FIELDNAME.fullmatch(field) or any(p in field for p in _DENIED_FIELD_PARTS):
                    raise ValueError(
                        "MCP_ALLOWED_FIELDS has an invalid or always-denied field name"
                    )
        return self

    def fields_for(self, doctype: str) -> tuple[str, ...]:
        """Gateway field policy for an allowed DocType: `name` plus configured extras."""
        extras = self.mcp_allowed_fields.get(doctype, ())
        return ("name", *dict.fromkeys(field for field in extras if field != "name"))
