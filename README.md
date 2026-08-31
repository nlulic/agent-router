# Agent Router

## LiteLLM

Local LiteLLM availability routing in front of a single upstream LiteLLM gateway.

```text
OpenCode
        ↓
local LiteLLM
        ↓
upstream LiteLLM
        ↓
upstream-provided models
```

The local proxy never connects directly to an external model provider. Upstream model IDs, the upstream URL, and credentials exist only in the `.env` file.

### Aliases

Clients request only these stable aliases:

```text
worker-explorer
worker-coder
orchestrator
reviewer
reviewer-specialist
coder-specialist-global
```

LiteLLM performs availability routing only. It never promotes work from one role to another. In particular, `worker-coder` never escalates to either specialist role; a specialist is used only when the client explicitly requests its alias.

### Availability chains

Each new role has one primary and exactly one private environment-selected fallback:

```text
orchestrator             → orchestrator fallback             → error
reviewer                 → reviewer fallback                 → error
reviewer-specialist      → reviewer-specialist fallback      → error
coder-specialist-global  → coder-specialist-global fallback  → error
```

The internal `*-fallback` model groups exist only to implement LiteLLM's ordered fallback configuration; they are not supported client-facing aliases.

The existing worker routing is preserved:

```text
worker-explorer  → worker-explorer fallback  → error
worker-coder     → worker-coder fallback     → error
```

## OpenCode

The `/opencode` directory adds capability orchestration above the repository's local LiteLLM availability router.

```text
OpenCode V2
 ↓
orchestrator (capability and delegation decisions)
 ├── explorer
 ├── coder
 ├── reviewer
 └── reviewer-specialist
       ↓
local LiteLLM
       ↓
availability fallback within the selected logical role
       ↓
upstream LiteLLM
```

OpenCode chooses a logical capability. LiteLLM independently chooses whether that role's primary or availability fallback serves the request. OpenCode never sees or selects the private physical model behind an alias.

### Provider

[`opencode.jsonc`](opencode.jsonc) declares one OpenAI-compatible provider:

```json
{
  "default_agent": "orchestrator",
  "providers": {
    "router": {
      "env": ["LOCAL_LITELLM_MASTER_KEY"],
      "package": "@opencode-ai/ai/providers/openai-compatible",
      "settings": {
        "baseURL": "http://127.0.0.1:4000/v1",
        "apiKey": "{env:LOCAL_LITELLM_MASTER_KEY}"
      }
    }
  }
}
```

The complete file declares exactly these logical model aliases:

```text
router/worker-explorer
router/worker-coder
router/orchestrator
router/reviewer
router/reviewer-specialist
```

Every alias explicitly advertises tool support plus text input/output, which this agentic routing contract requires. Context and output limits are intentionally omitted because the physical models and their limits are private and may differ across LiteLLM fallbacks. Current OpenCode applies fallback metadata to custom models when limits are absent; that metadata is an OpenCode assumption, not a claim about this router. Add accurate limits only if a safe public alias-level contract is established later.

### Agents and permissions

| Agent | Logical model | Mode | Policy |
|---|---|---|---|
| `orchestrator` | `orchestrator` | primary, default | Full lead role; may automatically launch explorer, coder, and reviewer; must ask for specialist review; cannot launch arbitrary agents |
| `explorer` | `worker-explorer` | subagent | Cheap default investigation worker; read/search plus narrow read-only Git and shell commands; edits, secrets, external paths, and child agents denied |
| `coder` | `worker-coder` | subagent | Cheap default implementation worker; read/edit/shell/tests allowed; remote push denied; destructive commands ask; child agents denied |
| `reviewer` | `reviewer` | subagent | Read-only independent review; read-only Git commands allowed; other validation commands ask; edits, commit/push, destructive Git, and child agents denied |
| `reviewer-specialist` | `reviewer-specialist` | subagent | Expensive, read-only high-risk review; same enforcement shape as reviewer; launching it requires user approval |

All four child definitions deny `subagent`, so delegation remains one level deep and the orchestrator owns decomposition. V2 custom subagents use their own permissions rather than inheriting the parent's restrictions.

#### Economy delegation policy

The orchestrator is instructed to:

- send broad repository discovery, symbol tracing, test location, and architecture mapping to `explorer`;
- send bounded routine implementation, tests, boilerplate, migrations, and mechanical refactors to `coder`;
- use `reviewer` selectively for meaningful behavior, multi-file, stateful, security-relevant, or risky changes, not trivial edits;
- request approval before unusually consequential review with `reviewer-specialist`;
- never invent or use an undeclared global specialist coding role;
- integrate and verify worker output rather than accepting it blindly;
- let LiteLLM handle temporary model/provider unavailability without changing capability tier.

### Prerequisites

- Current OpenCode V2
- The local LiteLLM proxy listening on `http://127.0.0.1:4000/v1`.
- `LOCAL_LITELLM_MASTER_KEY` available privately in the environment that starts OpenCode.

### Scripted installation

For macOS or Linux:

```bash
./opencode/scripts/install.sh
```

### Installation

Run the following commands from the repository root.

#### macOS and Linux

OpenCode's global configuration directory is `${XDG_CONFIG_HOME:-$HOME/.config}/opencode`.

Create the directory:

```bash
mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/agents"
```

If `opencode.jsonc` already exists there, do not overwrite it. Manually merge the `router` provider and `default_agent` from `opencode/opencode.jsonc` into the existing file.

For a fresh installation, create a symbolic link:

```bash
ln -s "$PWD/opencode/opencode.jsonc" \
  "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.jsonc"
```

Link the agents individually. These commands stop if a same-named file already exists:

```bash
for agent in "$PWD"/opencode/agents/*.md; do
  ln -s "$agent" \
    "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/agents/$(basename "$agent")"
done
```

#### Supply the local LiteLLM key

The key is not stored in the tracked configuration. Set it in the environment that launches OpenCode.

macOS or Linux:

```bash
export LOCAL_LITELLM_MASTER_KEY='your-private-local-key'
opencode2
```