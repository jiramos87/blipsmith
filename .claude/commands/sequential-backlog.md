---
description: Decompose a DEFINED PRD into a dependency-ordered, self-contained implementation backlog that implementer sessions execute one item at a time via /implement
---

Build a sequential implementation backlog from a PRD. Input: `docs/prd/{slug}.md` (must be Status: DEFINED; if DRAFT, stop and point to `/prd-grill-me`). Optional: `--refresh docs/backlogs/{slug}.md` to re-verify an existing backlog instead of authoring a new one.

Not the same as an improvement backlog. An improvement backlog ranks independent items by effort and impact for pickup in any order. This orders items by logical dependency for pickup in the proposed order; effort and impact are still recorded per item, but as metadata, never the sort key.

Position in the loop: one planning session writes ONE ordered backlog doc from a grilled PRD; cheap implementer sessions then run `/implement docs/backlogs/{slug}.md {item-id}` per item, reading only the doc header plus their item. Reach for this when a DEFINED PRD is too big for a single `/implement` session; for a small PRD, `/implement` the PRD directly.

Template (the doc contract lives there): `templates/sequential-backlog-template.md`.

1. **Load the contract.** Read the PRD in full: inputs/outputs, acceptance, edge cases, quality bar, invariants, dependencies, out-of-scope. Read the repo seams the work will touch, from live code, not memory.
2. **Ground-truth pass.** Verify every PRD dependency claim against live code / infra where possible (schema, env, scripts, deployed services). Record verdicts for Appendix A; anything unverifiable is marked UNVERIFIED with what would verify it. PRD-vs-reality contradictions go to Appendix B and are surfaced to the user before any items are written.
3. **Order by dependency.** Slice the PRD into items (aim for 0.5-1.5 day granularity) and order them topologically: an item comes after every item it depends on. When two items are independent, keep PRD-narrative order and note them as parallelizable. Ordering ignores effort and impact; still record each item's effort and impact as metadata. Every item passes the self-containment test: an implementer with ONLY the doc header plus that item (plus ambient CLAUDE.md) can build it. Pin every cross-item seam (env-var names, paths, table names, shared contracts) in the header so items cannot drift apart. Steps only a human can do get a needs-human flag inside the owning item.
4. **Write the doc.** Instantiate the template at `docs/backlogs/{slug}.md`: header and cross-item seam inventory, ledger (all items pending, in dependency order), items, appendices. Shape check before handoff: every item has typed acceptance, a files list, a depends-on line, an effort and impact, and a PRD reference; every seam an item mentions appears in the header inventory; the ledger order is a valid topological sort of the depends-on graph.
5. **Hand off.** Do NOT implement anything and do NOT commit. End with the item count, the top of the ledger, and the first dispatch: `/implement docs/backlogs/{slug}.md B01`.

Refresh mode (`--refresh`): skip steps 3-4; re-run the ground-truth pass against the doc's own items, update ledger rows contradicted by live code (with evidence), append a refreshed Appendix A. Never rewrite item bodies.

Hard boundaries: item bodies are immutable once published (a correction appends a `Note ({date}):` line); one backlog doc per PRD; never commit; stop after handoff.
