# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


# Triage palette → background / text / dot colours for the urgency pill
# on the printed report. One entry per ``urgency_level`` selection key.
URGENCY_PALETTE = {
    'red':    {'bg': '#fdecea', 'fg': '#c62828', 'dot': '#d9534f'},
    'orange': {'bg': '#fef0e6', 'fg': '#c66318', 'dot': '#ed8c3a'},
    'yellow': {'bg': '#fff8e1', 'fg': '#8a6d3b', 'dot': '#f0ad4e'},
    'green':  {'bg': '#e8f5e9', 'fg': '#2e7d32', 'dot': '#5cb85c'},
    'blue':   {'bg': '#e3f2fd', 'fg': '#1565c0', 'dot': '#3a78c2'},
}
NEUTRAL_PALETTE = {'bg': '#eef2f5', 'fg': '#475569', 'dot': '#94a3b8'}


class MedicalEncounter(models.Model):
    """Encounter fields specific to the printed medical report.

    Everything the report shows comes from the encounter, the patient or
    the company — these are the few sections that have no natural home in
    the base clinical model. Reused as-is from medical_app:

    * Clinical summary       -> ``history_present_illness``
    * Medical recommendation -> ``plan``
    * Patient history bullet -> ``patient_id.medical_history_ids``
    * Vital signs table      -> ``vitals_ids``
    * Diagnoses              -> ``diagnosis_ids``
    * Doctor / signature     -> ``doctor_id``
    """
    _inherit = 'medical.encounter'

    urgency_level = fields.Selection([
        ('red', 'Red – Immediate'),
        ('orange', 'Orange – Very Urgent'),
        ('yellow', 'Yellow – Urgent'),
        ('green', 'Green – Standard'),
        ('blue', 'Blue – Deferred Urgency'),
    ], string='Urgency Level', default='green', tracking=True,
        help="Triage colour shown on the medical report.")

    investigations_performed = fields.Html(
        string='Investigations Performed',
        help="Labs, imaging and bedside tests performed during the "
             "encounter and their results. Printed under "
             "'Investigations Performed' on the report.")

    therapies_administered = fields.Html(
        string='Therapies Administered',
        help="What was given to the patient during the visit "
             "(IV fluids, injections, etc.). Printed under "
             "'Therapies Administered' on the report.")

    discharge_medication_notes = fields.Html(
        string='Medications Prescribed upon Discharge',
        help="Free-text discharge prescription block. Printed under "
             "'Medications Prescribed upon Discharge' on the report.")

    discharge_condition = fields.Html(
        string='Condition at Discharge',
        help="Clinical status of the patient at discharge, including any "
             "fit-to-fly statement. Printed under 'Condition at Discharge'.")

    discharge_conclusion = fields.Html(
        string='Conclusion',
        help="Closing statement of the medical report.")

    report_date = fields.Date(
        string='Report Date', default=fields.Date.context_today,
        help="The date printed on the report. Defaults to today.")

    # ============================================================
    # Helpers used by the QWeb template
    # ============================================================
    def _urgency_label(self):
        """Human label for the selected urgency (or empty)."""
        self.ensure_one()
        return dict(self._fields['urgency_level'].selection).get(
            self.urgency_level, '')

    def _urgency_palette(self):
        """Background / text / dot colours for the urgency pill."""
        self.ensure_one()
        return URGENCY_PALETTE.get(self.urgency_level, NEUTRAL_PALETTE)

    # ============================================================
    # Report actions (header buttons)
    # ============================================================
    def action_print_report(self):
        """Trigger the standard PDF report from a form button."""
        return self.env.ref(
            'medical_app_reports.action_report_medical_encounter'
        ).report_action(self)

    def action_print_prescription(self):
        """Trigger the standalone prescription PDF.

        Guards against printing an empty Rx — there must be at least one
        structured prescription line on the encounter.
        """
        self.ensure_one()
        if not self.prescription_line_ids:
            raise UserError(_(
                "There are no prescription items on this encounter. "
                "Add at least one medication before printing the prescription."))
        return self.env.ref(
            'medical_app_reports.action_report_prescription'
        ).report_action(self)

    def action_send_by_email(self):
        """Open the standard mail composer pre-filled with the report.

        Mirrors what Odoo does on invoices and sales orders: a
        ``mail.compose.message`` wizard is opened with the medical-report
        ``mail.template`` selected, so the PDF is attached automatically
        and the patient is set as the default recipient.
        """
        self.ensure_one()
        template = self.env.ref(
            'medical_app_reports.email_template_medical_report',
            raise_if_not_found=False,
        )
        ctx = {
            'default_model': 'medical.encounter',
            'default_res_ids': self.ids,
            'default_template_id': template.id if template else False,
            'default_use_template': bool(template),
            'default_composition_mode': 'comment',
            'mail_post_autofollow': True,
        }
        return {
            'name': _('Send Medical Report'),
            'type': 'ir.actions.act_window',
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'view_id': False,
            'target': 'new',
            'context': ctx,
        }
