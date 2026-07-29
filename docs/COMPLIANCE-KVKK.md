# Marina AI — KVKK / GDPR Compliance

Requirements and controls for lawful operation of a continuous video system in a Turkish marina.

Status: **requirements draft — needs legal review** · Date: 2026-07-29

---

> ## ⚠️ This is not legal advice
>
> This document is written by the engineering side to (a) make the obligations visible early, and (b) specify the technical controls that satisfy them. **A qualified data-protection lawyer or advisor must review the legal basis, the privacy notice text, the retention period, and the VERBİS position before go-live.**
>
> The technical controls below are built regardless — they are good practice and they are what makes compliance *possible*. But whether the chosen legal basis is correct, and whether the retention period is defensible, are legal determinations, not engineering ones.

---

## 1. Why this applies

Continuous video recording of a marina entrance and pontoons is **processing of personal data** under Turkish Law No. 6698 (KVKK) and, where EU-resident data subjects are involved, the GDPR. This is true even though the system's *purpose* is to identify boats rather than people:

- Video captures identifiable individuals — crew, guests, staff, visitors.
- Vessel names and registrations, combined with berth and timing records, constitute personal data about their owners: a record of where a named individual's boat was, and when.
- Marina traffic data reveals movement patterns of identifiable people over time.

"We're only interested in the boats" is not a defence. The lawful basis, notice, and retention obligations attach to what is *captured and stored*, not to what the operator intends to look at.

A marina entrance is also a **public-facing area**, which raises the bar on proportionality — people passing by have not entered into any relationship with the marina.

---

## 2. Roles

| Role | Who | Notes |
|---|---|---|
| **Data controller** (*veri sorumlusu*) | The marina operator | Decides purposes and means; carries the primary legal obligations |
| **Data processor** (*veri işleyen*) | The software vendor / operator of this system, if distinct from the marina | Requires a written processing agreement |
| **Sub-processor** | Anthropic (vessel images sent for identification) | See §6 — this needs explicit treatment |

If the system is sold as a hosted service, the vendor is a processor and a **written data-processing agreement is mandatory**, specifying purposes, categories, retention, security measures, and sub-processors.

---

## 3. Lawful basis

Two plausible routes under KVKK Art. 5. This is the decision most needing legal input:

| Basis | Fit | Consideration |
|---|---|---|
| **Legitimate interest** (*meşru menfaat*, Art. 5/2-f) | Most likely | Requires a documented balancing test showing the marina's interest in security and operations does not override data subjects' rights. Generally accepted for proportionate security CCTV. |
| **Explicit consent** (*açık rıza*) | Poor fit | Cannot be freely given by people simply passing the entrance; unworkable for a public-facing area. |
| **Contract performance** (Art. 5/2-c) | Partial | Covers berth-holders under contract, but not visitors or passers-by. |

**Recommendation to counsel:** legitimate interest for the video and vessel-tracking processing, with a documented balancing test (*meşru menfaat dengeleme testi*) retained as evidence. Berth-holder contracts should additionally reference the processing.

**A note on the AI element.** The system does more than record: it identifies, links, and retains a history of vessel movements. That is a more intrusive processing operation than passive CCTV, and the balancing test should address it explicitly rather than treating this as ordinary security recording. A **DPIA** (*veri koruma etki değerlendirmesi*) is advisable — required under GDPR Art. 35 for systematic monitoring of a publicly accessible area on a large scale, and good practice under KVKK regardless.

---

## 4. Obligations checklist

### 4.1 Notice (*aydınlatma yükümlülüğü*)

- [ ] **Signage at every camera-covered area** — entrance, pontoons, bay approach — before the point of capture. Bilingual (Turkish + English) given international traffic.
- [ ] Signage states: that recording is taking place, the controller's identity, the purpose, the legal basis, retention period, and how to exercise rights.
- [ ] Full privacy notice (*aydınlatma metni*) available at the marina office and on the website.
- [ ] Berth-holder contracts reference the processing.

Minimum signage content:

