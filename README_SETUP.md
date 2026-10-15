# Frappe Enterprise MCP — Installation and OpenSpec Foundation

This is a **planning starter pack**, not a production MCP server. No write tools and no public HTTP endpoint are included.

## Intended architecture

- Primary product: standalone Python MCP server.
- Initial integration: Frappe/ERPNext v15/v16 REST API, using a restricted API user on a development site.
- First transport: local stdio; Streamable HTTP and remote client OAuth are **separate future milestones**.
- Zero custom Frappe app requirement for the read-only MVP.
- Optional Frappe companion app later for business operations that genuinely need native hooks and transaction guarantees.

## Prerequisites (macOS)

```bash
brew install git node uv
uv python install 3.12
brew install --cask claude-code  # skip if Claude Code is already installed
npm install -g @fission-ai/openspec@latest

git --version && node --version && uv --version && claude --version && openspec --version
```

OpenSpec currently requires Node.js >=20.19.0. The official MCP Python SDK requires Python >=3.11.

## Initialize the actual project

```bash
mkdir -p ~/Development/frappe-enterprise-mcp
cd ~/Development/frappe-enterprise-mcp
git init -b main
uv init --package --python 3.12
uv add 'mcp[cli]' httpx pydantic-settings
uv add --dev pytest pytest-asyncio respx ruff
openspec init --tools claude
```

Copy the **contents** of `openspec/config.example.yaml` in this pack into your generated project's `openspec/config.yaml`, retaining any useful project-specific settings already there.

Copy `CLAUDE.md`, `.env.example`, and `scripts/check_frappe_connection.py` into their corresponding locations in the project. Merge `.gitignore` contents carefully; never overwrite an existing useful ignore list.

```bash
cp .env.example .env
nano .env
uv run python scripts/check_frappe_connection.py
```

Use only disposable test data and a non-Administrator user. Add read-only permissions to one safe test DocType (for example `ToDo`) and verify `FRAPPE_URL` is the exact site URL you normally use, including local hostname and port if applicable.

## Create the plan in Claude Code — recommended path

The contents of `openspec/changes/...` in this pack are **reference artifacts**. To have Claude author and adjust them for your own repository, DO NOT first copy those prewritten change files; instead:

```bash
cd ~/Development/frappe-enterprise-mcp
claude
```

Within **Claude Code**:

```text
/opsx:propose establish-standalone-mcp-foundation
```

Follow the longer master prompt in `docs/MASTER_PROMPT.md` so Claude generates proposal, delta specs, design and tasks without implementation. Ask Claude to study the reference artifacts if you want its plan to be aligned with them.

Or, if you prefer using the starter artifacts directly, copy the provided `openspec/changes/establish-standalone-mcp-foundation/` folder into the actual project's `openspec/changes/`. **Do not run `/opsx:propose` again on an already created change.** Instead review and edit the artifacts directly.

## Validate plan before any implementation

Run in the terminal:

```bash
openspec status --change establish-standalone-mcp-foundation
openspec validate establish-standalone-mcp-foundation --strict
openspec show establish-standalone-mcp-foundation
git status --short
```

Review the acceptance criteria and architecture. Only after you approve the plan should you enter Claude Code and run:

```text
/opsx:apply establish-standalone-mcp-foundation
```

After running automated tests and verifying everything works, archive the completed change using `/opsx:archive` in Claude. Do not archive incomplete work.

## Security and deployment notes

- NEVER store real API credentials in the repository.
- No Administrator or System Manager API tokens in the MCP gateway.
- Do not run an unauthenticated remotely accessible Streamable HTTP MCP endpoint.
- For v0.1 the MCP process is single-user local stdio; the Frappe API token belongs to that restricted user.
- Backend API authorization, including field permissions, must be tested with restricted records and fields. Treat uncertain field permissions as deny.
- Only read operations are in scope; no arbitrary RPC, raw SQL, writes, submit/cancel or delete.
- Production-grade per-user OAuth, multi-site tenant routing, site approval enforcement and transaction receipts are deliberately planned for later changes.

## Sources (checked October 2026)

- OpenSpec: https://github.com/Fission-AI/OpenSpec
- OpenSpec CLI: https://github.com/Fission-AI/OpenSpec/blob/main/docs/cli.md
- Official MCP Python SDK: https://py.sdk.modelcontextprotocol.io/
- Frappe REST docs: https://docs.frappe.io/framework/user/en/guides/integration/rest_api
- Frappe token auth: https://docs.frappe.io/framework/user/en/api/rest
