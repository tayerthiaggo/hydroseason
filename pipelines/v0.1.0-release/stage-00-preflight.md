/caveman

Mode: read-only release-workspace preflight. Recommended model: GPT-5.5 medium (`codex --model gpt-5.5 -e medium`).

Use superpowers:using-git-worktrees to inspect and propose the safe workspace for executing `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`. Do not implement tasks or use subagents.

Inspect branch, worktrees, `git status --short`, ignored files and whether the plan and four audited documents are tracked and available from the intended base. Preserve all user changes: do not commit, stash, discard, move or overwrite them without explicit approval. Never implement on main/master.

Write the same final report to `pipelines/v0.1.0-release/outputs/stage-00.md` and return it: current state; changes to preserve; worktree visibility; recommended setup; exact safe commands requiring approval; blockers. Stop before mutating git state.
