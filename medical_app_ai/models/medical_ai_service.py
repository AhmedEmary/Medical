# -*- coding: utf-8 -*-
import base64
import json
import logging
import os
import re

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)

# Optional provider SDKs: the module installs without any of them. Each AI
# feature raises a clear error at use time if the SDK for the *selected*
# provider is missing, so only the provider you actually use needs its SDK.
try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None

try:
    from google import genai as google_genai
    from google.genai import types as google_types
except ImportError:  # pragma: no cover
    google_genai = None
    google_types = None

try:
    import openai
except ImportError:  # pragma: no cover
    openai = None

MAX_TOKENS = 8000
API_TIMEOUT = 120.0

# Supported AI providers. To add another provider: add an entry here and a
# matching ``_call_<key>`` handler on MedicalAIService below — nothing else
# in the module needs to change.
PROVIDERS = {
    'anthropic': {
        'label': 'Anthropic (Claude)',
        'default_model': 'claude-opus-4-7',
        'env_keys': ('ANTHROPIC_API_KEY',),
        'model_hint': 'e.g. claude-opus-4-7, claude-sonnet-4-6',
        'package': 'anthropic',
    },
    'google': {
        'label': 'Google (Gemini)',
        'default_model': 'gemini-2.5-pro',
        'env_keys': ('GEMINI_API_KEY', 'GOOGLE_API_KEY'),
        'model_hint': 'e.g. gemini-2.5-pro, gemini-2.5-flash',
        'package': 'google-genai',
    },
    'openai': {
        'label': 'OpenAI (GPT)',
        'default_model': 'gpt-4o',
        'env_keys': ('OPENAI_API_KEY',),
        'model_hint': 'e.g. gpt-4o, gpt-4o-mini, o3',
        'package': 'openai',
    },
}
PROVIDER_SELECTION = [(key, meta['label']) for key, meta in PROVIDERS.items()]
DEFAULT_PROVIDER = 'anthropic'
DEFAULT_MODEL = PROVIDERS[DEFAULT_PROVIDER]['default_model']

SYSTEM_BASE = """You are a clinical documentation assistant inside a medical \
records system. You support licensed healthcare professionals.

Operating rules:
- Everything you produce is a DRAFT for the clinician to review, edit and \
approve. You never make the final clinical decision.
- Use only the information provided to you. Never invent symptoms, history, \
examination findings, vitals or measurements. When information is missing, \
state that it is not documented rather than guessing.
- Be concise and use standard medical terminology.
- Surface anything that looks inconsistent, incomplete or clinically risky.
- Write for the clinician; never address the patient directly."""