> **Bu alan güvenlik kamerası ile izlenmektedir.**
> Veri sorumlusu: [Marina]. Amaç: güvenlik ve liman operasyon yönetimi.
> Hukuki sebep: KVKK m.5/2-f (meşru menfaat). Saklama süresi: [N] gün.
> Haklarınız ve detaylı aydınlatma metni için: [URL] / marina ofisi.
>
> *This area is monitored by security cameras. Controller: [Marina]. Purpose:
> security and marina operations management. Retention: [N] days. For your
> rights and the full privacy notice: [URL] / marina office.*

### 4.2 VERBİS registration

- [ ] Determine whether the controller must register with VERBİS (thresholds are based on employee count and annual balance sheet; most marinas of any size will meet them).
- [ ] If required, register the processing activity, including the video and vessel-tracking categories, before processing begins.

### 4.3 Retention and deletion

- [ ] Retention period **decided by counsel** and documented in a retention policy (*saklama ve imha politikası*).
- [ ] Automatic deletion enforced technically, not by procedure. See §5.
- [ ] Periodic destruction records maintained.

> **The 30-day default in this repository is an engineering placeholder, not a recommendation.** Turkish practice for security CCTV commonly lands somewhere between 30 and 90 days, but the defensible figure depends on the stated purpose. Longer retention needs a stronger justification, and "it might be useful" is not one.
>
> Note the asymmetry: **transit and berth records are business records and are retained indefinitely; the video is not.** Keeping the structured record while deleting the footage is both operationally sufficient and more defensible than retaining everything.

### 4.4 Data subject rights (KVKK Art. 11)

Individuals may request access, rectification, erasure, and information about processing.

- [ ] Documented procedure for receiving and answering requests within 30 days.
- [ ] Ability to search recordings by time and location to locate footage relating to a request.
- [ ] Ability to export a specific segment, and to delete on a substantiated erasure request.
- [ ] Vessel owners may request their vessel's movement history — the `/vessels/{id}/timeline` endpoint serves this directly.

**A known tension worth raising with counsel:** an erasure request may conflict with an active legal hold or an ongoing dispute. The `legal_hold` flag exists to make that conflict explicit and auditable rather than resolving it silently in either direction.

### 4.5 Security measures (KVKK Art. 12)

- [ ] Cameras on an isolated VLAN with no internet route
- [ ] Camera credentials encrypted at rest, never returned by any API
- [ ] Video accessible only via short-lived signed URLs, never a permanent public URL
- [ ] **Every media view and export written to `audit_log`** with actor, target, IP, timestamp
- [ ] Role-based access enforced at the API layer, tested by a role × endpoint matrix
- [ ] Encryption in transit (TLS) and at rest (disk/object-store encryption)
- [ ] Access reviewed periodically; departing staff deprovisioned
- [ ] Breach notification procedure: Kurul and affected individuals, within 72 hours

---

## 5. Technical controls implemented

Mapping obligations to the parts of the system that satisfy them:

