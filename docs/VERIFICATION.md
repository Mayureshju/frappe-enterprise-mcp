# Verification record — `establish-standalone-mcp-foundation`

Recorded 2026-10-15 on macOS (Apple Silicon), Python 3.12.13, uv 0.12.3. Locked versions:
`mcp` 2.3.0 (negotiates MCP protocol 2026-07-28), `httpx` 0.28.1, `pydantic` 2.14.1,
`pydantic-settings` 2.16.0, `pytest` 9.1.1, `pytest-asyncio` 1.4.0, `respx` 0.23.1, `ruff` 0.17.0.

## Quality gates (task 5.2)

| Command | Result |
| --- | --- |
| `uv sync --locked` | OK — 51 packages resolved, lockfile current |
| `uv run pytest` | 162 passed, 5 skipped (the live integration module, off by default) |
| `FRAPPE_INTEGRATION=1 uv run pytest tests/test_integration.py -rA` | 3 passed, 2 skipped (fixture variables not set) |
| `uv run ruff check .` | All checks passed |
| `openspec validate establish-standalone-mcp-foundation --strict` | Change is valid |
| `uv run python scripts/smoke_mcp_client.py` | PASS — see below |

Smoke test output (stdio, real server process, development site on loopback):

```text
server: frappe-enterprise-mcp 0.1.0, MCP protocol 2026-07-28
tools: frappe_get_current_user, frappe_get_document, frappe_list_documents
user: <non-Administrator user, redacted>
allowed DocType #1: 5 record(s) on page 1
document read with 1 allowed field(s)
non-allowlisted DocType -> doctype_not_allowed
PASS
```

## Compatibility matrix (task 4.3 — partial)

Live site: Frappe 15.118.0, ERPNext 15.119.1 (local bench). No Frappe v16 site was available.

| Behaviour | Endpoint | v15.118.0 | v16 |
| --- | --- | --- | --- |
| Credential resolves to a non-Administrator user | `GET /api/method/frappe.auth.get_logged_user` | Pass (live) | Not tested |
| List with explicit `fields`, `limit_start`, `limit_page_length` | `GET /api/resource/<DocType>` | Pass (live) | Not tested |
| Read one allowed document; only policy fields returned | `GET /api/resource/<DocType>/<name>` | Pass (live, over stdio) | Not tested |
| Missing record → 404 → `not_found`, no data | same | Pass (live) | Not tested |
| Non-allowlisted DocType rejected with no request | none | Pass (live) | Same code path |
| Record denied by Frappe → 403 → `access_denied`, no data | same | Mock-tested only; live fixture pending | Not tested |
| permlevel-restricted field withheld even if allowlisted | both resource endpoints | Mock-tested only; live fixture pending | Not tested |

Behaviour the gateway does not rely on Frappe for (fails closed on every version): unlisted fields
are dropped, `name` is the only default field, child tables are dropped, Administrator and Guest
are refused, redirects are rejected, and responses over 1 MiB are rejected.

To complete this matrix, a site administrator must prepare on disposable v15 **and** v16 sites:
a dedicated restricted user (see README), a record of the first allowed DocType that user cannot
read, and a permlevel 1 custom field on that DocType that the user's role cannot read, with a value
on a readable record. Then run the integration suite with `FRAPPE_IT_DENIED_NAME`,
`FRAPPE_IT_RESTRICTED_FIELD` and `FRAPPE_IT_RESTRICTED_NAME` set.

## Credential and network inspection (task 5.4)

Method: a script loaded the configured key and secret from `.env` (never printing them), searched
every repository file outside `.git/`, `.venv/` and `.env`, then started the server with
`python -m frappe_enterprise_mcp`, completed an MCP `initialize` and a `tools/call` over raw stdio,
and inspected the live process with `lsof` and `ps`.

| Check | Result |
| --- | --- |
| Repository files containing the configured API key or secret (68 scanned) | None |
| `.env` ignored by git (`git check-ignore .env`) / tracked | Ignored / not tracked |
| TCP listening sockets / UDP sockets of the running server | None / none |
| Outbound TCP connections at sample time | None open (the dev server closes connections per request) |
| Secret in process arguments | No (configuration comes from `.env`) |
| Secret in server stderr (audit log) | No |

## Findings that need operator action

- **The configured API user is not restricted.** It is not Administrator, but it can list `User`
  and `Role` records, which normally needs System Manager–level access. MCP exposure is still
  limited by the allowlist (one DocType, `name` only), but the stored credential is powerful.
  Provision a dedicated restricted user as described in the README, rotate the current key if it
  belongs to a person, and re-run the smoke and integration checks (task 1.3).
- The denied-record and permlevel fixtures and a v16 site are needed to finish task 4.3.
