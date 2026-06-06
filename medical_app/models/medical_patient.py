# -*- coding: utf-8 -*-
from datetime import date
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MedicalPatient(models.Model):
    _name = 'medical.patient'
    _description = 'Patient'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_name = 'display_name'

    # ------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------
    mrn = fields.Char(
        string='Medical Record Number',
        required=True, copy=False, readonly=True, index=True,
        default=lambda self: _('New'),
        tracking=True,
    )
    partner_id = fields.Many2one(
        'res.partner', string='Contact',
        ondelete='restrict', tracking=True,
        help="Linked contact in Odoo (used for invoicing and communication). "
             "Auto-created on save if not set, so the ID-scan wizard can "
             "fill it in afterwards.",
    )
    display_name = fields.Char(compute='_compute_display_name', store=True)
    active = fields.Boolean(default=True, tracking=True)

    # ------------------------------------------------------------
    # Personal data
    # ------------------------------------------------------------
    name = fields.Char(related='partner_id.name', store=True, readonly=False)
    image_1920 = fields.Image(related='partner_id.image_1920', readonly=False)
    image_128 = fields.Image(related='partner_id.image_128', readonly=True)
    date_of_birth = fields.Date(string='Date of Birth', tracking=True)
    age = fields.Integer(compute='_compute_age', store=True)
    age_display = fields.Char(compute='_compute_age', store=True)
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    ], tracking=True)
    blood_type = fields.Selection([
        ('a+', 'A+'), ('a-', 'A-'),
        ('b+', 'B+'), ('b-', 'B-'),
        ('ab+', 'AB+'), ('ab-', 'AB-'),
        ('o+', 'O+'), ('o-', 'O-'),
        ('unknown', 'Unknown'),
    ], default='unknown', tracking=True)
    national_id = fields.Char(string='National ID / Passport', tracking=True)
    phone = fields.Char(related='partner_id.phone', readonly=False, store=True)
    mobile = fields.Char(string='Mobile', tracking=True)
    email = fields.Char(related='partner_id.email', readonly=False, store=True)
    country_id = fields.Many2one(related='partner_id.country_id', readonly=False)

    # ------------------------------------------------------------
    # Emergency contact
    # ------------------------------------------------------------
    emergency_contact_name = fields.Char(string='Emergency Contact Name')
    emergency_contact_relation = fields.Char(string='Relationship')
    emergency_contact_phone = fields.Char(string='Emergency Phone')

    # ------------------------------------------------------------
    # Patient category & hotel link
    # ------------------------------------------------------------
    patient_category = fields.Selection([
        ('hotel_guest', 'Hotel Guest'),
        ('employee', 'Employee'),
        ('non_hotel_employee', 'Non-hotel Employee'),
        ('external', 'External Patient'),
    ], string='Patient Category', required=True, default='external', tracking=True)
    hotel_name = fields.Char(string='Hotel',
        help="Name of the hotel the guest is staying at. Printed on the "
             "medical report when the patient category is Hotel Guest.")
    room_number = fields.Char(string='Room Number',
        help="Hotel room number if applicable.")

    # ------------------------------------------------------------
    # Insurance
    # ------------------------------------------------------------
    insurance_provider_id = fields.Many2one(
        'res.partner', string='Insurance Provider',
        domain="[('is_company', '=', True)]",
    )
    insurance_policy_number = fields.Char(string='Policy Number')
    insurance_valid_until = fields.Date(string='Valid Until')
    insurance_assistance_company_id = fields.Many2one(
        'res.partner', string='Assistance Company',
        domain="[('is_company', '=', True)]",
    )
    insurance_franchise = fields.Char(string='Franchise')

    # ------------------------------------------------------------
    # Clinical data (One2many to dedicated models)
    # ------------------------------------------------------------
    medical_history_ids = fields.One2many(
        'medical.history', 'patient_id',
        domain=[('history_type', 'in', ('medical', 'family', 'social'))],
        string='Medical History',
    )
    surgical_history_ids = fields.One2many(
        'medical.history', 'patient_id',
        domain=[('history_type', '=', 'surgical')],
        string='Surgical History',
    )
    allergy_ids = fields.One2many(
        'medical.allergy', 'patient_id', string='Allergies',
    )
    medication_ids = fields.One2many(
        'medical.medication', 'patient_id', string='Medications',
    )
    active_medication_ids = fields.One2many(
        'medical.medication', 'patient_id',
        domain=[('active_treatment', '=', True)],
        string='Active Medications',
    )

    # ------------------------------------------------------------
    # Encounters
    # ------------------------------------------------------------
    encounter_ids = fields.One2many(
        'medical.encounter', 'patient_id', string='Encounters',
    )
    encounter_count = fields.Integer(compute='_compute_encounter_count')
    last_encounter_date = fields.Date(compute='_compute_last_encounter_date', store=True)

    # ------------------------------------------------------------
    # Computed clinical signals (latest vitals)
    # ------------------------------------------------------------
    last_weight = fields.Float(compute='_compute_last_vitals', store=False)
    last_height = fields.Float(compute='_compute_last_vitals', store=False)
    last_bmi = fields.Float(compute='_compute_last_vitals', store=False)

    # ------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------
    notes = fields.Html(string='Private Notes')
    has_critical_allergy = fields.Boolean(
        compute='_compute_has_critical_allergy', store=True,
        help="True if the patient has a severe or anaphylactic allergy.",
    )

    # ============================================================
    # Computed methods
    # ============================================================
    @api.depends('name', 'mrn')
    def _compute_display_name(self):
        for rec in self:
            if rec.mrn and rec.mrn != _('New'):
                rec.display_name = f"[{rec.mrn}] {rec.name or ''}"
            else:
                rec.display_name = rec.name or _('New Patient')

    @api.depends('date_of_birth')
    def _compute_age(self):
        today = date.today()
        for rec in self:
            if rec.date_of_birth:
                delta = relativedelta(today, rec.date_of_birth)
                rec.age = delta.years
                if delta.years >= 2:
                    rec.age_display = f"{delta.years} y"
                elif delta.years >= 1:
                    rec.age_display = f"{delta.years} y {delta.months} m"
                else:
                    rec.age_display = f"{delta.months} m {delta.days} d"
            else:
                rec.age = 0
                rec.age_display = ''

    @api.depends('encounter_ids')
    def _compute_encounter_count(self):
        for rec in self:
            rec.encounter_count = len(rec.encounter_ids)

    @api.depends('encounter_ids', 'encounter_ids.encounter_date')
    def _compute_last_encounter_date(self):
        for rec in self:
            dates = rec.encounter_ids.mapped('encounter_date')
            rec.last_encounter_date = max(dates) if dates else False

    def _compute_last_vitals(self):
        """Pull latest vitals from most recent encounter."""
        for rec in self:
            latest_vital = self.env['medical.vitals'].search([
                ('patient_id', '=', rec.id),
                ('weight', '>', 0),
            ], order='create_date desc', limit=1)
            rec.last_weight = latest_vital.weight or 0.0
            rec.last_height = latest_vital.height or 0.0
            rec.last_bmi = latest_vital.bmi or 0.0

    @api.depends('allergy_ids', 'allergy_ids.severity')
    def _compute_has_critical_allergy(self):
        for rec in self:
            rec.has_critical_allergy = any(
                a.severity in ('severe', 'anaphylaxis') for a in rec.allergy_ids
            )

    # ============================================================
    # Constraints
    # ============================================================
    @api.constrains('date_of_birth')
    def _check_dob(self):
        for rec in self:
            if rec.date_of_birth and rec.date_of_birth > date.today():
                raise ValidationError(_("Date of birth cannot be in the future."))

    # ============================================================
    # CRUD
    # ============================================================
    @api.model_create_multi
    def create(self, vals_list):
        Partner = self.env['res.partner']
        for vals in vals_list:
            if vals.get('mrn', _('New')) == _('New'):
                vals['mrn'] = self.env['ir.sequence'].next_by_code(
                    'medical.patient') or _('New')
            # Auto-create a contact if none was provided so the form can be
            # saved before the ID-scan wizard fills in the patient's name.
            # We also ensure ``name`` is set in vals — it's a stored related
            # field on partner_id.name, and writing an empty value through
            # the inverse violates res.partner's name constraint.
            if not vals.get('partner_id'):
                placeholder = vals.get('name') or _('New Patient')
                partner = Partner.create({
                    'name': placeholder,
                    'is_patient': True,
                })
                vals['partner_id'] = partner.id
                vals['name'] = placeholder
            else:
                Partner.browse(vals['partner_id']).is_patient = True
        return super().create(vals_list)

    # ============================================================
    # Actions
    # ============================================================
    def action_view_encounters(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Encounters'),
            'res_model': 'medical.encounter',
            'view_mode': 'list,form',
            'domain': [('patient_id', '=', self.id)],
            'context': {'default_patient_id': self.id},
        }

    def action_new_encounter(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Encounter'),
            'res_model': 'medical.encounter',
            'view_mode': 'form',
            'context': {'default_patient_id': self.id},
        }
