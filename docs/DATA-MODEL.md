# Marina AI — Data Model Reference

Complete schema reference. [`ARCHITECTURE.md §4`](./ARCHITECTURE.md) summarises the model conceptually; this document is the authoritative DDL, constraint, and index reference that Phase 0 implements.

Status: **specification** · Date: 2026-07-29

---

## 1. Entity relationships

```
                    ┌──────────┐
                    │ cameras  │
                    └────┬─────┘
                         │ 1:N
                    ┌────▼─────┐         ┌─────────┐
                    │  zones   │────────▶│ berths  │
                    └────┬─────┘   0:1   └────┬────┘
                         │ 1:N                │ 1:N
                    ┌────▼──────┐             │
                    │ transits  │             │
                    └────┬──────┘             │
                         │ N:1                │
                    ┌────▼──────────┐    ┌────▼──────────────┐
              ┌────▶│   vessels     │◀───│ berth_occupancy   │
              │     └────┬──────────┘    └───────────────────┘
              │          │ 1:N
              │     ┌────▼──────────────┐
              │     │ vessel_sightings  │  (embedding vector)
              │     └───────────────────┘
              │          │ 1:N
              │     ┌────▼──────────────┐
              │     │ identifications   │  (append-only)
              │     └───────────────────┘
              │
              └──── vessel_merges (source → target, reversible)

  Independent:  queue_samples (hypertable) · recordings · users · audit_log
```

**The central invariant:** `vessels` is never empty for an observed boat. Every transit references a vessel; if no name could be read, that vessel is provisional. This is enforced at the database level, not by convention.

---

## 2. Enumerated types

```sql
CREATE TYPE camera_kind    AS ENUM ('gate','identity','berth','bay');
CREATE TYPE zone_kind      AS ENUM ('gate_line','berth','queue_area');
CREATE TYPE transit_dir    AS ENUM ('in','out');
CREATE TYPE vessel_status  AS ENUM ('provisional','candidate','confirmed','merged');
CREATE TYPE ident_source   AS ENUM ('claude','manual','registry_match');
CREATE TYPE ident_trigger  AS ENUM ('gate','followup','operator','rematch');
CREATE TYPE merge_method   AS ENUM ('embedding','claude_compare','operator','name_match');
CREATE TYPE occupancy_src  AS ENUM ('vision','manual');
CREATE TYPE recording_kind AS ENUM ('continuous','event');
CREATE TYPE vessel_type    AS ENUM ('motor_yacht','sailing_yacht','rib','fishing',
                                    'catamaran','tender','other');
CREATE TYPE user_role      AS ENUM ('operator','manager','admin');
```

Native Postgres enums rather than check constraints or lookup tables: these values are closed sets that change only with a code change, and enums give type safety at the DB boundary.

---

## 3. Tables

### 3.1 `cameras`

```sql
CREATE TABLE cameras (
    id              serial PRIMARY KEY,
    name            text NOT NULL UNIQUE,
    kind            camera_kind NOT NULL,
    rtsp_url        text NOT NULL,
    rtsp_username   text,
    rtsp_password   bytea,                    -- encrypted at rest, never returned by API
    resolution_w    int, resolution_h int,
    native_fps      numeric(4,1),
    detect_fps      numeric(4,1) DEFAULT 6.0,
    is_active       boolean NOT NULL DEFAULT true,
    last_seen_at    timestamptz,
    calibration     jsonb DEFAULT '{}'::jsonb, -- lens/undistort params if used
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
```

`rtsp_password` is `bytea` holding an encrypted value, not `text`. It must never appear in an API response, log line, or error payload — a Phase 6 acceptance criterion.

### 3.2 `berths`

```sql
CREATE TABLE berths (
    id           serial PRIMARY KEY,
    code         text NOT NULL UNIQUE,        -- 'D-14'
    pontoon      text,
    max_loa_m    numeric(5,2),
    max_beam_m   numeric(4,2),
    draft_m      numeric(4,2),
    has_power    boolean DEFAULT false,
    has_water    boolean DEFAULT false,
    min_vessel_loa_m numeric(4,2),            -- filters tenders/dinghies out of occupancy
    is_active    boolean NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now()
);
```

### 3.3 `zones`

```sql
CREATE TABLE zones (
    id             serial PRIMARY KEY,
    camera_id      int NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    kind           zone_kind NOT NULL,
    name           text,
    geometry       jsonb NOT NULL,            -- normalised 0-1 coords, see below
    direction_hint jsonb,                     -- gate_line only: {"normal":[x,y]}
    berth_id       int REFERENCES berths(id) ON DELETE SET NULL,
    config         jsonb DEFAULT '{}'::jsonb, -- per-zone threshold overrides
    is_active      boolean NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT berth_zone_has_berth
        CHECK (kind <> 'berth' OR berth_id IS NOT NULL)
);
```

