# Axio Medical — Phase 1: Foundation

Custom Odoo 19 module for clinic operations: patient management, clinical encounters, history tracking, and document attachments. Designed to scale to prescriptions, AI assistance, and medical invoicing in later phases.

## What's in Phase 1

| Component | Purpose |
|---|---|
| `medical.patient` | Central patient record. Linked to `res.partner` for billing/contact reuse. Auto-generated MRN. |
| `medical.encounter` | One per visit. Holds SOAP sections, diagnoses, vitals. State machine: draft → in_progress → completed → invoiced. |
| `medical.history` | Medical, surgical, family, and social history. Single model, discriminated by `history_type`. |
| `medical.allergy` | Allergies as **structured data** (not free text) — required for Phase 3 AI safety checks. |
| `medical.medication` | Prescribed meds, OTC, vitamins, supplements. `active_treatment` flag separates current from historical. |
| `medical.vitals` | BP, HR, RR, temp, SpO₂, weight, height, BMI auto-computed, pain score. Per-encounter so trends are visible. |
| `medical.diagnosis` | ICD-10 catalog (small seed set; full catalog imported via CSV in production). |

## Security model

Four hierarchical groups:
1. **Receptionist** — patient registration, no clinical data
2. **Nurse** — vitals + read-only clinical
3. **Doctor** — full clinical, can complete encounters
4. **Medical Administrator** — config + master data

Record rule on `medical.encounter` restricts doctors to their own encounters by default; managers see all. Override in deployment if a different isolation policy is needed.

## What's NOT in Phase 1 (by design)

- Medical report PDF (Phase 2)
- Prescription with safety checks (Phase 2)
- Cash/credit invoicing wizard (Phase 2)
- AI report drafting and prescription safety (Phase 3)
- GDPR consent tracking, integrations (Phase 4)

## Install

```bash
# In your Odoo addons path
cd /path/to/custom/addons
# Copy or symlink axio_medical/
./odoo-bin -c odoo.conf -u axio_medical -d your_db --without-demo=False
```

For production install without demo data:
```bash
./odoo-bin -c odoo.conf -i axio_medical -d your_db
```

## Module structure

```
axio_medical/
├── __manifest__.py
├── __init__.py
├── models/
│   ├── __init__.py
│   ├── res_partner.py            # is_patient flag + stat button
│   ├── medical_diagnosis.py      # ICD-10 catalog
│   ├── medical_patient.py        # Patient + computes (age, BMI, encounter count)
│   ├── medical_history.py        # Medical/surgical/family/social
│   ├── medical_allergy.py        # Structured for safety checks
│   ├── medical_medication.py     # Meds, OTC, vitamins, supplements
│   ├── medical_vitals.py         # Per-encounter; BMI auto-computed
│   └── medical_encounter.py      # SOAP + state machine + diagnoses
├── views/
│   ├── medical_menu.xml
│   ├── medical_patient_views.xml      # List/kanban/form with critical-allergy banner
│   ├── medical_encounter_views.xml    # SOAP form, calendar, list
│   ├── medical_vitals_views.xml
│   ├── medical_history_views.xml
│   ├── medical_allergy_views.xml
│   ├── medical_medication_views.xml
│   ├── medical_diagnosis_views.xml
│   └── res_partner_views.xml
├── security/
│   ├── medical_security.xml      # Groups + record rules
│   └── ir.model.access.csv
├── data/
│   ├── medical_sequence.xml      # MRN, ENC sequences
│   └── medical_data.xml          # Seed ICD-10
├── demo/
│   └── medical_demo.xml
└── static/
    └── src/scss/medical.scss
```

## Key design decisions

1. **Patient linked to `res.partner`** — patients need to be billable; reusing the partner model avoids duplicating address/phone/email and integrates natively with accounting.

2. **Allergies as structured records** — non-negotiable. Free-text allergies cannot be cross-referenced by AI safety checks in Phase 3.

3. **Single `medical.history` model with `history_type` discriminator** — avoids three near-identical tables. Domain-filtered One2many fields on the patient form give the UX of separate tabs.

4. **Vitals belong to encounter, not patient** — trends over visits are clinically meaningful. The patient form shows last-recorded values via compute fields.

5. **State machine on encounter** — `draft → in_progress → completed → invoiced` with proper transition methods. Completion requires at least chief complaint or clinical notes; this is enforced server-side.

6. **`mail.thread` on patient and encounter** — gives free audit trail and attachment handling. Documents (lab results, imaging, etc.) attach via chatter and are visible per-encounter and per-patient.

## Phase 2 preview (not in this module)

- `axio_medical_report` — SOAP report PDF using QWeb; signed/locked state
- `axio_medical_prescription` — Rx model with Many2one to `product.product`, QR code, safety check stub
- `axio_medical_invoice` — wizard for cash/credit, extends `account.move` with `is_medical`, `encounter_id`

## Phase 3 preview (AI)

- `axio_medical_ai` — `medical.ai.service` abstract model, calls Claude API; `medical.ai.log` for audit
- Report drafting and prescription safety check actions on encounter and prescription forms
- All AI output presented as suggestion only; doctor accepts/rejects with full audit
