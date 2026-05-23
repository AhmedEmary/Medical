# -*- coding: utf-8 -*-
import base64
import json
import logging
import os
import re
import time

import requests

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

# Manus is an agentic, asynchronous API: ``task.create`` returns a task ID
# and the agent runs in the background. ``_call_manus`` polls
# ``task.listMessages`` to keep the same synchronous (text, log) contract
# as the other providers.
MANUS_API_BASE = 'https://api.manus.ai/v2'
MANUS_POLL_INTERVAL = 3.0   # seconds between polls
MANUS_TIMEOUT = 300.0       # hard cap so the request can't block forever

# Providers that handle image inputs. Used to transparently fall back to a
# vision-capable provider when the configured one (e.g. Manus) only does
# text. Order = preference for the fallback.
VISION_PROVIDERS = ('anthropic', 'google', 'openai')

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
    'manus': {
        'label': 'Manus (Agent)',
        'default_model': 'auto',
        'env_keys': ('MANUS_API_KEY',),
        'model_hint': "Leave as 'auto' — Manus picks the model.",
        'package': 'requests (built-in)',
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
    def _pick_vision_fallback(self):
        """Return the first vision-capable provider with an API key set,
        or ``None`` if none are configured. Used by ``_call_vision`` to
        bridge over text-only providers like Manus."""
        for candidate in VISION_PROVIDERS:
            if self._param_api_key(candidate):
                return candidate
        return None

    @api.model
    def _call_vision(self, feature, system_prompt, user_prompt, image_b64,
                     mime_type='image/jpeg', extra_images=None,
                     encounter=None, patient=None,
                     max_tokens=MAX_TOKENS):
        """Run a vision request (image + text) through the configured provider.

        ``image_b64`` is a base64-encoded image (the format Odoo stores
        ``Image`` / ``Binary`` fields in). ``extra_images`` is an optional
        list of ``{'data': <b64>, 'mime_type': <str>}`` dicts for multi-page
        documents — they are sent together with the primary image in a
        single request. Returns ``(text, log)`` like :meth:`_call`.
        """
        provider = self._param_provider()
        # Manus has no vision endpoint. Transparently fall back to the first
        # vision-capable provider that has a key configured (anthropic →
        # google → openai). This way users keep Manus selected for the
        # text-based AI features without breaking ID/document scans.
        if provider not in VISION_PROVIDERS:
            fallback = self._pick_vision_fallback()
            if fallback:
                _logger.info(
                    "Vision call: provider '%s' has no vision; falling back "
                    "to '%s'.", provider, fallback)
                provider = fallback
            else:
                raise UserError(_(
                    "The configured AI provider ('%s') does not support "
                    "image inputs, and no other vision-capable provider "
                    "has an API key configured.\n\nOpen Medical AI "
                    "Configuration and add a key for Anthropic, Google or "
                    "OpenAI to enable ID and document scans."
                ) % provider)
        model = self._param_model(provider)
        if encounter and not patient:
            patient = encounter.patient_id

        images = [{'data': image_b64, 'mime_type': mime_type}]
        for extra in extra_images or []:
            if extra and extra.get('data'):
                images.append({
                    'data': extra['data'],
                    'mime_type': extra.get('mime_type') or 'image/jpeg',
                })

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
                model, system_prompt, user_prompt, images, max_tokens)
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
                               images, max_tokens):
        if anthropic is None:
            raise UserError(_(
                "The 'anthropic' Python package is not installed on the "
                "server.\n\nInstall it with:  pip install -U anthropic"))
        client = anthropic.Anthropic(
            api_key=self._get_api_key('anthropic'), timeout=API_TIMEOUT)
        content = [
            {
                'type': 'image',
                'source': {
                    'type': 'base64',
                    'media_type': img['mime_type'],
                    'data': img['data'],
                },
            }
            for img in images
        ]
        content.append({'type': 'text', 'text': user_prompt})
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[{
                'type': 'text',
                'text': system_prompt,
                'cache_control': {'type': 'ephemeral'},
            }],
            messages=[{'role': 'user', 'content': content}],
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
                            images, max_tokens):
        if google_genai is None:
            raise UserError(_(
                "The 'google-genai' Python package is not installed on the "
                "server.\n\nInstall it with:  pip install -U google-genai"))
        client = google_genai.Client(api_key=self._get_api_key('google'))
        contents = [
            google_types.Part.from_bytes(
                data=base64.b64decode(img['data']),
                mime_type=img['mime_type'])
            for img in images
        ]
        contents.append(user_prompt)
        response = client.models.generate_content(
            model=model,
            contents=contents,
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
                            images, max_tokens):
        if openai is None:
            raise UserError(_(
                "The 'openai' Python package is not installed on the "
                "server.\n\nInstall it with:  pip install -U openai"))
        client = openai.OpenAI(
            api_key=self._get_api_key('openai'), timeout=API_TIMEOUT)
        user_content = [{'type': 'text', 'text': user_prompt}]
        for img in images:
            user_content.append({
                'type': 'image_url',
                'image_url': {
                    'url': 'data:%s;base64,%s' % (
                        img['mime_type'], img['data']),
                },
            })
        response = client.chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_content},
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
    def _call_manus(self, model, system_prompt, user_prompt, max_tokens):
        """Synchronous wrapper around Manus's async task API.

        Manus has no separate ``system`` role, so the system prompt is
        concatenated to the user prompt. We POST ``task.create``, then
        poll ``task.listMessages`` every ``MANUS_POLL_INTERVAL`` seconds
        until the agent reaches ``stopped`` (success) or ``error``,
        giving up after ``MANUS_TIMEOUT``.
        """
        api_key = self._get_api_key('manus')
        headers = {
            'x-manus-api-key': api_key,
            'Content-Type': 'application/json',
        }
        combined = system_prompt + "\n\n" + user_prompt
        payload = {
            'message': {
                'content': [{'type': 'text', 'text': combined}],
            },
        }
        _logger.info(
            "[MANUS] POST %s/task.create — payload=%s (text chars=%s)",
            MANUS_API_BASE, json.dumps(payload)[:1500], len(combined))
        try:
            resp = requests.post(
                MANUS_API_BASE + '/task.create',
                headers=headers, json=payload, timeout=API_TIMEOUT)
        except requests.RequestException as exc:
            _logger.warning("[MANUS] task.create transport error: %s", exc)
            raise UserError(_(
                "Manus task.create failed: %s") % exc) from exc

        _logger.info(
            "[MANUS] task.create HTTP %s; body=%s",
            resp.status_code, (resp.text or '')[:2000])

        if resp.status_code >= 400:
            detail = self._manus_extract_error(resp)
            _logger.warning(
                "[MANUS] task.create %s: %s | sent payload top-level keys=%s "
                "message keys=%s text chars=%s",
                resp.status_code, detail,
                list(payload.keys()),
                list(payload['message'].keys()),
                len(combined))
            raise UserError(_(
                "Manus task.create failed (HTTP %(c)s): %(d)s") % {
                    'c': resp.status_code, 'd': detail})

        try:
            data = resp.json()
        except ValueError as exc:
            _logger.warning("[MANUS] non-JSON response: %s", resp.text[:1000])
            raise UserError(_(
                "Manus returned a non-JSON response: %s") % resp.text[:500]
            ) from exc

        # The Manus response shape isn't stable across docs/versions, so
        # try several known places for the task id before giving up.
        task_id = (
            (data.get('task') or {}).get('id')
            or (data.get('data') or {}).get('task_id')
            or (data.get('data') or {}).get('id')
            or data.get('task_id')
            or data.get('id')
        )
        if not task_id:
            _logger.warning(
                "[MANUS] task.create returned no usable task id; "
                "response body=%s", json.dumps(data)[:2000])
            err = (
                ((data.get('error') or {}) if isinstance(data.get('error'), dict) else {})
                .get('message')
                or (data.get('error') if isinstance(data.get('error'), str) else None)
                or data.get('message')
                or data.get('detail')
                or _("response shape not recognised — see server log for the raw body")
            )
            raise UserError(_("Manus rejected the task: %s") % err)

        _logger.info("[MANUS] task created id=%s — starting poll loop", task_id)

        deadline = time.time() + MANUS_TIMEOUT
        poll_count = 0
        while time.time() < deadline:
            time.sleep(MANUS_POLL_INTERVAL)
            poll_count += 1
            try:
                lresp = requests.get(
                    MANUS_API_BASE + '/task.listMessages',
                    params={'task_id': task_id, 'order': 'asc', 'limit': 200},
                    headers=headers, timeout=API_TIMEOUT)
            except requests.RequestException as exc:
                _logger.warning(
                    "[MANUS] polling transport error for task %s: %s",
                    task_id, exc)
                raise UserError(_(
                    "Manus polling failed for task %s: %s") % (task_id, exc)
                ) from exc

            _logger.info(
                "[MANUS] poll #%s task=%s HTTP %s; body=%s",
                poll_count, task_id, lresp.status_code,
                (lresp.text or '')[:2000])

            if lresp.status_code >= 400:
                detail = self._manus_extract_error(lresp)
                raise UserError(_(
                    "Manus polling failed (HTTP %(c)s): %(d)s") % {
                        'c': lresp.status_code, 'd': detail})

            try:
                ldata = lresp.json()
            except ValueError as exc:
                _logger.warning(
                    "[MANUS] non-JSON poll response for task %s: %s",
                    task_id, lresp.text[:1000])
                raise UserError(_(
                    "Manus returned a non-JSON poll response: %s"
                ) % lresp.text[:500]) from exc

            # `ok` is informational only — some Manus responses just return
            # the events array without an envelope. Only bail if there's an
            # actual error field.
            if isinstance(ldata, dict) and ldata.get('error'):
                err = (
                    (ldata.get('error') or {}).get('message')
                    if isinstance(ldata.get('error'), dict) else ldata['error']
                ) or _("unknown error")
                raise UserError(_("Manus polling failed: %s") % err)

            events = (
                (ldata.get('events') if isinstance(ldata, dict) else None)
                or (ldata.get('messages') if isinstance(ldata, dict) else None)
                or (ldata.get('data') if isinstance(ldata, dict) else None)
                or []
            )
            _logger.info(
                "[MANUS] poll #%s parsed %s event(s); types=%s",
                poll_count, len(events) if hasattr(events, '__len__') else '?',
                [ev.get('type') for ev in events
                 if isinstance(ev, dict)][:20] if events else [])
            # Walk events in order; track the latest agent status and any
            # error message; collect assistant_message text for the result.
            agent_status = None
            error_message = ''
            assistant_texts = []
            for ev in events:
                ev_type = ev.get('type')
                if ev_type == 'status_update':
                    upd = ev.get('status_update') or {}
                    agent_status = upd.get('agent_status') or agent_status
                    if upd.get('error_message'):
                        error_message = upd['error_message']
                elif ev_type == 'assistant_message':
                    am = ev.get('assistant_message') or {}
                    # Accept either 'content' (new API) or 'text' (legacy).
                    text = am.get('content') or am.get('text') or ''
                    if text:
                        assistant_texts.append(text)

            if agent_status == 'error':
                raise UserError(_("Manus agent failed: %s") % (
                    error_message or _("no error message provided")))
            if agent_status == 'stopped':
                return ("\n".join(assistant_texts).strip(), 0, 0)

        raise UserError(_(
            "Manus task %(t)s did not finish within %(s)s seconds. "
            "Increase MANUS_TIMEOUT or use a different provider.") % {
                't': task_id, 's': int(MANUS_TIMEOUT)})

    @api.model
    def _manus_extract_error(self, resp):
        """Pull the most informative error string out of a Manus
        non-2xx response. Tries JSON paths first, falls back to raw text."""
        try:
            body = resp.json()
        except ValueError:
            return (resp.text or '')[:500] or _("empty response body")
        # Common shapes: {"ok": false, "error": {"message": "..."}}
        # or {"error": "..."} or {"message": "..."} or {"detail": "..."}.
        err = body.get('error')
        if isinstance(err, dict):
            for k in ('message', 'detail', 'description', 'code'):
                if err.get(k):
                    return str(err[k])
        if isinstance(err, str) and err:
            return err
        for k in ('message', 'detail', 'description'):
            if body.get(k):
                return str(body[k])
        return json.dumps(body)[:500]

    @api.model
    def _call_vision_manus(self, model, system_prompt, user_prompt,
                          images, max_tokens):
        """Vision is not implemented for Manus — raise a clear error."""
        raise UserError(_(
            "The Manus provider does not currently support image inputs. "
            "Switch the AI provider to Anthropic, Google or OpenAI in "
            "Settings → Medical AI Configuration to run document or ID "
            "scans, or use the Manus features that work on text only."))

    @api.model
    def _parse_json(self, text):
        """Parse a JSON object out of the model's response, tolerantly.

        Accepts plain JSON, JSON wrapped in ``` fences, or a JSON object
        embedded in surrounding text. As a last resort, attempts to repair
        a truncated/unbalanced JSON object (closing dangling strings and
        braces) so that at least the partial fields are usable instead
        of the whole call being lost.
        """
        cleaned = (text or '').strip()
        fenced = re.match(r'^```(?:json)?\s*(.*?)\s*```$', cleaned, re.DOTALL)
        if fenced:
            cleaned = fenced.group(1)
        try:
            return json.loads(cleaned)
        except (ValueError, TypeError):
            # Greedy: outermost { … } in the whole string.
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except ValueError:
                    pass
            # Fallback: non-greedy across multiple ```json fences.
            for fence in re.findall(
                    r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL):
                try:
                    return json.loads(fence)
                except ValueError:
                    continue
            # Last resort: AI responses are sometimes cut mid-string by
            # network/length/agent-stop. Try to close dangling strings
            # and braces so the partially extracted fields are still
            # usable.
            repaired = self._repair_truncated_json(cleaned)
            if repaired is not None:
                _logger.warning(
                    "[AI] _parse_json: response was truncated but repaired "
                    "by closing %s unbalanced container(s). Raw (%s chars):"
                    "\n%s",
                    repaired[1], len(text or ''), (text or '')[:2000])
                return repaired[0]
        _logger.warning(
            "[AI] _parse_json could not extract JSON. Raw response (%s chars):"
            "\n%s", len(text or ''), (text or '')[:2000])
        snippet = (text or '').strip()
        if len(snippet) > 300:
            snippet = snippet[:300] + '…'
        raise UserError(_(
            "The AI returned an unexpected format (no JSON object was "
            "found). Try again, or switch to a different provider in "
            "Medical AI Configuration.\n\nResponse preview:\n%s"
        ) % (snippet or _("(empty)")))

    @api.model
    def _repair_truncated_json(self, text):
        """Attempt to repair a JSON object truncated mid-string/mid-block.

        Walks the text tracking quote/escape state and brace/bracket
        depth, then appends the closing characters needed to make it
        parseable. Tries two strategies and returns the first that parses:

        1. Trim the unfinished trailing key/value (so an aborted field
           doesn't poison the document) and balance braces.
        2. Leave the body intact and just close any open string/braces.

        Returns ``(parsed_dict, close_count)`` on success, or ``None``
        if there's nothing JSON-like to recover.
        """
        if not text:
            return None
        start = text.find('{')
        if start == -1:
            return None
        body = text[start:]

        # Strategy 1: trim a trailing partial pair (",\n  \"key\": ..." or
        # ",\n  \"key\": \"value...) so the leftover document ends on a
        # complete value, then balance braces.
        trimmed = body.rstrip()
        trimmed = re.sub(
            r',\s*"[^"]*"\s*:\s*"[^"]*$', '', trimmed)  # mid-string value
        trimmed = re.sub(
            r',\s*"[^"]*"\s*:\s*$', '', trimmed)        # hanging colon
        trimmed = re.sub(
            r',\s*"[^"]*$', '', trimmed)                # unclosed key
        trimmed = re.sub(r',\s*$', '', trimmed)         # dangling comma

        for candidate in (trimmed, body):
            in_string = escape = False
            brace_depth = bracket_depth = 0
            for ch in candidate:
                if escape:
                    escape = False
                    continue
                if ch == '\\':
                    escape = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == '{':
                    brace_depth += 1
                elif ch == '}':
                    brace_depth -= 1
                elif ch == '[':
                    bracket_depth += 1
                elif ch == ']':
                    bracket_depth -= 1
            closure = ''
            if in_string:
                closure += '"'
            closure += ']' * max(bracket_depth, 0)
            closure += '}' * max(brace_depth, 0)
            if not closure:
                continue  # not actually unbalanced; nothing to repair here
            try:
                return json.loads(candidate + closure), len(closure)
            except ValueError:
                continue
        return None

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
            ('Physical examination', 'physical_exam'),
            ('Assessment', 'assessment'),
            ('Plan', 'plan'),
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
    def _draft_report_system(self):
        return SYSTEM_BASE + """

TASK: Draft the six free-text sections of a formal hotel-medical discharge
report. The doctor has typed minimal seed notes into each section on the
encounter (see "DOCTOR NOTES" in the input). Your job is to:

1. Expand each seed note into the verbose, professional register expected
   in a hotel-medical discharge document for the patient, the referring
   doctor, and potentially an airline / insurer.
2. Stay strictly within what the seed notes and the structured encounter
   data actually support. NEVER invent symptoms, findings, medications,
   diagnoses or measurements that aren't in the data.
3. If a seed note is blank, derive the section from the structured data
   (vitals, diagnoses, prescriptions, allergies, history) if possible;
   otherwise return "" for that section.

STYLE RULES (match the reference report closely):
- Third person, formal clinical register. Past tense for what was done,
  present tense for ongoing instructions.
- Use HTML and ONLY these tags: <p>, <ul>, <li>, <strong>, <br/>.
- Bold key clinical terms with <strong> (e.g. <strong>acute pharyngitis</strong>).
- Multiple short paragraphs for narrative sections, one fact per paragraph.
- Use bulleted <ul><li>…</li></ul> lists for itemised therapies,
  recommendations, and discharge medications.
- Do NOT include section headings, the patient's name, the doctor's name,
  the date, or the signature — those are rendered by the template.

SECTION-BY-SECTION FORMAT (mirror the reference):

* "history_present_illness" (Clinical Summary): 3-5 short paragraphs.
  - Para 1: open with the date and a one-sentence presentation of the
    chief complaint and key symptoms (bold the symptoms).
  - Para 2: explicitly state what dangerous findings were absent
    ("There was no evidence of airway compromise, …").
  - Para 3: the clinical evaluation performed and the conclusion
    (bold the working diagnosis).
  - Para 4: the immediate management initiated.
  - Para 5: the follow-up arrangement and the warning signs that
    should prompt return.

* "therapies_administered": one short intro line ("During the visit, the
  patient received:") followed by a <ul> listing each therapy as a
  separate <li>. Each item is a full sentence with the route and reason
  ("Intravenous Ceftriaxone 1 g was administered following a negative
  sensitivity test."). Return "" if nothing was administered.

* "discharge_medication_notes": one opening paragraph in the formal
  "Following a comprehensive clinical assessment, … the patient was
  assessed as <strong>clinically stable</strong>. Accordingly,
  <strong>appropriate medical treatment was prescribed</strong>, as
  outlined below, based on the clinical evaluation." Then a paragraph
  "The prescribed treatment plan includes:" followed by a <ul> of
  <li><strong>Drug</strong>: dose, frequency.</li> items. Close with a
  single-paragraph line about duration if known. Return "" if there are
  no discharge medications.

* "plan" (Medical Recommendation): a <ul> of 4-7 <li> items, each a
  full formal sentence ("The patient has been strongly advised to …",
  "Strict adherence to the prescribed treatment regimen is essential …",
  "Immediate medical re-evaluation is advised in case of …"). Cover:
  rest/avoidance, adherence, hydration, irritants to avoid, warning
  signs, follow-up. Skip items not supported by the data.

* "discharge_condition": 2-3 short paragraphs.
  - Para 1: clinical status anchored on the documented vitals/assessment
    (bold "stable", "improved", "fit to fly" where applicable).
  - Para 2: explicit fit-to-fly framing if the patient was assessed for
    travel, otherwise omit; reference the absence of red flags.
  - Para 3: travel/post-discharge instructions.

* "discharge_conclusion": exactly one closing sentence summarising the
  patient's overall fitness.

Respond with ONLY a JSON object (no other text, no markdown code fences)
with exactly these six keys, each containing an HTML string as described
above (or "" if no data supports it):
{
  "history_present_illness": "...",
  "therapies_administered": "...",
  "discharge_medication_notes": "...",
  "plan": "...",
  "discharge_condition": "...",
  "discharge_conclusion": "..."
}"""

    @api.model
    def _draft_report_user(self, encounter):
        return (
            "Draft the report sections for this encounter.\n\n"
            + self._encounter_context(encounter)
            + "\n\n"
            + self._doctor_notes_block(encounter)
        )

    @api.model
    def draft_report(self, encounter, system=None, user=None):
        """Return ``(dict, log)`` — drafted free-text sections for the PDF
        medical report. Pass ``system``/``user`` to override the built-in
        prompts (used by the preview wizard).
        """
        if system is None:
            system = self._draft_report_system()
        if user is None:
            user = self._draft_report_user(encounter)
        text, log = self._call(
            'report_draft', system, user, encounter=encounter)
        data = self._parse_json(text)
        result = {
            'history_present_illness': data.get('history_present_illness') or '',
            'therapies_administered': data.get('therapies_administered') or '',
            'discharge_medication_notes':
                data.get('discharge_medication_notes') or '',
            'plan': data.get('plan') or '',
            'discharge_condition': data.get('discharge_condition') or '',
            'discharge_conclusion': data.get('discharge_conclusion') or '',
        }
        return result, log

    @api.model
    def _doctor_notes_block(self, encounter):
        """Pass the doctor's terse per-section notes to the AI as seed text."""
        sections = [
            ('Clinical Summary', 'history_present_illness'),
            ('Therapies Administered', 'therapies_administered'),
            ('Discharge Medications', 'discharge_medication_notes'),
            ('Medical Recommendation', 'plan'),
            ('Condition at Discharge', 'discharge_condition'),
            ('Conclusion', 'discharge_conclusion'),
        ]
        lines = ["DOCTOR NOTES (seed text per section — expand these)"]
        for label, field in sections:
            value = html2plaintext(encounter[field] or '').strip()
            lines.append("- %s: %s" % (label, value or '(blank)'))
        # Structured prescription items, so the discharge_medication_notes
        # narrative can name and dose the drugs accurately.
        if encounter.prescription_line_ids:
            lines.append("")
            lines.append("DISCHARGE PRESCRIPTION ITEMS")
            for rx in encounter.prescription_line_ids:
                parts = [rx.product_name or '']
                if rx._frequency_label():
                    parts.append(rx._frequency_label())
                if rx._route_label():
                    parts.append("(%s)" % rx._route_label())
                if rx.duration_days:
                    parts.append("for %s days" % rx.duration_days)
                if rx.instructions:
                    parts.append("- %s" % rx.instructions)
                lines.append("- " + " ".join(p for p in parts if p).strip())
        return "\n".join(lines)

    @api.model
    def _suggest_diagnoses_system(self):
        catalog = self.env['medical.diagnosis'].search([])
        catalog_text = "\n".join(
            "%s | %s" % (d.code, d.name) for d in catalog)
        return SYSTEM_BASE + """

TASK: Suggest the most relevant ICD-10 diagnoses for this encounter.
You MUST pick only from the catalog of codes provided below — never invent
a code. Respond with ONLY a JSON object (no other text):
{"suggestions": [{"code": "<exact code from catalog>",
                  "rationale": "<one short sentence>"}]}
Suggest at most 5, ordered most to least likely. If nothing fits, return
an empty list.

AVAILABLE ICD-10 CODES (code | description):
""" + catalog_text

    @api.model
    def _suggest_diagnoses_user(self, encounter):
        return "Suggest ICD-10 diagnoses for this encounter.\n\n" \
            + self._encounter_context(encounter)

    @api.model
    def suggest_diagnoses(self, encounter, system=None, user=None):
        """Return ``(list, log)`` — suggested ``{code, rationale}`` dicts."""
        if system is None:
            system = self._suggest_diagnoses_system()
        if user is None:
            user = self._suggest_diagnoses_user(encounter)
        text, log = self._call(
            'diagnosis_suggest', system, user, encounter=encounter)
        data = self._parse_json(text)
        return data.get('suggestions') or [], log

    @api.model
    def _summarize_patient_system(self):
        return SYSTEM_BASE + """

TASK: Write a concise clinical briefing of this patient for a clinician who
is about to see them. Cover active problems, relevant history, allergies and
current medications, and anything that needs attention. Use short paragraphs
or bullet points. Plain text only."""

    @api.model
    def _summarize_patient_user(self, patient):
        return "Summarise this patient.\n\n" \
            + self._patient_full_context(patient)

    @api.model
    def summarize_patient(self, patient, system=None, user=None):
        """Return ``(text, log)`` — a concise clinical briefing."""
        if system is None:
            system = self._summarize_patient_system()
        if user is None:
            user = self._summarize_patient_user(patient)
        return self._call('history_summary', system, user, patient=patient)

    @api.model
    def _safety_check_system(self):
        return SYSTEM_BASE + """

TASK: Review this encounter's assessment and plan for safety concerns. Check
the proposed treatment against the patient's documented allergies and current
medications, and flag drug interactions, contraindications, duplicate therapy,
dosing concerns and missing safety steps.
Plain text only. Start with one overall line — either
"Overall: no major concerns identified" or
"Overall: concerns found - see below" — then list specific findings.
If something cannot be assessed because data is missing, say so."""

    @api.model
    def _safety_check_user(self, encounter):
        return "Perform a safety check on this encounter.\n\n" \
            + self._encounter_context(encounter)

    @api.model
    def safety_check(self, encounter, system=None, user=None):
        """Return ``(text, log)`` — a safety review of the encounter plan."""
        if system is None:
            system = self._safety_check_system()
        if user is None:
            user = self._safety_check_user(encounter)
        return self._call('safety_check', system, user, encounter=encounter)

    # ============================================================
    # Prompt preview helpers
    # ============================================================
    @api.model
    def build_prompts(self, mode, encounter=None, patient=None):
        """Return ``(system, user)`` for a given preview mode without
        sending anything. Used by the prompt-preview wizard."""
        if mode == 'report':
            return self._draft_report_system(), self._draft_report_user(encounter)
        if mode == 'diagnosis':
            return (self._suggest_diagnoses_system(),
                    self._suggest_diagnoses_user(encounter))
        if mode == 'summary':
            return (self._summarize_patient_system(),
                    self._summarize_patient_user(patient))
        if mode == 'safety':
            return (self._safety_check_system(),
                    self._safety_check_user(encounter))
        raise UserError(_("Unknown AI preview mode: %s") % mode)

    @api.model
    def preview_enabled(self):
        """Read the 'show prompt preview' user setting (default on)."""
        val = self.env['ir.config_parameter'].sudo().get_param(
            'medical_app_ai.preview_prompts', 'True')
        return str(val).strip().lower() not in ('0', 'false', 'no', '')
