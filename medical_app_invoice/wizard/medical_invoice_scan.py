# -*- coding: utf-8 -*-
"""Scan Invoice Document wizard.

Reception uploads an image of a printed / handwritten invoice and the
wizard:

1. Runs AI vision OCR through :class:`medical.invoice.ocr.service`.
2. Shows the extracted header (invoice number, dates, payment terms,
   patient information) and invoice lines (description, quantity, unit
   price, amount) in an editable review screen.
3. On Apply, writes the data onto the target ``account.move`` —
   updating header fields and replacing / appending invoice lines.

When no target invoice is passed the wizard creates a draft customer
invoice and lands the user on it.

The flow mirrors :mod:`medical_app_ai.wizard.medical_encounter_scan` /
:mod:`medical_app_ai.wizard.medical_id_scan` so the receptionist sees a
consistent ``upload → review → apply`` experience across the app.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MedicalInvoiceScanWizard(models.TransientModel):
    """Multi-image upload → AI extraction → review → Apply."""
    _name = 'medical.invoice.scan.wizard'
    _description = 'Scan Invoice Document'

    move_id = fields.Many2one(
        'account.move', string='Invoice',
        ondelete='cascade',
        help="The draft invoice the extracted data will be applied to. "
             "When empty, the wizard creates a new draft customer invoice.")

    state = fields.Selection([
        ('upload', 'Upload'),
        ('review', 'Review'),
    ], default='upload', required=True)

    # Multi-file upload via Many2many to ir.attachment — receptionist can
    # drop the invoice plus any supporting sheets in one shot.
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'medical_invoice_scan_wizard_attachment_rel',
        'wizard_id', 'attachment_id',
        string='Invoice Images')

    # ------------------------------------------------------------
    # Header (editable on review)
    # ------------------------------------------------------------
    invoice_number = fields.Char(string='Invoice Number')
    invoice_date = fields.Date()
    due_date = fields.Date()
    currency_id = fields.Many2one('res.currency', string='Currency')
    payment_term_id = fields.Many2one(
        'account.payment.term', string='Payment Terms')
    payment_terms_text = fields.Char(
        string='Payment Terms (text)',
        help="Raw payment-terms phrase as printed on the invoice. "
             "Shown for reference when no matching record exists.")
    narration = fields.Html(sanitize=True, string='Notes')

    # ------------------------------------------------------------
    # Patient information (extracted but not auto-applied — kept for
    # display so the receptionist can verify the invoice belongs to
    # the right patient).
    # ------------------------------------------------------------
    patient_name = fields.Char()
    patient_id_number = fields.Char(string='Passport / National ID')
    hotel_name = fields.Char()
    room_number = fields.Char()

    # ------------------------------------------------------------
    # Totals reported by the AI — read-only, for the receptionist to
    # cross-check the extracted lines against the printed total.
    # ------------------------------------------------------------
    ocr_subtotal = fields.Float(
        string='Reported Subtotal', readonly=True, digits=(16, 2))
    ocr_tax_total = fields.Float(
        string='Reported Tax', readonly=True, digits=(16, 2))
    ocr_total = fields.Float(
        string='Reported Total', readonly=True, digits=(16, 2))
    lines_total = fields.Float(
        string='Sum of Lines', compute='_compute_lines_total', digits=(16, 2))

    line_ids = fields.One2many(
        'medical.invoice.scan.wizard.line', 'wizard_id',
        string='Invoice Lines')

    raw_text = fields.Text(string='Raw AI Output', readonly=True)

    @api.depends('line_ids.subtotal')
    def _compute_lines_total(self):
        for rec in self:
            rec.lines_total = sum(rec.line_ids.mapped('subtotal'))

    # ============================================================
    # Defaults — when launched from an account.move form, pre-fill
    # the target invoice from the context.
    # ============================================================
    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        ctx = self.env.context
        move_id = ctx.get('default_move_id')
        if not move_id and ctx.get('active_model') == 'account.move':
            move_id = ctx.get('active_id')
        if move_id:
            vals['move_id'] = move_id
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
                "Please upload at least one image of the invoice before "
                "scanning."))

        images = [
            {'data': att.datas.decode()
                if isinstance(att.datas, bytes) else att.datas,
             'mime_type': att.mimetype or 'image/jpeg'}
            for att in self.attachment_ids if att.datas
        ]
        if not images:
            raise UserError(_(
                "The uploaded attachments contain no image data."))

        data = self.env['medical.invoice.ocr.service'].extract(
            images=images, move=self.move_id or None)

        currency = self._resolve_currency(data.get('currency'))
        payment_term = self._resolve_payment_term(data.get('payment_terms'))

        line_vals = [
            (0, 0, {
                'description': line['description'],
                'quantity': line['quantity'] or 1.0,
                'price_unit': line['price_unit'] or 0.0,
            })
            for line in data['lines']
        ]
        self.write({
            'state': 'review',
            'invoice_number': data.get('invoice_number') or '',
            'invoice_date': _date_or_false(data.get('invoice_date')),
            'due_date': _date_or_false(data.get('due_date')),
            'currency_id': currency.id if currency else False,
            'payment_term_id': payment_term.id if payment_term else False,
            'payment_terms_text': data.get('payment_terms') or '',
            'narration': _wrap_narration(data.get('narration')),
            'patient_name': data.get('patient_name') or '',
            'patient_id_number': data.get('patient_id_number') or '',
            'hotel_name': data.get('hotel_name') or '',
            'room_number': data.get('room_number') or '',
            'ocr_subtotal': data.get('subtotal') or 0.0,
            'ocr_tax_total': data.get('tax_total') or 0.0,
            'ocr_total': data.get('total') or 0.0,
            'line_ids': [(5, 0, 0)] + line_vals,
            'raw_text': data.get('raw_text') or '',
        })
        return self._reopen()

    def action_apply(self):
        """Write the reviewed data onto the target invoice.

        Two entry points:

        - **Existing draft invoice** (launched from the invoice form):
          update its header fields and append the extracted lines.
        - **Standalone** (no target): create a fresh draft customer
          invoice with the extracted data and open it.
        """
        self.ensure_one()
        move = self.move_id

        if move and move.state != 'draft':
            raise UserError(_(
                "Invoice %s is not in draft and cannot be modified by the "
                "scan wizard. Reset it to draft first.") % move.display_name)

        move_vals = self._build_move_vals()
        line_cmds = self._build_line_commands()

        if not move:
            move_vals.update({
                'move_type': 'out_invoice',
            })
            if line_cmds:
                move_vals['invoice_line_ids'] = line_cmds
            move = self.env['account.move'].create(move_vals)
        else:
            if move_vals:
                move.write(move_vals)
            if line_cmds:
                move.write({'invoice_line_ids': line_cmds})

        # Attach the uploaded images to the move so the source document
        # stays on record.
        for att in self.attachment_ids:
            att.sudo().write({
                'res_model': 'account.move',
                'res_id': move.id,
            })

        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoice'),
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
        }

    def action_back_to_upload(self):
        """Return to the upload screen to add/replace images."""
        self.ensure_one()
        self.write({'state': 'upload'})
        return self._reopen()

    # ============================================================
    # Helpers
    # ============================================================
    def _build_move_vals(self):
        """Header vals that should be written to the target move."""
        vals = {}
        if self.invoice_number:
            vals['ref'] = self.invoice_number
        if self.invoice_date:
            vals['invoice_date'] = self.invoice_date
        if self.due_date:
            vals['invoice_date_due'] = self.due_date
        if self.currency_id:
            vals['currency_id'] = self.currency_id.id
        if self.payment_term_id:
            vals['invoice_payment_term_id'] = self.payment_term_id.id
        if self.narration:
            vals['narration'] = self.narration
        return vals

    def _build_line_commands(self):
        """Build ``invoice_line_ids`` create commands for the move."""
        cmds = []
        for line in self.line_ids:
            if not line.description:
                continue
            cmds.append((0, 0, {
                'name': line.description,
                'quantity': line.quantity or 1.0,
                'price_unit': line.price_unit or 0.0,
            }))
        return cmds

    @api.model
    def _resolve_currency(self, code):
        """Look up an active currency by ISO code; return empty recordset
        if nothing matches."""
        if not code:
            return self.env['res.currency'].browse()
        return self.env['res.currency'].search(
            [('name', '=', code.upper())], limit=1)

    @api.model
    def _resolve_payment_term(self, text):
        """Match a printed payment-terms phrase to an account.payment.term
        record. Falls back to the 'Immediate Payment' record for common
        synonyms and to a name ilike search otherwise."""
        if not text:
            return self.env['account.payment.term'].browse()
        normalized = text.strip().lower()
        if any(k in normalized for k in (
                'immediate', 'on receipt', 'due upon receipt', 'cash')):
            term = self.env.ref(
                'account.account_payment_term_immediate',
                raise_if_not_found=False)
            if term:
                return term
        return self.env['account.payment.term'].search(
            [('name', 'ilike', text.strip())], limit=1)

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Scan Invoice Document'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


class MedicalInvoiceScanWizardLine(models.TransientModel):
    """One invoice line on the scan wizard's review screen.

    Mirrors the editable fields of ``account.move.line`` (description,
    quantity, unit price) so the receptionist can review each row before
    it lands on the invoice. Account, product and taxes are NOT extracted
    — Odoo's standard onchanges/defaults fill them in when the lines are
    actually created on the move.
    """
    _name = 'medical.invoice.scan.wizard.line'
    _description = 'Scanned Invoice Line (review)'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'medical.invoice.scan.wizard', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    description = fields.Char(string='Description', required=True)
    quantity = fields.Float(default=1.0, digits=(16, 2))
    price_unit = fields.Float(string='Unit Price', digits=(16, 2))
    subtotal = fields.Float(
        compute='_compute_subtotal', digits=(16, 2), string='Amount')

    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        for rec in self:
            rec.subtotal = (rec.quantity or 0.0) * (rec.price_unit or 0.0)


def _date_or_false(value):
    if not value:
        return False
    from datetime import datetime
    try:
        return datetime.strptime(value[:10], '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return False


def _wrap_narration(text):
    """Wrap a free-text note in a single <p> for the Html field."""
    if not text:
        return ''
    return '<p>%s</p>' % text.replace('\n', '<br/>')