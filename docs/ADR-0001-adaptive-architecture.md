# ADR-0001: Adaptive architecture — strangler-fig increments behind a live key, not a redesign

**Status:** Accepted
**Date:** 2026-09-06
**Decided in:** FIX_BACKLOG Part 5 (P6 review session)
**Supersedes:** nothing; this is the first ADR

## Context

The 2026-09-06 code review (FIX_BACKLOG Part 5) identified an "adaptive gap":
the agent's behaviour is governed by deterministic, hand-set constants —
`reuse_min_sources=2`, `reuse_min_score=0.0`, `min_evidence=1`,
`max_subqueries=4`, `search_limit=5`, `evidence_limit=8`, the corroboration
gates in `analyst._needs_corroboration`, and the tolerance floors in
`verification.py` (`MATCH_TOLERANCE=0.01`, `CONFLICT_TOLERANCE=0.05`,
`TOPICALITY_FLOOR=0.20`). A prior review proposed replacing this
configuration-driven architecture with a four-layer adaptive design
(Understanding, Governance, Execution, Learning) — policy extraction, shadow
mode, effectiveness telemetry, dynamic tool discovery, a learning layer.

Four measured facts in this repository decide against building that now:

1. **There is no learning signal offline.** The offline model is extractive
   and provably prompt-invariant: P3-3 ran the full suite twice with an
   audit-threat system prompt and got byte-identical answers, 8/8, in both
   modes. A policy chosen by a learning layer differs from a hardcoded one
   only when behaviour varies, and offline, behaviour cannot vary.
2. **Retrieval feedback is noise.** The default embedding is a two-dimensional
   hash (WRITEUP §6, weakness 6). Any layer that "learns" retrieval strategy
   offline would fit noise.
3. **The brief grades demonstrated behaviour in run logs**, and Part 1 of the
   backlog records the project's cardinal failure: four features committed,
   described as working, and unverifiable. A learning layer built without
   data would be that failure shape by construction — unfalsifiable offline.
4. **No live keys.** Every genuinely adaptive behaviour needs real model,
   embedding and search traffic, which P2's live mode, P3-2's authority
   signals and P3-3's real experiment already wait on.

## Decision

Strangler-fig, not redesign. The adaptive architecture is adopted as a
direction and decomposed into three gated increments. Nothing is built ahead
of the gate that makes it demonstrable.

**Increment 1 — policy extraction (gated on: nothing; behaviour-preserving,
doable offline).** Lift the hardcoded constants into one typed `Policies`
object passed through the agents, so a policy is data rather than scattered
literals. Pure refactor: all 329 tests must stay green, suite artifacts must
regenerate byte-identical in searches/fetches/verdicts. Tracked as backlog
P7-1.

**Increment 2 — shadow mode (gated on: increment 1). DONE 2026-09-06.** Run a candidate policy
alongside the live one and log both outcomes as trace events, changing no
behaviour. Implemented at the reuse decision — the one behaviour increment 3
would select on: `AnalystAgent(shadow_policies=...)` re-classifies the same
probe results under the shadow policy and traces `reuse_shadow_evaluated`
(live vs shadow skipped-queries, covered entities, a `divergent` flag; emitted
even on agreement so a live run can measure agreement rates, not just
divergences). No extra retrievals, no metric moves. Stated limits: the shadow
decision reuses probes fetched under the live `evidence_limit`, so a shadow
policy changing that knob is approximated; the shadow covers the reuse
decision only — the corroboration gates have no policy knobs to compare. The
plumbing is proven offline (`tests/unit/test_analyst.py`: no behaviour change,
divergence traced, agreement traced, validator allowlist in sync); comparison
is meaningful only where inputs vary — i.e. live.

**Increment 3 — policy selection from effectiveness (gated on: live key).**
Only once real runs produce real feedback: measure candidate policies on
trace-derived effectiveness (claims supported, corroboration accept rate,
cost per supported claim) and select per run. A learning layer, multi-armed
bandit or otherwise, is out of scope until this increment has data to learn
from. Dynamic tool discovery is out of scope outright: the tool surface is
five methods, and a discovery layer over five fixed tools is indirection.

## Alternatives considered

**Full four-layer redesign now.** Rejected. Every layer after Governance
produces nothing gradeable offline (facts 1–3), and it would replumb a
pipeline whose graded behaviours — budgets, audit feedback, corroboration,
trace completeness — were each individually won and tested. The redesign
risks trading demonstrated behaviour for architecture.

**Do nothing; keep constants.** Rejected, but narrowly. The P6 session
already fixed the review items that were defects (budget enforcement, lexical
channel, retry coverage). What remains is real but not a defect: the
constants work and are tested. Policy extraction is cheap insurance against
them accreting further.

## Consequences

- Positive: every threshold becomes a visible, single-sourced decision point;
  future policy work has a seam to plug into without touching agent logic.
- Positive: the adaptive ambition is recorded with gates instead of either
  silently dropped or built unfalsifiably — the same treatment P3-2 got.
- Negative: a `Policies` object threaded through three agents is a real
  constructor-surface change (the review already flagged `AnalystAgent`'s
  seven dependencies); increment 1 should not worsen that without also
  introducing a builder.
- Negative: until the live key exists, increments 2–3 are scaffolding. The
  write-up must not present them as adaptive behaviour — they are the
  capability to become adaptive.
