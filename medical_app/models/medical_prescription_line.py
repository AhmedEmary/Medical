# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


# Map our internal frequency keys to daily-dose multipliers used for some
# basic sanity checks on the printed prescription line.
FREQUENCY_PER_DAY = {
    'once_daily': 1,
    'twice_daily': 2,
    'three_times_daily': 3,
    'four_times_daily': 4,
    'every_4h': 6,
    'every_6h': 4,
    'every_8h': 3,
    'every_12h': 2,
    'weekly': 1 / 7.0,
    'as_needed': 0,
    'other': 0,
}


class MedicalPrescriptionLine(models.Model):
    """A single prescribed drug on an encounter.

    Structured (one row per drug) so that the safety checks in
    ``_compute_warning`` can run against the patient's allergies and
    active medications. The free-text ``discharge_medication_notes``
    field on the encounter remains available for narrative commentary
    that does not fit the structured columns.
    """
    _name = 'medical.prescription.line'
    _description = 'Encounter Prescription Line'
    _order = 'encounter_id, sequence, id'
    _rec_name = 'product_name'

    sequence = fields.Integer(default=10)
    encounter_id = fields.Many2one(
        'medical.encounter', required=True, ondelete='cascade', index=True,
    )
    patient_id = fields.Many2one(
        related='encounter_id.patient_id', store=True, index=True,
    )

    product_name = fields.Char(
        string='Drug', required=True,
        help="Drug name including strength, e.g. 'Klacid XL 500 mg'.")
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

    duration_days = fields.Integer(string='Duration (days)')
    quantity = fields.Char(string='Quantity / Dispense',
        help="e.g., 30 tablets, 1 box, 100 ml bottle.")
    refills = fields.Integer(string='Refills', default=0)
    instructions = fields.Text(string='Instructions',
        help="Free-text patient instructions (with food, at bedtime, ...).")

    # ------------------------------------------------------------
    # Safety warnings (computed, non-stored)
    # ------------------------------------------------------------
    warning_severity = fields.Selection([
        ('ok', 'OK'),
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('danger', 'Critical'),
    ], compute='_compute_warning', default='ok',
        help="Highest severity of the warnings raised for this line.")
    warning_message = fields.Text(
        compute='_compute_warning',
        help="Human-readable list of issues detected on this line.")
    has_warning = fields.Boolean(compute='_compute_warning')

    # ============================================================
    # Computes
    # ============================================================
    @api.depends('product_name', 'generic_name', 'frequency',
                 'duration_days', 'patient_id',
                 'patient_id.allergy_ids', 'patient_id.allergy_ids.allergen',
                 'patient_id.allergy_ids.severity',
                 'patient_id.active_medication_ids',
                 'patient_id.active_medication_ids.product_name')
    def _compute_warning(self):
        for line in self:
            issues = []  # list of (severity, text)

            # --- Allergy cross-check ---
            drug_terms = {
                (line.product_name or '').strip().lower(),
                (line.generic_name or '').strip().lower(),
            }
            drug_terms.discard('')
            for allergy in line.patient_id.allergy_ids:
                allergen = (allergy.allergen or '').strip().lower()
                if not allergen:
                    continue
                if any(allergen in term or term in allergen
                       for term in drug_terms):
                    sev = 'danger' if allergy.severity in (
                        'severe', 'anaphylaxis') else 'warning'
                    issues.append((sev, _(
                        "Allergy match: patient is allergic to %(a)s "
                        "(%(s)s).") % {
                            'a': allergy.allergen,
                            's': dict(
                                allergy._fields['severity'].selection
                            ).get(allergy.severity, '')}))

            # --- Duplicate / overlap with active medications ---
            for med in line.patient_id.active_medication_ids:
                med_terms = {
                    (med.product_name or '').strip().lower(),
                    (med.generic_name or '').strip().lower(),
                }
                med_terms.discard('')
                if med_terms & drug_terms:
                    issues.append(('warning', _(
                        "Already on active medication '%s'. Verify "
                        "this is not a duplicate prescription."
                    ) % med.product_name))

            # --- Required-field checks ---
            if not line.frequency or line.frequency == 'other' \
                    and not line.frequency_other:
                issues.append(('warning', _(
                    "Missing or unspecified frequency.")))
            if line.duration_days and line.duration_days < 0:
                issues.append(('warning', _(
                    "Duration cannot be negative.")))
            if line.refills and line.refills < 0:
                issues.append(('warning', _(
                    "Refills cannot be negative.")))

            # --- Pediatric / geriatric advisory ---
            patient_age = line.patient_id.age or 0
            if line.patient_id and patient_age and patient_age < 12:
                issues.append(('info', _(
                    "Pediatric patient (age %s). Verify weight-based dosing."
                ) % patient_age))
            elif patient_age >= 65:
                issues.append(('info', _(
                    "Geriatric patient (age %s). Consider renal/hepatic "
                    "dose adjustment.") % patient_age))

            # Rank severities and pick the worst.
            order = {'ok': 0, 'info': 1, 'warning': 2, 'danger': 3}
            top = 'ok'
            for sev, _txt in issues:
                if order[sev] > order[top]:
                    top = sev
            line.warning_severity = top
            line.warning_message = '\n'.join(
                f"• {text}" for _sev, text in issues) or False
            line.has_warning = bool(issues) and top != 'ok'

    # ============================================================
    # Helpers (used by the printed report)
    # ============================================================
    def _frequency_label(self):
        self.ensure_one()
        if self.frequency == 'other' and self.frequency_other:
            return self.frequency_other
        return dict(self._fields['frequency'].selection).get(
            self.frequency, '') or ''

    def _route_label(self):
        self.ensure_one()
        return dict(self._fields['route'].selection).get(self.route, '') or ''