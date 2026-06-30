# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class MedicalExternalVisit(models.Model):
    """External Physician Visit Declaration.

    Documents a visit by a physician who is NOT part of the hotel's contracted
    medical team. The hotel records the guest, the external doctor's
    credentials (national ID / passport and medical syndicate card), and
    prints a declaration that liability for the medical care stays with the
    visiting physician.
    """
    _name = 'medical.external.visit'
    _description = 'External Physician Visit'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'visit_date desc, id desc'
    _rec_name = 'reference'

    reference = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        index=True, default=lambda self: _('New'), tracking=True,
    )
    visit_date = fields.Datetime(
        string='Visit Date', default=fields.Datetime.now, tracking=True,
    )
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company)

    # ------------------------------------------------------------
    # Guest information (free text — guest may not be a patient record)
    # ------------------------------------------------------------
    guest_name = fields.Char(string='Guest Name', tracking=True)
    guest_national_id = fields.Char(string='Guest National ID / Passport')
    guest_nationality = fields.Char(string='Guest Nationality')
    room_number = fields.Char(string='Room Number', tracking=True)
    hotel_name = fields.Char(string='Hotel Name')
    guest_passport_image = fields.Binary(
        string='Guest Passport Scan', attachment=True)
    guest_passport_filename = fields.Char()

    # ------------------------------------------------------------
    # External physician information
    # ------------------------------------------------------------
    physician_name = fields.Char(string='Physician Name', tracking=True)
    physician_national_id = fields.Char(
        string='National ID / Passport No.', tracking=True)
    syndicate_no = fields.Char(
        string='Medical Syndicate Registration No.', tracking=True)
    specialty = fields.Char(string='Specialty')
    physician_mobile = fields.Char(string='Mobile Number')
    physician_passport_image = fields.Binary(
        string='Physician Passport Scan', attachment=True)
    physician_passport_filename = fields.Char()
    syndicate_card_image = fields.Binary(
        string='Syndicate Card Scan', attachment=True)
    syndicate_card_filename = fields.Char()

    # ------------------------------------------------------------
    # Ambulance / vehicle license
    # ------------------------------------------------------------
    ambulance_plate_number = fields.Char(string='Plate Number', tracking=True)
    ambulance_brand = fields.Char(string='Vehicle Make / Brand')
    ambulance_model = fields.Char(string='Model / Year')
    ambulance_vehicle_type = fields.Char(string='Vehicle Type')
    ambulance_chassis_number = fields.Char(string='Chassis Number')
    ambulance_engine_number = fields.Char(string='Engine Number')
    ambulance_color = fields.Char(string='Color')
    ambulance_owner_name = fields.Char(string='License Owner Name')
    ambulance_license_expiry = fields.Date(string='License Expiry Date')
    ambulance_license_image = fields.Binary(
        string='Vehicle License Scan', attachment=True)
    ambulance_license_filename = fields.Char()

    # ------------------------------------------------------------
    # Notes / extras
    # ------------------------------------------------------------
    notes = fields.Html(string='Notes')

    # ============================================================
    # CRUD
    # ============================================================
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('reference', _('New')) == _('New'):
                vals['reference'] = self.env['ir.sequence'].next_by_code(
                    'medical.external.visit') or _('New')
        return super().create(vals_list)

    # ============================================================
    # Actions
    # ============================================================
    def action_print_declaration(self):
        self.ensure_one()
        return self.env.ref(
            'medical_app_reports.action_report_external_physician_visit'
        ).report_action(self)