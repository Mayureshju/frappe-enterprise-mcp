# Security

## Supported use

Version 0.1.x is a **local development foundation**: a single-user stdio process acting as one
restricted Frappe API user against a development site. It is not supported for production, for
remote or shared deployment, or for use with Administrator or other high-privilege credentials.

## Reporting a vulnerability

Please report suspected vulnerabilities privately — through the repository host's private
vulnerability reporting once the project is published, or directly to the maintainer listed in
`pyproject.toml`. Do not open public issues for vulnerabilities, and do not include real
credentials or customer data in reports.

## Security model

| Threat | Control |
| --- | --- |
| High-privilege credential | Administrator and Guest identities are refused before any document read. The operator must still use a dedicated user without System Manager (the server cannot detect roles). |
| Forbidden DocType or record | DocType allowlist checked locally, with no request sent; Frappe's role, user-permission and record checks still apply and denials return no data. |
| Sensitive fields | Only `name` plus explicitly allowlisted scalar fields are returned; secret-like field names cannot be allowlisted; child tables are dropped. |
| SSRF / host switching | The site origin is fixed by validated configuration; tool inputs cannot carry URLs or extra arguments; names are encoded as one path segment; every request is checked against the configured origin; redirects are not followed; proxy settings are ignored. |
| Credential leakage | Secrets live only in `.env` (git-ignored) or the environment; startup errors never echo values; logs and errors never include headers, upstream bodies or tracebacks. |
| Prompt injection via ERP data | Tool descriptions and server instructions mark document content as untrusted data. Clients must still treat it as such. |
| Resource exhaustion | Page size, offset, argument length, response size, deadline and connection-pool limits. |
| Network exposure | stdio only; no listening socket. |

## Handling credentials

- Keep API keys only in `.env` or your shell environment. Never commit them or paste them into MCP
  client configuration files.
- Use a separate key per developer and per site. Do not reuse development keys for other services.
- If a key may have leaked, regenerate it in Frappe (**User → API Access → Generate Keys**) and
  check the site's logs.
