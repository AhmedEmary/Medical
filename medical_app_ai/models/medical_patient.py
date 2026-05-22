# -*- coding: utf-8 -*-
"""Patient/Partner button hooks for the Scan ID Document wizard."""
from odoo import _, models


class MedicalPatient(models.Model):
    _inherit = 'medical.patient'

    def action_scan_id_document(self):
        """Open the Scan ID wizard for this patient."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Scan ID Document'),
            'res_model': 'medical.id.scan.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_patient_id': self.id,
                'default_partner_id': self.partner_id.id,
            },
        }


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def action_scan_id_document(self):
        """Open the Scan ID wizard for this contact."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Scan ID Document'),
            'res_model': 'medical.id.scan.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_partner_id': self.id},
        }