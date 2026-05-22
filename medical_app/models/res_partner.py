# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_patient = fields.Boolean(string='Is a Patient', default=False, index=True)
    patient_id = fields.One2many(
        'medical.patient', 'partner_id', string='Patient Record',
    )
    patient_count = fields.Integer(compute='_compute_patient_count')

    @api.depends('patient_id')
    def _compute_patient_count(self):
        for partner in self:
            partner.patient_count = len(partner.patient_id)

    def action_view_patient(self):
        self.ensure_one()
        patient = self.patient_id[:1]
        if not patient:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': 'Patient Record',
            'res_model': 'medical.patient',
            'res_id': patient.id,
            'view_mode': 'form',
            'target': 'current',
        }
