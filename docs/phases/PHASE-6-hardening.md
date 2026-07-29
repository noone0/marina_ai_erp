# Phase 6 — Production hardening

**Goal:** make the system safe, operable, and legally deployable in a real marina.

**Delivers:** go-live readiness.
**Estimate:** ~2–3 weeks · **Depends on:** Phases 1–5

---

## In scope

- Authentication and role-based access control
- Alerting and on-call surface
- Scheduled reports
- Backup, restore, and disaster recovery
- KVKK / GDPR compliance controls
- Deployment, upgrade, and rollback procedure
- Operator documentation

## Out of scope

Multi-marina tenancy, the ERP/billing layer, mobile apps.

---

## Deliverables

1. Login with roles: **operator** (view, confirm identities), **manager** (+ reports, berth admin), **admin** (+ users, cameras, zones, retention).
2. Alerts fire to a real channel (email/Slack/webhook) for camera offline, queue depth, provisional backlog, storage pressure, reconciliation drift, and re-ID revert-rate spikes.
3. Daily and monthly reports: traffic, occupancy, average stay, identification rate.
4. Documented and **tested** backup/restore.
5. KVKK controls: signage text, retention enforcement, access audit, restricted export, data-processing record.
6. Runbook covering the common failure modes.

---

## Tasks

### Security
- [ ] JWT auth, password hashing (argon2), session/refresh handling
- [ ] RBAC enforced at the API layer, not only hidden in the UI
- [ ] Camera credentials encrypted at rest; never returned by any API
- [ ] Rate limiting; CORS lockdown; security headers
- [ ] Dependency and container scanning in CI

### Operations
- [ ] Alert rules with sensible thresholds and hysteresis to prevent flapping
- [ ] Grafana dashboards: pipeline health, identification quality, storage, cost
- [ ] Postgres backup (WAL archiving) + object-store versioning; **restore rehearsed and timed**
- [ ] Blue/green or rolling deploy with a documented rollback
- [ ] Migration safety: all migrations backwards-compatible for one release

### Reporting
- [ ] Scheduled report generation (PDF/XLSX) + email delivery
- [ ] Occupancy, traffic, average stay, identification-rate reports
- [ ] CSV export with audit logging

### Compliance (KVKK / GDPR)
- [ ] Retention configurable per data class, enforced automatically
- [ ] Access audit on every media view and export
- [ ] Data-processing record and signage text drafted for review
- [ ] Legal-hold mechanism exempting specific recordings from expiry
- [ ] Data-subject request procedure documented

---

## Acceptance criteria

- [ ] An unauthenticated request to every non-public endpoint returns 401; an under-privileged one returns 403. **Verified by an automated test matrix over roles × endpoints**, not by manual spot checks.
- [ ] Camera passwords never appear in any API response, log line, or error payload.
- [ ] **Restore rehearsal completed**: a database restored from backup into a clean environment, with elapsed time recorded. An untested backup is not a backup.
- [ ] Every alert rule has been deliberately triggered at least once in staging and observed to fire.
- [ ] Retention verifiably deletes expired media and rows, and legal-hold verifiably prevents it.
- [ ] Media access audit records actor, target, and timestamp for 100% of views and exports.
- [ ] Rollback exercised: deploy a release, roll it back, confirm the system is healthy and no data is lost.
- [ ] Runbook is usable by someone who did not build the system — validated by having such a person follow it.

---

## Dependencies

- Legal review of the retention period and processing record.
- A decision on where alerts go and who is on call.

---

## Risks

| Risk | Mitigation |
|---|---|
| **KVKK compliance treated as a checkbox and reviewed too late** | Start the legal review during Phase 5, not here. Continuous video of a public-facing area is personal-data processing, and retrofitting consent/signage/retention after go-live is far more expensive than building it in. |
| Backups exist but restore has never been tried | Rehearsal is an explicit acceptance criterion with a recorded time |
| Alert fatigue causes real alerts to be ignored | Tune thresholds in staging; hysteresis on every rule; keep the initial rule set deliberately small |
| RBAC enforced only in the frontend | API-level test matrix over roles × endpoints |
| On-prem box has no redundancy and is a single point of failure | Document the risk explicitly and agree an RTO with the marina; recording continuity matters more than dashboard uptime |
