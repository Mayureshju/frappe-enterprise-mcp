# Frappe Enterprise MCP

A standalone, open-source [Model Context Protocol](https://modelcontextprotocol.io) server that lets a
local AI client read from one Frappe/ERPNext site through its REST API, as one restricted API user.

> **Status: v0.1.0 foundation — local development only.** It runs over local **stdio** for a single
> user. It is **not production-ready, not enterprise-ready, and has no remote/HTTP mode**. Do not
> expose it on a network, and do not point it at production data.

## What you get

- Exactly three **read-only** tools: `frappe_get_current_user`, `frappe_list_documents`,
  `frappe_get_document`. No writes, submit/cancel, deletes, reports, attachments, arbitrary
  whitelisted methods or SQL.
- **Deny by default**: only DocTypes in `MCP_ALLOWED_DOCTYPES` can be read, and only `name` plus the
  fields you explicitly allow per DocType are returned. Frappe's own role, user and permlevel checks
  still apply; the gateway only ever narrows access.
- **Fixed target**: the site origin comes from configuration only. HTTPS is required except on
  loopback; redirects are never followed; proxy/netrc environment settings are ignored.
- **Identity guard**: `Administrator` and `Guest` identities are refused before any document read.
- **Bounded**: page size ≤ 50, offset ≤ 10,000, string arguments ≤ 140 chars, upstream response
  ≤ 1 MiB, per-request deadline 1–60 s (default 15), at most 4 concurrent upstream connections.
- **Safe errors and audit**: structured error categories with correlation IDs, never upstream
  bodies or tracebacks; one redacted JSON audit event per tool call on stderr.

Built with Python 3.12, uv, the official MCP Python SDK **`mcp` 2.3.0** (low-level `Server` API,
stdio transport), HTTPX 0.28.1 and Pydantic Settings 2.16.0. Tested against Frappe 15.118.0 /
ERPNext 15.119.1; Frappe v16 is not yet tested (see [docs/VERIFICATION.md](docs/VERIFICATION.md)).

## Install

```bash
uv sync --locked
cp .env.example .env   # then edit .env; it is git-ignored
```

## Provision a restricted API user

Do this on a **disposable development site**, as a site administrator:

1. Create a dedicated user for the MCP server (for example `mcp-reader@example.com`). Do not reuse a
   person's account, and give it **no** `System Manager` or `Administrator` role.
2. Create a role such as `MCP Reader`. In **Role Permission Manager** grant it only **Read** on the
   test DocType(s) at permlevel 0 — no Write, Create, Delete, Submit, Cancel, Amend, Import, Export,
   Report, Print, Email or Share. Optionally add **User Permissions** to narrow records further.
3. Assign only that role to the user.
4. On the user's form, **API Access → Generate Keys**. Put the key and secret into `.env`.
5. Check it: `uv run python scripts/check_frappe_connection.py`, then
   `uv run python scripts/smoke_mcp_client.py`.

To revoke access, regenerate the keys or disable the user. Never use Administrator keys, and never
reuse these keys for any other service or person.

## Configure

Settings come from environment variables, then `.env` in the working directory. Invalid settings
stop the server (exit code 2) **before any network call**; messages name the variable, never its
value.

| Variable | Default | Meaning |
| --- | --- | --- |
| `FRAPPE_URL` | required | Site origin, e.g. `https://erp.example.com`. `http` only for loopback hosts. No path, query or credentials. |
| `FRAPPE_API_KEY`, `FRAPPE_API_SECRET` | required | The restricted user's API credentials. |
| `MCP_ALLOWED_DOCTYPES` | empty (deny all) | Comma-separated DocType names, at most 20. Matched exactly (case-sensitive). |
| `MCP_ALLOWED_FIELDS` | `{}` | JSON object of extra fields per allowed DocType, e.g. `{"ToDo": ["status", "priority"]}`. At most 20 per DocType. Field names containing `password`, `secret`, `api_key` or `token` are always refused. |
| `MCP_SITE_ID` | `default` | Logical site label returned by `frappe_get_current_user` (the URL is never returned). |
| `FRAPPE_TIMEOUT_SECONDS` | `15` | Deadline per upstream request, 1–60 seconds. |
| `MCP_LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR` for this server's logs. Third-party loggers stay at `WARNING`. |

Only add a field to `MCP_ALLOWED_FIELDS` after checking it holds no sensitive data and that Frappe
withholds it from users without the right permlevel (`tests/test_integration.py` can check this).
Only scalar values are returned; child-table fields are always dropped.

## Run

The server speaks MCP on stdin/stdout and logs to stderr. It opens no listening socket.

```bash
uv run frappe-enterprise-mcp
```

Register it with a local MCP client, keeping secrets in `.env` rather than in client configuration:

```bash
# Claude Code
claude mcp add frappe -- uv run --directory /absolute/path/to/frappe-enterprise-mcp frappe-enterprise-mcp
```

```json
{
  "mcpServers": {
    "frappe": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/frappe-enterprise-mcp", "frappe-enterprise-mcp"]
    }
  }
}
```

For interactive inspection: `npx @modelcontextprotocol/inspector uv run --directory
/absolute/path/to/frappe-enterprise-mcp frappe-enterprise-mcp` (the Inspector runs its own local web
UI; this server still only uses stdio).

## Tools

Arguments are validated strictly: unknown arguments, wrong JSON types (e.g. `"5"` for an integer)
and out-of-range values are rejected before any request is sent to Frappe.

### `frappe_get_current_user()`

No arguments. Verifies the configured credential with Frappe on every call.

```json
{"site_id": "default", "user": "mcp-reader@example.com", "authenticated": true}
```

### `frappe_list_documents(doctype, limit=20, offset=0)`

`doctype` must be allowlisted; `limit` 1–50; `offset` 0–10,000. Records use Frappe's default order
(normally most recently modified first). Offset paging is not snapshot-consistent. No caller
filters, sorting or field selection.

```json
{"doctype": "ToDo", "records": [{"name": "a1b2c3", "status": "Open"}], "count": 1, "next_offset": null}
```

`count` is the number of records on this page. `next_offset` is set only when another page exists.

### `frappe_get_document(doctype, name)`

`name` is 1–140 characters and must not contain `/`, `\`, control characters or surrounding
whitespace, or consist only of dots. Frappe decides whether the user may read the record.

```json
{"doctype": "ToDo", "document": {"name": "a1b2c3", "status": "Open"}}
```

### Errors

Failures return `isError: true` with:

```json
{"error": {"category": "access_denied", "message": "Frappe denied access to the requested resource.", "correlation_id": "4f1c…"}}
```

| Category | Cause |
| --- | --- |
| `invalid_arguments` | Arguments failed validation (names the invalid fields, never values). |
| `unknown_tool` | No such tool. |
| `doctype_not_allowed` | DocType not in `MCP_ALLOWED_DOCTYPES`; nothing was sent to Frappe. |
| `authentication_failed` | Frappe rejected the credentials (401) or resolved them to `Guest`. |
| `identity_not_permitted` | The credentials belong to `Administrator`. |
| `access_denied` / `not_found` | Frappe returned 403 / 404. |
| `rate_limited` | Frappe returned 429. |
| `upstream_timeout` / `upstream_unavailable` | Deadline exceeded / connection failed. |
| `upstream_rejected` / `upstream_error` | Other 4xx / any 5xx from Frappe. |
| `redirect_rejected` | Frappe answered with a redirect (usually a wrong `FRAPPE_URL`). |
| `invalid_upstream_response` / `response_too_large` | Unexpected or oversized (> 1 MiB) response. |
| `internal_error` | Unexpected server fault; only the exception type is logged. |

## Audit events

Each tool call writes one JSON line to stderr through the `frappe_enterprise_mcp.audit` logger:

```text
2026-10-15 10:37:25,091 INFO frappe_enterprise_mcp.audit {"event": "tool_call", "tool": "frappe_list_documents", "request_id": "…", "outcome": "ok", "error_category": null, "duration_ms": 115.0, "doctype": "ToDo"}
```

`request_id` equals the `correlation_id` returned with errors. Events never contain credentials,
document names, field values, upstream bodies, or DocType strings that were rejected. Failed
upstream calls add `upstream_status`. Events are not retained anywhere else.

## Test

```bash
uv run pytest                                          # unit, protocol and stdio tests; no network
uv run ruff check .

# Live, read-only checks against the site in .env (use a restricted user on a dev site):
FRAPPE_INTEGRATION=1 uv run pytest tests/test_integration.py -rA
uv run python scripts/smoke_mcp_client.py              # local MCP client over real stdio
uv run python scripts/check_frappe_connection.py       # raw REST connectivity (uses ToDo)
```

The integration suite also runs denied-record and permlevel checks once a site administrator has
prepared fixtures and you set `FRAPPE_IT_DENIED_NAME` (a record of the first allowed DocType the API
user cannot read), `FRAPPE_IT_RESTRICTED_FIELD` (a permlevel > 0 field the user cannot read) and
`FRAPPE_IT_RESTRICTED_NAME` (a readable record where that field has a value).

## Limitations

- Local, single-user stdio only. There is no multi-user mode, remote HTTP transport or OAuth; those
  need their own design (Phase 2 in [docs/ROADMAP.md](docs/ROADMAP.md)).
- One site per process. `MCP_SITE_ID` is a label, not multi-site routing.
- The server rejects Administrator and Guest, but cannot tell whether a user holds powerful roles
  such as System Manager. Provisioning a genuinely restricted user is the operator's job.
- Field-level permission behaviour is verified with mocks; live permlevel and denied-record checks
  and Frappe v16 runs are still pending. Keep `MCP_ALLOWED_FIELDS` minimal until they pass.
- Child tables, names containing `/`, filters, sorting and linked-field expansion are unsupported.
- No retries, no HTTP proxy support, and HTTPS needs a certificate trusted by `certifi`.
- Audit events go to stderr only; there is no retention, alerting or dashboard.
- Pending enterprise controls: per-user OAuth delegation, multi-site tenant isolation, approval
  workflows before any write, audit retention, CI with dependency auditing and a v15/v16 matrix.

See [SECURITY.md](SECURITY.md) and [CONTRIBUTING.md](CONTRIBUTING.md).
