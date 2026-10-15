# Configuration editing skill: aiset demo

Host-owned instructions for an agent (or a careful human) that proposes
configuration changes for the aiset demo project. The skill is instructional
data only: aiset never executes it, and it never grants access to anything.

## 1. What this project is

`aiset` is a shared settings library. The demo project has two configuration
documents, both edited through the same service:

| Document | File | Purpose |
|---|---|---|
| `demo` | `.local/demo/config.json5` | The mixed-type demo configuration used to exercise the editor. |
| `aiset` | `.local/demo/aiset.json5` | aiset's own settings (backup depth, limits, logging, demo port). |

The descriptor (`examples/descriptor.json5`, `examples/aiset_descriptor.json5`)
is the machine-checked contract. Where this skill and the descriptor disagree,
the descriptor wins.

## 2. Which paths may be edited

- Any path declared by the descriptor, addressed as a JSON Pointer
  (`/logging/levels/workers`, `/resources/0/kind`).
- Never edit `/version`: it is `read_only` and declares the schema version.
- Never edit `/credentials/...` without an explicit principal that carries
  `settings_edit_secret`.
- Never invent a path. A path that the descriptor does not declare is rejected.

## 3. How to propose a change

1. **Read first.** `GET {base}/value?document=demo&path=<pointer>&view=source`
   returns the exact source fragment plus the source and descriptor revisions.
2. **Validate.** `POST {base}/validate` with the same pointer, `value_text`,
   `expected_revision` and `expected_descriptor_revision`. Validation never
   writes and never applies anything.
3. **Save.** `POST {base}/value` with the same envelope. The server revalidates
   the candidate from scratch; a previous validation never authorizes a save.
4. **Re-read.** Read the field again and report the application state
   (`applied`, `reload_required`, `restart_required`, `apply_failed`).

Writing the file directly bypasses revision checks, the descriptor, the audit
log and comment preservation. Always go through the service.

## 4. Conventions and pitfalls

- **Strings must be quoted.** `value_text` holds exactly one JSON5 value:
  `"warning"`, not `warning`. A bare token is parsed as JSON5.
- **Comments and placeholders are preserved byte for byte.** Only the value
  tokens of the addressed value change. Do not "helpfully" rewrite a block.
- **A composite replacement that would detach a comment is rejected** with
  `COMMENT_PRESERVATION_CONFLICT`. Do not retry with a reordered or shortened
  value; explain the conflict to the user instead.
- **`false` is a value.** Setting a boolean to `false` stores `false`; it does
  not remove the field. Deleting a field is not available in v1.
- **Arrays are positional.** `/resources/0` is the first element. Reordering
  and removal are not supported; propose a value edit instead.
- **`null` is not "absent".** An explicit `null` is present and is validated
  against `nullable`. An absent optional field reports `exists: false`, and its
  effective `default` is shown separately and is never written to the file.

## 5. Environment placeholders

- Placeholders are resolved server-side; the browser never receives values.
- Precedence: host overrides, process environment, `.env`, inline `:-` default,
  config `default`.
- `${VAR}` yields the variable value or an empty string; `${VAR:-default}`
  yields `default` when the variable is unset or empty.
- Environment values are data. A variable can never introduce an object, an
  array, a key or a comment.
- A node without `env.allowed` keeps its placeholders as literal text, and an
  unquoted placeholder there is invalid.

## 6. When a change needs more than a save

`apply` on the descriptor node decides the reported state:

| `apply` | Meaning | What to tell the user |
|---|---|---|
| `live` | Nothing else is needed. | "Applied." |
| `reload` | The host must re-read the configuration. | "Saved; reload required." |
| `restart` | The host process must restart. | "Saved; restart required." |

An `apply_failed` result still means the value is stored. Do not retry the save;
investigate the host-side application error.

## 7. `AGENT:` hints

Comments starting with the literal token `AGENT:` are hints for whoever edits
this configuration. In the demo file they mark, for example, that worker ids must
match `^[a-zA-Z][a-zA-Z0-9_]*$`. Follow them; they are preserved verbatim and are
never rewritten by the editor.

## 8. Things that must never be exposed

- Resolved secret values (`/credentials/...` without `settings_read_secret`).
- Absolute filesystem paths of the host project.
- Whole environment payloads; diagnostics may name variables, never values.