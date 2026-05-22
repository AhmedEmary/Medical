# -*- coding: utf-8 -*-
"""Encounter document OCR service.

Reads handwritten or printed clinical documents (encounter notes and
prescriptions) using the configured AI vision provider and returns a
normalized dict that the Scan Documents wizard can preview and apply to
the encounter.

A single call can ingest multiple pages (e.g. a handwritten encounter
sheet AND a separate prescription paper) — the AI is instructed to merge
the data from all images into one structured payload.
"""
import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


# Frequency phrases that the AI can output → our prescription line selection
# keys. Anything that doesn't match falls back to 'other' with the raw text
# preserved in ``frequency_other``.
FREQUENCY_MAP = {
    'once_daily': 'once_daily',
    'once a day': 'once_daily',
    'qd': 'once_daily',
    'twice_daily': 'twice_daily',
    'twice a day': 'twice_daily',
    'two times daily': 'twice_daily',
    'two times a day': 'twice_daily',
    'bid': 'twice_daily',
    'three_times_daily': 'three_times_daily',
    'three times daily': 'three_times_daily',
    'three times a day': 'three_times_daily',
    'tid': 'three_times_daily',
    'four_times_daily': 'four_times_daily',
    'four times daily': 'four_times_daily',
    'four times a day': 'four_times_daily',
    'qid': 'four_times_daily',
    'every_4h': 'every_4h',
    'every 4 hours': 'every_4h',
    'every_6h': 'every_6h',
    'every 6 hours': 'every_6h',
    'every_8h': 'every_8h',
    'every 8 hours': 'every_8h',
    'every_12h': 'every_12h',
    'every 12 hours': 'every_12h',
    'weekly': 'weekly',
    'once a week': 'weekly',
    'as_needed': 'as_needed',
    'as needed': 'as_needed',
    'prn': 'as_needed',
}

ROUTE_MAP = {
    'oral': 'oral', 'po': 'oral', 'by mouth': 'oral',
    'iv': 'iv', 'intravenous': 'iv',
    'im': 'im', 'intramuscular': 'im',
    'sc': 'sc', 'subcutaneous': 'sc', 'subq': 'sc',
    'topical': 'topical',
    'inhalation': 'inhalation', 'inhaled': 'inhalation',
    'rectal': 'rectal', 'pr': 'rectal',
    'ophthalmic': 'ophthalmic', 'eye': 'ophthalmic',
    'otic': 'otic', 'ear': 'otic',
    'nasal': 'nasal',
}


OCR_SYSTEM_PROMPT = """You are a clinical OCR assistant that reads medical \
encounter documents — handwritten or printed — and extracts the data into \
strict JSON for a hospital EMR.

Rules:
- Read only what is actually written on the images. NEVER invent measurements,
  drug names, dosages, diagnoses or findings.
- If a value cannot be read with confidence, leave it as an empty string
  (or null for numeric fields).
- Documents may include encounter notes (chief complaint, vitals, exam,
  procedures) AND a separate prescription paper. Merge data from ALL
  images into one payload — do not duplicate.
- For the narrative HTML fields (history_present_illness, physical_exam,
  plan, therapies_administered) use only these tags: <p>, <ul>, <li>,
  <strong>, <br/>. No headings, no images, no markdown.
- Vital signs go in the structured "vitals" object as numbers. SaO2/SpO2
  is a percentage integer; temperature is in degrees Celsius (float);
  BP comes as separate systolic and diastolic integers.
- For prescription items, return one object per drug line. Map frequency
  to one of: once_daily, twice_daily, three_times_daily,
  four_times_daily, every_4h, every_6h, every_8h, every_12h, weekly,
  as_needed, other. Use "other" with the verbatim phrase in
  "frequency_other" only when none of the standard keys fits.
- Map route to one of: oral, iv, im, sc, topical, inhalation, rectal,
  ophthalmic, otic, nasal. Empty string if not stated.
- Include drug strength inline in "product_name" (e.g. "Flagyl 500 mg",
  "Stopprhea 2 mg"). Do not emit a separate dose field.
- Output ONLY the JSON object — no commentary, no markdown fences."""


