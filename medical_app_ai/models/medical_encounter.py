# -*- coding: utf-8 -*-
from odoo import _, models


class MedicalEncounter(models.Model):
    """AI assist actions on the clinical encounter.

    Each action calls medical.ai.service, then opens the suggestion wizard
    so the doctor reviews the AI output before anything touches the record.
    """
    _inherit = 'medical.encounter'

    def action_ai_draft_report(self):
        """Draft the six free-text sections of the medical report.

        Opens the suggestion wizard pre-filled with the AI output; nothing
        is written to the encounter until the doctor clicks Apply.
        """
        self.ensure_one()
        data, log = self.env['medical.ai.service'].draft_report(self)
        wizard = self.env['medical.ai.suggestion'].create({
            'mode': 'report',
            'encounter_id': self.id,
            'log_id': log.id,
            'report_history_present_illness': data['history_present_illness'],
            'report_therapies_administered': data['therapies_administered'],
            'report_discharge_medication_notes':
                data['discharge_medication_notes'],
            'report_plan': data['plan'],
            'report_discharge_condition': data['discharge_condition'],
            'report_discharge_conclusion': data['discharge_conclusion'],
        })
        return wizard._action_open()

    def action_ai_suggest_diagnoses(self):
        self.ensure_one()
        suggestions, log = self.env['medical.ai.service'].suggest_diagnoses(self)
        codes = [s.get('code') for s in suggestions if s.get('code')]
        diagnoses = self.env['medical.diagnosis'].search([('code', 'in', codes)])
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

    def action_ai_summarize_patient(self):
        self.ensure_one()
        text, log = self.env['medical.ai.service'].summarize_patient(
            self.patient_id)
        wizard = self.env['medical.ai.suggestion'].create({
            'mode': 'summary',
            'encounter_id': self.id,
            'log_id': log.id,
            'result_text': text,
        })
        return wizard._action_open()

    def action_ai_safety_check(self):
        self.ensure_one()
        text, log = self.env['medical.ai.service'].safety_check(self)
        wizard = self.env['medical.ai.suggestion'].create({
            'mode': 'safety',
            'encounter_id': self.id,
            'log_id': log.id,
            'result_text': text,
        })
        return wizard._action_open()

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
