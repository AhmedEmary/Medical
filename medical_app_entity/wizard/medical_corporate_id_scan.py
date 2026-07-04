# -*- coding: utf-8 -*-
"""Scan Corporate / Hotel Employee ID wizard.

Reads a company- or hotel-issued employee badge, previews the extracted
fields for review, then applies them to a ``medical.patient`` and links
it to the right ``medical.entity`` (creating one on the fly if the
employer isn't in the system yet).
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


class MedicalCorporateIdScanWizard(models.TransientModel):
    _name = 'medical.corporate.id.scan.wizard'
    _description = 'Scan Corporate / Hotel Employee ID'

    # ------------------------------------------------------------
    # Input
    # ------------------------------------------------------------
    image = fields.Binary(
        string='ID Card Image', attachment=False,
        help="Front of the corporate or hotel employee ID badge.")
    image_filename = fields.Char()
    patient_id = fields.Many2one('medical.patient', string='Patient')

    # ------------------------------------------------------------
    # State + extracted fields
    # ------------------------------------------------------------
    state = fields.Selection([
        ('upload', 'Upload'),
        ('review', 'Review'),
    ], default='upload', required=True)

    employee_name = fields.Char()
    employee_code = fields.Char(string='Employee ID')
    department = fields.Char()
    position = fields.Char(string='Position / Job Title')
    employer_name = fields.Char()
    employer_type = fields.Selection([
        ('hotel', 'Hotel'),
        ('company', 'Corporate Company'),
    ], default='company')
    location = fields.Char(string='Location / City')
    issuer_name = fields.Char()
    issuer_title = fields.Char()
    valid_from = fields.Date()
    valid_to = fields.Date()
    raw_text = fields.Text(readonly=True)

    # Resolved entity (existing match, or blank → will be created on apply)
    entity_id = fields.Many2one(
        'medical.entity', string='Matched Entity',
        help="Existing entity that matches the employer name. "
             "If empty, a new entity will be created on Apply.",
    )
    entity_will_be_created = fields.Boolean(
        compute='_compute_entity_will_be_created')

    @api.depends('entity_id', 'employer_name')
    def _compute_entity_will_be_created(self):
        for rec in self:
            rec.entity_will_be_created = bool(
                not rec.entity_id and rec.employer_name)

    # ------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------
    def action_scan(self):
        self.ensure_one()
        if not self.image:
            raise UserError(_(
                "Please upload a photo of the employee ID card."))
        image_b64 = self.image.decode() if isinstance(
            self.image, bytes) else self.image
        mime = _guess_mime(self.image_filename)

        ocr = self.env['medical.corporate.id.ocr.service']
        result = ocr.extract(
            image_b64=image_b64,
            mime_type=mime,
            patient=self.patient_id or None,
        )
        entity = self._resolve_entity(
            result.get('employer_name'), result.get('employer_type'))

        self.write({
            'state': 'review',
            'employee_name': result.get('employee_name') or '',
            'employee_code': result.get('employee_code') or '',
            'department': result.get('department') or '',
            'position': result.get('position') or '',
            'employer_name': result.get('employer_name') or '',
            'employer_type': result.get('employer_type') or 'company',
            'location': result.get('location') or '',
            'issuer_name': result.get('issuer_name') or '',
            'issuer_title': result.get('issuer_title') or '',
            'valid_from': result.get('valid_from') or False,
            'valid_to': result.get('valid_to') or False,
            'raw_text': result.get('raw_text') or '',
            'entity_id': entity.id if entity else False,
        })
        return self._reopen()

    def action_apply(self):
        """Write reviewed fields to the patient. Creates the patient and/or
        entity when they don't exist yet.
        """
        self.ensure_one()
        entity = self.entity_id or self._create_entity()

        patient = self.patient_id
        if not patient:
            if not self.employee_name:
                raise UserError(_(
                    "No cardholder name was extracted. Fill in "
                    "'Employee Name' before applying."))
            partner = self.env['res.partner'].create({
                'name': self.employee_name,
                'is_patient': True,
            })
            patient = self.env['medical.patient'].create({
                'partner_id': partner.id,
                'name': self.employee_name,
                'patient_category': 'employee',
                'entity_id': entity.id if entity else False,
            })
        else:
            patient_vals = {}
            if self.employee_name and not patient.name:
                patient_vals['name'] = self.employee_name
            if entity:
                patient_vals['entity_id'] = entity.id
            # Force category to employee — that's the point of a corporate
            # ID scan. Even if the current category is external, we flip it.
            if patient.patient_category != 'employee':
                patient_vals['patient_category'] = 'employee'
            if patient_vals:
                patient.write(patient_vals)

        # Fields present on medical.patient via medical_app_entity — guard.
        extra = {}
        if hasattr(patient, 'employee_code') and self.employee_code:
            extra['employee_code'] = self.employee_code
        if hasattr(patient, 'department') and self.department:
            extra['department'] = self.department
        if hasattr(patient, 'job_title') and self.position:
            extra['job_title'] = self.position
        if extra:
            patient.write(extra)

        # Attach source image
        if self.image:
            self.env['ir.attachment'].sudo().create({
                'name': self.image_filename or 'corporate_id',
                'datas': self.image,
                'mimetype': _guess_mime(self.image_filename),
                'res_model': 'medical.patient',
                'res_id': patient.id,
            })

        patient.message_post(body=_(
            "Corporate ID scanned: %s") % ' · '.join(
                b for b in (
                    self.employer_name,
                    self.department,
                    self.position,
                    self.employee_code and _('ID %s') % self.employee_code,
                ) if b))

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
    def _resolve_entity(self, name, employer_type):
        """Try to match an existing medical.entity by (fuzzy) name."""
        if not name:
            return self.env['medical.entity'].browse()
        Entity = self.env['medical.entity']
        # Exact case-insensitive first.
        match = Entity.search(
            [('name', '=ilike', name.strip())], limit=1)
        if match:
            return match
        # Fall back to a contains match on the first meaningful token
        # (e.g. "Triumph Hotel" vs "Triumph Hotel Luxury").
        first_token = name.strip().split()[0] if name.strip() else ''
        if len(first_token) >= 3:
            return Entity.search([('name', 'ilike', first_token)], limit=1)
        return Entity.browse()

    def _create_entity(self):
        """Create a new medical.entity from the extracted employer info."""
        if not self.employer_name:
            return self.env['medical.entity'].browse()
        etype = self.employer_type or 'company'
        # Heuristic override: if the name contains "hotel"/"resort" but the
        # AI said 'company', trust the name.
        lname = self.employer_name.lower()
        if etype != 'hotel' and any(
                word in lname for word
                in ('hotel', 'resort', 'inn', 'suites', 'palace')):
            etype = 'hotel'
        vals = {
            'name': self.employer_name,
            'entity_type': etype,
        }
        if self.location:
            vals['city'] = self.location
        return self.env['medical.entity'].create(vals)

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Scan Corporate ID'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
