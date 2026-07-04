# -*- coding: utf-8 -*-
"""Corporate / hotel employee ID card OCR service.

Reads a company- or hotel-issued employee ID card (e.g. "Triumph Hotel
Luxury" staff card) and returns a normalized dict the scan wizard can
apply to a ``medical.patient`` — cardholder name, employee code,
department, position, and the issuing employer's brand + location.

Uses :class:`medical.ocr.mixin` for the send/parse/normalize glue.
"""
from odoo import models


RESULT_FIELDS = (
    'employee_name',
    'employee_code',        # ID number printed on the card
    'department',
    'position',             # job title / role
    'employer_name',        # printed brand / hotel / company
    'employer_type',        # 'hotel' | 'company' | ''
    'location',             # city / area printed on the card
    'issuer_name',          # signer, useful for audit
    'issuer_title',
    'valid_from',           # if the card shows a validity window
    'valid_to',
    'raw_text',
)


class MedicalCorporateIdOcrService(models.AbstractModel):
    _name = 'medical.corporate.id.ocr.service'
    _inherit = 'medical.ocr.mixin'
    _description = 'Medical Corporate / Hotel Employee ID OCR Service'

    _ocr_feature = 'corporate_id_ocr'
    _ocr_max_tokens = 4000

    def _ocr_result_fields(self):
        return RESULT_FIELDS

    def _ocr_system_prompt(self):
        return (
            "You are an OCR assistant that reads corporate and hotel "
            "employee ID badges (Egypt and the wider region). Cards typically "
            "carry: the employer's brand or hotel name (e.g. 'Triumph Hotel "
            "Luxury', 'Cleopatra Hospital', 'Marriott'), an employee photo, "
            "the cardholder's full name, department, position/job title, and "
            "an employee ID number. Some cards also list a location (city or "
            "district) and are signed by an area manager.\n\n"
            "Rules:\n"
            "- Read ONLY what is printed. Do not invent or guess.\n"
            "- For any field you cannot read confidently, return an empty "
            "string (or null for dates).\n"
            "- 'employee_name' is the cardholder's full name in Latin "
            "letters if visible; otherwise transliterate from Arabic.\n"
            "- 'employee_code' is the printed ID number.\n"
            "- 'employer_name' is the employer's brand as printed. Include "
            "the tier if it is part of the brand (e.g. 'Triumph Hotel "
            "Luxury').\n"
            "- 'employer_type' MUST be one of: 'hotel', 'company', ''. "
            "Choose 'hotel' when the card clearly identifies a hotel "
            "(Hotel/Resort/Inn/Suites in the name or hospitality context); "
            "'company' otherwise. Return '' only when you truly cannot "
            "tell.\n"
            "- 'location' is the city / district printed on the card, if "
            "any (e.g. 'Qalioub', 'Cairo', 'Sharm El-Sheikh'). Empty if "
            "not shown.\n"
            "- 'issuer_name' / 'issuer_title' come from the signature block, "
            "if any (e.g. 'Ehab Ahmed Shoman' / 'Area General Manager').\n"
            "- Dates (if any) MUST be ISO YYYY-MM-DD.\n"
            "- Output ONLY the JSON object, no commentary, no markdown "
            "fences.")

    def _ocr_user_prompt(self):
        return (
            "Extract the employee's data from this corporate/hotel ID card.\n"
            "\nRespond with ONLY a JSON object with exactly these keys:\n"
            "{\n"
            '  "employee_name": "",\n'
            '  "employee_code": "",\n'
            '  "department": "",\n'
            '  "position": "",\n'
            '  "employer_name": "",\n'
            '  "employer_type": "",\n'
            '  "location": "",\n'
            '  "issuer_name": "",\n'
            '  "issuer_title": "",\n'
            '  "valid_from": "",\n'
            '  "valid_to": ""\n'
            "}")

    def _ocr_normalize(self, data, raw_text):
        from .medical_insurance_card_ocr import _parse_date
        result = self._ocr_empty_result()
        for key in ('employee_name', 'employee_code', 'department', 'position',
                    'employer_name', 'location', 'issuer_name', 'issuer_title'):
            value = data.get(key)
            result[key] = (value or '').strip() if isinstance(value, str) else ''
        employer_type = (data.get('employer_type') or '').lower().strip()
        result['employer_type'] = (
            employer_type if employer_type in ('hotel', 'company') else '')
        result['valid_from'] = _parse_date(data.get('valid_from'))
        result['valid_to'] = _parse_date(data.get('valid_to'))
        result['raw_text'] = raw_text
        return result
