# -*- coding: utf-8 -*-
"""OCR scan hooks for the External Physician Visit form.

Three buttons live on the form:

- **Scan Guest Passport** — runs the existing passport / national ID OCR
  and fills the guest identity fields.
- **Scan Physician Passport** — same OCR, writes to the physician fields.
- **Scan Syndicate Card** — runs the Medical Syndicate Card OCR and fills
  the physician's syndicate number / specialty / name.

Each button opens the same one-step wizard, parameterized by which scan
mode is active (so we don't duplicate the upload+review flow three times).
"""
from odoo import _, models


class MedicalExternalVisit(models.Model):
    _inherit = 'medical.external.visit'

    def _open_scan_wizard(self, mode):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Scan Document'),
            'res_model': 'medical.external.visit.scan.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_visit_id': self.id,
                'default_scan_mode': mode,
            },
        }

    def action_scan_guest_passport(self):
        return self._open_scan_wizard('guest_passport')

    def action_scan_physician_passport(self):
        return self._open_scan_wizard('physician_passport')

    def action_scan_syndicate_card(self):
        return self._open_scan_wizard('syndicate_card')