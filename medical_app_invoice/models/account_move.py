# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class AccountMove(models.Model):
    """Link customer invoices to a clinical encounter.

    When ``encounter_id`` is set, the patient's identity and insurance
    details are surfaced on the invoice form and printed PDF. The
    encounter itself moves to the ``invoiced`` state once the linked
    invoice is posted.
    """
    _inherit = 'account.move'

    encounter_id = fields.Many2one(
        'medical.encounter', string='Clinical Encounter',
        index=True, ondelete='set null', copy=False,
        help="The clinical encounter that produced this invoice. When set, "
             "the patient's passport and insurance information is printed "
             "on the invoice.",
    )
    is_medical_invoice = fields.Boolean(
        compute='_compute_is_medical_invoice', store=True,
        help="True when the invoice is linked to a clinical encounter — "
             "drives the medical block on the form and PDF.",
    )
    patient_id = fields.Many2one(
        related='encounter_id.patient_id', store=True, readonly=True,
        string='Patient',
    )
    medical_passport = fields.Char(
        related='encounter_id.patient_id.national_id',
        string='Passport / National ID', readonly=True, store=True,
    )
    medical_insurance_provider_id = fields.Many2one(
        related='encounter_id.patient_id.insurance_provider_id',
        string='Insurance Provider', readonly=True, store=True,
    )
    medical_insurance_policy_number = fields.Char(
        related='encounter_id.patient_id.insurance_policy_number',
        string='Policy Number', readonly=True, store=True,
    )

    medical_insurance_valid_until = fields.Date(
        related='encounter_id.patient_id.insurance_valid_until',
        string='Coverage Valid Until', readonly=True, store=True,
    )

    @api.depends('encounter_id')
    def _compute_is_medical_invoice(self):
        for move in self:
            move.is_medical_invoice = bool(move.encounter_id)

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
