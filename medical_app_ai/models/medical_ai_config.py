# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .medical_ai_service import DEFAULT_PROVIDER, PROVIDER_SELECTION, PROVIDERS


class MedicalAIConfig(models.TransientModel):
    """Self-contained configuration screen for the AI assistant.

    Kept separate from res.config.settings so the global Settings page is
    untouched. Values are stored as ir.config_parameter entries, namespaced
    per provider so switching provider keeps each provider's own key/model.
    """
    _name = 'medical.ai.config'
    _description = 'Medical AI Configuration'

    provider = fields.Selection(
        PROVIDER_SELECTION,
        string='AI Provider', default=DEFAULT_PROVIDER, required=True,
        help="Which AI service the clinical assistant sends requests to. "
             "Each provider keeps its own API key and model.",
    )
    api_key = fields.Char(
        string='API Key',
        help="Authenticates clinical AI requests for the selected provider. "
             "Can also be set via an environment variable on the server.",
    )
    model = fields.Char(
        string='Model', required=True,
        help="The model identifier to use for the selected provider.",
    )
    model_hint = fields.Char(
        string='Example models', compute='_compute_model_hint',
        help="Example model identifiers for the selected provider.")
    preview_prompts = fields.Boolean(
        string='Preview prompts before sending', default=True,
        help="Open a wizard showing the exact prompt about to be sent to "
             "the AI, with a field for the doctor to add extra context. "
             "Turn off to send immediately on click.",
    )

    @api.depends('provider')
    def _compute_model_hint(self):
        for rec in self:
            meta = PROVIDERS.get(rec.provider) or PROVIDERS[DEFAULT_PROVIDER]
            rec.model_hint = meta['model_hint']

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        service = self.env['medical.ai.service']
        provider = service._param_provider()
        res['provider'] = provider
        res['api_key'] = service._param_api_key(provider)
        res['model'] = service._param_model(provider)
        res['preview_prompts'] = service.preview_enabled()
        return res

    @api.onchange('provider')
    def _onchange_provider(self):
        """Load the stored key/model for the newly selected provider."""
        if not self.provider:
            return
        service = self.env['medical.ai.service']
        self.api_key = service._param_api_key(self.provider)
        self.model = service._param_model(self.provider)

    def action_save(self):
        self.ensure_one()
        icp = self.env['ir.config_parameter'].sudo()
        provider = self.provider or DEFAULT_PROVIDER
        icp.set_param('medical_app_ai.provider', provider)
        icp.set_param('medical_app_ai.api_key_%s' % provider,
                      self.api_key or '')
        icp.set_param('medical_app_ai.model_%s' % provider,
                      self.model or PROVIDERS[provider]['default_model'])
        icp.set_param('medical_app_ai.preview_prompts',
                      'True' if self.preview_prompts else 'False')
        return {'type': 'ir.actions.act_window_close'}