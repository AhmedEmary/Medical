# -*- coding: utf-8 -*-
{
    'name': 'Medical - Entities (Hotels & Corporates)',
    'category': 'Healthcare',
    'summary': 'Group patients under hotels or corporate companies (entities).',
    'description': """
Axio Medical - Entities
=======================
Adds a shared ``medical.entity`` model (hotel or corporate company) that
patients can be linked to. Replaces the free-text ``hotel_name`` field with
a structured contact and unlocks:

- A dedicated "Corporate Employees" menu listing patients under companies.
- A dedicated "Hotel Guests" menu listing patients under hotels.
- Per-entity patient count, active-insurance count, and expiring-insurance
  alerts.
- Contract validity dates per entity so front desk can flag lapsed contracts.

The old ``hotel_name`` / ``room_number`` character fields are kept in place
for backward compatibility; when ``entity_id`` is set, ``hotel_name`` mirrors
its name.
    """,
    'author': 'Axio Parts',
    'website': 'https://axiob2b.com',
    'license': 'LGPL-3',
    'version': '1.0.0',
    'depends': [
        'medical_app',
        # Corporate/hotel employee ID scanning uses the OCR service
        # (medical.corporate.id.ocr.service) that lives in medical_app_ai.
        'medical_app_ai',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizard/medical_corporate_id_scan_views.xml',
        'views/medical_entity_views.xml',
        'views/medical_patient_views.xml',
        'views/medical_dashboard_views.xml',
        'views/medical_entity_menu.xml',
        'data/medical_dashboard_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'medical_app_entity/static/src/scss/dashboard.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
