# Marina AI — Tech Stack Decisions

Architecture Decision Records for the technology choices in this system. Each record states the decision, the context that forced it, what else was considered, the consequences we accept, and the conditions under which it should be revisited.

Status: **decided (pre-implementation)** · Date: 2026-07-29
Related: [`ARCHITECTURE.md`](./ARCHITECTURE.md) · [`TECHNICAL.md`](./TECHNICAL.md)

> **⚠️ Open item before implementation: [ADR-004](#adr-004--object-detection-model) (detector licensing).** It is the one decision here with commercial and legal consequences rather than purely technical ones, and it should be settled before Phase 1.

---

## Index

| ADR | Decision | Status |
|---|---|---|
| [001](#adr-001--primary-language-python-312) | Python 3.12 as primary language | Decided |
| [002](#adr-002--monorepo-with-uv-workspaces) | Monorepo with `uv` workspaces | Decided |
| [003](#adr-003--edge-first-deployment) | Edge-first deployment (on-prem GPU box) | Decided |
| [004](#adr-004--object-detection-model) | Object detection model | **Needs decision** |
| [005](#adr-005--multi-object-tracking) | ByteTrack for tracking | Decided |
| [006](#adr-006--hybrid-local-detection--cloud-identification) | Hybrid: local detection + Claude identification | Decided |
| [007](#adr-007--no-ais-receiver) | No AIS receiver — camera only | Decided (by owner) |
| [008](#adr-008--claude-model-and-invocation-pattern) | `claude-opus-5`, structured outputs, prompt caching | Decided |
| [009](#adr-009--re-identification-embeddings) | DINOv2 for re-ID embeddings | Decided |
| [010](#adr-010--postgresql-as-the-single-datastore) | PostgreSQL + TimescaleDB + pgvector | Decided |
| [011](#adr-011--redis-streams-as-the-event-bus) | Redis Streams as event bus | Decided |
| [012](#adr-012--s3-compatible-object-storage) | MinIO / S3-compatible object storage | Decided |
| [013](#adr-013--video-io-pyav-for-decode-ffmpeg-for-record) | PyAV decode, FFmpeg record | Decided |
| [014](#adr-014--fastapi-for-the-api-layer) | FastAPI | Decided |
| [015](#adr-015--sqlalchemy-20--alembic) | SQLAlchemy 2.0 + Alembic | Decided |
| [016](#adr-016--react--typescript--vite-spa) | React + TypeScript + Vite | Decided |
| [017](#adr-017--docker-compose-not-kubernetes) | Docker Compose, not Kubernetes | Decided |
| [018](#adr-018--in-process-scheduling-before-a-task-queue) | APScheduler before Celery | Decided |
| [019](#adr-019--observability-stack) | structlog + Prometheus + OpenTelemetry | Decided |
| [020](#adr-020--configuration-in-database-not-files) | Camera/zone config in DB, not files | Decided |

---

## ADR-001 — Primary language: Python 3.12

**Decision.** Python 3.12 for ingest, vision, identity, and API. TypeScript only in the browser.

**Context.** The entire computer-vision and ML ecosystem this system depends on — Ultralytics, PyTorch, DINOv2, OpenCV, PyAV, Shapely — is Python-first. The Anthropic SDK is first-class in Python. Splitting vision (Python) from API (Node/Go) would mean two runtimes, two dependency stories, duplicated domain models, and a serialisation boundary in the middle of the identity logic, which is the most intricate part of the system.

**Alternatives considered.**
- *Go or Rust for services, Python only for inference* — better runtime performance and lower memory, but the boundary lands exactly where the complexity is (identity resolution touches both DB and ML). Rejected: the cost is in coordination, not CPU.
- *Node/TypeScript throughout with a Python inference sidecar* — one language with the frontend, but pushes every vision dependency into a sidecar with an RPC hop per frame.

**Consequences.** Accept the GIL and higher memory per process. Mitigated by the process model in [`TECHNICAL.md §3`](./TECHNICAL.md#3-process-model): one process per camera, inference isolated to its own process. CPU-bound hot loops (quality scoring) use NumPy/OpenCV, which release the GIL.

**Revisit if.** A single box needs to exceed ~32 cameras and profiling shows Python overhead — not inference — is the ceiling.

---

## ADR-002 — Monorepo with `uv` workspaces

**Decision.** Single repository. `packages/` for importable libraries, `services/` for process entrypoints, `web/` for the frontend, managed by `uv` workspaces.

**Context.** Vision, identity, and API share domain models, event schemas, and config. Splitting them into separate repos with version pinning would mean a schema change becomes a multi-repo, multi-PR release dance for a one-developer team.

**Alternatives considered.** *Polyrepo with a published shared package* — appropriate at larger team sizes; pure overhead here. *Single flat package* — simpler still, but loses the enforced boundary that keeps side-effectful code out of libraries.

**Consequences.** One CI pipeline, atomic cross-cutting changes. The `packages/` vs `services/` split is enforced by a rule rather than tooling: nothing in `packages/` may open a socket or file handle at import time.

**Revisit if.** The team grows past ~4 developers, or a package genuinely needs independent release cadence.

---

## ADR-003 — Edge-first deployment

**Decision.** Inference and recording run on an on-prem GPU box at the marina. Only the API and identification calls egress.

**Context.** 16 cameras at 4 Mbps is ~64 Mbps sustained upstream. Sending raw video to the cloud is expensive, fragile on a marina's connectivity, and adds latency to a live dashboard. Video also stays on-premises, which materially simplifies the KVKK position.

**Alternatives considered.**
- *Full cloud with cloud-side inference* — simpler ops, but the bandwidth cost and dependency on an uplink that goes down in a storm are disqualifying for a system whose recording obligation is continuous.
- *Cloud inference on sampled frames only* — cheaper bandwidth, but berth occupancy and queue dwell need continuous tracking, not samples.

**Consequences.** A physical box per site to provision, monitor, and eventually replace. Single point of failure with no redundancy — [Phase 6](./phases/PHASE-6-hardening.md) requires this to be documented and an RTO agreed rather than pretended away. The Redis Streams boundary keeps a future central deployment possible without redesign.

**Revisit if.** Multi-marina scale makes per-site hardware ops the dominant cost, or marina uplinks become reliably fast.

---

## ADR-004 — Object detection model

> **⚠️ This decision is open and has commercial consequences. It should be settled before Phase 1.**

**Proposed decision.** YOLO11 via Ultralytics for the PoC and initial development, with the detector isolated behind `vision/detector.py` so it can be swapped without touching anything downstream.

**Context.** We need a fast, accurate detector for a single class (`boat`) at ~6 fps across 16 streams. Ultralytics YOLO11 is the strongest option on developer ergonomics: pretrained COCO weights include `boat`, tracking is bundled, batching and export are one-liners, and the documentation is excellent. For a PoC that must answer a question in eight days, that matters.

**The licensing problem.** Ultralytics is **AGPL-3.0**, with a paid Enterprise License as the alternative. AGPL's network clause is triggered by providing the software as a network service — which is exactly what a hosted marina dashboard is. For a commercial product this plausibly means either:

1. **Buy the Ultralytics Enterprise License** — clean, predictable, costs money annually; or
2. **Use a permissively-licensed detector** — no fee, somewhat more integration work.

Permissive alternatives worth evaluating:

| Model | License | Notes |
|---|---|---|
| **RF-DETR** (Roboflow) | Apache 2.0 | Modern DETR variant, strong accuracy, actively maintained |
| **D-FINE** | Apache 2.0 | Competitive real-time detection |
| **YOLOX** | Apache 2.0 | Mature, well-understood, weaker than current YOLO generations |
| **torchvision** (Faster R-CNN, RetinaNet) | BSD | Permissive and stable, but slower — likely too slow at 16×6 fps |
| **MMDetection** model zoo | Apache 2.0 | Broad choice, heavier framework |

Note that **ByteTrack itself is MIT** ([ADR-005](#adr-005--multi-object-tracking)) — it is only the Ultralytics *bundling* that carries AGPL. A permissive detector can be paired with an independent ByteTrack implementation.

**Recommendation.** Use Ultralytics for the PoC — the licence permits internal evaluation, and the PoC's purpose is to answer a question, not to ship. **Before Phase 1 begins**, decide between buying the Enterprise License and switching to RF-DETR or D-FINE. Deferring this past Phase 1 means the swap lands after fine-tuning work has been done against one model's tooling, which is the expensive moment to change.

I am flagging the risk, not giving legal advice — the AGPL network-service question should go to whoever handles the company's licensing.

**Consequences either way.** `detector.py` exposes a narrow interface (`detect(frames) -> list[Detection]`), so the swap is contained. Fine-tuning work is model-specific and is the part that gets thrown away if the decision changes late — which is the argument for deciding early.

**Revisit if.** Accuracy on small craft (RIBs, tenders) proves inadequate and fine-tuning is needed regardless — that changes the cost balance between the options.

---

## ADR-005 — Multi-object tracking: ByteTrack

**Decision.** ByteTrack, with `track_buffer` tuned to ~15 seconds.

**Context.** Tracking quality directly determines counting accuracy: **every ID switch is a phantom extra boat in the count.** Boats are slow, large, and get occluded by pontoons and other vessels for several seconds at a time. ByteTrack's association of low-confidence detections handles exactly this occlusion pattern, and it is MIT-licensed and dependency-light.

**Alternatives considered.**
- *BoT-SORT* — adds camera-motion compensation and appearance re-ID; better on moving cameras, which we don't have (all cameras are fixed). Kept as the documented fallback if measured ID-switch rate is too high.
- *DeepSORT* — appearance embeddings per frame add GPU cost we'd rather spend on the re-ID system that runs once per sighting.
- *OC-SORT* — strong on non-linear motion; boats move predictably, so the benefit is small.

**Consequences.** Long `track_buffer` trades memory and a small risk of associating two different boats across a long gap, against ID switches. Given the asymmetry — a switch inflates the count, a merge-across-gap does not — the long buffer is the right side to err on.

**Revisit if.** Measured ID switches exceed 1 per 20 boats on labelled footage ([Phase 1](./phases/PHASE-1-detect-count.md) acceptance criterion).

---

## ADR-006 — Hybrid: local detection + Claude identification

**Decision.** Local models run on every frame (detection, tracking, quality scoring). Claude runs once per identification attempt on 1–3 selected crops.

**Context.** Two very different workloads. Detection is high-frequency, low-semantic, latency-sensitive — perfect for a local GPU. Reading a stylised boat name, recognising a national flag, and judging whether two hulls are the same vessel is low-frequency, high-semantic work where a frontier VLM is dramatically better than anything self-hostable.

**Alternatives considered.**
- *Pure local OCR (PaddleOCR / EasyOCR / TrOCR)* — zero API cost and offline-capable, but boat names are a worst case for classical OCR: cursive and decorative fonts, curved transoms, chrome-on-white lettering, arbitrary rotation. Flags are not an OCR problem at all. Would need per-marina fine-tuning to be usable.
- *Claude on every frame* — vastly simpler code, no local GPU, but the per-frame cost is untenable and it cannot do per-frame tracking at all.
- *Cloud vision APIs (Google/AWS text detection)* — good at flat scene text, weak at the semantic parts (flag identification, "are these the same vessel", attribute extraction) that this design leans on.

**Consequences.** Two inference paths to operate. Cost is bounded by the best-shot selector, which is therefore the highest-leverage function in the codebase — it decides what the API sees. The system degrades gracefully: if the API is unreachable, detection, counting, berth occupancy, and recording all continue, and identification backs up in a queue.

**Revisit if.** Per-identification cost exceeds budget at volume, or a local VLM becomes good enough at transom text to justify the operational cost of hosting one.

---

## ADR-007 — No AIS receiver

**Decision.** Identification is camera-only. No AIS receiver. *(Owner decision, 2026-07-29.)*

**Context.** An AIS receiver (~€150 plus antenna) would provide exact MMSI, name, flag, and dimensions for AIS-equipped vessels with no vision involved, and serve as an independent cross-check on vision output. It was proposed and declined.

**Consequences — accepted deliberately.**
- Vision carries 100% of the identification burden with **no independent source to validate against**.
- Camera siting becomes the single largest determinant of system accuracy. The identification camera specification in [`ARCHITECTURE.md §2`](./ARCHITECTURE.md) is now a hard requirement rather than an optimisation.
- Visual re-ID ([ADR-009](#adr-009--re-identification-embeddings)) becomes load-bearing rather than a convenience: appearance is the only signal linking a boat seen today to the same boat seen last week.
- Provisional identities are not a nicety but structural — without AIS, a meaningful fraction of vessels will not be nameable from camera on first pass, and the system must remain fully useful for them.

The `vessels.mmsi` column is retained as a manual-entry field so a future change of mind costs a migration rather than a redesign.

**Revisit if.** Measured identification recall stays below what operators can tolerate after camera siting is optimised — at which point the trade is a €150 device against ongoing manual naming effort.

---

## ADR-008 — Claude model and invocation pattern

**Decision.** `claude-opus-5`, called via `messages.parse()` with a Pydantic schema, `effort: "medium"`, and prompt caching on the system prompt.

**Context.** Identification requires reading degraded text, recognising flags, estimating vessel dimensions, and — in the re-ID adjudication path — fine-grained visual comparison of two similar hulls. This is the hardest reasoning in the system and the place where model capability translates most directly into product value.

**Choices within the decision.**
- **Structured outputs** (`messages.parse` + schema) rather than prompting for JSON and parsing: the response is guaranteed schema-conformant, which removes a whole class of parse-failure handling from a background worker.
- **Prompt caching** on the long, stable system prompt (transom-reading guidance, flag disambiguation, when to return null). Cached reads are ~0.1× input cost. This requires the system prompt to contain **no per-request values** — no timestamps, camera IDs, or attempt numbers — enforced by an integration test asserting `cache_read_input_tokens > 0`.
- **`effort: "medium"`** as a starting point, calibrated in the PoC by sweeping `low`/`medium`/`high` against the labelled set. This is the primary cost/accuracy dial.
- **Null is a valid answer.** The prompt states that returning `null` with low confidence is correct and that inventing a plausible name is a failure. Enforced by regression tests feeding deliberately illegible crops.

**Alternatives considered.** *A smaller/cheaper model* — a legitimate cost lever, but identification accuracy is the entire value proposition of the product, and the call frequency (once per attempt, not per frame) keeps the absolute cost small. Downgrading to save cents while degrading the one capability the system exists to provide is a poor trade; it remains available if measured volume changes the arithmetic.

**Consequences.** External dependency in the identification path — mitigated because every other subsystem continues working without it. Cost tracked live via `identification_tokens_total`.

**Revisit if.** Measured cost per identification exceeds budget, or calibration shows a lower effort level matches quality at materially lower cost.

---

## ADR-009 — Re-identification embeddings: DINOv2

**Decision.** DINOv2 ViT-B/14 (Apache 2.0), 768-dim embeddings, stored and searched in pgvector, behind a swappable `vision/embedding.py` interface.

**Context.** With no AIS ([ADR-007](#adr-007--no-ais-receiver)), appearance is the only mechanism that unifies sightings of the same hull across time. DINOv2's self-supervised features are strong at instance-level retrieval without task-specific training, which matters because we have no labelled boat re-ID dataset at the start.

**Alternatives considered.**
- *CLIP image embeddings* — excellent semantically ("a white motor yacht") but weaker at instance discrimination, which is exactly what re-ID needs. Two different white yachts are semantically identical.
- *Dedicated person/vehicle re-ID networks* — trained on domains with very different appearance statistics; boats have no equivalent public benchmark.
- *Fine-tuned embedding model* — almost certainly better, and the plan is to get there. It requires labelled pairs, which the review queue generates as a by-product. Deferred to post-2b for that reason.

**Consequences.** Generic embeddings will be imperfect on visually similar production boats — many white motor yachts genuinely look alike. This is why the matcher gates on physical attributes first and why the ambiguous band is adjudicated by Claude. **The conservative-merge policy exists precisely because this component is the weakest link in the identity chain.**

**Revisit if.** Measured false-merge rate exceeds 1% ([Phase 2b](./phases/PHASE-2B-reid-followup.md) gate), at which point fine-tuning on accumulated review-queue labels is the next move.

---

## ADR-010 — PostgreSQL as the single datastore

**Decision.** PostgreSQL 16 with the TimescaleDB and pgvector extensions. One database for relational data, time series, and vector search.

**Context.** The system has three data shapes: relational (vessels, berths, transits), time series (`queue_samples` at 30 s resolution), and vectors (re-ID embeddings). Each has a specialist datastore, but adopting three means three operational stories, three backup procedures, and no transactional consistency across them.

That last point is decisive. The merge operation in [`TECHNICAL.md §7.5`](./TECHNICAL.md#75-merge) re-points rows across five tables **and** must stay consistent with embedding ownership. In one Postgres that is a single transaction. Split across Postgres and a vector database, it becomes a distributed-transaction problem with a partial-failure mode that silently corrupts identity data — the exact failure this design is most concerned about.

**Alternatives considered.**
- *Postgres + Qdrant/Milvus* — better vector performance at very large scale. At the volumes here (thousands of vessels, tens of thousands of sightings per marina per year), pgvector with an HNSW index is comfortably sufficient, and the consistency argument dominates.
- *Postgres + InfluxDB* — TimescaleDB is a Postgres extension and covers the need without a second system.
- *MongoDB* — schema flexibility is not the constraint; referential integrity across the identity graph is.

**Consequences.** One system to back up, monitor, and restore. Vector search will need revisiting long before relational load does. The `timescale/timescaledb-ha` image bundles pgvector, avoiding a custom build.

**Revisit if.** Sighting volume reaches millions per marina and pgvector HNSW recall or latency degrades measurably.

---

## ADR-011 — Redis Streams as the event bus

**Decision.** Redis 7 Streams with consumer groups.

**Context.** We need durable at-least-once delivery between ingest, processing, and identification, with replay for debugging, at single-marina volume (a few hundred events per minute). Redis is already needed for ephemeral tracker state, so Streams add no new operational dependency.

**Alternatives considered.**
- *Kafka* — the right answer at high throughput with multiple independent consumer teams. Here it is a JVM, ZooKeeper/KRaft, and partition management for a workload measured in hundreds of events per minute. Rejected as operational cost without benefit.
- *RabbitMQ* — solid, but adds a second infrastructure component for what Redis already covers, and replay is weaker.
- *Postgres `LISTEN`/`NOTIFY`* — no new component at all, but no durability, no consumer groups, and no replay. Tempting and wrong for a pipeline where losing a transit event loses a boat.
- *NATS JetStream* — genuinely good fit; Redis wins only because it is already present.

**Consequences.** Redis becomes a durability-relevant component and must be persisted and backed up, not treated as a disposable cache. At-least-once delivery makes consumer idempotency mandatory — implemented via `processed_events` checked in the same transaction as the domain write ([`TECHNICAL.md §5`](./TECHNICAL.md#5-event-contracts-redis-streams)).

**Revisit if.** Multi-marina central processing pushes throughput or fan-out beyond what a single Redis handles comfortably.

---

## ADR-012 — S3-compatible object storage (MinIO)

**Decision.** MinIO on-premises, S3 API, swappable for AWS S3 / Cloudflare R2 in a cloud deployment.

**Context.** Video dominates storage: roughly 0.5–1 TB per camera-month at 4 Mbps. This does not belong in a database or on a local filesystem that the application manages by hand.

**Alternatives considered.**
- *Local filesystem + NAS* — simplest, but we'd hand-build lifecycle expiry, signed URLs, and versioning, all of which the S3 API provides. Retention correctness is a compliance obligation, not a convenience.
- *Direct-to-cloud storage* — uplink bandwidth makes this untenable for continuous recording ([ADR-003](#adr-003--edge-first-deployment)).

**Consequences.** Lifecycle rules give us automatic retention enforcement, which is a KVKK requirement rather than a nice-to-have. Signed URLs let the API avoid proxying video while still auditing every access. A reconciling sweeper is still needed for objects orphaned by failed writes — lifecycle rules alone don't catch those.

**Revisit if.** A cloud deployment makes managed object storage cheaper than operating MinIO.

---

## ADR-013 — Video I/O: PyAV for decode, FFmpeg for record

**Decision.** PyAV (libav bindings) in the decode hot loop; FFmpeg subprocesses for segmented recording and clip stitching.

**Context.** Decoding runs continuously per camera and needs in-process frame access with control over threading and hardware acceleration. Recording and stitching are fire-and-forget batch operations where a subprocess is the simpler, more robust choice — and crucially, an isolated one.

**Alternatives considered.**
- *OpenCV `VideoCapture` for everything* — easiest, but its RTSP handling is opaque, reconnection behaviour is poor, and error reporting is nearly nonexistent. RTSP reconnection is a core reliability requirement, not an edge case.
- *GStreamer throughout* — more powerful pipeline model and better hardware-acceleration story; significantly steeper learning curve and heavier deployment. Reconsider if hardware decode becomes the bottleneck.
- *FFmpeg subprocess for decode too* — loses in-process frame access, adds a pipe copy per frame.

**Consequences.** Two video libraries in the stack. Justified by the isolation it buys: **the recorder is a separate process from inference, so a detector or GPU crash cannot stop recording** — an explicit acceptance criterion in [Phase 5](./phases/PHASE-5-recording.md).

**Revisit if.** CPU decode saturates before GPU inference does, making GStreamer's hardware pipeline worth the complexity.

---

## ADR-014 — FastAPI for the API layer

**Decision.** FastAPI + uvicorn.

**Context.** Needs async (WebSocket live feeds, concurrent I/O), Pydantic models shared with the event contracts and Claude schemas, and OpenAPI generation for the TypeScript client.

**Alternatives considered.** *Django + DRF* — batteries included, mature admin, but sync-first with a heavier ORM opinion that conflicts with SQLAlchemy 2.0 async. *Flask* — needs assembly for async and validation. *Litestar* — very close on merits; FastAPI wins on ecosystem and familiarity alone.

**Consequences.** Pydantic models are reused across API DTOs, event payloads, and Claude output schemas — one definition, three uses. Auth, RBAC, and admin are hand-built rather than inherited from a framework ([Phase 6](./phases/PHASE-6-hardening.md)).

---

## ADR-015 — SQLAlchemy 2.0 + Alembic

**Decision.** SQLAlchemy 2.0 async ORM with Alembic migrations.

**Context.** The identity model is a genuine graph — vessels merge into vessels, sightings and transits and occupancy all reference vessels, and merges must resolve transitively. This wants relationship mapping and transactional units of work, not hand-written SQL strings.

**Alternatives considered.** *Raw asyncpg* — fastest and most explicit; rejected because the merge/revert logic touching five tables is exactly what an ORM's unit-of-work makes safe. *SQLModel* — pleasant, but a thinner layer over both SQLAlchemy and Pydantic that tends to leak at the edges. *Tortoise ORM* — lighter, weaker migration story.

**Consequences.** ORM overhead on hot read paths; the few queries that matter (re-ID candidate fetch, vector search) drop to explicit SQL, as shown in [`TECHNICAL.md §7.3`](./TECHNICAL.md#73-re-id-matcher). Alembic migrations are required to be backwards-compatible for one release ([Phase 6](./phases/PHASE-6-hardening.md)) so rollback is real.

---

## ADR-016 — React + TypeScript + Vite SPA

**Decision.** React 18, TypeScript, Vite, TanStack Query, Zustand, Tailwind. Client-rendered SPA served as static files.

**Context.** The dashboard is a live operational console — WebSocket-driven video overlays, real-time counters, a zone editor with canvas drawing, and a video player. Almost nothing benefits from server rendering; the content is per-session live data behind authentication.

**Alternatives considered.** *Next.js* — SSR/SEO advantages that are irrelevant for an authenticated internal tool, plus a Node runtime to deploy on the edge box. *Vue / Svelte* — both fine; React chosen for ecosystem depth in the specific components needed (canvas annotation, hls.js integration, virtualised tables).

**Consequences.** A static bundle behind any web server, no Node process in production. TanStack Query handles server state; Zustand covers the small amount of genuine client state (selected camera, editor mode) without Redux ceremony.

---

## ADR-017 — Docker Compose, not Kubernetes

**Decision.** Docker Compose for both development and single-site production.

**Context.** One box per marina, roughly eight long-lived services, no autoscaling, no rolling multi-node deploys. Kubernetes solves problems this deployment does not have while adding a control plane that someone must operate on a machine sitting in a marina office.

**Alternatives considered.** *Kubernetes (k3s)* — reasonable if multi-site orchestration becomes central. *systemd units* — fewer moving parts still, but loses image-based deployment and reproducibility. *Nomad* — simpler than k8s, still more than needed.

**Consequences.** GPU access via `docker-compose.gpu.yml` overlay with the NVIDIA container runtime. No autoscaling, no self-healing beyond restart policies — acceptable for a fixed workload. Multi-site management is a gap that gets addressed when there is a second site.

**Revisit if.** Deployment reaches enough sites that centralised orchestration and fleet upgrades become the dominant operational cost.

---

## ADR-018 — In-process scheduling before a task queue

**Decision.** APScheduler in the `identifier` service for the follow-up loop, with a documented migration path to Celery.

**Context.** The follow-up scheduler ([`TECHNICAL.md §7.4`](./TECHNICAL.md#74-follow-up-scheduler)) is low-volume — a handful of jobs per provisional vessel over days. Redis Streams already handles the high-volume asynchronous work. Adding Celery brings brokers, workers, beat, and monitoring for what is currently a timer.

**Alternatives considered.** *Celery from the start* — avoids a later migration; rejected as premature for the volume. *Temporal* — excellent durable-workflow semantics, far too heavy here. *Postgres-backed job table with polling* — genuinely viable and dependency-free; APScheduler chosen for less bespoke code, with next-attempt time persisted in the DB so schedule state survives restarts either way.

**Consequences.** Scheduler state must be durable in the database, not in process memory — a restart must not lose pending follow-ups. Horizontal scaling of the identifier requires leader election or the Celery migration.

**Revisit if.** Follow-up volume grows enough to need multiple identifier workers.

---

## ADR-019 — Observability stack

**Decision.** structlog for structured logging, Prometheus client for metrics, OpenTelemetry for traces.

**Context.** The characteristic failure mode of this class of system is **silent degradation**: frames dropped, boats miscounted, identities wrongly merged, all without an error anywhere. Metrics are therefore a correctness mechanism, not an ops afterthought.

Three metrics exist specifically to catch silent failure:
- `ingest_frames_dropped_total` — frame loss degrades counting invisibly.
- Nightly count reconciliation drift — counting systems fail quietly.
- `reid_reverts_total` — a rising revert rate is the honest signal that the matcher has drifted, and it must surface without anyone running a query.

**Alternatives considered.** *Cloud APM (Datadog/New Relic)* — better UX, ongoing cost, and an external dependency on a box that may have intermittent connectivity. *Logs only* — insufficient: none of the three failures above produce a log line.

**Consequences.** Prometheus + Grafana run on the edge box. Traces span detection through identification so a slow or failed identification is diagnosable end to end.

---

## ADR-020 — Camera and zone configuration in the database

**Decision.** Cameras, gate lines, berth polygons, and queue areas live in database tables, edited through the UI. Not in config files.

**Context.** Zone geometry is operational data that marina staff adjust — a camera gets bumped, a pontoon is reconfigured, a berth is re-lined. Requiring a file edit and a redeploy for that makes the system depend on a developer for routine work, which is how these systems fall out of use.

**Alternatives considered.** *YAML files in the repo* — version-controlled and reviewable, but every zone tweak becomes a deployment. *Hybrid (files seeded into DB)* — the seed script does this for development without making files authoritative.

**Consequences.** Zone changes take effect without restarting services — an explicit [Phase 3](./phases/PHASE-3-berths.md) acceptance criterion. Coordinates are stored normalised (0–1) so they survive camera resolution changes. Zone edits are audited, since a bad polygon silently breaks occupancy detection and someone will need to know when it changed.

---

## Cross-cutting principles

Recurring reasoning behind several decisions above, recorded so they are applied consistently rather than re-argued:

1. **Prefer one system over three specialists** until measurements justify the split ([010](#adr-010--postgresql-as-the-single-datastore), [011](#adr-011--redis-streams-as-the-event-bus), [017](#adr-017--docker-compose-not-kubernetes)). Operational surface is the scarce resource on a single-developer, single-box deployment.
2. **Isolate the components most likely to change** behind narrow interfaces — detector, embedding model, frame source. Each has a live "revisit if" condition.
3. **Recording and counting must survive inference failure** ([013](#adr-013--video-io-pyav-for-decode-ffmpeg-for-record), [006](#adr-006--hybrid-local-detection--cloud-identification)). Degradation is acceptable; silent total loss is not.
4. **Every threshold is configuration, never a literal** — so calibration against labelled data is a config change rather than a code change and a release.
5. **Asymmetric errors get asymmetric defaults.** A duplicate vessel is cheap; a false merge is expensive. A missing name is honest; a wrong name destroys trust. Defaults lean toward the recoverable failure every time.