**Geometry is stored normalised (0–1), not in pixels.** A camera resolution change — or a swap to a different model — must not invalidate every polygon an operator drew. Denormalisation to pixels happens at load time.

```json
// gate_line
{"type":"line","points":[[0.12,0.55],[0.88,0.48]]}
// berth / queue_area
{"type":"polygon","points":[[0.2,0.3],[0.5,0.3],[0.5,0.7],[0.2,0.7]]}
```

`config` carries per-zone overrides of the global thresholds (e.g. a berth whose camera angle needs `overlap_enter: 0.5`). Global defaults live in settings; this is the escape hatch for the one berth that doesn't fit them.

### 3.4 `vessels`

The core table.

```sql
CREATE TABLE vessels (
    id                    serial PRIMARY KEY,
    status                vessel_status NOT NULL DEFAULT 'provisional',
    provisional_code      text UNIQUE,        -- 'T-0142', permanent once assigned

    -- identity
    name                  text,
    name_source           ident_source,
    flag_country          char(2),            -- ISO 3166-1 alpha-2
    registration_no       text,
    mmsi                  char(9),            -- manual entry only; no AIS (ADR-007)
    identity_confidence   numeric(4,3) NOT NULL DEFAULT 0.0,

    -- physical attributes (drive display name + re-ID gate)
    vessel_type           vessel_type,
    hull_color            text,
    hull_color_family     text,               -- coarse bucket for the re-ID gate
    superstructure_color  text,
    est_loa_m             numeric(5,2),
    distinctive_marks     text[],

    -- lifecycle
    merged_into_id        int REFERENCES vessels(id) ON DELETE RESTRICT,
    nickname              text,               -- operator label, survives merge as alias
    notes                 text,
    first_seen_at         timestamptz,
    last_seen_at          timestamptz,
    sighting_count        int NOT NULL DEFAULT 0,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT merged_has_target
        CHECK ((status = 'merged') = (merged_into_id IS NOT NULL)),
    CONSTRAINT not_self_merged
        CHECK (merged_into_id IS DISTINCT FROM id),
    CONSTRAINT confirmed_has_name
        CHECK (status <> 'confirmed' OR name IS NOT NULL),
    CONSTRAINT identifiable
        CHECK (name IS NOT NULL OR provisional_code IS NOT NULL)
);

CREATE SEQUENCE provisional_code_seq;   -- formatted 'T-%04d'; never recycled
```

Constraints worth noting:
- `identifiable` — a vessel row must have *something* to call it. This is the schema-level expression of "every boat gets an identity".
- `merged_has_target` — biconditional, so `status='merged'` and a null target cannot coexist in either direction.
- `merged_into_id` is `ON DELETE RESTRICT`, not `CASCADE`: deleting a vessel that others merged into must fail loudly rather than orphan history.

`hull_color_family` is a coarse bucket (`white`, `dark`, `blue`, `grey`, …) derived from `hull_color`. The re-ID gate matches on the family, because "off-white" and "cream" must not prevent a match.

### 3.5 `vessel_sightings`

```sql
CREATE TABLE vessel_sightings (
    id            bigserial PRIMARY KEY,
    vessel_id     int NOT NULL REFERENCES vessels(id) ON DELETE CASCADE,
    camera_id     int NOT NULL REFERENCES cameras(id),
    transit_id    bigint REFERENCES transits(id) ON DELETE SET NULL,
    berth_id      int REFERENCES berths(id) ON DELETE SET NULL,
    track_ref     text,
    seen_at       timestamptz NOT NULL,
    crop_uri      text NOT NULL,
    quality_score numeric(5,4),
    embedding     vector(768),                -- DINOv2 ViT-B/14
    created_at    timestamptz NOT NULL DEFAULT now()
);
```

`quality_score` is stored, not just used transiently, because the opportunistic follow-up trigger compares a new crop against the best prior crop for that vessel.

### 3.6 `transits`

```sql
CREATE TABLE transits (
    id             bigserial PRIMARY KEY,
    event_id       text NOT NULL UNIQUE,      -- ULID from the event bus, idempotency key
    vessel_id      int NOT NULL REFERENCES vessels(id) ON DELETE RESTRICT,
    camera_id      int NOT NULL REFERENCES cameras(id),
    zone_id        int REFERENCES zones(id) ON DELETE SET NULL,
    direction      transit_dir NOT NULL,
    track_ref      text NOT NULL,
    occurred_at    timestamptz NOT NULL,
    confidence     numeric(4,3),
    best_frame_uri text,
    clip_uri       text,
    created_at     timestamptz NOT NULL DEFAULT now()
);
```

