# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class AccountMove(models.Model):
    """Link customer invoices to a clinical encounter.

    The patient is resolved either from the linked clinical encounter or,
    when no encounter is set, from the invoice contact when that contact
    is flagged as a patient (``res.partner.is_patient``). Whenever the
    patient can be resolved, identity and insurance details are surfaced
    on the invoice form and printed PDF following standard medical-invoice
    practice.
    """
    _inherit = 'account.move'

    encounter_id = fields.Many2one(
        'medical.encounter', string='Clinical Encounter',
        index=True, ondelete='set null', copy=False,
        help="The clinical encounter that produced this invoice. When set, "
             "the patient's passport and insurance information is printed "
             "on the invoice.",
    )
    patient_id = fields.Many2one(
        'medical.patient', string='Patient',
        compute='_compute_patient_id', store=True, readonly=True, index=True,
    )
    is_medical_invoice = fields.Boolean(
        compute='_compute_is_medical_invoice', store=True,
        help="True when a patient record can be resolved — either via a "
             "linked clinical encounter or because the invoice contact is "
             "a registered patient. Drives the medical block on the form "
             "and PDF.",
    )

    # ------------------------------------------------------------
    # Patient identity (stored related — re-resolves when patient_id
    # changes, e.g. encounter set / contact promoted to patient).
    # ------------------------------------------------------------
    medical_mrn = fields.Char(
        related='patient_id.mrn',
        string='Medical Record Number',
        readonly=True, store=True,
    )
    medical_passport = fields.Char(
        related='patient_id.national_id',
        string='Passport / National ID',
        readonly=True, store=True,
    )
    medical_gender = fields.Selection(
        related='patient_id.gender',
        string='Gender', readonly=True, store=True,
    )
    medical_date_of_birth = fields.Date(
        related='patient_id.date_of_birth',
        string='Date of Birth', readonly=True, store=True,
    )
    medical_age_display = fields.Char(
        related='patient_id.age_display',
        string='Age', readonly=True, store=True,
    )
    medical_mobile = fields.Char(
        related='patient_id.mobile',
        string='Mobile', readonly=True, store=True,
    )
    medical_nationality_id = fields.Many2one(
        related='patient_id.country_id',
        string='Nationality', readonly=True, store=True,
    )
    medical_hotel_name = fields.Char(
        related='patient_id.hotel_name',
        string='Hotel', readonly=True, store=True,
    )
    medical_room_number = fields.Char(
        related='patient_id.room_number',
        string='Room Number', readonly=True, store=True,
    )

    # ------------------------------------------------------------
    # Insurance
    # ------------------------------------------------------------
    medical_insurance_provider_id = fields.Many2one(
        related='patient_id.insurance_provider_id',
        string='Insurance Provider', readonly=True, store=True,
    )
    medical_insurance_policy_number = fields.Char(
        related='patient_id.insurance_policy_number',
        string='Policy Number', readonly=True, store=True,
    )
    medical_reference_number = fields.Char(
        related='patient_id.reference_number',
        string='Reference Number', readonly=True, store=True,
    )
    medical_insurance_valid_until = fields.Date(
        related='patient_id.insurance_valid_until',
        string='Coverage Valid Until', readonly=True, store=True,
    )
    medical_insurance_assistance_company_id = fields.Many2one(
        related='patient_id.insurance_assistance_company_id',
        string='Assistance Company', readonly=True, store=True,
    )
    medical_insurance_franchise = fields.Char(
        related='patient_id.insurance_franchise',
        string='Franchise', readonly=True, store=True,
    )

    # ============================================================
    # Computes
    # ============================================================
    @api.depends('encounter_id', 'encounter_id.patient_id',
                 'partner_id', 'partner_id.is_patient',
                 'partner_id.patient_id')
    def _compute_patient_id(self):
        for move in self:
            if move.encounter_id.patient_id:
                move.patient_id = move.encounter_id.patient_id
            elif move.partner_id.is_patient and move.partner_id.patient_id:
                move.patient_id = move.partner_id.patient_id[:1]
            else:
                move.patient_id = False

    @api.depends('patient_id')
    def _compute_is_medical_invoice(self):
        for move in self:
            move.is_medical_invoice = bool(move.patient_id)

    # ============================================================
    # Actions
    # ============================================================
    def action_view_encounter(self):
        self.ensure_one()
        if not self.encounter_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Clinical Encounter'),
            'res_model': 'medical.encounter',
            'res_id': self.encounter_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_scan_invoice_document(self):
        """Open the Scan Invoice wizard pre-targeted at this draft move."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Scan Invoice Document'),
            'res_model': 'medical.invoice.scan.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_move_id': self.id},
        }

    # ============================================================
    # Push encounter to 'invoiced' when posting; revert on cancel
    # ============================================================
    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        encounters = posted.mapped('encounter_id').filtered(
            lambda e: e.state in ('draft', 'in_progress', 'completed'))
        if encounters:
            encounters.write({'state': 'invoiced'})
        return posted

    def button_cancel(self):
        encounters = self.mapped('encounter_id')
        res = super().button_cancel()
        # If all of the encounter's posted invoices are now cancelled,
        # walk it back to 'completed' so the doctor can re-bill.
        for enc in encounters:
            if enc.state != 'invoiced':
                continue
            live = enc.invoice_ids.filtered(
                lambda m: m.state == 'posted')
            if not live:
                enc.state = 'completed'
        return res