OCR_USER_PROMPT = """Extract the encounter data from the attached document \
image(s). Respond with ONLY a JSON object using exactly these keys:

{
  "chief_complaint": "",
  "history_present_illness": "",
  "physical_exam": "",
  "therapies_administered": "",
  "assessment": "",
  "plan": "",
  "diagnosis_text": "",
  "vitals": {
    "bp_systolic": null,
    "bp_diastolic": null,
    "heart_rate": null,
    "respiratory_rate": null,
    "temperature": null,
    "spo2": null,
    "glucose": null,
    "weight": null,
    "height": null
  },
  "prescription_lines": [
    {
      "product_name": "",
      "generic_name": "",
      "frequency": "",
      "frequency_other": "",
      "route": "",
      "duration_days": null,
      "quantity": "",
      "instructions": ""
    }
  ]
}

Notes on each field:
- "chief_complaint": one short sentence in the patient's words / symptoms.
- "history_present_illness": multi-paragraph HTML narrative of the history,
  onset, character, associated symptoms.
- "physical_exam": HTML narrative of examination findings.
- "therapies_administered": HTML narrative of procedures done DURING the
  visit (injections, IV fluids, etc).
- "assessment": HTML narrative of the clinical impression.
- "plan": HTML narrative of advice / follow-up / lifestyle instructions.
- "diagnosis_text": free-text diagnosis phrase from the document.
- "prescription_lines": leave [] if there is no prescription on the images."""


class MedicalEncounterOcrService(models.AbstractModel):
    """Stateless OCR helper used by the Scan Documents wizard."""
    _name = 'medical.encounter.ocr.service'
    _description = 'Medical Encounter Document OCR Service'

    @api.model
    def extract(self, images, encounter=None):
        """Extract clinical data from one or more document images.

        :param images: list of ``{'data': <base64-str>, 'mime_type': <str>}``
            dicts. Must contain at least one image.
        :param encounter: optional medical.encounter the data will be
            applied to (used for the AI log audit trail).
        :return: normalized dict — see :data:`OCR_USER_PROMPT` for the
            shape. All keys are always present; missing values are empty
            strings, empty lists, or ``None``.
        """
        if not images:
            raise UserError(_("Please upload at least one document image."))

        primary = images[0]
        service = self.env['medical.ai.service']
        text, _log = service._call_vision(
            feature='encounter_ocr',
            system_prompt=OCR_SYSTEM_PROMPT,
            user_prompt=OCR_USER_PROMPT,
            image_b64=primary['data'],
            mime_type=primary.get('mime_type') or 'image/jpeg',
            extra_images=images[1:],
            encounter=encounter,
            max_tokens=4000,
        )
        data = service._parse_json(text)
        return self._normalize(data)

    # ============================================================
    # Normalization
    # ------------------------------------------------------------
    # The AI is *asked* to follow the schema but may diverge slightly.
    # Here we coerce values into the exact shape the wizard expects so
    # the rest of the flow can trust the dict.
    # ============================================================
    @api.model
    def _normalize(self, data):
        vitals = data.get('vitals') or {}
        return {
            'chief_complaint': (data.get('chief_complaint') or '').strip(),
            'history_present_illness':
                data.get('history_present_illness') or '',
            'physical_exam': data.get('physical_exam') or '',
            'therapies_administered':
                data.get('therapies_administered') or '',
            'assessment': data.get('assessment') or '',
            'plan': data.get('plan') or '',
            'diagnosis_text': (data.get('diagnosis_text') or '').strip(),
            'vitals': {
                'bp_systolic': _to_int(vitals.get('bp_systolic')),
                'bp_diastolic': _to_int(vitals.get('bp_diastolic')),
                'heart_rate': _to_int(vitals.get('heart_rate')),
                'respiratory_rate': _to_int(vitals.get('respiratory_rate')),
                'temperature': _to_float(vitals.get('temperature')),
                'spo2': _to_int(vitals.get('spo2')),
                'glucose': _to_float(vitals.get('glucose')),
                'weight': _to_float(vitals.get('weight')),
                'height': _to_float(vitals.get('height')),
            },
            'prescription_lines': [
                self._normalize_rx(line)
                for line in (data.get('prescription_lines') or [])
                if line and (line.get('product_name') or '').strip()
            ],
            'raw_text': text_or_empty(data.get('raw_text')) or '',
        }

    @api.model
    def _normalize_rx(self, line):
        freq_raw = (line.get('frequency') or '').strip().lower()
        frequency = FREQUENCY_MAP.get(freq_raw, '')
        frequency_other = (line.get('frequency_other') or '').strip()
        if not frequency and freq_raw:
            frequency = 'other'
            frequency_other = frequency_other or line.get('frequency') or ''
        route_raw = (line.get('route') or '').strip().lower()
        route = ROUTE_MAP.get(route_raw, '')
        return {
            'product_name': (line.get('product_name') or '').strip(),
            'generic_name': (line.get('generic_name') or '').strip(),
            'frequency': frequency or '',
            'frequency_other': frequency_other,
            'route': route,
            'duration_days': _to_int(line.get('duration_days')) or 0,
            'quantity': (line.get('quantity') or '').strip(),
            'instructions': (line.get('instructions') or '').strip(),
        }


# ============================================================
# Helpers
# ============================================================
def _to_int(value):
    if value in (None, '', False):
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _to_float(value):
    if value in (None, '', False):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def text_or_empty(value):
    return value if isinstance(value, str) else ''