**`vessel_id` is `NOT NULL`.** This is the single most consequential constraint in the schema — it makes it structurally impossible to record a boat entering without an identity, which is exactly the requirement. It is only satisfiable because provisional minting happens before the transit row is written.

### 3.7 `identifications`

Append-only. Never updated, never deleted.

```sql
CREATE TABLE identifications (
    id              bigserial PRIMARY KEY,
    vessel_id       int NOT NULL REFERENCES vessels(id) ON DELETE CASCADE,
    transit_id      bigint REFERENCES transits(id) ON DELETE SET NULL,
    attempt_no      int NOT NULL,
    trigger         ident_trigger NOT NULL,
    source          ident_source NOT NULL,

    name            text,
    flag_country    char(2),
    registration_no text,
    vessel_type     vessel_type,
    field_confidence jsonb NOT NULL DEFAULT '{}'::jsonb,

    crop_uris       text[],
    model           text,
    input_tokens    int, output_tokens int, cached_tokens int,
    latency_ms      int,
    raw_response    jsonb,
    error           text,
    actor_user_id   int REFERENCES users(id),
    created_at      timestamptz NOT NULL DEFAULT now()
);
```

Rows are written for **failed and null-result attempts too**. Three reasons: the attempt budget must count them; a vessel that burned 8 attempts in good light is evidence its name isn't camera-readable and should go to an operator; and the corpus is training data for a future fine-tune.

An operator correction writes a new row with `source='manual'` — **the machine's original guess is preserved, not overwritten.** That is what makes the review queue auditable.

### 3.8 `berth_occupancy`

```sql
CREATE TABLE berth_occupancy (
    id          bigserial PRIMARY KEY,
    berth_id    int NOT NULL REFERENCES berths(id) ON DELETE RESTRICT,
    vessel_id   int REFERENCES vessels(id) ON DELETE SET NULL,
    transit_id  bigint REFERENCES transits(id) ON DELETE SET NULL,
    started_at  timestamptz NOT NULL,
    ended_at    timestamptz,
    confidence  numeric(4,3),
    source      occupancy_src NOT NULL DEFAULT 'vision',
    created_at  timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT sane_interval CHECK (ended_at IS NULL OR ended_at > started_at)
);

-- at most one open occupancy per berth
CREATE UNIQUE INDEX one_open_occupancy_per_berth
    ON berth_occupancy (berth_id) WHERE ended_at IS NULL;
```

That partial unique index is the guard against the state machine double-opening a berth on a flapping detection — a bug that would otherwise corrupt occupancy silently.

### 3.9 `vessel_merges`

```sql
CREATE TABLE vessel_merges (
    id                bigserial PRIMARY KEY,
    source_vessel_id  int NOT NULL REFERENCES vessels(id) ON DELETE RESTRICT,
    target_vessel_id  int NOT NULL REFERENCES vessels(id) ON DELETE RESTRICT,
    method            merge_method NOT NULL,
    similarity        numeric(5,4),
    evidence          jsonb NOT NULL,   -- MUST include the affected row-id manifest
    decided_by_user_id int REFERENCES users(id),
    merged_at         timestamptz NOT NULL DEFAULT now(),
    reverted_at       timestamptz,
    reverted_by_user_id int REFERENCES users(id),

    CONSTRAINT no_self_merge CHECK (source_vessel_id <> target_vessel_id)
);
```

**`evidence` must contain the row-id manifest** — the exact ids in each table that were re-pointed. Without it a revert cannot know which rows to move back, because by then other rows may legitimately reference the target vessel. Storing only a similarity score makes the merge irreversible in practice, which defeats the design.

### 3.10 `queue_samples`

```sql
CREATE TABLE queue_samples (
    ts             timestamptz NOT NULL,
    zone_id        int NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
    vessel_count   int NOT NULL,
    max_dwell_sec  int,
    avg_dwell_sec  int,
    PRIMARY KEY (ts, zone_id)
);
SELECT create_hypertable('queue_samples', 'ts');
SELECT add_retention_policy('queue_samples', INTERVAL '2 years');
```

### 3.11 `recordings`

```sql
CREATE TABLE recordings (
    id           bigserial PRIMARY KEY,
    camera_id    int NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    berth_id     int REFERENCES berths(id) ON DELETE SET NULL,
    kind         recording_kind NOT NULL,
    started_at   timestamptz NOT NULL,
    ended_at     timestamptz NOT NULL,
    storage_uri  text NOT NULL UNIQUE,
    size_bytes   bigint,
    expires_at   timestamptz,
    legal_hold   boolean NOT NULL DEFAULT false,
    created_at   timestamptz NOT NULL DEFAULT now()
);
```

`legal_hold` exempts a recording from retention expiry. Required because a dispute or investigation can outlive the retention window, and deleting evidence under an active hold is a serious problem.

### 3.12 `users` and `audit_log`

