# Marina AI — API Reference

REST + WebSocket contract. Base path `/api/v1`. Implemented across Phases 1–6; each endpoint notes the phase that introduces it.

Status: **specification** · Date: 2026-07-29

---

## 1. Conventions

| Aspect | Rule |
|---|---|
| Auth | `Authorization: Bearer <jwt>` on everything except `/auth/login` and `/health` |
| Content type | `application/json` |
| Timestamps | RFC 3339 / ISO 8601, always UTC, always with offset (`2026-07-29T08:14:22.310Z`) |
| Pagination | `?limit=` (default 50, max 500) + `?cursor=`; response carries `next_cursor` |
| Time filters | `?from=` / `?to=`, inclusive of `from`, exclusive of `to` |
| Errors | RFC 7807 problem+json |
| Idempotency | `Idempotency-Key` header honoured on all `POST`s that mutate |

**Cursor pagination, not offset.** The transit and sighting tables are append-heavy and constantly written; offset pagination would skip or duplicate rows as new data arrives underneath a paging client.

### Error shape

```json
{
  "type": "https://marina.local/errors/vessel-not-found",
  "title": "Vessel not found",
  "status": 404,
  "detail": "No vessel with id 4821",
  "instance": "/api/v1/vessels/4821"
}
```

| Status | Meaning |
|---|---|
| 400 | Malformed request |
| 401 | Missing/invalid token |
| 403 | Authenticated but role lacks permission |
| 404 | Not found |
| 409 | Conflict — e.g. merging a vessel into itself, confirming an already-confirmed vessel |
| 422 | Semantically invalid — e.g. a zone polygon with fewer than 3 points |
| 429 | Rate limited |

### Roles

| Role | Can |
|---|---|
| `operator` | Read everything; confirm/correct identities; accept merge suggestions |
| `manager` | + berth admin, reports, exports |
| `admin` | + users, cameras, zones, retention, legal holds |

RBAC is enforced in the API layer. Hiding a button in the UI is not access control — Phase 6 requires an automated test matrix over roles × endpoints.

---

## 2. Auth

### `POST /auth/login`
```json
// →
{ "email": "murat@example.com", "password": "..." }
// ←
{ "access_token": "eyJ...", "refresh_token": "eyJ...",
  "expires_in": 900,
  "user": { "id": 1, "full_name": "Murat", "role": "admin" } }
```

### `POST /auth/refresh` · `POST /auth/logout` · `GET /auth/me`

Access tokens are short-lived (15 min); refresh tokens are rotated on use and revoked on logout.

---

## 3. Cameras *(Phase 1)*

### `GET /cameras`
```json
{ "items": [
  { "id": 3, "name": "Gate Identity", "kind": "identity",
    "resolution": [3840, 2160], "detect_fps": 6.0,
    "is_active": true, "status": "online",
    "last_seen_at": "2026-07-29T08:14:20Z" }
] }
```

`status` is derived: `online` if `last_seen_at` is within 15 s, else `offline`.

**`rtsp_url`, `rtsp_username`, and `rtsp_password` are never returned by any endpoint, at any role.** Admins set them write-only via `PATCH`.

### `GET /cameras/{id}/snapshot`
Returns `image/jpeg` — the most recent decoded frame. Used by the zone editor.

### `POST /cameras` · `PATCH /cameras/{id}` · `DELETE /cameras/{id}` — *admin*

---

## 4. Zones *(Phase 1 read, Phase 3 editor)*

### `GET /cameras/{id}/zones`
```json
{ "items": [
  { "id": 7, "kind": "gate_line", "name": "Main entrance",
    "geometry": { "type": "line", "points": [[0.12,0.55],[0.88,0.48]] },
    "direction_hint": { "normal": [0.06, 0.99] },
    "berth_id": null, "config": {} }
] }
```

### `PUT /cameras/{id}/zones` — *admin*
Replaces the full zone set for a camera atomically. Takes effect without restarting services (Phase 3 acceptance criterion).

Coordinates are **normalised 0–1**, so zones survive a camera resolution change.

---

## 5. Transits *(Phase 1)*

### `GET /transits`

| Param | Notes |
|---|---|
| `from`, `to` | time window |
| `direction` | `in` / `out` |
| `vessel_id` | filter to one vessel |
| `camera_id` | |
| `identified` | `true` / `false` — filter provisional-only |

```json
{ "items": [
  { "id": 9081, "direction": "in",
    "occurred_at": "2026-07-29T08:14:22.310Z",
    "camera_id": 3, "zone_id": 7, "confidence": 0.94,
    "vessel": { "id": 142, "display_name": "SERENITY (was T-0142)",
                "status": "confirmed", "provisional_code": "T-0142",
                "flag_country": "TR" },
    "best_frame_uri": "/api/v1/media/frames%2F2026%2F07%2F29%2Fcam3-1721-a.jpg",
    "clip_uri": "/api/v1/media/clips%2F9081.mp4" }
  ],
  "next_cursor": "eyJpZCI6OTA4MX0" }
```