class MedicalAIService(models.AbstractModel):
    """Thin, audited wrapper around several AI provider APIs.

    Every clinical AI feature goes through ``_call``, which dispatches to the
    configured provider (Anthropic, Google Gemini, OpenAI, ...) and records
    each request in ``medical.ai.log``. The model never writes AI output to a
    record automatically — it returns drafts for the suggestion wizard.
    """
    _name = 'medical.ai.service'
    _description = 'Medical AI Service'

    # ============================================================
    # Configuration
    # ============================================================
    # Config parameters are namespaced per provider
    # (``medical_app_ai.api_key_<provider>`` / ``medical_app_ai.model_<provider>``)
    # so switching provider keeps each provider's own credentials and model.
    @api.model
    def _param_provider(self):
        """The configured AI provider key, validated against PROVIDERS."""
        provider = self.env['ir.config_parameter'].sudo().get_param(
            'medical_app_ai.provider') or DEFAULT_PROVIDER
        return provider if provider in PROVIDERS else DEFAULT_PROVIDER

    @api.model
    def _param_model(self, provider):
        """Stored model id for ``provider`` (falls back to its default)."""
        icp = self.env['ir.config_parameter'].sudo()
        model = icp.get_param('medical_app_ai.model_%s' % provider)
        if not model and provider == 'anthropic':
            model = icp.get_param('medical_app_ai.model')  # pre-multi-provider
        return model or PROVIDERS[provider]['default_model']

    @api.model
    def _param_api_key(self, provider):
        """Stored API key for ``provider`` from config params (may be empty)."""
        icp = self.env['ir.config_parameter'].sudo()
        key = icp.get_param('medical_app_ai.api_key_%s' % provider)
        if not key and provider == 'anthropic':
            key = icp.get_param('medical_app_ai.api_key')  # pre-multi-provider
        return key or ''

    @api.model
    def _get_api_key(self, provider):
        """Resolve the API key for ``provider`` from config or environment."""
        key = self._param_api_key(provider)
        if not key:
            for env_var in PROVIDERS[provider]['env_keys']:
                key = os.environ.get(env_var)
                if key:
                    break
        if not key:
            meta = PROVIDERS[provider]
            raise UserError(_(
                "No API key is configured for %(provider)s.\n\n"
                "Set one under Medical > Configuration > AI Configuration, "
                "or via the %(env)s environment variable.",
                provider=meta['label'],
                env=' / '.join(meta['env_keys']),
            ))
        return key

    # ============================================================
    # Core call
    # ============================================================
    @api.model
    def _call(self, feature, system_prompt, user_prompt,
              encounter=None, patient=None, max_tokens=MAX_TOKENS):
        """Run one AI request, log it, and return ``(text, log)``.

        The request is dispatched to the configured provider via its
        ``_call_<provider>`` handler, which returns
        ``(text, input_tokens, output_tokens)``.

        :param feature: medical.ai.log feature key, for the audit trail
        :param system_prompt: stable instructions (prompt-cached where able)
        :param user_prompt: the per-request clinical data
        """
        provider = self._param_provider()
        model = self._param_model(provider)
        if encounter and not patient:
            patient = encounter.patient_id

        # The log is created first (state=error) so a crash mid-call still
        # leaves a trace; it is flipped to success once the response lands.
        log = self.env['medical.ai.log'].sudo().create({
            'feature': feature,
            'provider': provider,
            'model': model,
            'encounter_id': encounter.id if encounter else False,
            'patient_id': patient.id if patient else False,
            'user_id': self.env.user.id,
            'request_summary': user_prompt[:10000],
            'state': 'error',
        })

        try:
            handler = getattr(self, '_call_%s' % provider)
            text, input_tokens, output_tokens = handler(
                model, system_prompt, user_prompt, max_tokens)
        except UserError as exc:
            # Configuration / missing-SDK errors — surface as-is, but still
            # record them on the log so the audit trail is complete.
            log.write({'error_message': str(exc)})
            raise
        except Exception as exc:  # noqa: BLE001 - surface any failure cleanly
            log.write({'error_message': str(exc)})
            _logger.warning(
                "Medical AI call (%s/%s) failed: %s", provider, feature, exc)
            raise UserError(_(
                "The AI request failed:\n\n%s", exc)) from exc

        log.write({
            'state': 'success',
            'response': text,
            'input_tokens': input_tokens or 0,
            'output_tokens': output_tokens or 0,
        })
        return text, log

    # ============================================================
    # Provider handlers
    # ------------------------------------------------------------
    # Each returns ``(text, input_tokens, output_tokens)`` for a single
    # request. They are resolved by name from ``_call`` as ``_call_<provider>``.
    # ============================================================
    @api.model
    def _call_anthropic(self, model, system_prompt, user_prompt, max_tokens):
        if anthropic is None:
            raise UserError(_(
                "The 'anthropic' Python package is not installed on the "
                "server.\n\nInstall it with:  pip install -U anthropic"))
        client = anthropic.Anthropic(
            api_key=self._get_api_key('anthropic'), timeout=API_TIMEOUT)
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            thinking={'type': 'adaptive'},
            system=[{
                'type': 'text',
                'text': system_prompt,
                # Stable prefix — cached so repeated calls are cheaper.
                'cache_control': {'type': 'ephemeral'},
            }],
            messages=[{'role': 'user', 'content': user_prompt}],
        )
        text = ''.join(
            block.text for block in response.content
            if block.type == 'text'
        ).strip()
        return (text,
                response.usage.input_tokens,
                response.usage.output_tokens)

    @api.model
    def _call_google(self, model, system_prompt, user_prompt, max_tokens):
        if google_genai is None:
            raise UserError(_(
                "The 'google-genai' Python package is not installed on the "
                "server.\n\nInstall it with:  pip install -U google-genai"))
        client = google_genai.Client(api_key=self._get_api_key('google'))
        response = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=google_types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=max_tokens,
            ),
        )
        usage = response.usage_metadata
        return (
            (response.text or '').strip(),
            getattr(usage, 'prompt_token_count', 0) if usage else 0,
            getattr(usage, 'candidates_token_count', 0) if usage else 0,
        )

    @api.model
    def _call_vision(self, feature, system_prompt, user_prompt, image_b64,
                     mime_type='image/jpeg', encounter=None, patient=None,
                     max_tokens=MAX_TOKENS):
        """Run a vision request (image + text) through the configured provider.

        ``image_b64`` is a base64-encoded image (the format Odoo stores
        ``Image`` / ``Binary`` fields in). Returns ``(text, log)`` like
        :meth:`_call`.
        """
        provider = self._param_provider()
        model = self._param_model(provider)
        if encounter and not patient:
            patient = encounter.patient_id

        log = self.env['medical.ai.log'].sudo().create({
            'feature': feature,
            'provider': provider,
            'model': model,
            'encounter_id': encounter.id if encounter else False,
            'patient_id': patient.id if patient else False,
            'user_id': self.env.user.id,
            'request_summary': user_prompt[:10000],
            'state': 'error',
        })

        try:
            handler = getattr(self, '_call_vision_%s' % provider)
            text, input_tokens, output_tokens = handler(
                model, system_prompt, user_prompt,
                image_b64, mime_type, max_tokens)
        except UserError as exc:
            log.write({'error_message': str(exc)})
            raise
        except Exception as exc:  # noqa: BLE001
            log.write({'error_message': str(exc)})
            _logger.warning(
                "Medical AI vision call (%s/%s) failed: %s",
                provider, feature, exc)
            raise UserError(_(
                "The AI vision request failed:\n\n%s", exc)) from exc

        log.write({
            'state': 'success',
            'response': text,
            'input_tokens': input_tokens or 0,
            'output_tokens': output_tokens or 0,
        })
        return text, log

    @api.model
    def _call_vision_anthropic(self, model, system_prompt, user_prompt,
                               image_b64, mime_type, max_tokens):
        if anthropic is None:
            raise UserError(_(
                "The 'anthropic' Python package is not installed on the "
                "server.\n\nInstall it with:  pip install -U anthropic"))
        client = anthropic.Anthropic(
            api_key=self._get_api_key('anthropic'), timeout=API_TIMEOUT)
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[{
                'type': 'text',
                'text': system_prompt,
                'cache_control': {'type': 'ephemeral'},
            }],
            messages=[{
                'role': 'user',
                'content': [
                    {
                        'type': 'image',
                        'source': {
                            'type': 'base64',
                            'media_type': mime_type,
                            'data': image_b64,
                        },
                    },
                    {'type': 'text', 'text': user_prompt},
                ],
            }],
        )
        text = ''.join(
            block.text for block in response.content
            if block.type == 'text'
        ).strip()
        return (text,
                response.usage.input_tokens,
                response.usage.output_tokens)

    @api.model
    def _call_vision_google(self, model, system_prompt, user_prompt,
                            image_b64, mime_type, max_tokens):
        if google_genai is None:
            raise UserError(_(
                "The 'google-genai' Python package is not installed on the "
                "server.\n\nInstall it with:  pip install -U google-genai"))
        client = google_genai.Client(api_key=self._get_api_key('google'))
        image_part = google_types.Part.from_bytes(
            data=base64.b64decode(image_b64), mime_type=mime_type)
        response = client.models.generate_content(
            model=model,
            contents=[image_part, user_prompt],
            config=google_types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=max_tokens,
            ),
        )
        usage = response.usage_metadata
        return (
            (response.text or '').strip(),
            getattr(usage, 'prompt_token_count', 0) if usage else 0,
            getattr(usage, 'candidates_token_count', 0) if usage else 0,
        )

    @api.model
    def _call_vision_openai(self, model, system_prompt, user_prompt,
                            image_b64, mime_type, max_tokens):
        if openai is None:
            raise UserError(_(
                "The 'openai' Python package is not installed on the "
                "server.\n\nInstall it with:  pip install -U openai"))
        client = openai.OpenAI(
            api_key=self._get_api_key('openai'), timeout=API_TIMEOUT)
        data_url = 'data:%s;base64,%s' % (mime_type, image_b64)
        response = client.chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': [
                    {'type': 'text', 'text': user_prompt},
                    {'type': 'image_url', 'image_url': {'url': data_url}},
                ]},
            ],
        )
        usage = response.usage
        return (
            (response.choices[0].message.content or '').strip(),
            getattr(usage, 'prompt_tokens', 0) if usage else 0,
            getattr(usage, 'completion_tokens', 0) if usage else 0,
        )

    @api.model
    def _call_openai(self, model, system_prompt, user_prompt, max_tokens):
        if openai is None:
            raise UserError(_(
                "The 'openai' Python package is not installed on the "
                "server.\n\nInstall it with:  pip install -U openai"))
        client = openai.OpenAI(
            api_key=self._get_api_key('openai'), timeout=API_TIMEOUT)
        response = client.chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
        )
        usage = response.usage
        return (
            (response.choices[0].message.content or '').strip(),
            getattr(usage, 'prompt_tokens', 0) if usage else 0,
            getattr(usage, 'completion_tokens', 0) if usage else 0,
        )

    @api.model
    def _parse_json(self, text):
        """Parse a JSON object out of the model's response, tolerantly."""
        cleaned = (text or '').strip()
        fenced = re.match(r'^```(?:json)?\s*(.*?)\s*```$', cleaned, re.DOTALL)
        if fenced:
            cleaned = fenced.group(1)
        try:
            return json.loads(cleaned)
        except (ValueError, TypeError):
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except ValueError:
                    pass
        raise UserError(_(
            "The AI returned an unexpected format. Please try again."))

    # ============================================================
    # Clinical context builders
    # ============================================================
    @api.model
    def _selection_label(self, record, field):
        value = record[field]
        return dict(record._fields[field].selection).get(value) or value \
            or 'not documented'

    @api.model
    def _patient_lines(self, patient):
        """Patient identity, allergies and current medications."""
        lines = [
            "PATIENT",
            "- Record number: %s" % (patient.mrn or 'n/a'),
            "- Age: %s" % (patient.age or 'not documented'),
            "- Gender: %s" % self._selection_label(patient, 'gender'),
            "- Blood type: %s" % self._selection_label(patient, 'blood_type'),
        ]
        if patient.allergy_ids:
            lines.append("ALLERGIES")
            for allergy in patient.allergy_ids:
                lines.append("- %s [%s]: %s" % (
                    allergy.allergen,
                    self._selection_label(allergy, 'severity'),
                    allergy.reaction or 'reaction not documented',
                ))
        else:
            lines.append("ALLERGIES: none documented")

        if patient.active_medication_ids:
            lines.append("CURRENT MEDICATIONS")
            for med in patient.active_medication_ids:
                lines.append("- %s %s %s" % (
                    med.product_name,
                    med.dose or '',
                    self._selection_label(med, 'frequency'),
                ).strip())
        else:
            lines.append("CURRENT MEDICATIONS: none documented")
        return lines

    @api.model
    def _encounter_context(self, encounter):
        """Full text context for one encounter."""
        lines = self._patient_lines(encounter.patient_id)
        lines += [
            "",
            "CURRENT ENCOUNTER",
            "- Type: %s" % self._selection_label(encounter, 'encounter_type'),
            "- Chief complaint: %s" % (
                encounter.chief_complaint or 'not documented'),
        ]
        vitals = encounter.vitals_ids[:1]
        if vitals:
            measures = [
                "BP %s" % vitals.bp_display if vitals.bp_display else None,
                "HR %s" % vitals.heart_rate if vitals.heart_rate else None,
                "RR %s" % vitals.respiratory_rate
                if vitals.respiratory_rate else None,
                "Temp %s C" % vitals.temperature if vitals.temperature else None,
                "SpO2 %s%%" % vitals.spo2 if vitals.spo2 else None,
                "Weight %s kg" % vitals.weight if vitals.weight else None,
            ]
            measures = [m for m in measures if m]
            lines.append("- Latest vitals: %s" % (
                ", ".join(measures) or 'recorded, no values'))
        else:
            lines.append("- Vitals: none recorded")

        # Any clinical text already on the encounter.
        for label, field in [
            ('History of present illness', 'history_present_illness'),
            ('Review of systems', 'review_of_systems'),
            ('Physical examination', 'physical_exam'),
            ('Assessment', 'assessment'),
            ('Plan', 'plan'),
            ('Clinical notes', 'clinical_notes'),
        ]:
            value = html2plaintext(encounter[field] or '').strip()
            if value:
                lines.append("- %s: %s" % (label, value))

        if encounter.diagnosis_ids:
            lines.append("- Recorded diagnoses: %s" % ", ".join(
                "%s %s" % (d.code, d.name) for d in encounter.diagnosis_ids))
        return "\n".join(lines)

    @api.model
    def _patient_full_context(self, patient):
        """Patient context plus history and recent encounters."""
        lines = self._patient_lines(patient)
        if patient.medical_history_ids:
            lines += ["", "HISTORY"]
            for hist in patient.medical_history_ids:
                lines.append("- [%s] %s (%s)" % (
                    self._selection_label(hist, 'history_type'),
                    hist.condition,
                    self._selection_label(hist, 'status'),
                ))
        recent = patient.encounter_ids[:5]
        if recent:
            lines += ["", "RECENT ENCOUNTERS"]
            for enc in recent:
                date = enc.encounter_date and enc.encounter_date.date() or ''
                lines.append("- %s: %s" % (
                    date, enc.chief_complaint or self._selection_label(
                        enc, 'encounter_type')))
        return "\n".join(lines)

    # ============================================================
    # Feature methods
    # ============================================================
    @api.model
    def draft_soap_note(self, encounter):
        """Return ``(dict, log)`` — drafted SOAP sections as plain text."""
        system = SYSTEM_BASE + """

TASK: Draft a SOAP-style clinical note from the encounter data below.
Respond with ONLY a JSON object (no other text) with exactly these keys,
each a plain-text string:
- "history": History of Present Illness (Subjective)
- "exam": Physical Examination (Objective) — only findings supported by data
- "assessment": Assessment — the likely clinical picture and reasoning
- "plan": Plan — suggested investigations, treatment and follow-up
Keep each section short. Where data is missing, write a brief placeholder
for the clinician to complete rather than inventing content."""
        user = "Draft a SOAP note for this encounter.\n\n" \
            + self._encounter_context(encounter)
        text, log = self._call('soap_draft', system, user, encounter=encounter)
        data = self._parse_json(text)
        result = {
            'history': data.get('history') or '',
            'exam': data.get('exam') or '',
            'assessment': data.get('assessment') or '',
            'plan': data.get('plan') or '',
        }
        return result, log

    @api.model
    def suggest_diagnoses(self, encounter):
        """Return ``(list, log)`` — suggested ``{code, rationale}`` dicts."""
        catalog = self.env['medical.diagnosis'].search([])
        catalog_text = "\n".join(
            "%s | %s" % (d.code, d.name) for d in catalog)
        system = SYSTEM_BASE + """

TASK: Suggest the most relevant ICD-10 diagnoses for this encounter.
You MUST pick only from the catalog of codes provided below — never invent
a code. Respond with ONLY a JSON object (no other text):
{"suggestions": [{"code": "<exact code from catalog>",
                  "rationale": "<one short sentence>"}]}
Suggest at most 5, ordered most to least likely. If nothing fits, return
an empty list.

AVAILABLE ICD-10 CODES (code | description):
""" + catalog_text
        user = "Suggest ICD-10 diagnoses for this encounter.\n\n" \
            + self._encounter_context(encounter)
        text, log = self._call(
            'diagnosis_suggest', system, user, encounter=encounter)
        data = self._parse_json(text)
        return data.get('suggestions') or [], log

    @api.model
    def summarize_patient(self, patient):
        """Return ``(text, log)`` — a concise clinical briefing."""
        system = SYSTEM_BASE + """

TASK: Write a concise clinical briefing of this patient for a clinician who
is about to see them. Cover active problems, relevant history, allergies and
current medications, and anything that needs attention. Use short paragraphs
or bullet points. Plain text only."""
        user = "Summarise this patient.\n\n" \
            + self._patient_full_context(patient)
        return self._call('history_summary', system, user, patient=patient)

    @api.model
    def safety_check(self, encounter):
        """Return ``(text, log)`` — a safety review of the encounter plan."""
        system = SYSTEM_BASE + """

TASK: Review this encounter's assessment and plan for safety concerns. Check
the proposed treatment against the patient's documented allergies and current
medications, and flag drug interactions, contraindications, duplicate therapy,
dosing concerns and missing safety steps.
Plain text only. Start with one overall line — either
"Overall: no major concerns identified" or
"Overall: concerns found - see below" — then list specific findings.
If something cannot be assessed because data is missing, say so."""
        user = "Perform a safety check on this encounter.\n\n" \
            + self._encounter_context(encounter)
        return self._call('safety_check', system, user, encounter=encounter)
