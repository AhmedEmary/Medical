# -*- coding: utf-8 -*-
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MedicalPatient(models.Model):
    _inherit = 'medical.patient'

    entity_id = fields.Many2one(
        'medical.entity', string='Entity',
        ondelete='restrict', index=True, tracking=True,
        help="Hotel or corporate company this patient belongs to. Used to "
             "filter the Hotel Patients, Corporate Patients and External "
             "Patients menus.",
    )
    entity_type = fields.Selection(
        related='entity_id.entity_type', store=True, readonly=True,
        string='Entity Type',
    )
    employee_code = fields.Char(
        string='Employee Code', tracking=True,
        help="Company employee number / staff ID.",
    )
    department = fields.Char(string='Department', tracking=True)
    job_title = fields.Char(string='Position / Job Title', tracking=True)

    # ------------------------------------------------------------
    # Insurance extension
    # ------------------------------------------------------------
    insurance_valid_from = fields.Date(
        string='Valid From', tracking=True,
        help="Date the current insurance coverage began.",
    )
    insurance_tpa_id = fields.Many2one(
        'res.partner', string='TPA (Network)',
        domain="[('is_company', '=', True)]", tracking=True,
        help="Third Party Administrator / hospital network printed on the "
             "insurance card (e.g. Wadi El-Neel, Cleopatra, GlobeMed).",
    )
    insurance_expired = fields.Boolean(
        compute='_compute_insurance_status', store=True,
    )
    insurance_days_left = fields.Integer(
        string='Days Until Expiry',
        compute='_compute_insurance_status', store=True,
    )
    insurance_status = fields.Selection([
        ('none', 'No Insurance'),
        ('active', 'Active'),
        ('expiring', 'Expiring Soon'),
        ('expired', 'Expired'),
    ], compute='_compute_insurance_status', store=True, string='Insurance Status')

    @api.depends('insurance_valid_until', 'insurance_policy_number')
    def _compute_insurance_status(self):
        today = date.today()
        for rec in self:
            has_policy = bool(rec.insurance_policy_number
                              or rec.insurance_provider_id)
            if not rec.insurance_valid_until:
                rec.insurance_days_left = 0
                rec.insurance_expired = False
                rec.insurance_status = 'active' if has_policy else 'none'
                continue
            delta = (rec.insurance_valid_until - today).days
            rec.insurance_days_left = delta
            rec.insurance_expired = delta < 0
            if delta < 0:
                rec.insurance_status = 'expired'
            elif delta <= 30:
                rec.insurance_status = 'expiring'
            else:
                rec.insurance_status = 'active'

    @api.constrains('insurance_valid_from', 'insurance_valid_until')
    def _check_insurance_dates(self):
        for rec in self:
            if (rec.insurance_valid_from and rec.insurance_valid_until
                    and rec.insurance_valid_until < rec.insurance_valid_from):
                raise ValidationError(_(
                    "Insurance 'Valid Until' cannot be earlier than "
                    "'Valid From'."))

    # ------------------------------------------------------------
    # Onchange: entity_id → suggest category and prefill defaults.
    # ------------------------------------------------------------
    @api.onchange('entity_id')
    def _onchange_entity_id(self):
        for rec in self:
            if not rec.entity_id:
                continue
            if rec.entity_id.entity_type == 'hotel':
                if rec.patient_category != 'hotel_guest':
                    rec.patient_category = 'hotel_guest'
            else:
                if rec.patient_category not in (
                        'employee', 'non_hotel_employee'):
                    rec.patient_category = 'employee'
                if (not rec.insurance_provider_id
                        and rec.entity_id.default_insurance_provider_id):
                    rec.insurance_provider_id = \
                        rec.entity_id.default_insurance_provider_id

    @api.constrains('entity_id', 'patient_category')
    def _check_entity_category(self):
        # An external patient with an entity is a data error. Employee and
        # non_hotel_employee can sit under either a hotel or a corporate
        # entity — only guard the external case.
        for rec in self:
            if rec.entity_id and rec.patient_category == 'external':
                raise ValidationError(_(
                    "An external patient cannot be linked to an entity. "
                    "Change the category to Employee or Hotel Guest, or "
                    "unlink the entity."))

    # ------------------------------------------------------------
    # Keep the legacy ``hotel_name`` Char in sync with the entity.
    # We hide the field from the UI but keep it populated so old
    # reports/invoices/kanban references keep working without an
    # exhaustive template rewrite. When the entity changes, hotel_name
    # follows; when the entity is unlinked, we clear the derived value.
    # ------------------------------------------------------------
    def write(self, vals):
        res = super().write(vals)
        if 'entity_id' in vals:
            for rec in self:
                target = (rec.entity_id.name
                          if rec.entity_id
                          and rec.entity_id.entity_type == 'hotel'
                          else False)
                if rec.hotel_name != target:
                    super(MedicalPatient, rec).write({'hotel_name': target})
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if (rec.entity_id and rec.entity_id.entity_type == 'hotel'
                    and rec.hotel_name != rec.entity_id.name):
                super(MedicalPatient, rec).write(
                    {'hotel_name': rec.entity_id.name})
        return records

    def action_scan_corporate_id(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Scan Corporate / Hotel Employee ID'),
            'res_model': 'medical.corporate.id.scan.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_patient_id': self.id},
        }