**Every transit carries a vessel.** There is no null case — a boat that could not be identified returns its provisional record.

### `GET /transits/counts`
```
?from=2026-07-01&to=2026-07-29&bucket=day
```
```json
{ "buckets": [ { "ts": "2026-07-28T00:00:00Z", "in": 41, "out": 38 } ] }
```

---

## 6. Vessels *(Phase 2a)*

### `GET /vessels`

| Param | Notes |
|---|---|
| `q` | Full-text across name, provisional code, nickname, registration — **one box matches both `SERENITY` and `T-0142`** |
| `status` | `provisional` / `candidate` / `confirmed` |
| `in_marina` | `true` — currently has an open berth occupancy |

```json
{ "items": [
  { "id": 142, "status": "confirmed",
    "display_name": "SERENITY (was T-0142)",
    "provisional_code": "T-0142", "name": "SERENITY",
    "flag_country": "TR", "registration_no": "TR 34 A 1234",
    "vessel_type": "motor_yacht", "hull_color": "white",
    "est_loa_m": 12.4, "identity_confidence": 0.93,
    "first_seen_at": "2026-07-12T08:14:00Z",
    "last_seen_at": "2026-07-27T11:20:00Z",
    "sighting_count": 14,
    "current_berth": { "id": 14, "code": "D-14" } },

  { "id": 187, "status": "provisional",
    "display_name": "T-0187 · white · motor yacht · ~9 m",
    "provisional_code": "T-0187", "name": null,
    "flag_country": null, "vessel_type": "motor_yacht",
    "hull_color": "white", "est_loa_m": 9.1,
    "identity_confidence": 0.0, "sighting_count": 2,
    "current_berth": { "id": 22, "code": "C-07" } }
] }
```

The second record is the point of the design: an unidentified boat is a complete, usable record — berthed, counted, searchable — not a gap.

### `GET /vessels/{id}`
Full detail: attributes, all crops, identification attempt history, merge history.

Requesting a merged vessel returns **`301` with `Location` pointing at the surviving record**, so old bookmarks and printed reports still resolve.

### `GET /vessels/{id}/timeline`
```json
{ "items": [
  { "kind": "transit",   "at": "2026-07-12T08:14:22Z", "direction": "in",
    "clip_uri": "..." },
  { "kind": "identified","at": "2026-07-12T09:02:11Z", "attempt_no": 4,
    "name": "SERENITY", "confidence": 0.93, "source": "claude" },
  { "kind": "berth_in",  "at": "2026-07-12T08:31:07Z", "berth": "D-14" },
  { "kind": "berth_move","at": "2026-07-14T10:02:00Z", "from": "D-14", "to": "C-07" },
  { "kind": "transit",   "at": "2026-07-19T16:45:00Z", "direction": "out" },
  { "kind": "merged_in", "at": "2026-07-27T11:22:00Z", "from_vessel": 203,
    "method": "embedding", "similarity": 0.94 }
] }
```

### `POST /vessels/{id}/confirm` — *operator*
```json
{ "name": "SERENITY", "flag_country": "TR",
  "registration_no": "TR 34 A 1234", "vessel_type": "motor_yacht" }
```
Writes a new `identifications` row with `source: "manual"` and promotes to `confirmed`. **The machine's original proposal is preserved, not overwritten.**

If the confirmed name matches an existing confirmed vessel, the response includes a merge suggestion rather than performing it silently:
```json
{ "vessel": {...},
  "merge_suggestion": { "target_vessel_id": 88, "similarity": 0.91,
                        "reason": "name_match" } }
```

### `POST /vessels/{id}/identify` — *operator*
Forces an immediate identification attempt, bypassing the follow-up backoff. `202 Accepted`; result arrives over WebSocket.

### `PATCH /vessels/{id}` — *operator*
Nickname and notes only. Identity fields go through `/confirm` so they are audited.

---

## 7. Merges *(Phase 2b)*

### `POST /vessels/{id}/merge` — *operator*
```json
{ "target_vessel_id": 88, "reason": "same vessel, confirmed by operator" }
```
`id` is merged **into** `target_vessel_id`; the target survives. `409` if either is already merged or if the two are the same.

### `POST /merges/{id}/revert` — *operator*
Restores all re-pointed rows from the merge's row-id manifest. `409` if already reverted, or if a subsequent merge depends on this one.

### `GET /merges`
Audit list, filterable by `reverted=true` — the query that answers "is the matcher drifting".

---

## 8. Review queue *(Phase 2a / 2b)*

