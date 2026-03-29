/fast

You are working inside the managed repository at C:\Users\ahnd6\.jakal-flow-workspace\projects\c-users-ahnd6-onedrive-github-lit-main-679f7c0bcc\.lineages\ln5\repo.
Follow any AGENTS.md rules in the repository.
Treat the saved execution plan as the current scope boundary unless the user explicitly updates it.
You are executing one node of a saved DAG execution tree.
Do not expand scope beyond the active task, dependency boundary, and scope guard.
Managed planning documents live outside the repo at C:\Users\ahnd6\.jakal-flow-workspace\projects\c-users-ahnd6-onedrive-github-lit-main-679f7c0bcc\.lineages\ln5\docs.
Verification command for this step: python -m pytest.

Current task:
- Title: Ship Release Surfaces
- UI description: Finish the CLI, desktop UI, packaging, docs, and release tests on the unified backend.
- Success criteria: The installable CLI and desktop UI both drive the same backend for the required v1 workflows; packaging keeps headless CLI use lightweight while preserving GUI launchability; documentation and help text describe lit as an autonomous local execution VCS with honest Git interoperability limits and a clear Jakal Flow backend path; and automated tests cover the shipped workflows, legacy repository compatibility, and the named performance smoke scenarios.
- Depends on: ST6
- Owned paths:
- pyproject.toml
- README.md
- docs/lit-v1-product-design.md
- docs/lit-v1-upgrade-notes.md
- src/lit/cli.py
- src/lit/commands
- src/lit_gui/contracts.py
- src/lit_gui/session.py
- src/lit_gui/backend/snapshot.py
- src/lit_gui/views
- tests/test_cli_end_to_end.py
- tests/test_git_export.py
- tests/test_performance_smoke.py
- tests/gui
- Step metadata:
{
  "candidate_block_id": "B7",
  "candidate_owned_paths": [
    "pyproject.toml",
    "README.md",
    "docs",
    "src/lit/cli.py",
    "src/lit/commands",
    "src/lit_gui/contracts.py",
    "src/lit_gui/session.py",
    "src/lit_gui/backend/snapshot.py",
    "src/lit_gui/views",
    "tests"
  ],
  "implementation_notes": "Keep the CLI coherent and quiet by default, with structured JSON where inspection matters. Preserve the GUI rule that views talk only through the session/backend boundary, and update docs to move the product identity away from local-Git language while explaining the Git bridge and Jakal Flow integration seam directly.",
  "is_skeleton_contract": false,
  "join_reason": "",
  "lineage_id": "LN5",
  "parallel_worker_status": "failed",
  "parallel_worker_synced_at": "2026-03-29T03:50:07+00:00",
  "parallelizable_after": [
    "B6"
  ],
  "skeleton_contract_docstring": ""
}

Codex execution instruction:
Rebuild the public product surface on top of the unified backend: make the CLI task-oriented with human and JSON output for checkpoint, rollback, verify, lineage, artifact, gc, doctor, and export workflows; extend the desktop session, DTOs, and views to expose checkpoint timeline, provenance, verification, lineage promotion, conflict review, rollback, artifact usage, and repository health; make GUI installation optional if practical; and land the README, product design doc, upgrade note, command help, end-to-end tests, GUI tests, backward-compatibility tests, and performance smoke coverage needed for a release-grade v1.

Memory context:
Relevant prior memory:
- [success] block 1: Ship Release Surfaces :: Completed block with one search-enabled Codex pass.
- [summary] block 1: Ship Release Surfaces :: python -m pytest exited with 0

Push skipped: push_disabled
- [failure] block 3: Ship Release Surfaces :: Search-enabled Codex pass regressed tests and was rolled back.
- [failure] block 2: Ship Release Surfaces :: Search-enabled Codex pass regressed tests and was rolled back.
- [failure] block 1: Ship Release Surfaces :: Search-enabled Codex pass regressed tests and was rolled back.

Plan snapshot:
# Execution Plan

- Repository: lit
- Working directory: C:\Users\ahnd6\OneDrive\문서\GitHub\lit
- Source: https://github.com/Ahnd6474/lit.git
- Branch: main
- Generated at: 2026-03-29T11:10:35+00:00

## Plan Title
lit v1 autonomous release

## User Prompt
You are working in the lit repository.

Mission:
Ship lit as a release-grade v1 product for autonomous local coding workflows and as the intended future repository backend for Jakal Flow.

This is not a prototype, foundation slice, or intermediate milestone task.
Do not optimize for partial progress.
Deliver a cohesive end-to-end product.

Product identity:
- lit is not a “local Git clone.”
- lit is a local execution VCS for long-running autonomous coding workflows on one machine.
- Its core promises are:
  1) human-controlled autonomy
  2) complete rollback
  3) structured multi-agent provenance
  4) safe validated checkpoints
  5) parallel lineage isolation and promotion
  6) local-first artifact and state management
  7) installable CLI and desktop UI
- Git-like commands may remain for familiarity, but Git parity is not the goal.

