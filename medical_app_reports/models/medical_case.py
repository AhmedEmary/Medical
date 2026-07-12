# -*- coding: utf-8 -*-
from odoo import fields, models


class MedicalCase(models.Model):
    """Report-side additions to the medical case: a print date and the
    button that renders the Medical Condition Report PDF."""
    _inherit = 'medical.case'

    report_date = fields.Date(
        string='Report Date', default=fields.Date.context_today,
        help="Date printed on the Medical Condition Report. Defaults to today.")

    def action_print_case_report(self):
        """Trigger the Medical Condition Report PDF from a form button."""
        return self.env.ref(
            'medical_app_reports.action_report_medical_case'
        ).report_action(self)
