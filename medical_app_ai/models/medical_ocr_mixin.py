# -*- coding: utf-8 -*-
"""Shared OCR service pattern.

Every OCR service in this module (ID docs, encounter docs, ambulance license,
syndicate card, insurance card, …) does the same three things:

1. Send an image + prompt to ``medical.ai.service._call_vision``.
2. Parse the JSON response.
3. Normalize it into a stable dict of fields the wizard binds to.

This mixin captures the shape so a new service only has to declare its
prompt, the fields it extracts, and how to normalize the AI's raw JSON.

Existing services aren't migrated in this pass — they work, and migrating
them is a mechanical follow-up that deserves its own diff and tests.

Usage::

    class MyOcr(models.AbstractModel):
        _name = 'medical.my.ocr.service'
        _inherit = 'medical.ocr.mixin'
        _description = 'My Document OCR'

        _ocr_feature = 'my_ocr'          # medical.ai.log feature key
        _ocr_max_tokens = 4000

        def _ocr_result_fields(self):
            return ('some_field', 'other_field', 'raw_text')

        def _ocr_system_prompt(self):
            return "You are an OCR assistant that reads …"

        def _ocr_user_prompt(self):
            return "Extract the following fields as JSON: …"

        def _ocr_normalize(self, data, raw_text):
            return {
                'some_field': (data.get('some_field') or '').strip(),
                'other_field': (data.get('other_field') or '').strip(),
                'raw_text': raw_text,
            }
"""
from odoo import _, api, models
from odoo.exceptions import UserError


class MedicalOcrMixin(models.AbstractModel):
    """AbstractModel that concrete OCR services inherit from.

    Subclasses only need to implement the four ``_ocr_*`` hooks below.
    """
    _name = 'medical.ocr.mixin'
    _description = 'Medical OCR Service Mixin'

    # Log feature key — override on the subclass.
    _ocr_feature = 'ocr_generic'
    # Vision output budget. Reasoning models eat this on hidden tokens,
    # so keep it generous.
    _ocr_max_tokens = 6000

    # ------------------------------------------------------------
    # Hooks — override on the concrete service
    # ------------------------------------------------------------
    def _ocr_result_fields(self):
        """Return the tuple of keys every extraction result must have.

        Missing values default to empty string; keys containing 'date'
        default to False.
        """
        return ()

    def _ocr_system_prompt(self):
        raise NotImplementedError

    def _ocr_user_prompt(self):
        raise NotImplementedError

    def _ocr_normalize(self, data, raw_text):
        """Turn the parsed JSON dict into a stable result dict.

        The base implementation just passes through any keys named in
        ``_ocr_result_fields()`` and coerces them to strings. Override
        for stricter normalization (dates, selections, nested fields).
        """
        result = self._ocr_empty_result()
        for key in self._ocr_result_fields():
            value = data.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                result[key] = value.strip()
            else:
                result[key] = value
        result['raw_text'] = raw_text
        return result

    # ------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------
    @api.model
    def extract(self, image_b64, mime_type='image/jpeg',
                extra_images=None, patient=None, encounter=None):
        """Extract data from an image. Returns a dict shaped by
        :meth:`_ocr_result_fields`, always including ``raw_text``."""
        if not image_b64:
            raise UserError(_("Please upload an image first."))
        service = self.env['medical.ai.service']
        text, log = service._call_vision(
            feature=self._ocr_feature,
            system_prompt=self._ocr_system_prompt(),
            user_prompt=self._ocr_user_prompt(),
            image_b64=image_b64,
            mime_type=mime_type,
            extra_images=extra_images,
            patient=patient,
            encounter=encounter,
            max_tokens=self._ocr_max_tokens,
        )
        data = service._parse_json(text) or {}
        result = self._ocr_normalize(data, text)
        # Guarantee raw_text is present even if a subclass forgets it.
        result.setdefault('raw_text', text)
        return result

    # ------------------------------------------------------------
    # Helpers for subclasses
    # ------------------------------------------------------------
    def _ocr_empty_result(self):
        result = {}
        for key in self._ocr_result_fields():
            result[key] = False if 'date' in key else ''
        return result
