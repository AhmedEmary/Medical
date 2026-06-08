# -*- coding: utf-8 -*-
from odoo import _, fields, models


class MedicalAISuggestion(models.TransientModel):
    """Review surface for AI output.

    The doctor reads (and, for drafts, edits) the AI suggestion here, then
    either applies it to the encounter or closes without changes. Nothing is
    written to the encounter until the doctor clicks an Apply button.
    """
    _name = 'medical.ai.suggestion'
    _description = 'AI Suggestion Review'

    mode = fields.Selection([
        ('report', 'Report Draft'),
        ('diagnosis', 'Diagnosis Suggestion'),
        ('summary', 'Patient Summary'),
        ('safety', 'Safety Check'),
    ], required=True, readonly=True)
    encounter_id = fields.Many2one(
        'medical.encounter', string='Encounter', required=True, readonly=True)
    log_id = fields.Many2one('medical.ai.log', string='AI Log', readonly=True)

    # Report draft — the nine free-text sections that the PDF report prints.
    # Html (not Text) so the AI's <p>/<ul>/<strong> formatting renders and
    # the doctor can edit it with the rich-text widget before applying.
    # Ordered to match the printed report.
    report_history_present_illness = fields.Html(
        string='History of Present Illness (S)', sanitize=True)
    report_physical_exam = fields.Html(
        string='Physical Examination (O)', sanitize=True)
    report_assessment = fields.Html(
        string='Assessment (A) / Diagnoses', sanitize=True)
    report_investigations_performed = fields.Html(
        string='Investigations Performed', sanitize=True)
    report_plan = fields.Html(
        string='Plan (P)', sanitize=True)
    report_therapies_administered = fields.Html(
        string='Therapies Administered', sanitize=True)
    report_discharge_medication_notes = fields.Html(
        string='Medications Prescribed upon Discharge', sanitize=True)
    report_discharge_condition = fields.Html(
        string='Condition at Discharge', sanitize=True)
    report_discharge_conclusion = fields.Html(
        string='Conclusion', sanitize=True)

    # Diagnosis suggestion.
    suggested_diagnosis_ids = fields.Many2many(
        'medical.diagnosis', string='Suggested Diagnoses')

    # Free-text AI output (rationale / summary / safety findings).
    result_text = fields.Text(string='AI Output', readonly=True)

    def _action_open(self):
        self.ensure_one()
        titles = {
            'report': _('AI Report Draft'),
            'diagnosis': _('AI Diagnosis Suggestions'),
            'summary': _('AI Patient Summary'),
            'safety': _('AI Safety Check'),
        }
        return {
            'type': 'ir.actions.act_window',
            'name': titles.get(self.mode, _('AI Suggestion')),
            'res_model': 'medical.ai.suggestion',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _mark_applied(self):
        if self.log_id:
            self.log_id.sudo().applied = True

    def action_apply_report(self):
        """Write the (doctor-reviewed) report draft onto the encounter.

        Fields are already HTML (sanitized by Odoo on write), so we copy
        them straight to the encounter without any conversion.
        """
        self.ensure_one()
        self.encounter_id.write({
            'history_present_illness': self.report_history_present_illness or False,
            'physical_exam': self.report_physical_exam or False,
            'assessment': self.report_assessment or False,
            'investigations_performed':
                self.report_investigations_performed or False,
            'plan': self.report_plan or False,
            'therapies_administered': self.report_therapies_administered or False,
            'discharge_medication_notes':
                self.report_discharge_medication_notes or False,
            'discharge_condition': self.report_discharge_condition or False,
            'discharge_conclusion': self.report_discharge_conclusion or False,
        })
        self._mark_applied()
        return {'type': 'ir.actions.act_window_close'}

    def action_apply_diagnoses(self):
        """Add the suggested diagnoses to the encounter."""
        self.ensure_one()
        if self.suggested_diagnosis_ids:
            self.encounter_id.diagnosis_ids = [
                (4, did) for did in self.suggested_diagnosis_ids.ids
            ]
        self._mark_applied()
        return {'type': 'ir.actions.act_window_close'}
