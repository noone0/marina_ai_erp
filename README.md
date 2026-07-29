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

### Design & planning
| Document | Purpose |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | What the system is and why it's built this way |
| [`docs/TECH-STACK.md`](docs/TECH-STACK.md) | Technology decision records — what was chosen, what was rejected, and why |
| [`docs/POC.md`](docs/POC.md) | The go/no-go experiment: can we read boat names from video? |
| [`docs/phases/`](docs/phases/) | Phase-by-phase execution plan |

### Implementation reference
| Document | Purpose |
|---|---|
| [`docs/TECHNICAL.md`](docs/TECHNICAL.md) | Module layout, event contracts, algorithms, thresholds |
| [`docs/DATA-MODEL.md`](docs/DATA-MODEL.md) | Complete schema: DDL, constraints, indexes, retention |
| [`docs/API.md`](docs/API.md) | REST + WebSocket contract |
| [`docs/PROMPTS.md`](docs/PROMPTS.md) | Identification and comparison prompts, calibration, regression gates |

### Deployment & operations
| Document | Purpose |
|---|---|
| [`docs/CAMERA-SITING.md`](docs/CAMERA-SITING.md) | Camera placement, optics arithmetic, commissioning checklist |
| [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | Dev setup, deployment, monitoring, runbook, backup/restore |
| [`docs/COMPLIANCE-KVKK.md`](docs/COMPLIANCE-KVKK.md) | Data protection requirements and controls |
| [`docs/GLOSSARY.md`](docs/GLOSSARY.md) | Marine, technical, and system terms (EN/TR) |

**Start with the PoC.** Identification is the one genuinely risky capability — everything else is well-understood computer vision. The PoC exists to produce a measured answer before the rest is built on top of it.

**Read `CAMERA-SITING.md` before ordering hardware.** With AIS excluded, every piece of vessel identity comes from pixels. If a transom crosses the frame at 40 px wide, the name is not in the image and no amount of software recovers it.

## Stack

Python 3.12 · YOLO11 + ByteTrack · DINOv2 + pgvector · Claude (`claude-opus-5`) for vision identification · FastAPI · PostgreSQL + TimescaleDB · Redis Streams · MinIO · React + TypeScript

## Design principles

- **Every boat has an identity from first sighting** — real or provisional, never null.
- **A wrong merge is worse than a duplicate.** The identity matcher is deliberately conservative; ambiguity creates a new record or an operator suggestion, never a silent merge.
- **A wrong name is worse than no name.** The model is instructed that returning null is correct behaviour; confident false names fail CI.
- **Recording never depends on inference.** A detector crash must not stop the cameras recording.
- **Silent failure is the enemy.** Dropped frames, count drift, and merge reverts are all metrics with alerts, because counting systems degrade invisibly.

## Open items

Two decisions are outstanding and both have consequences beyond engineering:

| Item | Why it matters | Deadline |
|---|---|---|
| **Detector licensing** ([ADR-004](docs/TECH-STACK.md#adr-004--object-detection-model)) | Ultralytics YOLO11 is AGPL-3.0, whose network clause is triggered by a hosted dashboard. Either buy the Enterprise License or switch to a permissive detector (RF-DETR, D-FINE). | Before Phase 1 — fine-tuning is model-specific, so a late swap is expensive |
| **Third-country transfer** ([COMPLIANCE §6](docs/COMPLIANCE-KVKK.md)) | Vessel crops sent to the Anthropic API constitute a transfer abroad under KVKK Art. 9 and need a documented basis. | Before Phase 2a — if it can't be justified, the identification architecture changes |

## Legal

Continuous video of a public-facing area is personal-data processing under KVKK (Law No. 6698) and GDPR. Signage, a documented lawful basis, retention with automatic deletion, access logging, and possibly VERBİS registration are required before go-live. Start the legal review during Phase 5, not Phase 6 — see [`docs/COMPLIANCE-KVKK.md`](docs/COMPLIANCE-KVKK.md).

Nothing in this repository is legal advice.
