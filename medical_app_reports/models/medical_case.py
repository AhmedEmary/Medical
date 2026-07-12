# -*- coding: utf-8 -*-
from odoo import fields, models


class MedicalCase(models.Model):
    """Report-side additions to the medical case: a print date and the
    button that renders the Medical Condition Report PDF."""
    _inherit = 'medical.case'

    report_date = fields.Date(
        string='Report Date', default=fields.Date.context_today,
        help="Date printed on the Medical Condition Report. Defaults to today.")

    # Arabic mirror of the narrative sections — populated either by hand
    # or by the AI medical-translator button (see medical_app_ai). Rendered
    # by the Arabic Medical Condition Report template.
    name_ar = fields.Char(
        string='Case Title (Arabic)',
        help="Arabic translation of the case title, printed on the Arabic "
             "Medical Condition Report.")
    cause_ar = fields.Html(
        string='Cause of Injury / Illness (Arabic)')
    initial_diagnosis_ar = fields.Html(
        string='Initial Medical Diagnosis (Arabic)')
    current_complaint_ar = fields.Html(
        string='Current Medical Complaint (Arabic)')
    sick_leave_note_ar = fields.Html(
        string='Sick Leave (Arabic)')

    def action_print_case_report(self):
        """Trigger the Medical Condition Report PDF from a form button."""
        return self.env.ref(
            'medical_app_reports.action_report_medical_case'
        ).report_action(self)

    def action_print_case_report_ar(self):
        """Trigger the Arabic Medical Condition Report PDF."""
        return self.env.ref(
            'medical_app_reports.action_report_medical_case_ar'
        ).report_action(self)
