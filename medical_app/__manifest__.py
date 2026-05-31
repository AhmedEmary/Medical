# -*- coding: utf-8 -*-
{
    'name': 'Medical',
    'category': 'Healthcare',
    'summary': 'Patient management, clinical encounters, prescriptions and medical invoicing',
    'description': """
Axio Medical - Phase 1: Foundation
===================================
Core clinical data model:
- Patients (linked to res.partner) with categories (hotel guest / employee / external)
- Medical & surgical history
- Allergies (critical for prescribing safety)
- Current medications & vitamins
- Clinical encounters with vitals
- Document attachments per patient/encounter
- Role-based security (Receptionist / Nurse / Doctor / Admin)

Phase 2 (outputs), Phase 3 (AI), and Phase 4 (hardening) are separate modules
that depend on this one.
    """,
    'author': 'Axio Parts',
    'website': 'https://axiob2b.com',
    'license': 'LGPL-3',
    'version': '1.1.0',
    'depends': [
        'base',
        'mail',
        'contacts',
        'product',
        'hr',
    ],
    'data': [
        # Security
        'security/medical_security.xml',
        'security/ir.model.access.csv',
        # Data
        'data/medical_sequence.xml',
        'data/medical_data.xml',
        # Views — actions must load before menus that reference them
        'views/medical_patient_views.xml',
        'views/medical_history_views.xml',
        'views/medical_allergy_views.xml',
        'views/medical_medication_views.xml',
        'views/medical_prescription_line_views.xml',
        'views/medical_encounter_views.xml',
        'views/medical_vitals_views.xml',
        'views/medical_diagnosis_views.xml',
        'views/res_partner_views.xml',
        'views/medical_menu.xml',
    ],
    'demo': [
        'demo/medical_demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'medical_app/static/src/scss/medical.scss',
        ],
    },
    'application': True,
    'installable': True,
    'auto_install': False,
}
