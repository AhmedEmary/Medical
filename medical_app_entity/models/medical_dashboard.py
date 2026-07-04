# -*- coding: utf-8 -*-
"""Medical dashboard — the app landing page.

A tiny model whose rows are the tiles rendered on the dashboard kanban:
"All Patients", "Hotel Patients", "Corporate Patients", "External
Patients", plus Entities and Today's Encounters. Each tile carries a
computed count and, on click, opens the matching act_window.

The rows themselves are seeded in ``data/medical_dashboard_data.xml``;
users don't create/edit them directly, so the model is not exposed in
menus or forms.
"""
from datetime import date

from odoo import _, api, fields, models


class MedicalDashboardTile(models.Model):
    _name = 'medical.dashboard.tile'
    _description = 'Medical Dashboard Tile'
    _order = 'sequence, id'
    _rec_name = 'name'

    name = fields.Char(required=True, translate=True)
    subtitle = fields.Char(translate=True)
    icon = fields.Char(
        default='users',
        help="Font Awesome icon name (without the 'fa-' prefix).",
    )
    gradient_start = fields.Char(
        default='#2b5876',
        help="Card top-left gradient color (CSS hex).",
    )
    gradient_end = fields.Char(
        default='#4e4376',
        help="Card bottom-right gradient color (CSS hex).",
    )
    sequence = fields.Integer(default=10)
    tile_type = fields.Selection([
        ('all', 'All Patients'),
        ('hotel', 'Hotel Patients'),
        ('corporate', 'Corporate Patients'),
        ('external', 'External Patients'),
        ('entities_hotel', 'Hotels'),
        ('entities_company', 'Corporate Companies'),
        ('encounters_today', "Today's Encounters"),
        ('insurance_expiring', 'Insurance Expiring Soon'),
    ], required=True)
    active = fields.Boolean(default=True)

    # Live count shown big on each card.
    tile_count = fields.Integer(
        compute='_compute_tile_count',
    )

    # ------------------------------------------------------------
    # Counts
    # ------------------------------------------------------------
    def _compute_tile_count(self):
        Patient = self.env['medical.patient']
        Entity = self.env['medical.entity']
        today = date.today()
        for rec in self:
            t = rec.tile_type
            if t == 'all':
                rec.tile_count = Patient.search_count([])
            elif t == 'hotel':
                rec.tile_count = Patient.search_count(
                    [('patient_category', '=', 'hotel_guest')])
            elif t == 'corporate':
                rec.tile_count = Patient.search_count(
                    [('patient_category', '=', 'employee')])
            elif t == 'external':
                rec.tile_count = Patient.search_count(
                    [('patient_category', '=', 'external')])
            elif t == 'entities_hotel':
                rec.tile_count = Entity.search_count(
                    [('entity_type', '=', 'hotel')])
            elif t == 'entities_company':
                rec.tile_count = Entity.search_count(
                    [('entity_type', '=', 'company')])
            elif t == 'encounters_today':
                rec.tile_count = self.env['medical.encounter'].search_count(
                    [('encounter_date', '>=', today)])
            elif t == 'insurance_expiring':
                rec.tile_count = Patient.search_count(
                    [('insurance_status', 'in', ('expired', 'expiring'))])
            else:
                rec.tile_count = 0

    # ------------------------------------------------------------
    # Click-through
    # ------------------------------------------------------------
    def action_open(self):
        """Open the act_window matching this tile."""
        self.ensure_one()
        Actions = self.env['ir.actions.act_window']
        xmlid_by_type = {
            'all': 'medical_app.action_medical_patient',
            'hotel': 'medical_app_entity.action_medical_patient_hotel',
            'corporate': 'medical_app_entity.action_medical_patient_corporate',
            'external': 'medical_app_entity.action_medical_patient_external',
            'entities_hotel': 'medical_app_entity.action_medical_entity_hotel',
            'entities_company':
                'medical_app_entity.action_medical_entity_company',
        }
        xmlid = xmlid_by_type.get(self.tile_type)
        if xmlid:
            return self.env['ir.actions.act_window']._for_xml_id(xmlid)

        if self.tile_type == 'encounters_today':
            today = date.today()
            return {
                'type': 'ir.actions.act_window',
                'name': _("Today's Encounters"),
                'res_model': 'medical.encounter',
                'view_mode': 'list,form',
                'domain': [('encounter_date', '>=', today)],
            }
        if self.tile_type == 'insurance_expiring':
            return {
                'type': 'ir.actions.act_window',
                'name': _('Insurance Expiring or Expired'),
                'res_model': 'medical.patient',
                'view_mode': 'list,form',
                'domain': [
                    ('insurance_status', 'in', ('expired', 'expiring')),
                ],
            }
        return False
