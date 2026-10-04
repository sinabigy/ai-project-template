<!-- ai-project-template:readme -->
# AI project template

A small, model-independent bootstrap layer for projects built by AI agents, humans, or both. Any worker can enter the repository, understand it, find the current task, retrieve only the context it needs, verify its work externally and leave a compact handoff, all without previous chat history.

**Requirements:** Python ≥ 3.9 (standard library only).
**Optional:**
- `git`: precise `.gitignore` handling and map provenance.
- Universal Ctags: a symbol index.
- `jsonschema`: full schema validation.

Each optional tool degrades gracefully when it's missing.

## Use it

```sh
# New project
cp -R ai-project-template my-project && cd my-project && rm -rf .git && git init
python3 tools/ai-init --name "My Project"            # add --objective "..." only if you have one

# Existing repository (copies only protocol files, never overwrites)
python3 /path/to/ai-project-template/tools/ai-init --target /path/to/repo

# New project from a copy of a protocol-enabled project (a blueprint or a fork)
python3 tools/ai-init --derive --name "New Project" --origin-name my-blueprint --origin-version 1.0
```

`ai-init`:
- detects the stack;
- records inferred validation commands as unconfirmed;
- resets template state;
- queues task T-0001 (project discovery);
- maps the repository;
- runs `ai-check`.

Re-running it is safe. This README is replaced by a project README on initialization.

`ai-init --derive` starts a new instance from a copy of an initialized project:
- **Reset:** task history, task summaries and state (they belong to the source).
- **Kept:** knowledge, decisions, constraints, confirmed validation commands and the
  architecture block (inherited).
- **Recorded:** provenance, in `instance.derived_from` and `architecture.origin`.

## Tools

| Command | Purpose |
|---|---|
| `tools/ai-init` | Initialize a copy or retrofit an existing repo |
| `tools/ai-check [--strict-runtime] [--json]` | Validate canonical state; exit 1 on failure |
| `tools/ai-validate [--stage S] [--json] [--report F]` | Run confirmed validation commands; pass/fail/skip report |
| `tools/ai-map` | Bounded, provenance-stamped repo map → `.ai/map/` (gitignored) |
| `tools/ai-task new/start/block/unblock/complete/list/current/show` | Task packets and an enforced state machine |
| `tools/ai-route T-NNNN` | Capability requirements, plus matching workers from the local registry |

Run the template's self-tests with `python3 -m unittest discover -s tools/tests -p 'template_selftest.py'`. They only run in an uninitialized template, and they are deliberately named so that a project's pytest never collects them. Retrofits don't copy them.

## Layout

```
AI_PROTOCOL.md            hot-path protocol (~1.7k tokens), the only file every worker reads in full
AGENTS.md CLAUDE.md …     thin shims pointing at the protocol
docs/protocol/            detailed guidance, retrieved on demand
.ai/config/               canonical, vendor-free config (project, capabilities, routing, context, budgets)
.ai/schemas/              JSON Schema 2020-12 for every machine-readable file
.ai/state/                STATUS.md, CURRENT_TASK.json (pointer), ROADMAP.json
.ai/knowledge/            architecture, conventions, constraints, lessons, known issues, ADRs
.ai/tasks/<status>/       task packets
.ai/templates/            reusable task definitions and file templates (instantiated by ai-init)
.ai/context/summaries/    result and handoff packets
.ai/evals/                acceptance, regression, benchmarks
.ai/map/  .ai/runtime/    generated and local only (gitignored)
```

## Principles

- The repository owns the objective, state, tasks, decisions, evidence and memory. Models are replaceable workers.
- Routing is by capability. Concrete models live only in the local `.ai/runtime/` registry.
- Canonical state is JSON, which the guaranteed runtime can parse. Knowledge is Markdown.
- Tools establish facts. Tests establish truth. The user defines the objective.

See `docs/protocol/CHANGELOG.md` for the template version.
