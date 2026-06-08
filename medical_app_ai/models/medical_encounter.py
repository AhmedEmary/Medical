# -*- coding: utf-8 -*-
from odoo import _, models


class MedicalEncounter(models.Model):
    """AI assist actions on the clinical encounter.

    Each action either opens the prompt-preview wizard (default) so the
    doctor can review and augment the prompt before sending, or — when
    the preview setting is off — calls the AI service immediately and
    opens the suggestion wizard with the result.
    """
    _inherit = 'medical.encounter'

    def _ai_run(self, mode):
        """Either open the preview wizard or dispatch directly, based on the
        ``medical_app_ai.preview_prompts`` setting."""
        self.ensure_one()
        service = self.env['medical.ai.service']
        if service.preview_enabled():
            return self.env['medical.ai.prompt.preview'].open_for(
                mode, encounter=self,
                patient=self.patient_id if mode == 'summary' else None,
            )
        return self._ai_run_direct(mode)

    def _ai_run_direct(self, mode):
        """Old behaviour — no preview, send immediately."""
        self.ensure_one()
        service = self.env['medical.ai.service']
        if mode == 'report':
            data, log = service.draft_report(self)
            wizard = self.env['medical.ai.suggestion'].create({
                'mode': 'report',
                'encounter_id': self.id,
                'log_id': log.id,
                'report_history_present_illness': data['history_present_illness'],
                'report_physical_exam': data['physical_exam'],
                'report_assessment': data['assessment'],
                'report_investigations_performed':
                    data['investigations_performed'],
                'report_plan': data['plan'],
                'report_therapies_administered': data['therapies_administered'],
                'report_discharge_medication_notes':
                    data['discharge_medication_notes'],
                'report_discharge_condition': data['discharge_condition'],
                'report_discharge_conclusion': data['discharge_conclusion'],
            })
            return wizard._action_open()
        if mode == 'diagnosis':
            suggestions, log = service.suggest_diagnoses(self)
            codes = [s.get('code') for s in suggestions if s.get('code')]
            diagnoses = self.env['medical.diagnosis'].search(
                [('code', 'in', codes)])
            rationale = "\n".join(
                "- %s: %s" % (s.get('code'), s.get('rationale') or '')
                for s in suggestions
            ) or _("The assistant did not suggest any diagnoses.")
            wizard = self.env['medical.ai.suggestion'].create({
                'mode': 'diagnosis',
                'encounter_id': self.id,
                'log_id': log.id,
                'suggested_diagnosis_ids': [(6, 0, diagnoses.ids)],
                'result_text': rationale,
            })
            return wizard._action_open()
        if mode == 'summary':
            text, log = service.summarize_patient(self.patient_id)
            wizard = self.env['medical.ai.suggestion'].create({
                'mode': 'summary',
                'encounter_id': self.id,
                'log_id': log.id,
                'result_text': text,
            })
            return wizard._action_open()
        if mode == 'safety':
            text, log = service.safety_check(self)
            wizard = self.env['medical.ai.suggestion'].create({
                'mode': 'safety',
                'encounter_id': self.id,
                'log_id': log.id,
                'result_text': text,
            })
            return wizard._action_open()

    # ============================================================
    # Public buttons
    # ============================================================
    def action_ai_draft_report(self):
        return self._ai_run('report')

    def action_ai_suggest_diagnoses(self):
        return self._ai_run('diagnosis')

    def action_ai_summarize_patient(self):
        return self._ai_run('summary')

    def action_ai_safety_check(self):
        return self._ai_run('safety')

    def action_scan_documents(self):
        """Open the Scan Encounter Documents wizard for this encounter."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Scan Encounter Documents'),
            'res_model': 'medical.encounter.scan.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_encounter_id': self.id},
        }
