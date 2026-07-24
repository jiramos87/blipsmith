---
description: Implement a whole DEFINED PRD, or a single item from a sequential backlog, with minimal diffs, then run the verify gate
---

Implement in one of two modes, chosen by what you are pointed at:
- **Whole PRD:** `/implement docs/prd/{slug}.md` - build the entire feature from its DEFINED PRD.
- **One backlog item:** `/implement docs/backlogs/{slug}.md {item-id}` - build a single item from a sequential backlog (see `/sequential-backlog`).

## Whole PRD

Implement the feature defined in `docs/prd/{slug}.md`.

1. Read the PRD acceptance, quality bar, invariants, and out-of-scope. If the acceptance is ambiguous, stop and ask. Restate the acceptance scenarios + edge cases as a checklist, and map each one to a planned test.
2. Identify the seam: which layer / extension point this plugs into, and what must stay unchanged (the pure core, public contracts, the PRD's invariants). Prefer extending via data/config over editing core logic. Then plan the smallest diff that satisfies the acceptance, matching the surrounding code style.
3. Implement in place. Grow tests for the feature from the checklist in step 1 - one test per acceptance scenario AND per edge case, asserting both sides of every boundary (red then green).
4. Run the verify gate (see the `verify` skill). Iterate until green.
5. Stop before commit. Summarize what changed (and which invariants you preserved) and the next command.

Do not exceed the PRD scope. New ideas become new PRDs.

## One backlog item

Implement a single item from `docs/backlogs/{slug}.md`, identified by its item id.

1. Read ONLY the backlog header (including the cross-item seam inventory) and the target item - not the whole PRD, not other items. If the item's acceptance is ambiguous, or a dependency it relies on is not yet done, stop and say so. Restate the item's acceptance + edge cases as a checklist, and map each one to a planned test.
2. Identify the seam from the item and the header, and honor the pinned cross-item names exactly so later items still fit. Plan the smallest diff that satisfies the item's acceptance, matching the surrounding code style.
3. Implement in place. Grow tests from the checklist - one per acceptance scenario and edge case, asserting both sides of every boundary (red then green).
4. Run the verify gate (see the `verify` skill). Iterate until green.
5. Update the item's ledger row to done (never edit any item body). Stop before commit. Summarize what changed and print the next dispatch: `/implement docs/backlogs/{slug}.md {next-item-id}`.

Do not exceed the item's scope. A cross-item or out-of-scope finding gets a `Note ({date}):` line on the relevant item, or goes back to `/sequential-backlog`; it is never folded into this diff.
