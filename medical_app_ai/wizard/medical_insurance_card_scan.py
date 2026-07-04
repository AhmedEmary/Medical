# -*- coding: utf-8 -*-
"""Scan Insurance Card wizard.

Reception uploads a photo of a private insurance card, the wizard runs
vision OCR through ``medical.insurance.card.ocr.service``, and shows the
extracted fields for review. On Apply, the fields are written to a
``medical.patient`` (and optionally a matching ``res.partner`` for the
insurance underwriter).
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


MIME_BY_EXT = {
    'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
    'png': 'image/png', 'webp': 'image/webp',
    'gif': 'image/gif', 'bmp': 'image/bmp', 'tiff': 'image/tiff',
    'pdf': 'application/pdf',
}


def _guess_mime(filename):
    if not filename:
        return 'image/jpeg'
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return MIME_BY_EXT.get(ext, 'image/jpeg')


class MedicalInsuranceCardScanWizard(models.TransientModel):
    _name = 'medical.insurance.card.scan.wizard'
    _description = 'Scan Insurance Card'

    # ------------------------------------------------------------
    # Input
    # ------------------------------------------------------------
    image_front = fields.Binary(
        string='Card Front', attachment=False,
        help="Front of the insurance card.")
    image_front_filename = fields.Char()
    image_back = fields.Binary(
        string='Card Back', attachment=False,
        help="Optional — back of the card if it carries the policy number "
             "or copay percentages.")
    image_back_filename = fields.Char()

    patient_id = fields.Many2one('medical.patient', string='Patient')

    # ------------------------------------------------------------
    # State + extracted fields
    # ------------------------------------------------------------
    state = fields.Selection([
        ('upload', 'Upload'),
        ('review', 'Review'),
    ], default='upload', required=True)

    policy_holder_name = fields.Char(string='Cardholder Name')
    insurance_company = fields.Char(string='Insurance Company')
    plan_name = fields.Char(string='Plan')
    network_name = fields.Char(string='Network / TPA')
    policy_number = fields.Char(string='Policy Number')
    employee_code = fields.Char(string='Employee Code')
    department = fields.Char()
    valid_from = fields.Date()
    valid_to = fields.Date()
    copay_outpatient_pct = fields.Float(
        string='Outpatient Copay %',
        help="Patient share on outpatient services, in percent (10 = 10%).",
    )
    copay_medication_pct = fields.Float(string='Medication Copay %')
    copay_chronic_pct = fields.Float(string='Chronic Copay %')
    room_class = fields.Char(string='Room Class')
    covered_hospitals = fields.Text()
    notes = fields.Text()
    raw_text = fields.Text(readonly=True)

    # Resolved link to an existing insurance provider partner
    insurance_provider_id = fields.Many2one(
        'res.partner', string='Insurance Provider (resolved)',
        domain="[('is_company', '=', True)]",
    )

    # ------------------------------------------------------------
    # Defaults from context
    # ------------------------------------------------------------
    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        ctx = self.env.context
        if ctx.get('default_patient_id') or ctx.get('active_patient_id'):
            vals['patient_id'] = (ctx.get('default_patient_id')
                                  or ctx.get('active_patient_id'))
        return vals

    # ------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------
    def action_scan(self):
        """Run OCR on the uploaded image(s) and switch to review."""
        self.ensure_one()
        if not self.image_front:
            raise UserError(_(
                "Please upload the front of the insurance card first."))

        image_b64 = self.image_front.decode() if isinstance(
            self.image_front, bytes) else self.image_front
        mime = _guess_mime(self.image_front_filename)

        extra_images = []
        if self.image_back:
            back = self.image_back.decode() if isinstance(
                self.image_back, bytes) else self.image_back
            extra_images.append({
                'data': back,
                'mime_type': _guess_mime(self.image_back_filename),
            })

        ocr = self.env['medical.insurance.card.ocr.service']
        result = ocr.extract(
            image_b64=image_b64,
            mime_type=mime,
            extra_images=extra_images,
            patient=self.patient_id or None,
        )
        provider = self._resolve_provider(result.get('insurance_company'))

        self.write({
            'state': 'review',
            'policy_holder_name': result.get('policy_holder_name') or '',
            'insurance_company': result.get('insurance_company') or '',
            'plan_name': result.get('plan_name') or '',
            'network_name': result.get('network_name') or '',
            'policy_number': result.get('policy_number') or '',
            'employee_code': result.get('employee_code') or '',
            'department': result.get('department') or '',
            'valid_from': result.get('valid_from') or False,
            'valid_to': result.get('valid_to') or False,
            'copay_outpatient_pct': result.get('copay_outpatient_pct') or 0.0,
            'copay_medication_pct': result.get('copay_medication_pct') or 0.0,
            'copay_chronic_pct': result.get('copay_chronic_pct') or 0.0,
            'room_class': result.get('room_class') or '',
            'covered_hospitals': result.get('covered_hospitals') or '',
            'notes': result.get('notes') or '',
            'raw_text': result.get('raw_text') or '',
            'insurance_provider_id': provider.id if provider else False,
        })
        return self._reopen()

    def action_apply(self):
        """Write the reviewed fields onto the patient (creating one if none)."""
        self.ensure_one()
        patient = self.patient_id
        if not patient:
            if not self.policy_holder_name:
                raise UserError(_(
                    "No cardholder name was extracted. Fill in "
                    "'Cardholder Name' or open the wizard from an existing "
                    "patient record."))
            partner = self.env['res.partner'].create({
                'name': self.policy_holder_name,
                'is_patient': True,
            })
            patient = self.env['medical.patient'].create({
                'partner_id': partner.id,
                'name': self.policy_holder_name,
            })

        # Resolve or create the insurance provider partner if none matched
        provider = self.insurance_provider_id
        if not provider and self.insurance_company:
            provider = self._resolve_provider(self.insurance_company)
            if not provider:
                provider = self.env['res.partner'].create({
                    'name': self.insurance_company,
                    'is_company': True,
                })

        patient_vals = {}
        if provider:
            patient_vals['insurance_provider_id'] = provider.id
        if self.policy_number:
            patient_vals['insurance_policy_number'] = self.policy_number
        if self.valid_to:
            patient_vals['insurance_valid_until'] = self.valid_to
        # These fields ship with medical_app_entity — guard with hasattr
        # so the wizard still works when only medical_app_ai is installed.
        if hasattr(patient, 'insurance_valid_from') and self.valid_from:
            patient_vals['insurance_valid_from'] = self.valid_from
        if hasattr(patient, 'insurance_tpa_id') and self.network_name:
            tpa = self._resolve_provider(self.network_name)
            if not tpa:
                tpa = self.env['res.partner'].create({
                    'name': self.network_name,
                    'is_company': True,
                })
            patient_vals['insurance_tpa_id'] = tpa.id
        if hasattr(patient, 'employee_code') and self.employee_code:
            patient_vals['employee_code'] = self.employee_code
        if hasattr(patient, 'department') and self.department:
            patient_vals['department'] = self.department
        if patient_vals:
            patient.write(patient_vals)

        # Post an audit note on the patient chatter summarising the scan
        summary_bits = [
            self.insurance_company or self.network_name or _('Unknown insurer'),
            self.plan_name or '',
            self.policy_number and _('Policy %s') % self.policy_number or '',
            self.valid_from and self.valid_to
                and _('Valid %s → %s') % (self.valid_from, self.valid_to)
                or '',
        ]
        patient.message_post(
            body=_("Insurance card scanned: %s") % ' · '.join(
                b for b in summary_bits if b),
        )

        # Attach source images
        self._attach_documents(patient)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'medical.patient',
            'res_id': patient.id,
            'view_mode': 'form',
        }

    def action_back_to_upload(self):
        self.ensure_one()
        self.write({'state': 'upload'})
        return self._reopen()

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------
    def _resolve_provider(self, name):
        """Best-effort match on the insurance company name."""
        if not name:
            return self.env['res.partner'].browse()
        Partner = self.env['res.partner']
        # Exact insensitive first.
        exact = Partner.search([
            ('is_company', '=', True),
            ('name', '=ilike', name.strip()),
        ], limit=1)
        if exact:
            return exact
        # Fall back to contains match on the first meaningful token.
        first_token = name.strip().split()[0] if name.strip() else ''
        if len(first_token) >= 3:
            return Partner.search([
                ('is_company', '=', True),
                ('name', 'ilike', first_token),
            ], limit=1)
        return Partner.browse()

    def _attach_documents(self, patient):
        Attachment = self.env['ir.attachment'].sudo()
        common = {
            'res_model': 'medical.patient',
            'res_id': patient.id,
        }
        if self.image_front:
            Attachment.create({
                **common,
                'name': self.image_front_filename or 'insurance_card_front',
                'datas': self.image_front,
                'mimetype': _guess_mime(self.image_front_filename),
            })
        if self.image_back:
            Attachment.create({
                **common,
                'name': self.image_back_filename or 'insurance_card_back',
                'datas': self.image_back,
                'mimetype': _guess_mime(self.image_back_filename),
            })

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Scan Insurance Card'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
