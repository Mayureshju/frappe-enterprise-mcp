# Contributing

## Workflow

1. **Spec first.** New capabilities start with an approved proposal and specification
   (planning artifacts are kept out of version control). Implement only what the approved
   change describes.
2. **Use the installed SDK.** Check `uv.lock` for the MCP SDK version before touching MCP code;
   v2 APIs differ from v1 snippets found online.
3. **Small, reviewed commits to `main`.** Tests and lints must pass before committing.

## Setup and checks

```bash
uv sync --locked
uv run pytest
uv run ruff check .
```

Live checks (`FRAPPE_INTEGRATION=1 uv run pytest tests/test_integration.py -rA`) run only against
disposable development sites with a restricted, non-Administrator API user, and must stay read-only.
Never alter production data to test a tool.

## Rules that reviews enforce

- Deny by default. Never expose all DocTypes or fields, `fields=["*"]`, arbitrary whitelisted
  methods, raw SQL, caller-supplied URLs or hosts, or write endpoints.
- Frappe permissions stay authoritative; gateway policy may only narrow them.
- Never print or log tokens, `Authorization` headers, raw upstream responses or `.env` contents.
  Unit tests use dummy credentials; `tests/conftest.py` hides your real `.env` from them.
- Errors reaching MCP clients use the fixed categories in `server.py`; no upstream bodies or
  tracebacks.
- Every new limit, policy or error path needs a test, including the negative case.
- No unauthenticated network listener. Remote transport and OAuth need their own approved change.
