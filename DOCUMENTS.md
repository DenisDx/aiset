# Documents

aiset is an independent library with its own document set. This file lists
every document and what it is responsible for, per the agent workflow in
[AGENTS.md](AGENTS.md).

| File | Responsibility |
|---|---|
| [SPEC.md](SPEC.md) | Complete frozen specification: goal, findings, library boundaries, descriptor grammar, paths and edit semantics, resolver policy, comment-preserving storage, service semantics, security, acceptance matrix, phased plan, UI customization, hooks, logging. Read-only for agents. |
| [SPEC_.md](SPEC_.md) | Approved amendments to the protected `SPEC.md`, pending consolidation: structural operations, tree snapshots, generated editors, the phase 4 list, merge precedence, the `any` value type, and union resolution. Format defined by `AGENTS.md`. |
| [SPEC_service.md](SPEC_service.md) | Scoped normative specification of the service and transport contract: Python signatures, HTTP routes, MCP tools, views and permissions, revisions, result and error envelopes, Config object, callbacks, UI asset API, CLI. Kept in sync with the implementation. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Current internal architecture: file structure, logical components and their boundaries, principal data structures and flows. |
| [README.md](README.md) | Project overview, integration boundary, environment policy, structure, install/run/test commands, document map. |
| [AGENT_INTEGRATION.md](AGENT_INTEGRATION.md) | Task-oriented integration guide for agents: a numbered integration checklist, pinned install/submodule and mount-prefix guidance, hard rules, Python/HTTP/editor contracts, descriptor inheritance and grammar, tree snapshots including union alternatives, operations, permissions, error table, proxy/asset checks, troubleshooting, and extension/testing checklists. Optimized for model consumption; points to the normative documents instead of repeating them. |
| [IMPLEMENTATION_LOG.md](IMPLEMENTATION_LOG.md) | Implementation plan and work log: phases, completion marks, decisions and deviations. |
| [ROADMAP.md](ROADMAP.md) | Deferred work and directions that are not current assignments: specification-deferred milestones and host-side follow-ups. |
| [proposal_improvement8.md](proposal_improvement8.md) | Defects and feature requests found by the `aiset-flutter` implementation, including localized `description`/`title`. Status lives in the proposal. |
| [proposal_improvement7.md](proposal_improvement7.md) | Union object/array alternatives: the alternative's children are a structure, synthetic fields compose one value, and choosing the matching shape replaces nothing. |
| [proposal_improvement6.md](proposal_improvement6.md) | Union editing: a placeholder keeps the shape chooser, `matched_option` is inferred from the source value, and alternatives carry distinct labels. |
| [proposal_improvement5.md](proposal_improvement5.md) | Three defects in the `proposal_improvement4.md` implementation: duplicated CSS selectors, required classes the library did not paint, and no stated stability of the class inventory. |
| [proposal_improvement4.md](proposal_improvement4.md) | The host-owned design contract: class inventory, `--aiset-*` variables, structural rules in the library, reference theme. |
| [proposal_improvement3.md](proposal_improvement3.md) | `GET {base}/documents` requires `settings_read_source` unless the host opts into a public list. |
| [proposal_improvement2.md](proposal_improvement2.md) | Host-driven library changes: assets under the mount prefix, `validate-document`, union `matched_option`, unsupported-capability reporting. |
| [proposal_improvement_aidir.md](proposal_improvement_aidir.md) | Changes the aidir host needs from the library, each with a reproduction; the implementation record is in `IMPLEMENTATION_LOG.md` phase K. |
| [proposal_doctor.md](proposal_doctor.md) | Proposal for a `doctor` API: validate a document, report every issue with a fix class, and optionally repair the mechanically fixable part; includes the host command contract. |
| [proposal_demo2.md](proposal_demo2.md) | Proposed full demo2 host: reusable configuration tree, structural edits, AI chat, lifecycle actions, launcher, and acceptance contract. |
| [proposal_search.md](proposal_search.md) | Browser-only tree search over keys, values and descriptions, with expand/scroll/focus reveal, plus a sticky visible-path breadcrumb. |
| [TEST.md](TEST.md) | Test protocol: automated suite coverage, manual browser and demo protocol, acceptance matrix mapping. |
| [commands.md](commands.md) | Real commands: local environment setup, demo start, tests, descriptor CLI. |
| [DOCUMENTS.md](DOCUMENTS.md) | This document map. |
| [AGENTS.md](AGENTS.md) | Agent workflow; read-only for agents. |
| [memory/context.md](memory/context.md) | Compact shared working context: decisions, assumptions, blockers, user preferences. |
| [memory/history.md](memory/history.md) | Append-only chronological record of requests, operations and results. |
| [demo_aidir_config.template.json5](demo_aidir_config.template.json5) | Host-owned example descriptor for aidir written in the grammar; reference for host integrations. |
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

## Naming and local files

- `SPEC_service.md` and `AGENT_INTEGRATION.md` keep their established names: they
  are this project's scoped service specification and agent integration guide.
- A `local_` prefix marks a local replacement or local working note. Such files
  are excluded from Git (`local_*` in `.gitignore`) and are not part of the
  shared document set. They must not be the only record of a project decision.
- Protected documents are never edited. Corrections to `SPEC.md` use the
  `SPEC_.md` overlay; corrections to other protected documents use a
  `<name>_.md` proposal.

## Change control

- `SPEC.md` is agent-write-protected. A required correction goes into
  `SPEC_.md` with the section format required by `AGENTS.md`.
- An interface change updates `SPEC_service.md` and the implementation in the
  same change (SPEC_service.md section 22).
- A change to internal boundaries, interfaces, data representations, or flows
  updates `ARCHITECTURE.md`.
- New behaviour is recorded in `IMPLEMENTATION_LOG.md`; decisions with
  rationale go into `AGENT_INTEGRATION.md` section 19.3, next to the rules they
  explain.
