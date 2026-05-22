# Medical AI Assistant (`medical_app_ai`)

Phase 3 — a configurable AI layer on top of `medical_app`. Works with
**Anthropic (Claude)**, **Google (Gemini)** and **OpenAI (GPT)**.

## What it does

On a clinical encounter, a doctor gets four **AI Assist** buttons on the
Consultation tab:

| Button | What it does |
|--------|--------------|
| **Draft SOAP** | Drafts History / Exam / Assessment / Plan from the encounter data. |
| **Suggest Diagnoses** | Recommends ICD-10 codes from the catalog. |
| **Summarize Patient** | Produces a short clinical briefing of the patient. |
| **Safety Check** | Reviews the plan against the patient's allergies and medications. |

Every result opens in a review wizard. The doctor edits/accepts or discards —
**nothing is written to the record automatically**. All requests are recorded
in **Medical → Configuration → AI Activity Log**.

## Setup

1. Install the SDK for the provider(s) you want to use on the Odoo server:
   ```
   pip install -U anthropic      # Anthropic (Claude)
   pip install -U google-genai   # Google (Gemini)
   pip install -U openai         # OpenAI (GPT)
   ```
   Only the SDK for the *selected* provider is needed.
2. Install this module (it depends on `medical_app`).
3. In **Medical → Configuration → AI Configuration**, pick the provider,
   enter its API key and model. Each provider keeps its own key/model, so
   you can switch between them freely.

The API key can also come from an environment variable on the server:
`ANTHROPIC_API_KEY`, `GEMINI_API_KEY` / `GOOGLE_API_KEY`, or `OPENAI_API_KEY`.

## Providers

| Provider | Default model | SDK package |
|----------|---------------|-------------|
| Anthropic (Claude) | `claude-opus-4-7` | `anthropic` |
| Google (Gemini) | `gemini-2.5-pro` | `google-genai` |
| OpenAI (GPT) | `gpt-4o` | `openai` |

To add another provider: add an entry to `PROVIDERS` and a matching
`_call_<provider>` handler in `medical_ai_service.py` — nothing else changes.

## ID document OCR

A **Scan ID Document** button is available on:

- the patient form (header)
- the contact (`res.partner`) form (button box)
- **Medical → Operations → Scan ID Document** (standalone, creates a new contact)

The wizard accepts an image of a passport or national ID card and runs OCR in
two stages:

1. **MRZ parser** (offline, deterministic). Requires `passporteye` and
   `tesseract-ocr` on the server:
   ```
   pip install passporteye
   apt-get install tesseract-ocr
   ```
   Reads the machine-readable zone at the bottom of passports / ID-1 cards.

2. **AI vision fallback** through the configured provider. Used when MRZ is
   missing/unreadable, or when "AI vision only" is selected. Works on any
   document the vision model can read (residence permits, driver licenses,
   handwritten cards).

The extracted fields are shown for **review** — the operator edits anything
that looks wrong and clicks **Apply**. Patient fields (`date_of_birth`,
`gender`, `national_id`) and contact fields (`name`, `country_id`) are updated.
The uploaded image is also attached to the record. Every AI call lands in the
AI Activity Log under the `id_ocr` feature.

## Design notes

- `medical.ai.service` — audited, provider-agnostic wrapper. `_call`
  dispatches to a per-provider `_call_<provider>` handler; the Anthropic
  handler uses adaptive thinking and prompt caching on the stable system
  prompt.
- `medical.ai.log` — full audit trail (provider, model, prompt, response,
  tokens, accepted).
- `medical.ai.suggestion` — the doctor's review/accept wizard.
- AI output is always presented as a **suggestion**; the clinician decides.
- API keys are never hard-coded — they live in `ir.config_parameter`
  (namespaced per provider) or the environment.
