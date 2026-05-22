# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.tools import plaintext2html


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

    # Report draft — the six free-text sections that the PDF report prints.
    # All editable so the doctor can correct the AI before applying.
    report_history_present_illness = fields.Text(
        string='Clinical Summary')
    report_therapies_administered = fields.Text(
        string='Therapies Administered')
    report_discharge_medication_notes = fields.Text(
        string='Medications Prescribed upon Discharge')
    report_plan = fields.Text(
        string='Medical Recommendation')
    report_discharge_condition = fields.Text(
        string='Condition at Discharge')
    report_discharge_conclusion = fields.Text(
        string='Conclusion')

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
        """Write the (doctor-reviewed) report draft onto the encounter."""
        self.ensure_one()
        self.encounter_id.write({
            'history_present_illness':
                plaintext2html(self.report_history_present_illness or ''),
            'therapies_administered':
                plaintext2html(self.report_therapies_administered or ''),
            'discharge_medication_notes':
                plaintext2html(self.report_discharge_medication_notes or ''),
            'plan':
                plaintext2html(self.report_plan or ''),
            'discharge_condition':
                plaintext2html(self.report_discharge_condition or ''),
            'discharge_conclusion':
                plaintext2html(self.report_discharge_conclusion or ''),
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
