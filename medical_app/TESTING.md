# Medical App — Test Plan

Manual QA guide for the `medical_app` module (Odoo 19).
Work through it top to bottom; later sections assume data created earlier.

For each case: **Steps** are what to do, **Expected** is what must happen.
Mark each as Pass / Fail and note the build/commit you tested.

---

## 1. Environment setup

| # | Step | Expected |
|---|------|----------|
| 1.1 | Create a clean database and install the module:<br>`dropdb odoo-medical` then start Odoo with `-d odoo-medical -i medical_app` | Server log ends with `Modules loaded.` and `Registry loaded` — **no ERROR / CRITICAL / Traceback** lines. |
| 1.2 | Open `http://localhost:8069`, log in as admin. | Login succeeds. |
| 1.3 | Look at the top app menu. | A **Medical** app is visible. |

If install fails, stop and capture the traceback — nothing else can be tested.

---

## 2. Smoke test

| # | Step | Expected |
|---|------|----------|
| 2.1 | Open **Medical** → Operations. | Sub-menus: Patients, Encounters, Vitals. |
| 2.2 | Open **Medical** → Configuration. | Sub-menus: Diagnoses (ICD-10), Diagnosis Categories. |
| 2.3 | Open each list view (Patients, Encounters, Vitals, Diagnoses, Categories). | Each opens with no error; empty ones show the "no content" helper. |

---

## 3. Diagnoses & categories

| # | Step | Expected |
|---|------|----------|
| 3.1 | Configuration → Diagnoses (ICD-10). | **56 diagnoses** listed. |
| 3.2 | Configuration → Diagnosis Categories. | **14 categories** (I, II, IV, V, VI, IX, X, XI, XII, XIII, XIV, XVIII, XIX, XXI). |
| 3.3 | Open category "Diseases of the respiratory system". | Stat button shows **7** diagnoses; the embedded list shows them. |
| 3.4 | Click the diagnoses stat button. | Opens a filtered diagnosis list for that category only. |
| 3.5 | In the diagnosis list, group by **Category** (search → Group By → Category). | Diagnoses group under their category names. |
| 3.6 | Create a diagnosis with code `I10` (a duplicate). | Save is blocked: *"ICD-10 code must be unique."* |
| 3.7 | Create a category with chapter code `IX` (a duplicate). | Save is blocked: *"ICD-10 chapter must be unique."* |
| 3.8 | Open any diagnosis form. | `Category` is a dropdown; `ICD Chapter` is filled automatically and read-only. |

---

## 4. Patients

| # | Step | Expected |
|---|------|----------|
| 4.1 | Operations → Patients → New. Pick/create a contact in `Contact`, set Patient Category = External. Save. | Saves. **Medical Record Number** is auto-assigned (not "New"). |
| 4.2 | Check the title. | Shows `[MRN] Patient name`. |
| 4.3 | Set **Date of Birth** to a past date, save. | `Age` field shows the correct age. |
| 4.4 | Set **Date of Birth** to a future date, save. | Blocked: *"Date of birth cannot be in the future."* |
| 4.5 | Set Patient Category = **Hotel Guest**. | Room Number / Check-in / Check-out fields appear. |
| 4.6 | Set Check-in **after** Check-out, save. | Blocked: *"Check-in date must be before check-out date."* |
| 4.7 | Open the linked contact (res.partner). | It has **Is a Patient** ticked and a **Patient** stat button. |
| 4.8 | Edit the patient's Phone / Email. | The value also changes on the linked contact (related fields). |
| 4.9 | Switch the Patients view to **Kanban**. | Cards render with photo (or placeholder) — no JS error. |

---

## 5. Allergies & critical-allergy banner

| # | Step | Expected |
|---|------|----------|
| 5.1 | On a patient → Allergies tab, add an allergy with Severity = **Mild**. Save. | Row saved; no banner. |
| 5.2 | Add another allergy with Severity = **Anaphylaxis**. Save. | A red **"Critical Allergy"** banner appears at the top of the patient form. |
| 5.3 | Check the Patients list. | That patient's row is shown in red (decoration). |
| 5.4 | Change the severe allergy back to Mild. Save & reload. | Banner disappears; row no longer red. |

---

## 6. Medications & history

| # | Step | Expected |
|---|------|----------|
| 6.1 | Patient → Medications tab, add one with **Currently Taking** ticked. | Saved. |
| 6.2 | Set its End Date to a past date (use the onchange). | **Currently Taking** auto-unticks. |
| 6.3 | Patient → Medical History tab, add a row and pick an **ICD-10 Code** while leaving Condition empty. | Condition auto-fills from the diagnosis name. |
| 6.4 | Patient → Surgical History tab, add a row. | It appears only under Surgical History, not Medical History (history_type filter). |

