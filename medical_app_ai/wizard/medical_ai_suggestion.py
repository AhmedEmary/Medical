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
        ('soap', 'SOAP Draft'),
        ('diagnosis', 'Diagnosis Suggestion'),
        ('summary', 'Patient Summary'),
        ('safety', 'Safety Check'),
    ], required=True, readonly=True)
    encounter_id = fields.Many2one(
        'medical.encounter', string='Encounter', required=True, readonly=True)
    log_id = fields.Many2one('medical.ai.log', string='AI Log', readonly=True)

    # SOAP draft — editable plain text the doctor can correct before applying.
    soap_history = fields.Text(string='History of Present Illness (S)')
    soap_exam = fields.Text(string='Physical Examination (O)')
    soap_assessment = fields.Text(string='Assessment (A)')
    soap_plan = fields.Text(string='Plan (P)')

    # Diagnosis suggestion.
    suggested_diagnosis_ids = fields.Many2many(
        'medical.diagnosis', string='Suggested Diagnoses')

    # Free-text AI output (rationale / summary / safety findings).
    result_text = fields.Text(string='AI Output', readonly=True)

    def _action_open(self):
        self.ensure_one()
        titles = {
            'soap': _('AI SOAP Draft'),
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

    def action_apply_soap(self):
        """Write the (doctor-reviewed) SOAP draft onto the encounter."""
        self.ensure_one()
        self.encounter_id.write({
            'history_present_illness': plaintext2html(self.soap_history or ''),
            'physical_exam': plaintext2html(self.soap_exam or ''),
            'assessment': plaintext2html(self.soap_assessment or ''),
            'plan': plaintext2html(self.soap_plan or ''),
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
