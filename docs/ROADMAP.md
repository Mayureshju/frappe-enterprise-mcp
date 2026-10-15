# Milestone Roadmap

## Phase 0: Decisions and Threat Model
- Confirm architecture ADR: standalone-first, optional Frappe bridge.
- Review 3-5 strong existing open-source MCP implementations and identify non-duplicate contributions.
- Verify SDK major version and MCP transport approach, Frappe v15/v16 permission behavior.
- Finish and approve OpenSpec artifacts. Stop before feature implementation.

## Phase 1: Read-only Local MVP
- Local stdio, one restricted ERPNext API identity, one configured Frappe dev site.
- Exactly 3 tools for current user/list/get with default-deny policy.
- Mocked tests, permission/field integration tests, bounded API access, structured errors and redacted logging.

## Phase 2: Remote Identity and Transport
- Streamable HTTP behind HTTPS, OAuth for MCP clients, separate per-user Frappe authorization.
- Audience validation, CSRF/SSRF/origin safeguards, secret storage and revocation, security tests.

## Phase 3: Controlled Enterprise Read Operations
- Multi-site registry, strict tenant isolation, schema tools, vetted report tools, Resources and Prompts.
- Audit retention, health checks and operator controls.

## Phase 4: Safe Write Operations
- Proposals, approvals, revalidation, idempotency, audited receipts, ambiguity and recovery rules.
- Only add optional Frappe native bridge for workflows requiring execution-side assurances.

## Phase 5: Business Packs and Release
- ERPNext Sales, Buying, Stock, Accounts, optional HRMS packs with native validation and integration tests.
- Benchmarks, security review, reproducible CI, documentation and open-source releases.
