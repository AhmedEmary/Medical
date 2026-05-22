# -*- coding: utf-8 -*-
"""Scan Encounter Documents wizard.

The doctor uploads photos / scans of handwritten encounter notes and / or
the prescription paper. The wizard:

1. Runs OCR + AI extraction through
   :class:`medical.encounter.ocr.service`.
2. Shows the extracted clinical data and prescription lines in an editable
   review screen.
3. On Apply, writes the data onto the encounter — narrative HTML fields
   are written directly; a single :class:`medical.vitals` row is created;
   prescription line records are created on the encounter.

All uploaded images are saved as attachments on the encounter, so the
source documents stay on record.
"""
import base64
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MedicalEncounterScanWizard(models.TransientModel):
    """Multi-image upload → AI extraction → review → Apply."""
    _name = 'medical.encounter.scan.wizard'
    _description = 'Scan Encounter Documents'

    encounter_id = fields.Many2one(
        'medical.encounter', string='Encounter', required=True, readonly=True)
    patient_id = fields.Many2one(
        related='encounter_id.patient_id', readonly=True)

    state = fields.Selection([
        ('upload', 'Upload'),
        ('review', 'Review'),
    ], default='upload', required=True)

    # Multi-file upload via Many2many to ir.attachment. The doctor can drop
    # multiple images (encounter sheet + prescription paper) and they're all
    # sent to the AI in one request.
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'medical_encounter_scan_wizard_attachment_rel',
        'wizard_id', 'attachment_id',
        string='Document Images')

    # Extracted clinical fields — editable on review.
    chief_complaint = fields.Text()
    history_present_illness = fields.Html(sanitize=True)
    physical_exam = fields.Html(sanitize=True)
    therapies_administered = fields.Html(sanitize=True)
    assessment = fields.Html(sanitize=True)
    plan = fields.Html(sanitize=True)
    diagnosis_text = fields.Char(string='Diagnosis (free text)')

    # Vitals.
    bp_systolic = fields.Integer(string='Systolic BP')
    bp_diastolic = fields.Integer(string='Diastolic BP')
    heart_rate = fields.Integer(string='Heart Rate')
    respiratory_rate = fields.Integer(string='Respiratory Rate')
    temperature = fields.Float(string='Temperature (°C)', digits=(3, 1))
    spo2 = fields.Integer(string='SpO₂ (%)')
    glucose = fields.Float(string='Blood Glucose (mg/dL)')
    weight = fields.Float(string='Weight (kg)', digits=(5, 2))
    height = fields.Float(string='Height (cm)', digits=(5, 1))

    # Prescription lines — editable Many2many to a transient mirror so the
    # doctor can review/correct each row before they hit the encounter.
    prescription_line_ids = fields.One2many(
        'medical.encounter.scan.wizard.line', 'wizard_id',
        string='Prescription Lines')

    raw_text = fields.Text(string='Raw AI Output', readonly=True)

    # ============================================================
    # Defaults
    # ============================================================
    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        ctx = self.env.context
        encounter_id = (ctx.get('default_encounter_id')
                        or ctx.get('active_id') if
                        ctx.get('active_model') == 'medical.encounter'
                        else ctx.get('default_encounter_id'))
        if encounter_id:
            vals['encounter_id'] = encounter_id
        return vals

    # ============================================================
    # Actions
    # ============================================================
    def action_scan(self):
        """Send the uploaded images to the AI vision provider and pre-fill
        the review fields with whatever could be extracted."""
        self.ensure_one()
        if not self.attachment_ids:
            raise UserError(_(
                "Please upload at least one image of the encounter notes "
                "or prescription before scanning."))

        images = [
            {'data': att.datas.decode()
                if isinstance(att.datas, bytes) else att.datas,
             'mime_type': att.mimetype or 'image/jpeg'}
            for att in self.attachment_ids if att.datas
        ]
        if not images:
            raise UserError(_(
                "The uploaded attachments contain no image data."))

        data = self.env['medical.encounter.ocr.service'].extract(
            images=images, encounter=self.encounter_id)
        v = data['vitals']
        rx_lines = [
            (0, 0, {
                'product_name': line['product_name'],
                'generic_name': line['generic_name'],
                'frequency': line['frequency'] or False,
                'frequency_other': line['frequency_other'],
                'route': line['route'] or False,
                'duration_days': line['duration_days'],
                'quantity': line['quantity'],
                'instructions': line['instructions'],
            })
            for line in data['prescription_lines']
        ]
        self.write({
            'state': 'review',
            'chief_complaint': data['chief_complaint'],
            'history_present_illness': data['history_present_illness'],
            'physical_exam': data['physical_exam'],
            'therapies_administered': data['therapies_administered'],
            'assessment': data['assessment'],
            'plan': data['plan'],
            'diagnosis_text': data['diagnosis_text'],
            'bp_systolic': v['bp_systolic'] or 0,
            'bp_diastolic': v['bp_diastolic'] or 0,
            'heart_rate': v['heart_rate'] or 0,
            'respiratory_rate': v['respiratory_rate'] or 0,
            'temperature': v['temperature'] or 0.0,
            'spo2': v['spo2'] or 0,
            'glucose': v['glucose'] or 0.0,
            'weight': v['weight'] or 0.0,
            'height': v['height'] or 0.0,
            'prescription_line_ids': [(5, 0, 0)] + rx_lines,
            'raw_text': data.get('raw_text') or '',
        })
        return self._reopen()

    def action_apply(self):
        """Write the reviewed data onto the encounter."""
        self.ensure_one()
        encounter = self.encounter_id

        # --- Narrative fields ---
        encounter_vals = {}
        if self.chief_complaint:
            encounter_vals['chief_complaint'] = self.chief_complaint
        if self.history_present_illness:
            encounter_vals['history_present_illness'] = \
                self.history_present_illness
        if self.physical_exam:
            encounter_vals['physical_exam'] = self.physical_exam
        if self.therapies_administered:
            encounter_vals['therapies_administered'] = \
                self.therapies_administered
        if self.assessment:
            encounter_vals['assessment'] = self.assessment
        if self.plan:
            encounter_vals['plan'] = self.plan
        if encounter_vals:
            encounter.write(encounter_vals)

        # --- Vitals row ---
        vitals_vals = {
            'encounter_id': encounter.id,
            'bp_systolic': self.bp_systolic or False,
            'bp_diastolic': self.bp_diastolic or False,
            'heart_rate': self.heart_rate or False,
            'respiratory_rate': self.respiratory_rate or False,
            'temperature': self.temperature or False,
            'spo2': self.spo2 or False,
            'glucose': self.glucose or False,
            'weight': self.weight or False,
            'height': self.height or False,
        }
        if any(v for k, v in vitals_vals.items() if k != 'encounter_id'):
            self.env['medical.vitals'].create(vitals_vals)

        # --- Prescription lines ---
        for line in self.prescription_line_ids:
            if not line.product_name:
                continue
            self.env['medical.prescription.line'].create({
                'encounter_id': encounter.id,
                'product_name': line.product_name,
                'generic_name': line.generic_name or False,
                'frequency': line.frequency or False,
                'frequency_other': line.frequency_other or False,
                'route': line.route or False,
                'duration_days': line.duration_days or 0,
                'quantity': line.quantity or False,
                'instructions': line.instructions or False,
            })

        # --- Attach the uploaded images to the encounter so the source
        #     stays on record. ---
        for att in self.attachment_ids:
            att.sudo().write({
                'res_model': 'medical.encounter',
                'res_id': encounter.id,
            })

        return {
            'type': 'ir.actions.act_window',
            'name': _('Encounter'),
            'res_model': 'medical.encounter',
            'res_id': encounter.id,
            'view_mode': 'form',
        }

    def action_back_to_upload(self):
        """Return to the upload screen to add/replace images."""
        self.ensure_one()
        self.write({'state': 'upload'})
        return self._reopen()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Scan Encounter Documents'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