| Obligation | Control | Where |
|---|---|---|
| Retention enforcement | `recordings.expires_at` + object-store lifecycle rules + reconciling sweeper for orphans | [Phase 5](./phases/PHASE-5-recording.md) |
| Exemption for disputes | `recordings.legal_hold` blocks expiry | [`DATA-MODEL.md §3.11`](./DATA-MODEL.md) |
| Access auditing | `audit_log` row on every `/media/{key}` call and every export | [`API.md §11`](./API.md) |
| No permanent media URLs | 5-minute signed redirects only | [`API.md §11`](./API.md) |
| Access control | JWT + RBAC enforced server-side | [Phase 6](./phases/PHASE-6-hardening.md) |
| Credential protection | `rtsp_password` stored encrypted, excluded from all responses | [`DATA-MODEL.md §3.1`](./DATA-MODEL.md) |
| Data minimisation | Only best-shot crops retained long-term, not full frames; detection stream never persisted | [`TECHNICAL.md §5`](./TECHNICAL.md) |
| Locality | Video stays on-premises; only small crops leave the site | [ADR-003](./TECH-STACK.md#adr-003--edge-first-deployment) |
| Right of access | `/vessels/{id}/timeline`, recordings queryable by time and location | [`API.md`](./API.md) |

**Data minimisation deserves emphasis** because it is the strongest argument available in a balancing test. The system does not ship video off-site. It sends a handful of small cropped images — of a boat, not of people — to an external API, and retains only structured records long-term. That is a materially narrower processing footprint than "we upload all our CCTV to the cloud", and the design should be described that way in the DPIA.

---

## 6. Third-country transfer: the Anthropic API

**This needs explicit legal treatment and is easy to overlook.**

Vessel crops are sent to the Anthropic API for identification. That is a **transfer of personal data abroad** (KVKK Art. 9 / GDPR Chapter V), because the images may incidentally contain identifiable individuals — crew on deck, people on the pontoon.

Points for counsel:

- **What is transferred:** cropped images of vessels, typically 1–3 per identification attempt. Not continuous video, not full frames, not audio.
- **What is not transferred:** the recorded archive, berth records, personal details of berth-holders, camera streams.
- **Frequency:** once per identification attempt — a few hundred per day at most, not continuous.
- **Basis for transfer:** requires an appropriate mechanism under KVKK Art. 9 (explicit consent, an undertaking approved by the Kurul, or an adequacy decision) or GDPR Chapter V. Anthropic's data-processing terms and any certifications should be reviewed against this.
- **Mitigation available:** the best-shot selector can be biased to prefer crops framed tightly on the hull and transom, reducing the chance of capturing people. **This is a genuine, cheap engineering mitigation and should be implemented** — a tighter crop is also better for OCR, so it costs nothing in accuracy.
- **Retention at the processor:** confirm and document Anthropic's retention terms for API inputs.

If the transfer cannot be justified, the fallback is a locally-hosted vision model at materially lower accuracy — a significant product change, which is why this question should be answered **before** Phase 2a, not after.

---

## 7. Proportionality — what not to build

Some capabilities would be technically straightforward and legally hazardous. Recording them here as deliberate non-goals:

| Not built | Why |
|---|---|
| Face recognition | Biometric data — a special category under KVKK Art. 6 requiring explicit consent. Wholly disproportionate to marina operations. |
| Person tracking / re-ID across cameras | Systematic monitoring of individuals; far beyond the stated purpose. |
| Audio recording | Rarely justifiable, often unlawful, and of no operational value here. |
| Behavioural analytics on people | Outside the purpose entirely. |
| Indefinite video retention | Fails the storage-limitation principle. |
| Cameras covering vessel interiors or accommodation | Disproportionate intrusion into private space. Berth cameras must be framed to exclude cabin windows and cockpits where practical. |

That last row is a **camera-siting constraint**, not just a policy statement — it belongs in the survey checklist in [`CAMERA-SITING.md`](./CAMERA-SITING.md) and should be verified at commissioning.

---

## 8. Pre-go-live checklist

Everything here must be complete before the system processes live data in production.

- [ ] Legal review completed and documented
- [ ] Lawful basis determined; balancing test written and retained
- [ ] DPIA completed
- [ ] Privacy notice drafted, reviewed, and published
- [ ] Signage installed at every covered area, bilingual, before the point of capture
- [ ] VERBİS position determined; registration filed if required
- [ ] Retention period decided, configured, and **verified to actually delete**
- [ ] Data-processing agreement signed (if vendor ≠ controller)
- [ ] Third-country transfer basis for the Anthropic API documented
- [ ] Data-subject request procedure documented and staff trained
- [ ] Breach notification procedure documented
- [ ] Access control tested (role × endpoint matrix)
- [ ] Audit logging verified on 100% of media views and exports
- [ ] Berth cameras verified not to cover vessel interiors
- [ ] Staff with video access trained on lawful use

**Start this during Phase 5, not Phase 6.** Retrofitting consent mechanics, signage, and retention after a system is live is far more expensive than building them in — and if the legal review lands badly on the third-country transfer question, it changes the identification architecture. That is a Phase 2a-level dependency, discovered at Phase 6 cost if left late.
