# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError


class MedicalCase(models.Model):
    """AI assist actions on the medical case:
    * draft the Medical Condition Report sections from every linked encounter,
    * translate the drafted / edited English sections into Arabic for the
      Arabic Medical Condition Report."""
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

    def action_ai_translate_case_arabic(self):
        """Translate the (edited) English case sections into Arabic.

        Writes directly into the Arabic mirror fields on the case and on
        each linked encounter — the doctor reviews / edits on the Arabic
        Report tab before printing the Arabic Medical Condition Report.
        """
        self.ensure_one()
        if not (self.cause or self.initial_diagnosis or self.current_complaint
                or self.sick_leave_note or self.encounter_ids):
            raise UserError(_(
                "Fill in the case sections (or link at least one encounter) "
                "before translating."))
        data, _log = self.env['medical.ai.service'].translate_case_to_arabic(self)

        self.write({
            'name_ar': data['name'] or self.name_ar,
            'cause_ar': data['cause'],
            'initial_diagnosis_ar': data['initial_diagnosis'],
            'current_complaint_ar': data['current_complaint'],
            'sick_leave_note_ar': data['sick_leave_note'],
        })

        # Map translated timeline notes back to encounters by reference,
        # falling back to chronological order for any that don't match.
        encounters = self._report_encounters()
        by_ref = {e.reference: e for e in encounters}
        used = self.env['medical.encounter']
        leftovers = list(encounters)
        for item in data['timeline']:
            enc = by_ref.get(item['encounter_ref'])
            if not enc or enc in used:
                enc = next((e for e in leftovers if e not in used), None)
            if not enc:
                continue
            used |= enc
            enc.case_timeline_note_ar = item['note']

        self.message_post(body=_(
            "Arabic translation of the Medical Condition Report drafted by "
            "AI. Review the <em>Arabic Report</em> tab before printing."))
