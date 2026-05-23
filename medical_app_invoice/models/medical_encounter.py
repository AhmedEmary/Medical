# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MedicalEncounter(models.Model):
    """Invoicing extension for clinical encounters."""
    _inherit = 'medical.encounter'

    # Bring back the 'invoiced' step. Driven automatically when an
    # invoice linked to the encounter is posted.
    state = fields.Selection(
        selection_add=[('invoiced', 'Invoiced')],
        ondelete={'invoiced': 'set default'},
    )

    invoice_ids = fields.One2many(
        'account.move', 'encounter_id', string='Invoices',
        domain=[('move_type', 'in', ('out_invoice', 'out_refund'))],
    )
    invoice_count = fields.Integer(compute='_compute_invoice_summary')
    invoice_total = fields.Monetary(
        compute='_compute_invoice_summary', currency_field='invoice_currency_id',
        help="Total of non-cancelled invoices linked to this encounter.",
    )
    invoice_residual = fields.Monetary(
        compute='_compute_invoice_summary', currency_field='invoice_currency_id',
        help="Amount still owed across non-cancelled invoices.",
    )
    invoice_currency_id = fields.Many2one(
        'res.currency', compute='_compute_invoice_summary',
    )
    invoice_status = fields.Selection([
        ('none', 'No invoice'),
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('paid', 'Paid'),
    ], compute='_compute_invoice_summary', default='none')

    @api.depends('invoice_ids', 'invoice_ids.state',
                 'invoice_ids.amount_total', 'invoice_ids.amount_residual',
                 'invoice_ids.payment_state', 'invoice_ids.currency_id')
    def _compute_invoice_summary(self):
        company_currency = self.env.company.currency_id
        for rec in self:
            live = rec.invoice_ids.filtered(lambda m: m.state != 'cancel')
            rec.invoice_count = len(live)
            currency = (live[:1].currency_id or company_currency)
            rec.invoice_currency_id = currency.id
            rec.invoice_total = sum(live.mapped('amount_total'))
            rec.invoice_residual = sum(live.mapped('amount_residual'))
            if not live:
                rec.invoice_status = 'none'
            elif all(m.payment_state in ('paid', 'in_payment', 'reversed')
                     for m in live if m.state == 'posted') \
                    and any(m.state == 'posted' for m in live):
                rec.invoice_status = 'paid'
            elif any(m.state == 'posted' for m in live):
                rec.invoice_status = 'posted'
            else:
                rec.invoice_status = 'draft'

    # ============================================================
    # Actions
    # ============================================================
    def action_create_invoice(self):
        """Create an empty draft invoice for the patient and open it.

        No invoice lines are pre-populated — the receptionist fills them
        in directly on the invoice form. Encounter context (chief
        complaint and diagnoses) is copied into the invoice's narration
        for reference.
        """
        self.ensure_one()
        if not self.patient_id:
            raise UserError(_("Cannot invoice an encounter without a patient."))
        partner = self.patient_id.partner_id
        if not partner:
            raise UserError(_(
                "Patient %s has no linked contact. Open the patient form, "
                "save once to auto-create the contact, then try again."
            ) % self.patient_id.display_name)

        narration_bits = []
        if self.chief_complaint:
            narration_bits.append(_("Chief complaint: %s") % self.chief_complaint)
        if self.diagnosis_ids:
            narration_bits.append(_("Diagnosis: %s") % ", ".join(
                "%s %s" % (d.code, d.name) for d in self.diagnosis_ids))

        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'encounter_id': self.id,
            'invoice_date': fields.Date.context_today(self),
            'narration': "\n".join(narration_bits) or False,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoice'),
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_invoices(self):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Invoices'),
            'res_model': 'account.move',
            'domain': [('encounter_id', '=', self.id)],
            'context': {
                'default_encounter_id': self.id,
                'default_partner_id': self.patient_id.partner_id.id
                if self.patient_id else False,
                'default_move_type': 'out_invoice',
            },
        }
        if self.invoice_count == 1:
            action.update({
                'view_mode': 'form',
                'res_id': self.invoice_ids[:1].id,
            })
        else:
            action['view_mode'] = 'list,form'
        return action