```sql
CREATE TABLE users (
    id            serial PRIMARY KEY,
    email         citext NOT NULL UNIQUE,
    password_hash text NOT NULL,              -- argon2id
    full_name     text,
    role          user_role NOT NULL DEFAULT 'operator',
    is_active     boolean NOT NULL DEFAULT true,
    last_login_at timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_log (
    id           bigserial PRIMARY KEY,
    actor_user_id int REFERENCES users(id) ON DELETE SET NULL,
    action       text NOT NULL,               -- 'media.view','vessel.merge','zone.update'
    target_type  text, target_id text,
    ip_address   inet,
    detail       jsonb,
    occurred_at  timestamptz NOT NULL DEFAULT now()
);
```

`audit_log` is a KVKK obligation, not a convenience: every media view and export must be attributable. See [`COMPLIANCE-KVKK.md`](./COMPLIANCE-KVKK.md).

### 3.13 `processed_events`

```sql
CREATE TABLE processed_events (
    event_id     text PRIMARY KEY,
    stream       text NOT NULL,
    processed_at timestamptz NOT NULL DEFAULT now()
);
```

The idempotency guard. Inserted **in the same transaction** as the domain write; a conflict means the event was already handled and the transaction is abandoned. Redis Streams gives at-least-once delivery, so without this a redelivered transit event double-counts a boat.

---

## 4. Indexes

```sql
-- hot paths
CREATE INDEX ON transits (occurred_at DESC);
CREATE INDEX ON transits (vessel_id, occurred_at DESC);
CREATE INDEX ON transits (direction, occurred_at DESC);
CREATE INDEX ON berth_occupancy (berth_id, started_at DESC);
CREATE INDEX ON berth_occupancy (vessel_id, started_at DESC);
CREATE INDEX ON identifications (vessel_id, attempt_no);
CREATE INDEX ON vessel_sightings (vessel_id, seen_at DESC);
CREATE INDEX ON recordings (camera_id, started_at DESC);
CREATE INDEX ON audit_log (actor_user_id, occurred_at DESC);

-- vector search
CREATE INDEX ON vessel_sightings USING hnsw (embedding vector_cosine_ops);

-- exclude merged vessels from the hot path (they accumulate forever)
CREATE INDEX ON vessels (status) WHERE status <> 'merged';
CREATE INDEX ON vessels (last_seen_at DESC) WHERE status <> 'merged';

-- re-ID candidate gate
CREATE INDEX ON vessels (vessel_type, hull_color_family, est_loa_m)
    WHERE status <> 'merged';

-- one search box matching both 'SERENITY' and 'T-0142'
CREATE INDEX vessels_search_idx ON vessels USING gin (
    to_tsvector('simple',
        coalesce(name,'') || ' ' ||
        coalesce(provisional_code,'') || ' ' ||
        coalesce(nickname,'') || ' ' ||
        coalesce(registration_no,''))
);

-- retention sweeper
CREATE INDEX ON recordings (expires_at) WHERE legal_hold = false;
```

The partial indexes matter more than they look. Merged vessels are never deleted, so without `WHERE status <> 'merged'` every registry query degrades permanently as the marina accumulates history.

---

## 5. Resolving merged vessels

Any read that accepts a vessel id must resolve through the merge chain:

```sql
CREATE OR REPLACE FUNCTION resolve_vessel(v_id int) RETURNS int AS $$
DECLARE cur int := v_id; nxt int; hops int := 0;
BEGIN
    LOOP
        SELECT merged_into_id INTO nxt FROM vessels WHERE id = cur;
        EXIT WHEN nxt IS NULL;
        cur := nxt; hops := hops + 1;
        IF hops > 5 THEN
            RAISE EXCEPTION 'merge chain too deep or cyclic for vessel %', v_id;
        END IF;
    END LOOP;
    RETURN cur;
END;
$$ LANGUAGE plpgsql STABLE;
```

The depth cap catches cycles, which a buggy merge could otherwise create and which would hang every read touching that vessel. Raising loudly beats looping forever.

---

## 6. Retention

| Data | Default retention | Mechanism |
|---|---|---|
| Continuous recordings | 30 days *(placeholder — legal decision)* | `expires_at` + object lifecycle + sweeper |
| Event clips | 90 days | same |
| Best-shot crops | 1 year | same |
| `queue_samples` | 2 years | TimescaleDB retention policy |
| `transits`, `berth_occupancy` | indefinite | business records |
| `vessels`, `identifications` | indefinite | registry + audit trail |
| `audit_log` | 2 years minimum | KVKK |

Anything with `legal_hold = true` is exempt from expiry. The 30-day video default is a **placeholder pending legal review**, not a recommendation — see [`COMPLIANCE-KVKK.md`](./COMPLIANCE-KVKK.md).
