# Test Protocol

## Current scope

aiset currently contains documents only. There is no executable application
or automated software-test suite.

Bootstrap verification:

1. Check that the expected documents exist and the old aidir proposal path is
   absent after the move.
2. Compare [AGENTS.md](AGENTS.md) byte-for-byte with the original aidir copy.
3. Parse all JSON/JSON5 examples in [SPEC_.md](SPEC_.md).
4. Check local Markdown links and consistency of the aiset name/placement.
5. Confirm that aidir excludes the complete aiset directory from Git tracking.
6. Confirm that aiset is its own Git repository and no submodule is configured.
7. Verify aiset ignore rules exclude runtime files but retain documentation,
   agent memory, tracked examples, and dependency lockfiles.

The inherited formatting in the exact [AGENTS.md](AGENTS.md) copy is not changed
as part of bootstrap. Initial document validation may use available host tooling
without making it a declared runtime dependency of aiset.

## Implementation gates

Use the acceptance matrix in [SPEC_.md](SPEC_.md), section 12, as the source of
truth. In particular:

- Verify comment preservation against exact bytes, not just parsed values.
- Test descriptor metadata diagnostics separately from config-value validation.
- Test the standalone UI/backend without a host, accounts, or Redis.
- Run the same library revision against multiple host adapters unchanged.
- Test failed/conflicting writes for unchanged disk state and clear errors.

Record real test commands in [commands.md](commands.md) as tooling is added.
No future acceptance requirement is claimed as passing merely because the
documents are present.

## Complete working specification

[SPEC_.md](SPEC_.md) is the complete specification, not an amendment document.
Check that sections 1-20 occur once, the descriptor/storage/API contracts are
present, and no old-text/replacement wrappers or duplicate phase/question lists
remain. The service and transport interface is in [SPEC_service.md](SPEC_service.md).
There must be no separate SPEC.md during this drafting stage.

The AI section defines a future host skill requirement only; it must not imply
that a model connection, skill loader, agent runtime, or caller already exists.

The first working milestone must be the standalone editor on default port 8383,
with all declared fixture types and browser read/validate/save/restart checks.
These remain future software acceptance tests, not completed implementation.

## Execution-environment checks

Verify the agreed section 3.4 policy in future software tests:

- The same package works in the host environment and aiset's local `.venv/`.
- Standalone tests need no host-installed packages or host state.
- Local environment setup is explicit; import/startup never creates or switches it.
- Dependency conflicts are reported without changing the host environment.
- Selecting a virtual environment does not implicitly enable demo mode.

This policy is documentation only at present; no local venv was provisioned.

## Proposed helper and hook checks

Before implementing sections 18-19, test:

- Helpers propose values through the ordinary service; cancel writes nothing.
- Creation helpers obey current path/append/transaction capability limits.
- Parent replacements cannot bypass descendant hook bindings or protections.
- Before hooks are pure and may reject without persistence; after-hook failures
  retain explicit committed revision and application state.
- Sync/async callbacks share contracts and never run under the file lock.
- Stale snapshots, missing tags, timeouts, and unknown delivery outcomes are
  explicit; no event-loop blocking, silent skipping, or blind retries.

These extensions remain outside M1, and no helper/hook runtime exists yet.
