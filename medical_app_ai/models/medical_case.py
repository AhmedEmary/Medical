# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError


class MedicalCase(models.Model):
    """AI assist action on the medical case: draft the Medical Condition
    Report sections from every linked encounter, for review before applying."""
    _inherit = 'medical.case'

    def action_ai_draft_case(self):
        """Draft the case report sections and open the review wizard."""
        self.ensure_one()
        if not self.encounter_ids:
            raise UserError(_(
                "Link at least one encounter to this case before drafting "
                "the report."))
        service = self.env['medical.ai.service']
        data, log = service.summarize_case(self)

        # Map the AI's per-encounter notes back to encounters by reference,
        # falling back to chronological order for any that don't match.
        encounters = self._report_encounters()
        by_ref = {e.reference: e for e in encounters}
        used = self.env['medical.encounter']
        timeline_cmds = []
        leftovers = list(encounters)
        for item in data['timeline']:
            enc = by_ref.get(item['encounter_ref'])
            if not enc or enc in used:
                enc = next((e for e in leftovers if e not in used), None)
            if not enc:
                continue
            used |= enc
            timeline_cmds.append((0, 0, {
                'encounter_id': enc.id,
                'note': item['note'],
            }))
        # Any encounter the AI skipped still gets an (empty) editable row.
        for enc in encounters:
            if enc not in used:
                timeline_cmds.append((0, 0, {
                    'encounter_id': enc.id,
                    'note': False,
                }))

        wizard = self.env['medical.ai.suggestion'].create({
            'mode': 'case',
            'case_id': self.id,
            'log_id': log.id,
            'case_cause': data['cause'],
            'case_initial_diagnosis': data['initial_diagnosis'],
            'case_current_complaint': data['current_complaint'],
            'case_sick_leave': data['sick_leave_note'],
            'timeline_line_ids': timeline_cmds,
        })
        return wizard._action_open()