class MedicalEncounterScanWizardLine(models.TransientModel):
    """One prescription line on the scan wizard's review screen.

    Mirrors the fields of :class:`medical.prescription.line` so the doctor
    can review and edit each prescribed drug before it lands on the
    encounter. Kept as a transient model — these rows have no meaning
    outside the wizard.
    """
    _name = 'medical.encounter.scan.wizard.line'
    _description = 'Scanned Prescription Line (review)'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'medical.encounter.scan.wizard', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    product_name = fields.Char(string='Drug', required=True)
    generic_name = fields.Char(string='Generic Name')
    frequency = fields.Selection([
        ('once_daily', 'Once daily'),
        ('twice_daily', 'Twice daily (BID)'),
        ('three_times_daily', 'Three times daily (TID)'),
        ('four_times_daily', 'Four times daily (QID)'),
        ('every_4h', 'Every 4 hours'),
        ('every_6h', 'Every 6 hours'),
        ('every_8h', 'Every 8 hours'),
        ('every_12h', 'Every 12 hours'),
        ('weekly', 'Weekly'),
        ('as_needed', 'As needed (PRN)'),
        ('other', 'Other'),
    ])
    frequency_other = fields.Char(string='Frequency (other)')
    route = fields.Selection([
        ('oral', 'Oral'),
        ('iv', 'Intravenous'),
        ('im', 'Intramuscular'),
        ('sc', 'Subcutaneous'),
        ('topical', 'Topical'),
        ('inhalation', 'Inhalation'),
        ('rectal', 'Rectal'),
        ('ophthalmic', 'Ophthalmic'),
        ('otic', 'Otic'),
        ('nasal', 'Nasal'),
    ])
    duration_days = fields.Integer(string='Duration (days)')
    quantity = fields.Char(string='Quantity')
    instructions = fields.Text(string='Instructions')