Primary user:
- The primary user is Jakal Flow operating on a local machine for long tasks.
- The system must support agent roles such as planner, executor, debugger, merge resolver, optimizer, closeout, and scheduler-supervised parallel workers.
- Human review and override must remain possible at plan, checkpoint, and promotion boundaries.

End-state requirement:
Build the complete v1, not a stepping stone.
At the end of this task, lit must feel like a real standalone product and a credible future backend for Jakal Flow with minimal conceptual mismatch.

Required product capabilities:

1. Repository engine
- Preserve and harden the content-addressed storage model.
- Keep snapshots fast, deduplicated, and cheap on local disks.
- Support ordinary commits plus first-class safe checkpoints.
- Support atomic rollback to the latest safe checkpoint or a selected safe checkpoint.
- Add crash-safe journaling for multi-step operations.
- Add repository locking for concurrent local operations.

2. Structured provenance
- Replace minimal authorship with structured provenance stored in the commit/checkpoint model and exposed throughout the product.
- Every commit/checkpoint must be able to record:
  - actor_role
  - actor_id
  - prompt_template or agent_family
  - run_id
  - block_id
  - step_id
  - lineage_id
  - verification_status
  - verification_summary
  - committed_at
  - origin_commit
  - rewritten_from
  - promoted_from
- Metadata must survive merge, rebase, lineage promotion, rollback bookkeeping, export, and history display.
- Backward compatibility with older commits lacking these fields is mandatory.

3. Safe checkpoint system
- Safe checkpoints must be first-class objects or refs, not a CLI-only label.
- Support:
  - mark checkpoint safe
  - list safe checkpoints
  - inspect checkpoint details
  - show latest safe checkpoint
  - rollback to latest safe checkpoint
  - rollback to selected safe checkpoint
  - pin / unpin safe checkpoints
  - optional checkpoint approval state / note
- Safe checkpoints must be visible in both CLI and desktop UI.
- A safe checkpoint is the canonical last-known-good state.

4. Verification-aware workflow
- Implement a real verification result model.
- Support repository-configured verification commands and per-checkpoint/commit verification recording.
- Store verification results using:
  - state fingerprint
  - environment fingerprint
  - command identity
  - timestamps
  - return code
  - output references
- Implement local verification cache replay.
- Support statuses such as:
  - never_verified
  - passed
  - failed
  - cached_pass
  - cached_fail
  - stale
- Safe checkpoint promotion must be verification-aware by design.

5. Lineage and parallel work isolation
- Add first-class lineage support for parallel agent work.
- A lineage must track:
  - lineage_id
  - base checkpoint
  - current head
  - owned paths...

Mid-term plan:
# Mid-Term Plan

This block follows the user-reviewed execution step.

- [ ] MT1 -> ST7: Ship Release Surfaces

Scope guard:
# Scope Guard

- Repository URL: https://github.com/Ahnd6474/lit.git
- Branch: main
- Project slug: c-users-ahnd6-onedrive-github-lit-main-679f7c0bcc

## Rules

1. Treat the saved project plan and reviewed execution steps as the current scope boundary unless the user explicitly changes them.
2. Mid-term planning must stay a strict subset of the saved plan.
3. Prefer small, reversible, test-backed changes.
4. Do not widen product scope automatically.
5. Only update README or docs to reflect verified repository state, and reserve README.md edits for planning-time alignment or the final closeout pass.
6. Roll back to the current safe revision when validation regresses.

Research notes:
# Research Notes

No research notes recorded yet.

Additional user instructions:
None.

Required workflow:
1. Inspect the relevant project files first so function names, module boundaries, and terminology stay consistent with the codebase.
2. Determine the smallest safe change set that satisfies the task instruction and success criteria.
3. Add or update executable tests that locally verify the task.
4. Implement the task in code.
5. Run the verification command and keep docs aligned only with verified behavior.
6. Do not edit README.md during normal execution steps. Reserve README updates for planning artifacts outside the repo or the final closeout pass unless the user explicitly says otherwise.
7. Record concise research or implementation notes in C:\Users\ahnd6\.jakal-flow-workspace\projects\c-users-ahnd6-onedrive-github-lit-main-679f7c0bcc\.lineages\ln5\docs\RESEARCH_NOTES.md when they materially help traceability.
8. If the task cannot be completed safely in one pass, explain why in docs/BLOCK_REVIEW.md instead of making speculative edits.

Execution rules:
- Treat the owned paths above as the primary write scope for this node.
- Avoid editing files that are primarily owned by other pending nodes unless a tiny compatibility adjustment is strictly required.
- Do not assume sibling nodes have already landed.
- If the task would require a broad cross-node refactor, stop and document the blocker instead of making merge-sensitive edits.
- If `step_metadata.step_kind` is `join` or `barrier`, treat this node as an explicit integration checkpoint on the current branch rather than a normal isolated feature pass.
- For join or barrier nodes, focus on reconciling already-completed upstream work, validating the combined behavior, and making only the smallest integration-safe edits needed to satisfy the success criteria.
- Keep the change set merge-friendly, traceable, and limited.
- Leave repository-wide handoff docs like README.md alone during step execution.
- Use web search only when directly necessary for official documentation or narrowly scoped factual verification.
