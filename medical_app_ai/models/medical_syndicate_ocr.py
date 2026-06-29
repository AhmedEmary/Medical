# -*- coding: utf-8 -*-
"""Medical Syndicate Card OCR service.

Reads a doctor's Medical Syndicate registration card image and returns a
normalized dict of the physician's credentials. There is no MRZ on these
cards, so the AI vision provider is the only strategy.
"""
import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


RESULT_FIELDS = (
    'physician_name',
    'syndicate_no',
    'specialty',
    'national_id',
    'mobile',
    'raw_text',
)


SYSTEM_PROMPT = """You are an OCR assistant that reads Medical Syndicate \
registration cards (physician licensing cards) and returns the holder's \
credentials as structured JSON.

Rules:
- Read only what is printed on the card. Do not invent or guess.
- For any field you cannot read with confidence, return an empty string.
- Output ONLY the JSON object, no commentary, no markdown fences."""


USER_PROMPT = """Extract the physician's credentials from this Medical
Syndicate card image.

Respond with ONLY a JSON object with exactly these keys:
{
  "physician_name": "",
  "syndicate_no": "",
  "specialty": "",
  "national_id": "",
  "mobile": ""
}"""


class MedicalSyndicateOcrService(models.AbstractModel):
    """Stateless OCR helper for Medical Syndicate registration cards."""
    _name = 'medical.syndicate.ocr.service'
    _description = 'Medical Syndicate Card OCR Service'

    @api.model
    def extract(self, image_b64, mime_type='image/jpeg', patient=None):
        if not image_b64:
            raise UserError(_("Please upload an image of the syndicate card first."))

        service = self.env['medical.ai.service']
        text, _log = service._call_vision(
            feature='syndicate_ocr',
            system_prompt=SYSTEM_PROMPT,
            user_prompt=USER_PROMPT,
            image_b64=image_b64,
            mime_type=mime_type,
            patient=patient,
            max_tokens=4000,
        )
        data = service._parse_json(text)

        return {
            'physician_name': (data.get('physician_name') or '').strip(),
            'syndicate_no': (data.get('syndicate_no') or '').strip(),
            'specialty': (data.get('specialty') or '').strip(),
            'national_id': (data.get('national_id') or '').strip(),
            'mobile': (data.get('mobile') or '').strip(),
            'raw_text': text,
        }