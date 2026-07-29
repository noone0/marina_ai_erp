# Marina AI ERP

AI-supported marina management with visual recognition. Detects, identifies, and tracks vessels from marina cameras — entry/exit counting, vessel identification, berth occupancy, queue monitoring, and automatic video archiving.

> **Status: planning.** This repository currently contains the architecture, technical specification, phase plans, and PoC definition. No implementation yet.

## Capabilities (planned)

| # | Capability | Phase |
|---|---|---|
| 1 | Count boats entering the marina | 1 |
| 2 | Identify which boat entered (name, flag, registration) | 2a |
| 3 | Track which boat parked in which berth | 3 |
| 4 | Waiting queue at the marina mouth / bay | 4 |
| 5 | Automatic video recording of berths | 5 |
| 6 | Log name, flag, serial number, entry time | 2a |

Boats that cannot be identified from camera are **not** left as unknowns — they receive a provisional identity (`T-0142`) and are tracked, berthed, and logged exactly like named vessels. The system keeps re-attempting identification from berth cameras, and when a name finally resolves, the full history follows it.

## Documentation

| Document | Purpose |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | What the system is and why it's built this way |
| [`docs/TECHNICAL.md`](docs/TECHNICAL.md) | Module layout, data contracts, algorithms, thresholds |
| [`docs/TECH-STACK.md`](docs/TECH-STACK.md) | Technology decision records — what was chosen, what was rejected, and why |
| [`docs/POC.md`](docs/POC.md) | The go/no-go experiment: can we read boat names from video? |
| [`docs/phases/`](docs/phases/) | Phase-by-phase execution plan |

**Start with the PoC.** Identification is the one genuinely risky capability — everything else is well-understood computer vision. The PoC exists to produce a measured answer before the rest is built on top of it.

## Stack

Python 3.12 · YOLO11 + ByteTrack · DINOv2 + pgvector · Claude (`claude-opus-5`) for vision identification · FastAPI · PostgreSQL + TimescaleDB · Redis Streams · MinIO · React + TypeScript

## Design principles

- **Every boat has an identity from first sighting** — real or provisional, never null.
- **A wrong merge is worse than a duplicate.** The identity matcher is deliberately conservative; ambiguity creates a new record or an operator suggestion, never a silent merge.
- **A wrong name is worse than no name.** The model is instructed that returning null is correct behaviour; confident false names fail CI.
- **Recording never depends on inference.** A detector crash must not stop the cameras recording.
- **Silent failure is the enemy.** Dropped frames, count drift, and merge reverts are all metrics with alerts, because counting systems degrade invisibly.

## Legal

Continuous video of a public-facing area is personal-data processing under KVKK/GDPR. Signage, documented retention with automatic deletion, access logging, and a data-processing record are required before go-live. See [`docs/ARCHITECTURE.md §8`](docs/ARCHITECTURE.md) and [Phase 6](docs/phases/PHASE-6-hardening.md).
