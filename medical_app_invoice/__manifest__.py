# -*- coding: utf-8 -*-
{
    'name': 'Medical Invoicing',
    'version': '19.0.1.0.0',
    'category': 'Healthcare',
    'summary': 'Create customer invoices straight from a clinical encounter, '
               'with insurance and passport details printed on the invoice.',
    'description': """
Medical Invoicing
=================
Adds invoicing on top of medical_app:

* A **Create Invoice** action on the encounter that builds a draft
  ``account.move`` for the patient's contact, pre-filled with the
  consultation and any prescription items.
* A stat button on the encounter shows how many invoices were issued
  and the total amount across them.
* The encounter ``state`` gains an ``invoiced`` step, reached
  automatically once any of its invoices is posted.
* The invoice form and PDF print the patient's **passport / national ID**,
  **insurance provider**, **policy number**, **coverage type** and
  **validity** whenever the invoice is linked to an encounter.
""",
    'author': 'Axio Parts',
    'website': 'https://axiob2b.com',
    'license': 'LGPL-3',
    'depends': [
        'medical_app',
        'account',
    ],
    'data': [
        'views/medical_encounter_views.xml',
        'views/account_move_views.xml',
        'report/account_move_report.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
}
