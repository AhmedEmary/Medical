# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MedicalMedication(models.Model):
    """Current medications, vitamins, and supplements for a patient.

    A single model with a 'med_type' discriminator covers all four
    categories from the spec (prescribed, OTC, vitamin, supplement).
    The 'active_treatment' flag distinguishes ongoing from historical.
    """
    _name = 'medical.medication'
    _description = 'Patient Medication / Supplement'
    _order = 'active_treatment desc, start_date desc'
    _rec_name = 'product_name'

    patient_id = fields.Many2one(
        'medical.patient', required=True, ondelete='cascade', index=True,
    )
    med_type = fields.Selection([
        ('prescribed', 'Prescribed'),
        ('otc', 'Over-the-counter'),
        ('vitamin', 'Vitamin'),
        ('supplement', 'Supplement'),
    ], default='prescribed', required=True, index=True)

    # Drug identity - free text now, will link to product.product in Phase 2
    product_name = fields.Char(string='Name', required=True)
    generic_name = fields.Char(string='Generic Name')

    # Dosage details
    dose = fields.Char(string='Dose', help="e.g., 500 mg, 10 ml")
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
    ], default='once_daily')
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
        ('other', 'Other'),
    ], default='oral')

    start_date = fields.Date(default=fields.Date.context_today)
    end_date = fields.Date()
    active_treatment = fields.Boolean(
        string='Currently Taking', default=True, index=True,
    )

    indication = fields.Char(string='Reason / Indication')
    prescribed_by = fields.Char(string='Prescribed By')
    notes = fields.Text()

    @api.onchange('end_date')
    def _onchange_end_date(self):
        if self.end_date and self.end_date < fields.Date.today():
            self.active_treatment = False
