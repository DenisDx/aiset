# Documents

aiset is an independent library with its own document set. This file lists
every document and what it is responsible for, per the agent workflow in
[AGENTS.md](AGENTS.md).

| File | Responsibility |
|---|---|
| [SPEC.md](SPEC.md) | Complete frozen specification: goal, findings, library boundaries, descriptor grammar, paths and edit semantics, resolver policy, comment-preserving storage, service semantics, security, acceptance matrix, phased plan, UI customization, hooks, logging. Read-only for agents. |
| [SPEC_service.md](SPEC_service.md) | Normative service and transport contract: Python signatures, HTTP routes, MCP tools, views and permissions, revisions, result and error envelopes, Config object, callbacks, UI asset API, CLI. Kept in sync with the implementation. |
| [README.md](README.md) | Project overview, integration boundary, environment policy, structure, install/run/test commands, document map. |
| [AGENT_INTEGRATION.md](AGENT_INTEGRATION.md) | Task-oriented integration guide for agents: a numbered integration checklist, pinned install/submodule and mount-prefix guidance, hard rules, Python/HTTP/editor contracts, descriptor inheritance and grammar, tree snapshots including union alternatives, operations, permissions, error table, proxy/asset checks, troubleshooting, and extension/testing checklists. Optimized for model consumption; points to the normative documents instead of repeating them. |
| [IMPLEMENTATION_LOG.md](IMPLEMENTATION_LOG.md) | Implementation plan and work log: phases, completion marks, decisions and deviations. |
| [proposal_demo2.md](proposal_demo2.md) | Proposed full demo2 host: reusable configuration tree, structural edits, AI chat, lifecycle actions, launcher, and acceptance contract. |
| [proposal_improvement7.md](proposal_improvement7.md) | Implemented union object/array alternatives: the alternative's children are a structure, synthetic fields compose one value, and choosing the matching shape replaces nothing. |
| [proposal_improvement6.md](proposal_improvement6.md) | Implemented union editing: a placeholder keeps the shape chooser, `matched_option` is inferred from the source value, and alternatives carry distinct labels. |
| [proposal_doctor.md](proposal_doctor.md) | Proposal for a `doctor` API: validate a document, report every issue with a fix class, and optionally repair the mechanically fixable part; includes the host command contract. |
| [TEST.md](TEST.md) | Test protocol: automated suite coverage, manual browser and demo protocol, acceptance matrix mapping. |
| [commands.md](commands.md) | Real commands: local environment setup, demo start, tests, descriptor CLI. |
| [DOCUMENTS.MD](DOCUMENTS.MD) | This document map. |
| [SPEC_.md](SPEC_.md) | Proposed corrections to the protected `SPEC.md`: structural operations, tree snapshots, generated editors, the phase 4 list, merge precedence, the `any` value type, and union resolution. |
| [proposal_demo2.md](proposal_demo2.md) | Proposal that defines the `demo2` acceptance host and the reusable editor extensions it required. |
| [proposal_improvement_aidir.md](proposal_improvement_aidir.md) | Changes the aidir host needs from the library, each with a reproduction; every item is implemented and recorded in `IMPLEMENTATION_LOG.md` phase K. |
| [proposal_improvement2.md](proposal_improvement2.md) | Host-driven library changes: assets under the mount prefix, `validate-document`, union `matched_option`, unsupported-capability reporting. |
| [proposal_improvement3.md](proposal_improvement3.md) | `GET {base}/documents` requires `settings_read_source` unless the host opts into a public list. |
| [proposal_improvement4.md](proposal_improvement4.md) | The host-owned design contract: class inventory, `--aiset-*` variables, structural rules in the library, reference theme. |
| [proposal_improvement5.md](proposal_improvement5.md) | Three defects in the `proposal_improvement4.md` implementation: duplicated CSS selectors, required classes the library did not paint, and no stated stability of the class inventory. |
| [notes_aidir_integration1.md](notes_aidir_integration1.md) | Host-side follow-ups found while wiring aidir to `proposal_improvement5.md` (stale comments, a coverage test that cannot see an unpainted required class). |
| [AGENTS.md](AGENTS.md) | Exact copy of the host agent workflow; read-only for agents. |
| [memory/context.md](memory/context.md) | Working context between sessions: decisions, open questions, user preferences, notes. |
| [memory/history.md](memory/history.md) | Chronological record of requests, operations and results. |
| [demo_aidir_config.template.json5](demo_aidir_config.template.json5) | Host-owned example descriptor for aidir written in the proposed grammar; reference for host integrations. |
| [examples/descriptor.json5](examples/descriptor.json5) | Demo descriptor covering every row of the M1 fixture matrix. |
| [examples/config.json5](examples/config.json5) | Commented mixed-type demo configuration used as the seeding example; never modified at runtime. |
| [examples/aiset_descriptor.json5](examples/aiset_descriptor.json5) | Descriptor for aiset's own settings document (SPEC.md 3.6). |
| [examples/aiset.json5](examples/aiset.json5) | aiset's own settings document, seeded into `.local/demo/`. |
| [examples/SKILL.md](examples/SKILL.md) | Host-provided Markdown configuration-editing skill (SPEC.md 14.2); instructional only. |
| [demo2/app.py](demo2/app.py) | demo2 host backend: settings, resolver, lifecycle routes, chat route. |
| [demo2/agent.py](demo2/agent.py) | demo2 configuration assistant: OpenAI-compatible transport and the bounded read/stage tool loop. |
| [demo2/env.py](demo2/env.py) | `.env` reader used as resolver data. |
| [demo2/descriptor.json5](demo2/descriptor.json5) | demo2 descriptor covering every required shape, including the `includes` section whose elements are typed from the component descriptor. |
| [demo2/conf2/descriptor.json5](demo2/conf2/descriptor.json5) | Descriptor of the component override document; declares the `typedefvalue1` and `typedefvalue2` templates that the main descriptor uses through `typedef_sources`. |
| [demo2/conf2/config.json5](demo2/conf2/config.json5) | The override update merged onto `includes.conf2` (SPEC.md 10.1); a test fixture of the host. |
| [demo2/config.json5.example](demo2/config.json5.example) | demo2 configuration template; seeded into the ignored local `config.json5`. |
| [demo2/.env.example](demo2/.env.example) | demo2 environment template, including the AI model name; seeded into the ignored local `.env`. |
| [demo2/frontend/](demo2/frontend/) | demo2 page, host script, and AIDIR-like stylesheet. |
| [demo2/tests/test_app.py](demo2/tests/test_app.py) | Host, launcher, and assistant tests. |
| [run_demo2.sh](run_demo2.sh) | Supported demo2 entry point: seeds missing state and runs the host with the local interpreter. |

## Change control

- `SPEC.md` is agent-write-protected. A required correction goes into
  `SPEC_.md` with the section format required by `AGENTS.md`.
- An interface change updates `SPEC_service.md` and the implementation in the
  same change (SPEC_service.md section 22).
- New behaviour is recorded in `IMPLEMENTATION_LOG.md`; decisions with
  rationale goes into `AGENT_INTEGRATION.md` section 19.3, next to the rules it
explains.