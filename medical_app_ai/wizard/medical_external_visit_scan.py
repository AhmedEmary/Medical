# -*- coding: utf-8 -*-
"""Scan wizard for External Physician Visit documents.

Three scan modes share the same form:

- ``guest_passport``: passport / national ID for the hotel guest.
- ``physician_passport``: passport / national ID for the visiting doctor.
- ``syndicate_card``: Egyptian Medical Syndicate registration card.

The wizard uploads an image, runs the matching OCR service, shows the
extracted fields for review, then writes them to the external visit on
Apply.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


SCAN_MODES = [
    ('guest_passport', 'Guest Passport / National ID'),
    ('physician_passport', 'Physician Passport / National ID'),
    ('syndicate_card', 'Medical Syndicate Card'),
]


class MedicalExternalVisitScanWizard(models.TransientModel):
    _name = 'medical.external.visit.scan.wizard'
    _description = 'External Visit Document Scan'

    visit_id = fields.Many2one(
        'medical.external.visit', required=True, ondelete='cascade')
    scan_mode = fields.Selection(
        SCAN_MODES, string='Scan Type', required=True, default='guest_passport')

    state = fields.Selection([
        ('upload', 'Upload'),
        ('review', 'Review'),
    ], default='upload', required=True)

    image = fields.Binary(string='Document Image', attachment=False)
    image_filename = fields.Char()
    raw_text = fields.Text(string='Raw OCR Output', readonly=True)

    # Passport-shaped fields
    full_name = fields.Char(string='Full Name')
    document_number = fields.Char(string='Document Number')
    nationality = fields.Char(help="ISO 3-letter country code.")

    # Syndicate-shaped fields
    syndicate_no = fields.Char(string='Syndicate Registration No.')
    specialty = fields.Char(string='Specialty')
    mobile = fields.Char(string='Mobile')

    # ============================================================
    # Actions
    # ============================================================
    def action_scan(self):
        self.ensure_one()
        if not self.image:
            raise UserError(_("Please upload an image of the document."))

        mime_type = _guess_mime(self.image_filename)
        image_b64 = (self.image.decode() if isinstance(self.image, bytes)
                     else self.image)
        vals = {'state': 'review'}

        if self.scan_mode == 'syndicate_card':
            ocr = self.env['medical.syndicate.ocr.service']
            result = ocr.extract(image_b64=image_b64, mime_type=mime_type)
            vals.update({
                'full_name': result.get('physician_name') or '',
                'syndicate_no': result.get('syndicate_no') or '',
                'specialty': result.get('specialty') or '',
                'document_number': result.get('national_id') or '',
                'mobile': result.get('mobile') or '',
                'raw_text': result.get('raw_text') or '',
            })
        else:
            ocr = self.env['medical.id.ocr.service']
            result = ocr.extract(
                image_b64=image_b64,
                mime_type=mime_type,
                prefer='auto',
            )
            vals.update({
                'full_name': result.get('full_name') or '',
                'document_number': result.get('document_number') or '',
                'nationality': result.get('nationality') or '',
                'raw_text': result.get('raw_text') or '',
            })

        self.write(vals)
        return self._reopen()

    def action_apply(self):
        self.ensure_one()
        visit = self.visit_id
        if not visit:
            raise UserError(_("No external visit linked to this scan."))

        visit_vals = {}
        if self.scan_mode == 'guest_passport':
            if self.full_name:
                visit_vals['guest_name'] = self.full_name
            if self.document_number:
                visit_vals['guest_national_id'] = self.document_number
            if self.nationality:
                visit_vals['guest_nationality'] = self.nationality
            if self.image:
                visit_vals['guest_passport_image'] = self.image
                visit_vals['guest_passport_filename'] = self.image_filename
        elif self.scan_mode == 'physician_passport':
            if self.full_name:
                visit_vals['physician_name'] = self.full_name
            if self.document_number:
                visit_vals['physician_national_id'] = self.document_number
            if self.image:
                visit_vals['physician_passport_image'] = self.image
                visit_vals['physician_passport_filename'] = self.image_filename
        else:  # syndicate_card
            if self.full_name and not visit.physician_name:
                visit_vals['physician_name'] = self.full_name
            if self.syndicate_no:
                visit_vals['syndicate_no'] = self.syndicate_no
            if self.specialty:
                visit_vals['specialty'] = self.specialty
            if self.mobile:
                visit_vals['physician_mobile'] = self.mobile
            if self.document_number and not visit.physician_national_id:
                visit_vals['physician_national_id'] = self.document_number
            if self.image:
                visit_vals['syndicate_card_image'] = self.image
                visit_vals['syndicate_card_filename'] = self.image_filename

        if visit_vals:
            visit.write(visit_vals)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'medical.external.visit',
            'res_id': visit.id,
            'view_mode': 'form',
        }

    def action_back_to_upload(self):
        self.ensure_one()
        self.write({'state': 'upload'})
        return self._reopen()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Scan Document'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


def _guess_mime(filename):
    name = (filename or '').lower()
    if name.endswith('.png'):
        return 'image/png'
    if name.endswith('.webp'):
        return 'image/webp'
    if name.endswith('.heic') or name.endswith('.heif'):
        return 'image/heic'
    if name.endswith('.pdf'):
        return 'application/pdf'
    return 'image/jpeg'