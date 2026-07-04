# -*- coding: utf-8 -*-
"""Insurance / medical card OCR service.

Reads an image of a private insurance card (e.g. Egyptian "MIC Mohandes
Insurance / Wadi El-Neel Gold", or any equivalent) and returns a normalized
dict of insurance fields the scan wizard can apply to a ``medical.patient``.

Uses :class:`medical.ocr.mixin` for the send/parse/normalize glue.
"""
from datetime import datetime

from odoo import models


RESULT_FIELDS = (
    'policy_holder_name',        # cardholder full name
    'insurance_company',         # underwriter (e.g. "Mohandes Insurance")
    'plan_name',                 # named plan / tier (e.g. "Triumph Luxury")
    'network_name',              # TPA / hospital network (e.g. "Wadi El-Neel")
    'policy_number',             # long numeric id
    'employee_code',             # short staff id printed on the card
    'department',                # printed department / office
    'valid_from',                # date or False
    'valid_to',                  # date or False
    'copay_outpatient_pct',      # float, printed on many cards
    'copay_medication_pct',
    'copay_chronic_pct',
    'room_class',                # e.g. "Double", "Private"
    'covered_hospitals',         # free text list of hospitals
    'notes',                     # anything else printed
    'raw_text',
)


class MedicalInsuranceCardOcrService(models.AbstractModel):
    _name = 'medical.insurance.card.ocr.service'
    _inherit = 'medical.ocr.mixin'
    _description = 'Medical Insurance Card OCR Service'

    _ocr_feature = 'insurance_card_ocr'
    _ocr_max_tokens = 6000

    def _ocr_result_fields(self):
        return RESULT_FIELDS

    def _ocr_system_prompt(self):
        return (
            "You are an OCR assistant that reads private health insurance "
            "cards. Cards are often bilingual (Arabic + English) and issued "
            "by companies like Mohandes Insurance (MIC), AXA, Bupa, MetLife, "
            "GlobeMed, Nextcare, and their TPA networks (Wadi El-Neel, "
            "Cleopatra, etc.).\n\n"
            "Rules:\n"
            "- Read ONLY what is printed. Do not invent, guess or infer.\n"
            "- For any field you cannot read confidently, return an empty "
            "string (or null for dates and numbers).\n"
            "- Dates MUST be in ISO format YYYY-MM-DD. If the card shows a "
            "range like 'from 01/07/2025 to 30/06/2026' or 'valid "
            "01-07-2025 / 30-06-2026', extract both endpoints.\n"
            "- Copay / cost-share percentages are numbers only (e.g. 10 for "
            "'10%'), not strings with a '%' sign.\n"
            "- 'insurance_company' is the underwriter/insurer (e.g. "
            "'Mohandes Insurance'). 'network_name' is the network or TPA "
            "brand printed alongside it (e.g. 'Wadi El-Neel Gold'). If only "
            "one is visible, put it in 'insurance_company' and leave "
            "'network_name' empty.\n"
            "- 'plan_name' is the plan tier if the card names one (e.g. "
            "'Triumph Luxury', 'Gold', 'Platinum').\n"
            "- Output ONLY the JSON object, no commentary, no markdown fences.")

    def _ocr_user_prompt(self):
        return (
            "Extract the insurance data from this card image.\n\n"
            "Respond with ONLY a JSON object with exactly these keys:\n"
            "{\n"
            '  "policy_holder_name": "",\n'
            '  "insurance_company": "",\n'
            '  "plan_name": "",\n'
            '  "network_name": "",\n'
            '  "policy_number": "",\n'
            '  "employee_code": "",\n'
            '  "department": "",\n'
            '  "valid_from": "",\n'
            '  "valid_to": "",\n'
            '  "copay_outpatient_pct": null,\n'
            '  "copay_medication_pct": null,\n'
            '  "copay_chronic_pct": null,\n'
            '  "room_class": "",\n'
            '  "covered_hospitals": "",\n'
            '  "notes": ""\n'
            "}")

    def _ocr_normalize(self, data, raw_text):
        result = self._ocr_empty_result()
        for key in ('policy_holder_name', 'insurance_company', 'plan_name',
                    'network_name', 'policy_number', 'employee_code',
                    'department', 'room_class', 'covered_hospitals', 'notes'):
            value = data.get(key)
            if isinstance(value, list):
                # 'covered_hospitals' sometimes comes back as a list.
                value = ', '.join(str(v).strip() for v in value if v)
            result[key] = (value or '').strip() if value else ''
        result['valid_from'] = _parse_date(data.get('valid_from'))
        result['valid_to'] = _parse_date(data.get('valid_to'))
        result['copay_outpatient_pct'] = _parse_pct(
            data.get('copay_outpatient_pct'))
        result['copay_medication_pct'] = _parse_pct(
            data.get('copay_medication_pct'))
        result['copay_chronic_pct'] = _parse_pct(data.get('copay_chronic_pct'))
        result['raw_text'] = raw_text
        return result


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def _parse_date(value):
    """Accept ISO YYYY-MM-DD or common d/m/Y forms; return date or False."""
    if not value or not isinstance(value, str):
        return False
    text = value.strip()[:10]
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return False


def _parse_pct(value):
    """Accept int/float/str; strip trailing %; clamp to [0, 100]; else 0.0."""
    if value is None or value == '':
        return 0.0
    try:
        if isinstance(value, str):
            value = value.strip().rstrip('%').strip()
            if not value:
                return 0.0
        n = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, n))
