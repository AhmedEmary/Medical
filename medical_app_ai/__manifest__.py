# -*- coding: utf-8 -*-
{
    'name': 'Medical AI Assistant',
    'version': '19.0.1.0.0',
    'category': 'Healthcare',
    'summary': 'Multi-provider AI (Claude, Gemini, GPT) for clinical '
               'drafting, diagnosis suggestions, patient summaries and '
               'prescription safety checks',
    'description': """
Medical AI Assistant (Phase 3)
==============================
Adds an AI layer on top of medical_app. On a clinical encounter the
doctor can:

- Draft a SOAP note from the encounter data
- Get ICD-10 diagnosis suggestions from the catalog
- Get a concise summary of the patient's history
- Run a safety check of the plan against allergies and medications

The AI provider is configurable — Anthropic (Claude), Google (Gemini)
and OpenAI (GPT) are supported out of the box, and more can be added.

Every AI output is a *suggestion* — the doctor reviews, edits and accepts
it. All requests are recorded in an audit log.

Install the SDK for the provider you use:
- Anthropic:  pip install -U anthropic
- Google:     pip install -U google-genai
- OpenAI:     pip install -U openai

ID document OCR
---------------
A 'Scan ID Document' button on patient and contact forms reads a passport
or national ID image and pre-fills the identity fields. For offline MRZ
parsing of passports install:

  pip install passporteye
  apt-get install tesseract-ocr     # passporteye needs Tesseract

Without passporteye the wizard falls back to the configured AI vision
provider, which always works as long as one of the SDKs above is set up.
""",
    'author': 'Axio Parts',
    'website': 'https://axiob2b.com',
    'license': 'LGPL-3',
    'depends': [
        'medical_app',
        # The AI Report Draft tab and the report-drafting prompt reference
        # the discharge / therapies fields defined in medical_app_reports.
        'medical_app_reports',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizard/medical_ai_prompt_preview_views.xml',
        'wizard/medical_ai_suggestion_views.xml',
        'wizard/medical_id_scan_views.xml',
        'wizard/medical_encounter_scan_views.xml',
        'wizard/medical_external_visit_scan_views.xml',
        'wizard/medical_insurance_card_scan_views.xml',
        'views/medical_ai_config_views.xml',
        'views/medical_ai_log_views.xml',
        'views/medical_encounter_views.xml',
        'views/medical_case_views.xml',
        'views/medical_id_scan_buttons.xml',
        'views/medical_external_visit_views.xml',
        'views/medical_ai_menu.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
}
