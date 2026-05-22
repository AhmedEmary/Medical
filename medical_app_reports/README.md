# Medical Reports (`medical_app_reports`)

Phase 2 — printable PDF reports on top of `medical_app`.

## What it does

Adds a **Medical Report** action under the **Print** menu of every
clinical encounter. The output is a multi-page A4 PDF with a bilingual
(English / Arabic) header and footer, a triage-coloured urgency dot, a
vital-signs table, and signature block — fully dynamic from the
encounter, the patient and the company record.

## Sections (in print order)

| Section | Source |
|---------|--------|
| Header (every page) | `res.company.logo` + fixed bilingual title |
| Title block | `res.company` name / address / phone |
| Personal Information | `patient_id` (name, gender, age, MRN) + `encounter_date` |
| Clinical Summary | `history_present_illness` |
| Urgency Level | `urgency_level` (new) — coloured dot + label |
| Patient History | `patient_id.medical_history_ids` and active medications |
| Therapies Administered | `therapies_administered` (new) |
| Vital Signs Table | `vitals_ids` |
| Diagnosis | `diagnosis_ids` (name) |
| Medications Prescribed upon Discharge | `discharge_medication_notes` (new) |
| Medical Recommendation | `plan` |
| Condition at Discharge | `discharge_condition` (new) |
| Conclusion | `discharge_conclusion` (new) |
| Signature | `doctor_id` (name, job title) + `report_date` (new) |
| Footer (every page) | `res.company` phone, email, VAT, registry |

Each section is omitted when its source field is empty, so the report
adapts to how much you filled in.

## New fields on `medical.encounter`

All added under a new **Report** notebook page on the encounter form:

- `urgency_level` (Selection: red / orange / yellow / green / blue) —
  triage colour rendered as a coloured dot.
- `therapies_administered` (Html)
- `discharge_medication_notes` (Html)
- `discharge_condition` (Html)
- `discharge_conclusion` (Html)
- `report_date` (Date) — defaults to today.

## Setup

1. Install the module (it depends on `medical_app`).
2. Make sure the company record (**Settings → Companies**) has its
   logo, address, phone, email, **Tax ID** (`vat`) and
   **Company Registry** (`company_registry`) filled in — they all feed
   the report header and footer.
3. Open a clinical encounter, fill in the new **Report** tab fields,
   then **Print → Medical Report**.

## Design notes

- One QWeb template, no Python rendering — uses the standard
  `ir.actions.report` engine with a custom `report.paperformat`
  (`paperformat_medical_report`).
- `web.basic_layout` is used instead of `web.external_layout` so the
  report can supply its own bilingual header and two-column footer.
- The watermark is an inline SVG positioned inside the page body; it
  prints behind the content thanks to a low z-index. It will appear on
  the first page reliably; multi-page watermark behaviour depends on
  the wkhtmltopdf version on the server.
- File name: `Medical Report - <encounter reference>.pdf` (driven by
  `print_report_name` on the report action).
