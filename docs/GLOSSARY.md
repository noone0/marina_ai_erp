# Marina AI — Glossary

Marine, technical, and system terms used across this documentation, with Turkish equivalents.

---

## 1. Marine terms

| English | Türkçe | Meaning |
|---|---|---|
| **Berth** | Bağlama yeri / palamar yeri | A single mooring position for one vessel |
| **Pontoon** | İskele / ponton | Floating walkway with berths along it |
| **Marina mouth / entrance** | Marina ağzı / giriş kanalı | The navigable channel into the marina |
| **Transom** | Kıç aynalık | The flat rear face of the hull — **where the boat's name usually is** |
| **Bow** | Baş / pruva | Front of the vessel |
| **Stern** | Kıç | Rear of the vessel |
| **Hull** | Tekne gövdesi | The main body of the vessel |
| **Superstructure** | Üst yapı | Cabin/deckhouse above the hull |
| **LOA** (length overall) | Tam boy | Total length — the key sizing dimension for berth allocation |
| **Beam** | Genişlik / en | Maximum width |
| **Draft** | Su çekimi | Depth below waterline |
| **Ensign** | Bayrak / sancak | The national flag flown from the stern — **the flag we read** |
| **Port of registry** | Bağlama limanı | Home port, often on the transom under the name. **Not the flag.** |
| **Fender** | Usturmaça | Protective bumper between hull and pontoon (~0.4–0.8 m, useful for size estimation) |
| **Mooring** | Palamar | Securing a vessel to a berth |
| **RIB** | Şişme bot / RIB | Rigid inflatable boat |
| **Tender** | Servis botu | Small boat serving a larger yacht |
| **Flybridge** | Fly / üst kumanda | Upper steering position on a motor yacht |
| **Radar arch** | Radar kemeri | Structural arch aft carrying antennas — **a strong re-ID feature** |
| **Davit** | Matafora | Crane arm for lifting a tender |
| **Bimini** | Bimini / tente | Canvas sun cover over the cockpit |
| **Anchorage** | Demirleme sahası | Area outside the marina where vessels wait at anchor |
| **Knot** | Knot / deniz mili/saat | 1 knot ≈ 0.514 m/s. Harbour speeds are typically 3–5 knots. |
| **Sail number** | Yelken numarası | Registration on a mainsail, e.g. `TUR 5521` |
| **MMSI** | MMSI | 9-digit Maritime Mobile Service Identity. Manual entry only — no AIS ([ADR-007](./TECH-STACK.md#adr-007--no-ais-receiver)) |
| **AIS** | AIS | Automatic Identification System. **Deliberately excluded from this system.** |

---

## 2. System concepts

| Term | Meaning |
|---|---|
| **Track** | One vessel followed across consecutive frames by the tracker. Has a `track_ref` like `cam3-1721`. Lives only while the boat is in view. |
| **Track ID switch** | The tracker loses a boat and re-assigns a new ID. **Each switch is a phantom extra boat in the count** — the reason `track_buffer` is tuned long. |
| **Transit** | A confirmed gate crossing — a boat entering or leaving. One durable row per crossing. |
| **Gate line** | A directed line drawn on a camera image; crossing it in a direction produces a transit. |
| **Hysteresis** | Requiring a change to persist before acting on it. Used at the gate (minimum displacement) and for berths (dwell thresholds) to stop flapping. |
| **Best shot** | The highest-quality crop of a track, chosen by `quality_score`. **Decides what the API sees — the main cost and accuracy lever.** |
| **Provisional identity** | A vessel record with a temporary code (`T-0142`) instead of a name. **Fully functional**: berths, counts, logs, and reports treat it exactly like a named vessel. |
| **Candidate** | A vessel with a proposed name awaiting operator confirmation. |
| **Confirmed** | A vessel whose name is established, by high-confidence reading or operator confirmation. |
| **Merge** | Unifying two vessel records that are the same physical boat. The source becomes `status='merged'` and points at the survivor; history follows. Reversible. |
| **Re-ID (re-identification)** | Recognising that a boat seen now is one seen before, from appearance. **Load-bearing** because there is no AIS. |
| **Follow-up loop** | Repeated identification attempts on provisional vessels from berth cameras until named or budget-exhausted. **Where most identifications actually happen.** |
| **Attempt budget** | Cap (default 8) on identification attempts per vessel, so an unreadable boat cannot consume unbounded API calls. |
| **Review queue** | Operator work list: low-confidence identifications and merge suggestions. |
| **Back-propagation** | Applying a resolved name across a track's entire history, so a boat shows its name from first appearance rather than from the moment it was read. |
| **Occupancy state machine** | The dwell-based logic deciding a berth is occupied or empty, resistant to boats manoeuvring through a neighbour's polygon. |
| **Dwell** | Time a vessel remains inside a zone. Distinguishes a waiting boat from one passing through. |
| **Reconciliation** | Nightly check that `in − out` matches active occupancy. **Catches silent counting drift.** |
| **τ (tau)** | Confidence threshold above which an identification is auto-accepted. Calibrated against labelled data, not chosen. |
| **PPM (pixels per metre)** | Resolution at the target. ~50 to track a boat, **~250–400 to read its name.** The number that decides camera siting. |
| **Golden set** | Labelled crops with known correct answers, including deliberately illegible ones. The regression gate for prompt changes. |
| **Legal hold** | Flag exempting a recording from retention deletion, for disputes or investigations. |

---

## 3. Stack terms

| Term | Meaning |
|---|---|
| **YOLO** | Real-time object detector. Finds boats in frames. See [ADR-004](./TECH-STACK.md#adr-004--object-detection-model) — licensing is an open item. |
| **ByteTrack** | Multi-object tracker associating detections across frames into tracks. MIT licensed. |
| **DINOv2** | Self-supervised vision model producing embeddings used for re-ID. |
| **Embedding** | A 768-dim vector representing a crop's appearance. Similar boats give similar vectors. |
| **pgvector** | Postgres extension for storing and searching vectors. |
| **HNSW** | Approximate nearest-neighbour index used for fast embedding search. |
| **TimescaleDB** | Postgres extension for time-series data (`queue_samples`). |
| **Hypertable** | A TimescaleDB table auto-partitioned by time. |
| **Redis Streams** | Append-only log used as the event bus, with consumer groups and replay. |
| **Consumer group** | Redis mechanism letting several workers share a stream without duplicating work. |
| **Idempotency** | Handling a redelivered event without duplicating its effect. Enforced via `processed_events`. |
| **ULID** | Sortable unique identifier used as `event_id`. |
| **RTSP** | Real Time Streaming Protocol — how IP cameras deliver video. |
| **ONVIF** | Interoperability standard for IP cameras. |
| **PoE** | Power over Ethernet — one cable for power and data. |
| **fMP4 / HLS** | Fragmented MP4 and HTTP Live Streaming — segmented recording and browser playback. |
| **WDR** | Wide Dynamic Range — camera feature for high-contrast scenes. Helps with backlight, **cannot recover clipped highlights.** |
| **Prompt caching** | Reusing a cached system prompt prefix at ~0.1× cost. Breaks if any per-request value enters the prefix. |
| **Structured outputs** | Constraining the model's response to a schema, so parsing cannot fail. |
| **Effort** | Parameter controlling reasoning depth and token spend. Primary cost/accuracy dial. |

---

## 4. Compliance terms

| Term | Türkçe | Meaning |
|---|---|---|
| **KVKK** | Kişisel Verilerin Korunması Kanunu | Turkish personal data protection law, No. 6698 |
| **Data controller** | Veri sorumlusu | Decides purposes and means — the marina operator |
| **Data processor** | Veri işleyen | Processes on the controller's behalf — the software vendor |
| **Privacy notice** | Aydınlatma metni | Required disclosure to data subjects |
| **Legitimate interest** | Meşru menfaat | Likely lawful basis (KVKK Art. 5/2-f) |
| **Balancing test** | Meşru menfaat dengeleme testi | Documented assessment that the interest does not override rights |
| **VERBİS** | VERBİS | Turkish controllers' registry |
| **DPIA** | Veri koruma etki değerlendirmesi | Data Protection Impact Assessment |
| **Retention policy** | Saklama ve imha politikası | Documented retention and destruction rules |
| **Data subject rights** | İlgili kişi hakları | Access, rectification, erasure (KVKK Art. 11) |
| **Third-country transfer** | Yurt dışına veri aktarımı | Sending data abroad — relevant to the Anthropic API ([`COMPLIANCE-KVKK.md §6`](./COMPLIANCE-KVKK.md)) |

---

## 5. Naming conventions

| Pattern | Example | Meaning |
|---|---|---|
| `T-NNNN` | `T-0142` | Provisional vessel code. Sequential, marina-scoped, **never reused** — an old radio note must always resolve. |
| `cam{id}-{n}` | `cam3-1721` | Track reference: camera 3, track 1721 |
| Berth code | `D-14` | Pontoon D, position 14 |
| Display name (named) | `SERENITY (was T-0142)` | Name plus provisional code, retained permanently for traceability |
| Display name (provisional) | `T-0187 · white · motor yacht · ~9 m` | Code plus attributes, so staff can find the boat visually |
