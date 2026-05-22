# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MedicalHistory(models.Model):
    """Single model for medical, surgical, family, and social history.

    A 'history_type' field discriminates the kind. This keeps the
    UI simple (one One2many per category, filtered by domain) and
    avoids three near-identical tables.
    """
    _name = 'medical.history'
    _description = 'Medical / Surgical History'
    _order = 'date_recorded desc, id desc'
    _rec_name = 'condition'

    patient_id = fields.Many2one(
        'medical.patient', required=True, ondelete='cascade',
        index=True,
    )
    history_type = fields.Selection([
        ('medical', 'Medical'),
        ('surgical', 'Surgical'),
        ('family', 'Family'),
        ('social', 'Social'),
    ], required=True, default='medical', index=True)

    # Common fields
    condition = fields.Char(string='Condition / Procedure', required=True)
    diagnosis_id = fields.Many2one(
        'medical.diagnosis', string='ICD-10 Code',
        help="Optional structured code.",
    )
    date_recorded = fields.Date(string='Date', default=fields.Date.context_today)
    status = fields.Selection([
        ('active', 'Active'),
        ('resolved', 'Resolved'),
        ('chronic', 'Chronic'),
        ('inactive', 'Inactive'),
    ], default='active')
    notes = fields.Text()

    # Surgical-specific
    surgeon_name = fields.Char(string='Surgeon')
    hospital = fields.Char(string='Hospital')
    complications = fields.Text(string='Complications')

    # Family-specific (e.g., "Father - Diabetes")
    family_relation = fields.Char(string='Relation')

    recorded_by = fields.Many2one(
        'res.users', default=lambda self: self.env.user,
        string='Recorded By', readonly=True,
    )

    @api.onchange('diagnosis_id')
    def _onchange_diagnosis(self):
        if self.diagnosis_id and not self.condition:
            self.condition = self.diagnosis_id.name
