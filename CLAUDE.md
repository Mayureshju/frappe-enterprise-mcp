# Project Instructions — Frappe Enterprise MCP

## Product
Build an open-source, standalone Python MCP server to connect authorized AI clients to Frappe/ERPNext through supported APIs. A native Frappe companion app may be introduced later, only where requirements prove it necessary.

## Current milestone
Implement only `establish-standalone-mcp-foundation`: local single-user stdio transport; validated configuration; restricted Frappe API client; get current user; list and retrieve permitted documents; structured safe errors; basic audit events; mocked and integration tests. No production HTTP listener.

## Mandatory workflow
- For new capabilities, use OpenSpec change artifacts first: proposal, specs, design, tasks.
- Do not implement code until the corresponding change passes `openspec validate <change> --strict` and the user requests implementation.
- Use the installed SDK APIs, not stale snippets; check `uv.lock` and current SDK version before writing MCP code.
- Small reviewed commits to main; tests and lints must pass before committing.
- Never alter data in production to test an MCP tool.

## Security boundaries
- Default-deny DocTypes and fields. Do not expose all documents, `fields=["*"]`, arbitrary whitelisted methods, raw SQL, arbitrary HTTP destinations or write endpoints.
- Preserve Frappe per-user permissions; gateway allowlists are additional restrictions, never a replacement.
- Restrict site URL to an explicitly configured development host; no request-controlled URLs, SSRF or unsafe redirects. Enforce HTTPS outside loopback/local development.
- Never print/log tokens, authorization headers, raw sensitive responses or `.env` contents.
- No Administrator key or token shared between users or tenants.
- No unauthenticated remote MCP endpoint. Remote access and OAuth require their own design and tests.
- Sanitize API errors before presenting to LLM clients.

## Quality requirements
- Python 3.12; uv; pytest; respx; ruff; typed configuration and bounded timeouts.
- Frappe v15/v16 compatibility matrix and negative-permission tests.
- Explicit limits for pagination, field requests, response size and timeouts.
- Use stable structured tool responses, no leaking HTTP stack traces.
