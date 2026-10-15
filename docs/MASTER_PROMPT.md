# Claude Code Master Prompt (use after `openspec init --tools claude`)

Paste the following into Claude Code **after** invoking `/opsx:propose establish-standalone-mcp-foundation` or include it in the same chat before that invocation:

> You are the lead architect of an open-source, enterprise-oriented Frappe/ERPNext MCP project. We have selected a standalone-first hybrid architecture: a Python MCP server using supported REST API endpoints, with a completely optional native Frappe companion app only for future site-side advanced guarantees. Do not create a Frappe app in this change.
>
> Build only the planning artifacts for `establish-standalone-mcp-foundation` using the installed OpenSpec spec-driven workflow. Do not implement application features yet. Target Python 3.12, uv, official MCP Python SDK (inspect the actually installed major version; avoid mixing v1/v2 APIs), HTTPX, Pydantic Settings, pytest, respx and ruff. Target Frappe v15/v16 via `/api/method/frappe.auth.get_logged_user` and read-only `/api/resource` endpoints.
>
> This phase is local single-user stdio only, using a dedicated non-Administrator development-site API user. It MUST NOT expose a remote unauthenticated HTTP service. Create exactly three v0.1 tools: `frappe_get_current_user`, `frappe_list_documents`, `frappe_get_document`. Deny all DocTypes by default except a documented explicit allowlist, and limit returned fields, sizes, pagination, timeouts and redirects. Do not expose create/update/delete/submit/cancel, unrestricted whitelisted RPC, SQL, arbitrary URLs, user-specified remote sites, or production financial data.
>
> Require native Frappe permission checks, gateway restrictions as an additional layer, permission/field-level negative tests, redacted logging and safe errors. Explicitly test behavior for Frappe v15/v16 rather than assuming the two versions share identical output semantics. Failing to verify a field's access MUST fail closed.
>
> Generate: proposal.md (why, scope, out-of-scope); capability delta specs with MUST/SHALL requirements and WHEN/THEN scenarios; design.md (components, API contracts, threat model, decisions, test matrix, rollout); tasks.md (small implementation steps, security tests, exit criteria). Include a roadmap that keeps OAuth, multi-site, remote HTTP, native bridge and business writes for later changes. Validate with `openspec validate establish-standalone-mcp-foundation --strict`. Summarize open decisions and stop before implementation.

Useful references: `README_SETUP.md`, `CLAUDE.md`, and the example planning artifacts in this pack.
