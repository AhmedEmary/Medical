# -*- coding: utf-8 -*-
{
    'name': 'Medical Reports',
    'version': '19.0.1.0.0',
    'category': 'Healthcare',
    'summary': 'Printable clinical encounter / discharge report (PDF)',
    'description': """
Medical Reports (Phase 2)
==========================
Adds a printable PDF report for a clinical encounter, designed for use
as a patient-facing medical / discharge / fit-to-fly report.

The report is a QWeb template rendered through the standard Odoo report
engine. It is driven entirely by data on the encounter, the patient and
the company — no copy-pasting between the file and Odoo.

Sections
--------
- Header (every page): company logo + bilingual department title
- Title block: company name, address, phone
- Personal information (patient name, gender, age, MRN, encounter date)
- Clinical summary (from the encounter's history of present illness)
- Urgency level (triage colour)
- Patient history (from the patient's medical history)
- Therapies administered during the visit
- Vital signs table (from recorded vitals)
- Diagnoses (from the encounter's ICD-10 codes)
- Medications prescribed upon discharge
- Medical recommendation (from the encounter plan)
- Condition at discharge
- Conclusion
- Signature block (doctor name / title / report date)
- Footer (every page): company phone, email, tax ID, company registry
""",
    'author': 'Axio Parts',
    'website': 'https://axiob2b.com',
    'license': 'LGPL-3',
    'depends': [
        'medical_app',
        'mail',
    ],
    'data': [
        # Views (only field additions, no security needed)
        'views/medical_encounter_views.xml',
        'views/medical_case_views.xml',
        # Report templates first, then the action that references them,
        # then the mail template that references the action.
        'report/external_layout_inherit.xml',
        'report/medical_encounter_report.xml',
        'report/prescription_report.xml',
        'report/clinic_visit_report.xml',
        'report/dama_report.xml',
        'report/patient_registration_report.xml',
        'report/external_physician_visit_report.xml',
        'report/medical_case_report.xml',
        'report/medical_case_report_ar.xml',
        'report/medical_report_actions.xml',
        'report/prescription_report_actions.xml',
        'report/clinic_visit_actions.xml',
        'report/dama_report_actions.xml',
        'report/patient_registration_actions.xml',
        'report/external_physician_visit_actions.xml',
        'report/medical_case_actions.xml',
        'data/mail_template_medical_report.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
}
