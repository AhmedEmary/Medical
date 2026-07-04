# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MedicalEntity(models.Model):
    """A hotel or corporate company that groups patients together.

    Replaces the free-text ``hotel_name`` field on ``medical.patient`` with a
    real record so we can:
      - Filter patients by employer / hotel from a single menu.
      - Attach a contract validity window (front desk flags lapsed contracts).
      - Roll up per-entity patient counts and expiring-insurance alerts.
    """
    _name = 'medical.entity'
    _description = 'Medical Entity (Hotel / Corporate)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    _rec_name = 'name'

    name = fields.Char(required=True, tracking=True, index=True)
    code = fields.Char(
        string='Short Code', tracking=True,
        help="Optional short code used on reports and lists (e.g. 'MICO', 'WEN').",
    )
    entity_type = fields.Selection([
        ('hotel', 'Hotel'),
        ('company', 'Corporate Company'),
    ], required=True, default='company', tracking=True, index=True)
    active = fields.Boolean(default=True, tracking=True)
    partner_id = fields.Many2one(
        'res.partner', string='Contact',
        ondelete='restrict', tracking=True,
        help="Linked res.partner used for invoicing, addresses and contacts. "
             "Auto-created on save if not set.",
    )

    # Contact & address (mirrored on partner_id for reuse)
    phone = fields.Char(related='partner_id.phone', readonly=False, store=True)
    email = fields.Char(related='partner_id.email', readonly=False, store=True)
    website = fields.Char(related='partner_id.website', readonly=False, store=True)
    street = fields.Char(related='partner_id.street', readonly=False, store=True)
    city = fields.Char(related='partner_id.city', readonly=False, store=True)
    country_id = fields.Many2one(
        related='partner_id.country_id', readonly=False, store=True)

    # Contract window
    contract_start = fields.Date(tracking=True)
    contract_end = fields.Date(tracking=True)
    contract_state = fields.Selection([
        ('active', 'Active'),
        ('expiring', 'Expiring Soon'),
        ('expired', 'Expired'),
        ('not_set', 'No Contract Dates'),
    ], compute='_compute_contract_state', store=True, string='Contract Status')

    # Business defaults / discount applied on invoices
    default_insurance_provider_id = fields.Many2one(
        'res.partner', string='Default Insurance Provider',
        domain="[('is_company', '=', True)]",
        help="Suggested on new patients created under this entity.",
    )
    default_discount_pct = fields.Float(
        string='Default Discount %',
        help="Applied by the medical invoicing module on invoices for "
             "patients of this entity, when no per-invoice override is set.",
    )
    notes = fields.Html()

    # Reverse links & stats
    patient_ids = fields.One2many(
        'medical.patient', 'entity_id', string='Patients',
    )
    patient_count = fields.Integer(
        compute='_compute_stats', store=False)
    active_patient_count = fields.Integer(
        compute='_compute_stats', store=False)
    insured_patient_count = fields.Integer(
        compute='_compute_stats', store=False)
    expiring_insurance_count = fields.Integer(
        compute='_compute_stats', store=False,
        help="Patients whose insurance expires in the next 30 days.",
    )

    _sql_constraints = [
        ('code_unique',
         'UNIQUE(code)',
         'The entity short code must be unique.'),
    ]

    # ------------------------------------------------------------
    # Computed
    # ------------------------------------------------------------
    @api.depends('contract_start', 'contract_end')
    def _compute_contract_state(self):
        today = date.today()
        soon = today + timedelta(days=30)
        for rec in self:
            if not rec.contract_start and not rec.contract_end:
                rec.contract_state = 'not_set'
            elif rec.contract_end and rec.contract_end < today:
                rec.contract_state = 'expired'
            elif rec.contract_end and rec.contract_end <= soon:
                rec.contract_state = 'expiring'
            else:
                rec.contract_state = 'active'

    def _compute_stats(self):
        Patient = self.env['medical.patient']
        today = date.today()
        soon = today + timedelta(days=30)
        if not self.ids:
            for rec in self:
                rec.patient_count = 0
                rec.active_patient_count = 0
                rec.insured_patient_count = 0
                rec.expiring_insurance_count = 0
            return

        def _tally(domain, ctx=None):
            src = Patient.with_context(ctx or {})
            grouped = src._read_group(
                domain, groupby=['entity_id'], aggregates=['__count'])
            return {entity.id: count for entity, count in grouped if entity}

        all_counts = _tally(
            [('entity_id', 'in', self.ids)], {'active_test': False})
        active_counts = _tally([('entity_id', 'in', self.ids)])
        insured_counts = _tally([
            ('entity_id', 'in', self.ids),
            ('insurance_policy_number', '!=', False),
        ])
        expiring_counts = _tally([
            ('entity_id', 'in', self.ids),
            ('insurance_valid_until', '>=', today),
            ('insurance_valid_until', '<=', soon),
        ])
        for rec in self:
            rec.patient_count = all_counts.get(rec.id, 0)
            rec.active_patient_count = active_counts.get(rec.id, 0)
            rec.insured_patient_count = insured_counts.get(rec.id, 0)
            rec.expiring_insurance_count = expiring_counts.get(rec.id, 0)

    # ------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------
    @api.constrains('contract_start', 'contract_end')
    def _check_contract_dates(self):
        for rec in self:
            if (rec.contract_start and rec.contract_end
                    and rec.contract_end < rec.contract_start):
                raise ValidationError(_(
                    "Contract end date cannot be before the start date."))

    # ------------------------------------------------------------
    # CRUD — auto-create the linked res.partner
    # ------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        Partner = self.env['res.partner']
        for vals in vals_list:
            if not vals.get('partner_id'):
                partner = Partner.create({
                    'name': vals.get('name') or _('New Entity'),
                    'is_company': True,
                })
                vals['partner_id'] = partner.id
        return super().create(vals_list)

    def write(self, vals):
        # Keep partner name in sync with entity name so contacts search works.
        res = super().write(vals)
        if 'name' in vals:
            for rec in self:
                if rec.partner_id and rec.partner_id.name != rec.name:
                    rec.partner_id.name = rec.name
        # Cascade renames to patients' legacy hotel_name field.
        if 'name' in vals or 'entity_type' in vals:
            Patient = self.env['medical.patient'].sudo()
            for rec in self:
                target = rec.name if rec.entity_type == 'hotel' else False
                patients = Patient.search([('entity_id', '=', rec.id)])
                stale = patients.filtered(lambda p: p.hotel_name != target)
                if stale:
                    stale.write({'hotel_name': target})
        return res

    # ------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------
    def action_view_patients(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s — Patients') % self.name,
            'res_model': 'medical.patient',
            'view_mode': 'kanban,list,form',
            'domain': [('entity_id', '=', self.id)],
            'context': {
                'default_entity_id': self.id,
                'default_patient_category': (
                    'hotel_guest' if self.entity_type == 'hotel'
                    else 'employee'),
            },
        }

    def action_view_expiring_insurance(self):
        self.ensure_one()
        today = date.today()
        soon = today + timedelta(days=30)
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s — Expiring Insurance') % self.name,
            'res_model': 'medical.patient',
            'view_mode': 'list,form',
            'domain': [
                ('entity_id', '=', self.id),
                ('insurance_valid_until', '>=', today),
                ('insurance_valid_until', '<=', soon),
            ],
        }
