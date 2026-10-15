# Bootstrap Commands

Run these from the aiset directory.

## Current checks

Confirm that the specification and agent context exist:

```sh
test -f SPEC_.md && test ! -e SPEC.md && test -f AGENTS.md && test -f memory/context.md
```

Find implementation placeholders in new files:

```sh
grep -nE 'TODO:|FIXME:|TBD:|\?\?\?' README.md SPEC_.md TEST.md memory/context.md
```

The working specification intentionally contains preparation/discussion headings;
their locations and open questions are registered in [memory/context.md](memory/context.md).
No matches means grep exits with status 1. The copied agent workflow contains
illustrative placeholder markers; those are documentation examples, not pending
implementation tasks.

## Git checks

This directory is its own Git repository:

```sh
git status --short
git diff --check
```

These report aiset's own status, not the parent aidir repository.

## Runtime and tests

No install, server, or software-test command exists yet. Add real commands here
when the corresponding tooling is implemented; do not use aidir's environment
as an implicit aiset runtime dependency.
