# Phases — index

Execution plan for Marina AI. Each phase ends with something demonstrable and independently useful — no phase exists purely to enable a later one.

Read first: [`../ARCHITECTURE.md`](../ARCHITECTURE.md) (what & why) · [`../TECHNICAL.md`](../TECHNICAL.md) (how) · [`../POC.md`](../POC.md) (the go/no-go experiment that precedes all of this).

## Order and dependencies

```
   PoC  ──►  Phase 0  ──►  Phase 1  ──►  Phase 2a  ──►  Phase 2b
 (risk)     (foundation)   (count)     (identify)     (re-ID +
                              │                        follow-up)
                              ├──────►  Phase 3  (berths)
                              ├──────►  Phase 4  (queue)
                              └──────►  Phase 5  (recording)
                                             │
                                        Phase 6  (hardening)
```

Phases 3, 4 and 5 depend only on Phase 1 and can run in parallel or be reordered by priority. Phase 3 becomes materially more useful after 2a (a berth showing `SERENITY` beats one showing `track-1721`), but it does not block on it.

| Phase | Title | Delivers | Est. |
|---|---|---|---|
| [PoC](../POC.md) | Identify & track | go/no-go on name reading | ~8 d |
| [0](./PHASE-0-foundations.md) | Foundations | runnable skeleton, schema, CI | ~1 wk |
| [1](./PHASE-1-detect-count.md) | Detect & count | requirement #1 | ~2 wk |
| [2a](./PHASE-2A-identify.md) | Identify + provisional identity | requirements #2, #6 | ~2 wk |
| [2b](./PHASE-2B-reid-followup.md) | Re-ID + follow-up | vessel history over time | ~2–3 wk |
| [3](./PHASE-3-berths.md) | Berth occupancy | requirement #3 | ~2 wk |
| [4](./PHASE-4-queue.md) | Queue analytics | requirement #4 | ~1 wk |
| [5](./PHASE-5-recording.md) | Video archive | requirement #5 | ~2 wk |
| [6](./PHASE-6-hardening.md) | Production hardening | go-live readiness | ~2–3 wk |

Estimates assume one developer and exclude camera installation and the site survey, which are on the critical path for Phase 2a quality.

## Requirement traceability

| Requirement | Phase |
|---|---|
| Count boats entering the marina | 1 |
| Which boat entered (name, flag, serial) | 2a |
| Which boat parked in which area | 3 |
| Queue at the mouth / bay | 4 |
| Auto-record parking slot video | 5 |
| Log name, flag, serial, entry time | 2a (+1 for time) |
| *Unify unidentified boats under a temp name* | 2a |
| *Follow up until identified, and track after* | 2b |

## Phase document template

Each phase doc carries: **Goal · In scope · Out of scope · Deliverables · Tasks · Acceptance criteria · Dependencies · Risks**. Acceptance criteria are written to be checkable by someone who did not build the phase.