### `GET /review-queue`
```
?kind=identification|merge&sort=age_desc
```
```json
{ "items": [
  { "kind": "identification", "vessel_id": 187,
    "display_name": "T-0187 · white · motor yacht · ~9 m",
    "proposed": { "name": "SEA BREEZE", "name_confidence": 0.71 },
    "crops": ["/api/v1/media/..."],
    "attempts": 5, "age_hours": 31 },

  { "kind": "merge", "source_vessel_id": 203, "target_vessel_id": 142,
    "similarity": 0.83,
    "evidence": { "same_vessel": true, "confidence": 0.86,
                  "evidence": "matching black radar arch with raked support...",
                  "differences": "different fender placement" },
    "crops": { "source": "...", "target": "..." } }
] }
```

Sorted oldest-first by default. `vessels_provisional_current` and queue age are alerted on in Phase 6, because an ignored review queue is the predictable operational failure.

---

## 9. Berths *(Phase 3)*

### `GET /berths`
```json
{ "items": [
  { "id": 14, "code": "D-14", "pontoon": "D",
    "max_loa_m": 15.0, "is_active": true,
    "occupancy": { "vessel_id": 142,
                   "display_name": "SERENITY (was T-0142)",
                   "started_at": "2026-07-12T08:31:07Z",
                   "confidence": 0.88 } }
] }
```
`occupancy` is `null` when empty. This single call backs the marina map.

### `GET /berths/{id}/occupancy`
Historical occupancy for a berth: who, when, how long.

### `POST /berths` · `PATCH /berths/{id}` — *manager*

---

## 10. Queue *(Phase 4)*

### `GET /queue/current`
```json
{ "zone_id": 12, "as_of": "2026-07-29T08:15:00Z",
  "vessel_count": 3, "max_dwell_sec": 840, "avg_dwell_sec": 430,
  "estimated_wait_sec": 600, "estimate_sample_count": 22,
  "vessels": [
    { "vessel_id": 187, "display_name": "T-0187 · white · motor yacht · ~9 m",
      "dwell_sec": 840 }
  ] }
```

`estimate_sample_count` is returned so the UI can suppress the estimate when the sample is too small to trust. An estimate presented without its sample size invites false confidence.

### `GET /queue/history?from&to&bucket=hour`

---

## 11. Recordings & media *(Phase 5)*

### `GET /recordings`
```
?camera_id=9&berth_id=14&from=...&to=...&kind=continuous|event
```

### `GET /media/{key}`
`302` redirect to a signed object-storage URL, valid 5 minutes.

**Every call writes an `audit_log` row** (actor, target, IP, timestamp). This is a KVKK obligation, and the reason media is never served directly by the API or fronted by a permanent public URL.

### `POST /recordings/{id}/legal-hold` — *admin*
Exempts a recording from retention expiry. Required because a dispute can outlive the retention window.

---

## 12. Reports *(Phase 6)*

### `GET /reports/traffic?from&to&bucket`
### `GET /reports/occupancy?from&to`
### `GET /reports/identification?from&to`
```json
{ "total_transits": 1204,
  "identified_at_gate": 412,
  "identified_by_followup": 631,
  "still_provisional": 161,
  "identification_rate": 0.866,
  "mean_attempts_to_identify": 2.7,
  "operator_corrections": 48,
  "false_names_detected": 2 }
```

This report is the system's own quality scorecard. `identified_by_followup` vs `identified_at_gate` measures whether the follow-up loop is earning its cost ([Phase 2b](./phases/PHASE-2B-reid-followup.md) acceptance criterion), and `false_names_detected` — corrections where the machine had asserted above τ — is the precision metric that matters most.

### `GET /reports/{name}/export?format=csv|xlsx` — *manager*
Audited.

---

## 13. WebSocket

`GET /ws/live` — JWT via `?token=` or the `Sec-WebSocket-Protocol` header.

### Subscribe
```json
{ "action": "subscribe", "topics": ["transits", "berths", "detections.3"] }
```

| Topic | Payload |
|---|---|
| `detections.{camera_id}` | Live bounding boxes, ~6/s. Ephemeral, never persisted. |
| `transits` | New transit with vessel |
| `berths` | Occupancy change |
| `queue` | Queue sample |
| `review_queue` | New item needing operator attention |
| `cameras` | Online/offline transition |

```json
{ "topic": "transits", "ts": "2026-07-29T08:14:22.310Z",
  "data": { "id": 9081, "direction": "in", "vessel": {...} } }
```

Clients must tolerate reconnection with gaps: the socket is a live feed, not a durable log. On reconnect, refetch current state over REST and resume streaming. This mirrors the server-side reconnection contract in [`TECHNICAL.md §5`](./TECHNICAL.md#5-event-contracts-redis-streams).

---

## 14. Health & metrics

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` | none | Liveness — process is up |
| `GET /health/ready` | none | Readiness — DB, Redis, object store reachable |
| `GET /metrics` | none, but bound to the internal interface only | Prometheus scrape |
