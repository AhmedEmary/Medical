# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


EXTRA_HEADER = "\n\n--- Additional context from doctor ---\n"


class MedicalAIPromptPreview(models.TransientModel):
    """Preview the prompt being sent to the AI and add free-text context.

    Opens before any encounter-level AI action when the
    ``medical_app_ai.preview_prompts`` setting is on. The doctor can:

    * read the exact system + user prompts that will be sent,
    * type extra context that gets appended to the user prompt,
    * (advanced) edit the user prompt directly.

    Clicking Send dispatches to the configured AI provider through the
    existing ``medical.ai.service`` entry points, then opens the standard
    suggestion review wizard with the result.
    """
    _name = 'medical.ai.prompt.preview'
    _description = 'AI Prompt Preview'

    mode = fields.Selection([
        ('report', 'Draft Report'),
        ('diagnosis', 'Suggest Diagnoses'),
        ('summary', 'Summarize Patient'),
        ('safety', 'Safety Check'),
    ], required=True, readonly=True)
    encounter_id = fields.Many2one(
        'medical.encounter', string='Encounter', readonly=True)
    patient_id = fields.Many2one(
        'medical.patient', string='Patient', readonly=True)

    provider_label = fields.Char(
        string='Provider', readonly=True,
        help="The AI provider the request will be sent to.")
    model_name = fields.Char(string='Model', readonly=True)

    system_prompt = fields.Text(string='System prompt', readonly=True)
    user_prompt = fields.Text(
        string='User prompt',
        help="Data and instructions sent on this request. "
             "Enable Advanced edit to modify it before sending.",
    )
    extra_context = fields.Text(
        string='Extra context / notes',
        help="Free-text the doctor adds for this run only — appended to "
             "the user prompt under a clearly marked section. Use this for "
             "anything not already on the encounter (verbal complaints, "
             "context from a phone call, things to emphasise, etc.).",
    )
    advanced_edit = fields.Boolean(
        string='Advanced: edit raw prompt',
        help="Off (default): user prompt is read-only and only your Extra "
             "context is appended. On: you can edit the user prompt "
             "directly — careful with JSON output instructions for Draft "
             "Report and Suggest Diagnoses.",
    )

    # ============================================================
    # Defaults / record open
    # ============================================================
    @api.model
    def open_for(self, mode, encounter=None, patient=None):
        """Build a preview wizard for the given mode and return its open
        action. Called from encounter AI buttons when previewing is on."""
        service = self.env['medical.ai.service']
        system, user = service.build_prompts(
            mode, encounter=encounter, patient=patient)
        provider = service._param_provider()
        resolved_patient = patient or (encounter and encounter.patient_id)
        wizard = self.create({
            'mode': mode,
            'encounter_id': encounter.id if encounter else False,
            'patient_id': resolved_patient.id if resolved_patient else False,
            'provider_label': self._provider_label(provider),
            'model_name': service._param_model(provider),
            'system_prompt': system,
            'user_prompt': user,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Preview AI Prompt'),
            'res_model': 'medical.ai.prompt.preview',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    @api.model
    def _provider_label(self, key):
        from ..models.medical_ai_service import PROVIDERS
        meta = PROVIDERS.get(key)
        return meta['label'] if meta else (key or '')

    # ============================================================
    # Send
    # ============================================================
    def _final_user_prompt(self):
        """The user prompt that will actually be sent: raw (possibly edited)
        user prompt plus any extra context appended under a clear header."""
        self.ensure_one()
        base = self.user_prompt or ''
        extra = (self.extra_context or '').strip()
        if extra:
            return base + EXTRA_HEADER + extra
        return base

    def action_send(self):
        self.ensure_one()
        if self.mode in ('report', 'diagnosis', 'safety') and not self.encounter_id:
            raise UserError(_("Missing encounter for this AI action."))
        if self.mode == 'summary' and not self.patient_id:
            raise UserError(_("Missing patient for the summary action."))

        service = self.env['medical.ai.service']
        system = self.system_prompt or ''
        user = self._final_user_prompt()

        if self.mode == 'report':
            data, log = service.draft_report(
                self.encounter_id, system=system, user=user)
            wizard = self.env['medical.ai.suggestion'].create({
                'mode': 'report',
                'encounter_id': self.encounter_id.id,
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

        if self.mode == 'diagnosis':
            suggestions, log = service.suggest_diagnoses(
                self.encounter_id, system=system, user=user)
            codes = [s.get('code') for s in suggestions if s.get('code')]
            diagnoses = self.env['medical.diagnosis'].search(
                [('code', 'in', codes)])
            rationale = "\n".join(
                "- %s: %s" % (s.get('code'), s.get('rationale') or '')
                for s in suggestions
            ) or _("The assistant did not suggest any diagnoses.")
            wizard = self.env['medical.ai.suggestion'].create({
                'mode': 'diagnosis',
                'encounter_id': self.encounter_id.id,
                'log_id': log.id,
                'suggested_diagnosis_ids': [(6, 0, diagnoses.ids)],
                'result_text': rationale,
            })
            return wizard._action_open()

        if self.mode == 'summary':
            text, log = service.summarize_patient(
                self.patient_id, system=system, user=user)
            wizard = self.env['medical.ai.suggestion'].create({
                'mode': 'summary',
                'encounter_id': self.encounter_id.id if self.encounter_id else False,
                'log_id': log.id,
                'result_text': text,
            })
            return wizard._action_open()

        if self.mode == 'safety':
            text, log = service.safety_check(
                self.encounter_id, system=system, user=user)
            wizard = self.env['medical.ai.suggestion'].create({
                'mode': 'safety',
                'encounter_id': self.encounter_id.id,
                'log_id': log.id,
                'result_text': text,
            })
            return wizard._action_open()

        raise UserError(_("Unknown AI mode: %s") % self.mode)
