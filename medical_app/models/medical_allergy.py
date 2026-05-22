# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MedicalAllergy(models.Model):
    """Patient allergies.

    Kept as a dedicated model (not free text) because Phase 3 AI
    safety checks must reliably cross-reference structured data.
    """
    _name = 'medical.allergy'
    _description = 'Patient Allergy'
    _order = 'severity desc, allergen'

    patient_id = fields.Many2one(
        'medical.patient', required=True, ondelete='cascade', index=True,
    )
    allergen = fields.Char(required=True,
        help="Substance the patient is allergic to (drug, food, environmental).")
    allergen_type = fields.Selection([
        ('drug', 'Drug'),
        ('food', 'Food'),
        ('environmental', 'Environmental'),
        ('contact', 'Contact'),
        ('other', 'Other'),
    ], default='drug', required=True)
    reaction = fields.Char(string='Reaction',
        help="e.g., rash, swelling, anaphylaxis, GI upset.")
    severity = fields.Selection([
        ('mild', 'Mild'),
        ('moderate', 'Moderate'),
        ('severe', 'Severe'),
        ('anaphylaxis', 'Anaphylaxis'),
    ], default='moderate', required=True, index=True)
    onset_date = fields.Date(string='First Noted')
    notes = fields.Text()
    verified = fields.Boolean(string='Verified',
        help="Confirmed by physician (not just patient-reported).")

    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('allergen', 'severity')
    def _compute_display_name(self):
        sev_dict = dict(self._fields['severity'].selection)
        for rec in self:
            sev = sev_dict.get(rec.severity, '')
            rec.display_name = f"{rec.allergen} ({sev})" if rec.allergen else sev
