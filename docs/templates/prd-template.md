# PRD: {Feature}

Status: DRAFT -> DEFINED -> SHIPPED. (DRAFT while polling, DEFINED once acceptance is locked, SHIPPED once `reconcile` confirms the body matches the live product.) Behavior only. Do not prescribe class names or implementation steps; the implementer owns architecture.

## Why
One or two lines: the user problem and why it matters now.

## User experience (the loop)
What the user sees and does, start to finish. The happy path in plain language.

## Inputs & outputs (the contract)
What goes in and what comes out — data shapes and states, not internal types.
- Inputs: {what the caller/user provides, and the valid range/shape}.
- Outputs: {what they get back — shape, the set of result states, error/empty signals}.

## Acceptance (Given / When / Then)
**Happy path**
- Given {context}, When {action}, Then {observable outcome}.

**Edge cases & failure modes**
Enumerate explicitly — this is where gaps hide. Cover both sides of every boundary, empty/missing/duplicate inputs, and each failure/degradation path.
- Given {boundary / empty / missing / invalid}, When {action}, Then {safe, observable outcome}.

## Quality bar
Concrete, checkable bars (performance, accessibility, error handling, empty/loading states).

## Out of scope
What this feature explicitly does not do.

**Invariants** — existing behaviors/contracts that must NOT change (the behavioral guardrail the implementer must preserve).

## Done looks like
One sentence describing the shippable result.

## Scope changes (living log)
A PRD is a living doc, not a contract written once. When the build diverges from this spec, record it here instead of silently editing the body, then update the body to match. The honest trail is the point: a too-perfect PRD reads as fabricated.
- {date}: {what changed} - {dropped | promoted target->real | added | deferred} - {one-line why}.

Move `Status` to SHIPPED once `reconcile` confirms the body matches the live product.
