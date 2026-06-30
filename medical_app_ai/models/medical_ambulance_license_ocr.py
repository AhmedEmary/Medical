# -*- coding: utf-8 -*-
"""Ambulance / vehicle license OCR service.

Reads an ambulance vehicle license image and returns the printed
vehicle and license fields as a normalized dict. The AI vision provider
is the only strategy — vehicle licenses do not have a machine-readable
zone.
"""
import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are an OCR assistant that reads ambulance / \
vehicle license documents (front and back) and returns the printed \
vehicle and license data as structured JSON.

Rules:
- Read only what is printed on the license. Do not invent or guess.
- For any field you cannot read with confidence, return an empty string.
- For the expiry date, return ISO format YYYY-MM-DD when possible;
  otherwise return the date exactly as printed.
- Output ONLY the JSON object, no commentary, no markdown fences."""


USER_PROMPT = """Extract the ambulance / vehicle license data from this
image.

Respond with ONLY a JSON object with exactly these keys:
{
  "plate_number": "",
  "brand": "",
  "model": "",
  "vehicle_type": "",
  "chassis_number": "",
  "engine_number": "",
  "color": "",
  "owner_name": "",
  "license_expiry": ""
}"""


class MedicalAmbulanceLicenseOcrService(models.AbstractModel):
    """Stateless OCR helper for ambulance / vehicle license documents."""
    _name = 'medical.ambulance.license.ocr.service'
    _description = 'Ambulance License OCR Service'

    @api.model
    def extract(self, image_b64, mime_type='image/jpeg', patient=None):
        if not image_b64:
            raise UserError(_("Please upload an image of the vehicle license first."))

        service = self.env['medical.ai.service']
        text, _log = service._call_vision(
            feature='ambulance_license_ocr',
            system_prompt=SYSTEM_PROMPT,
            user_prompt=USER_PROMPT,
            image_b64=image_b64,
            mime_type=mime_type,
            patient=patient,
            max_tokens=4000,
        )
        data = service._parse_json(text)

        return {
            'plate_number': (data.get('plate_number') or '').strip(),
            'brand': (data.get('brand') or '').strip(),
            'model': (data.get('model') or '').strip(),
            'vehicle_type': (data.get('vehicle_type') or '').strip(),
            'chassis_number': (data.get('chassis_number') or '').strip(),
            'engine_number': (data.get('engine_number') or '').strip(),
            'color': (data.get('color') or '').strip(),
            'owner_name': (data.get('owner_name') or '').strip(),
            'license_expiry': (data.get('license_expiry') or '').strip(),
            'raw_text': text,
        }
