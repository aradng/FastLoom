---
description: What not to write — comments, dead code, defensive paths, premature abstractions
---

# Code style — minimalism

The repo is intentionally minimal. Read once, edit confidently. The rules below are how we keep it that way.

## Comments

- **Default: write none.** Code is self-explaining when names are good. Re-stating what the code does adds noise.
- Only add a comment when the **why** is non-obvious: a hidden constraint, a subtle invariant, a workaround for a specific bug, behavior that would surprise a future reader.
- **Don't reference the current task, PR, ticket, or fix:** "added for the user dashboard flow", "fixes #123", "for backwards compatibility with the old API" — these rot. The git log already has that.
- **Don't paraphrase signatures:** docstrings repeating what `def foo(bar: int) -> str:` already says are negative-value comments.
- **No multi-paragraph docstrings or multi-line comment blocks.** One short line is the cap.
- One specific exception: **subtle Beanie/FastStream hooks** (e.g. ordering rules in `launcher/main.py`) warrant a one-line marker because the ordering is load-bearing.

## What not to write

- **No defensive code for paths that can't happen.** Trust internal callers. Validate only at system boundaries (HTTP input, broker payload, DB read).
- **No fallback branches for invariants the type system already enforces.** If `foo: int`, don't `if isinstance(foo, int):`.
- **No feature flags for code that can simply change.** If a behavior switch is genuinely runtime-controlled, gate on `isinstance(TC.general, X)`; otherwise just edit the code.
- **No backwards-compatibility shims after a rename/refactor** unless the rename crosses a published API boundary. Internal code: delete and update callers.
- **No half-finished implementations.** Either finish or revert.
- **No abstractions for hypothetical futures.** Three similar lines beat one cleverly generic helper used twice.

## Renaming / deletion hygiene

- When you remove a function/variable/type, **delete it fully** — including any re-exports, `_var` renames, `// removed for X` markers, or stub re-exports.
- Don't leave `# type: ignore` once the underlying type issue is fixed.

## When fixing a bug

- Fix the bug. **Don't surround-cleanup** unrelated code in the same change. Save that for a follow-up PR. Mixed diffs are unreviewable.

## When adding a feature

- Add only what the feature requires. No "while I'm here" refactors. The smallest possible diff that delivers the feature is the right diff.
