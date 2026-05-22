# -*- coding: utf-8 -*-
from odoo import fields, models

from .medical_ai_service import PROVIDER_SELECTION


class MedicalAILog(models.Model):
    """Audit trail of every AI request made by the clinical AI layer.

    Records are created (via sudo) by medical.ai.service for every call,
    successful or not, so there is a full history of what was sent, what
    came back, and whether the clinician accepted the suggestion.
    """
    _name = 'medical.ai.log'
    _description = 'Medical AI Request Log'
    _order = 'create_date desc'

    feature = fields.Selection([
        ('report_draft', 'Report Draft'),
        ('diagnosis_suggest', 'Diagnosis Suggestion'),
        ('history_summary', 'Patient Summary'),
        ('safety_check', 'Safety Check'),
        ('id_ocr', 'ID Document OCR'),
        ('encounter_ocr', 'Encounter Document OCR'),
        # Kept so old log rows from before the SOAP feature was removed
        # still display a label instead of a blank cell.
        ('soap_draft', 'SOAP Note Draft (legacy)'),
    ], string='Feature', required=True, index=True, readonly=True)
    provider = fields.Selection(
        PROVIDER_SELECTION, string='Provider', index=True, readonly=True)
    model = fields.Char(string='Model', readonly=True)
    encounter_id = fields.Many2one(
        'medical.encounter', string='Encounter',
        ondelete='set null', index=True, readonly=True,
    )
    patient_id = fields.Many2one(
        'medical.patient', string='Patient',
        ondelete='set null', index=True, readonly=True,
    )
    user_id = fields.Many2one(
        'res.users', string='Requested By', readonly=True,
        default=lambda self: self.env.user,
    )
    request_summary = fields.Text(string='Prompt', readonly=True)
    response = fields.Text(string='AI Response', readonly=True)
    input_tokens = fields.Integer(readonly=True)
    output_tokens = fields.Integer(readonly=True)
    state = fields.Selection([
        ('success', 'Success'),
        ('error', 'Error'),
    ], string='Status', default='error', required=True, index=True, readonly=True)
    error_message = fields.Text(readonly=True)
    applied = fields.Boolean(
        string='Accepted by Clinician',
        help="Set when the clinician applied this suggestion to the record.",
    )
