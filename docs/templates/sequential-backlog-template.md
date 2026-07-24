# Implementation backlog: {Feature}

Source PRD: `docs/prd/{slug}.md` (Status: DEFINED). Built by `/sequential-backlog` on {date}.

Items are ordered by dependency, NOT by effort or impact. Effort and impact are retained per item as metadata, never the sort key. Item bodies are immutable once published; a correction appends a `Note ({date}):` line to the item, it never rewrites it.

## How to use this doc

Dispatch one item per implementer session, in ledger order, with `/implement docs/backlogs/{slug}.md {item-id}`. Each session reads ONLY this header plus its own item (plus ambient CLAUDE.md). Everything an item needs is either inside that item or pinned in the Cross-item seams inventory below.

## Cross-item seams (pinned)

The shared names later items depend on, fixed here so items cannot drift apart: env-var names, paths, table / collection names, route prefixes, shared types and contracts.

- {name}: {value or shape} - introduced by {item-id}, consumed by {item-ids}.

## Ledger (progress, in dependency order)

| Item | Title | Depends on | Effort | Impact | Status |
|---|---|---|---|---|---|
| B01 | {title} | none | S | high | pending |
| B02 | {title} | B01 | M | med | pending |

Statuses: pending -> in-progress -> done. The implementer updates its own row; it never edits an item body. The ledger order is a valid topological sort of the depends-on graph.

## Items

### B01 - {title}

- **Depends on:** {item-ids | none}
- **Effort:** {S | M | L, roughly 0.5-1.5 day}  **Impact:** {high | med | low}
- **PRD reference:** {the acceptance scenarios / sections this item delivers}
- **Seam:** {which layer or extension point this plugs into; what must stay unchanged}
- **Files:** {paths this item creates or edits}
- **Acceptance (Given / When / Then):** the typed scenarios and edge cases this item must pass, both sides of every boundary.
- **Needs human:** {any step only a human can do - signups, content, review - or "none"}

### B02 - {title}

(repeat the item shape above)

## Appendix A - Ground-truth verdicts

Every PRD dependency claim verified against live code / infra. VERIFIED or UNVERIFIED (with what would verify it).

- {claim}: {VERIFIED | UNVERIFIED} - {evidence, or the gap and what would close it}.

## Appendix B - PRD-vs-reality contradictions

Where the PRD disagrees with live code / infra. Surfaced to the owner before implementing the affected item.

- {contradiction}: {detail} - affects {item-id}.