---

## 7. Encounters & workflow

| # | Step | Expected |
|---|------|----------|
| 7.1 | Operations → Encounters → New. Pick a patient. Save. | **Reference** auto-assigned; state = **Draft**. |
| 7.2 | Confirm the patient-context fields (Age, Gender, Blood Type) populate. | They mirror the patient record (read-only). |
| 7.3 | Open the **Patient Context** tab. | Shows the patient's allergies and active medications. |
| 7.4 | If the patient has a critical allergy, check the encounter form. | Red critical-allergy alert is shown. |
| 7.5 | Click **Start Consultation**. | State → **In Progress**. |
| 7.6 | On the Consultation tab, confirm the SOAP sections. | Each rich-text note (History of Present Illness, Review of Systems, Physical Examination, Assessment, Plan, Additional Notes) shows a **visible, clickable editor box** — not a blank line. |
| 7.7 | Type text into a couple of note boxes; add a diagnosis under Assessment. Save. | Content persists after reload. |
| 7.8 | Click **Complete Encounter** with Chief Complaint **and** Clinical Notes empty. | Blocked: message asking to document chief complaint or clinical notes. |
| 7.9 | Fill Chief Complaint, then **Complete Encounter**. | State → **Completed**; Audit tab records completed date/by. |
| 7.10 | Click **Reopen**. | State → **In Progress**. |
| 7.11 | Create another encounter, **Cancel** it (confirm the dialog), then **Set to Draft**. | State goes Cancelled → Draft. |

---

## 8. Vitals

| # | Step | Expected |
|---|------|----------|
| 8.1 | On an encounter → Vitals tab → **Record Vitals**. Enter Weight 80 kg, Height 180 cm. Save. | **BMI** ≈ 24.69, category **Normal**. |
| 8.2 | Enter Weight 110, Height 170. | BMI ≈ 38.06, category **Obese**. |
| 8.3 | Enter Systolic 120, Diastolic 80. | The vitals record name shows `… · BP 120/80`. |
| 8.4 | Open the patient form after recording vitals. | Latest weight/height/BMI reflect the most recent vitals. |

---

## 9. Roles & permissions

Create four test users (Settings → Users), each assigned **one** Medical privilege:
Receptionist, Nurse, Doctor, Medical Administrator. Log in as each.

| # | Role | Expected |
|---|------|----------|
| 9.1 | Receptionist | Sees the Medical app and Patients. Can create/edit patients. Encounters are **read-only** (no create/edit). |
| 9.2 | Nurse | Can see Encounters and record Vitals. Cannot delete clinical records. |
| 9.3 | Doctor | Full clinical access; can Complete/Reopen encounters (those buttons are visible). |
| 9.4 | Doctor (record rule) | A doctor sees encounters where they are the doctor, or with no doctor set — not other doctors' encounters. |
| 9.5 | Medical Administrator | Sees everything incl. the **Audit** tab on encounters and the Configuration menu. |
| 9.6 | A user with **no** Medical privilege | Does **not** see the Medical app at all. |

---

## 10. Regression checks (Odoo 19 migration fixes)

Quick re-checks for the issues fixed during migration — all should now be clean:

- [ ] Module installs with no traceback (patient `mobile` field; `res.groups` privilege).
- [ ] All search views open; Group By works (no RelaxNG error).
- [ ] Patient kanban renders images (no `kanban_image` JS error).
- [ ] Encounter SOAP note editors are visibly sized.
- [ ] Server log shows **no** `_sql_constraints` / duplicate-label / inconsistent-compute warnings.
- [ ] The Medical app icon and menu appear for a user in a Medical group.

---

## 11. Automated tests (optional, recommended)

This plan is manual. To add regression-proof automated tests, create
`tests/` in the module with Odoo `TransactionCase` tests, e.g.:

- `test_patient.py` — MRN sequence, age compute, DOB constraint, partner `is_patient` flag.
- `test_encounter.py` — state machine transitions and the `action_complete` guard.
- `test_vitals.py` — BMI calculation and category boundaries.
- `test_diagnosis.py` — unique-code constraints.

Run with: `odoo-bin -d <db> -i medical_app --test-enable --stop-after-init`

---

## Test run record

| Date | Tester | Build / commit | Result | Notes |
|------|--------|----------------|--------|-------|
|      |        |                |        |       |
