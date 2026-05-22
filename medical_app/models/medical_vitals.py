# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MedicalVitals(models.Model):
    """Vital signs recorded during an encounter.

    Belongs to encounter (not patient) so trends over visits are visible.
    """
    _name = 'medical.vitals'
    _description = 'Vital Signs'
    _order = 'measurement_time desc'
    _rec_name = 'display_name'

    encounter_id = fields.Many2one(
        'medical.encounter', required=True, ondelete='cascade', index=True,
    )
    patient_id = fields.Many2one(
        related='encounter_id.patient_id', store=True, index=True,
    )
    measurement_time = fields.Datetime(
        string='Measurement Time', default=fields.Datetime.now, required=True,
    )
    measured_by = fields.Many2one(
        'res.users', default=lambda self: self.env.user, string='Measured By',
    )
    display_name = fields.Char(compute='_compute_display_name')

    # Blood pressure
    bp_systolic = fields.Integer(string='Systolic BP (mmHg)')
    bp_diastolic = fields.Integer(string='Diastolic BP (mmHg)')
    bp_display = fields.Char(compute='_compute_bp_display', store=True)

    # Other vitals
    heart_rate = fields.Integer(string='Heart Rate (bpm)')
    respiratory_rate = fields.Integer(string='Respiratory Rate (/min)')
    temperature = fields.Float(string='Temperature (°C)', digits=(3, 1))
    spo2 = fields.Integer(string='SpO₂ (%)')
    glucose = fields.Float(string='Blood Glucose (mg/dL)')
    pain_score = fields.Integer(string='Pain Score (0-10)',
        help="Subjective pain assessment, 0 = none, 10 = worst imaginable.")

    # Anthropometrics
    weight = fields.Float(string='Weight (kg)', digits=(5, 2))
    height = fields.Float(string='Height (cm)', digits=(5, 1))
    bmi = fields.Float(string='BMI', compute='_compute_bmi', store=True, digits=(4, 2))
    bmi_category = fields.Char(compute='_compute_bmi', store=True)

    notes = fields.Text()

    # ============================================================
    # Computes
    # ============================================================
    @api.depends('bp_systolic', 'bp_diastolic')
    def _compute_bp_display(self):
        for rec in self:
            if rec.bp_systolic and rec.bp_diastolic:
                rec.bp_display = f"{rec.bp_systolic}/{rec.bp_diastolic}"
            else:
                rec.bp_display = ''

    @api.depends('weight', 'height')
    def _compute_bmi(self):
        for rec in self:
            if rec.weight and rec.height and rec.height > 0:
                height_m = rec.height / 100.0
                rec.bmi = round(rec.weight / (height_m ** 2), 2)
                if rec.bmi < 18.5:
                    rec.bmi_category = 'Underweight'
                elif rec.bmi < 25:
                    rec.bmi_category = 'Normal'
                elif rec.bmi < 30:
                    rec.bmi_category = 'Overweight'
                else:
                    rec.bmi_category = 'Obese'
            else:
                rec.bmi = 0.0
                rec.bmi_category = ''

    @api.depends('measurement_time', 'bp_display')
    def _compute_display_name(self):
        for rec in self:
            ts = fields.Datetime.to_string(rec.measurement_time) if rec.measurement_time else ''
            label = f"Vitals {ts}".strip()
            if rec.bp_display:
                label = f"{label} · BP {rec.bp_display}"
            rec.display_name = label
