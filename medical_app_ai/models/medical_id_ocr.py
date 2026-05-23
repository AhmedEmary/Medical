# -*- coding: utf-8 -*-
"""ID document OCR service.

Reads a passport / national ID image and returns a normalized dict of patient
identity fields. Two strategies are tried in order:

1. **MRZ parsing** via the optional ``passporteye`` package — deterministic
   and offline, but only works for documents with a Machine-Readable Zone
   (passports, some national ID cards) and needs Tesseract installed.

2. **AI vision fallback** through :class:`medical.ai.service`, which sends the
   image to the configured provider (Claude / Gemini / GPT) and asks for a
   structured JSON extraction.

The returned dict always has the same keys so the wizard can render a stable
form regardless of which strategy ran. Missing values are empty strings (or
``False`` for dates).
"""
import base64
import logging
from datetime import date, datetime
from io import BytesIO

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# passporteye is optional. We catch any exception, not just ImportError,
# because the library transitively imports scikit-image / numpy and can fail
# with non-ImportError errors on mismatched dep versions. We must never let
# this take down the whole module — the AI fallback should still work.
try:
    from passporteye import read_mrz
except Exception:  # noqa: BLE001 - intentionally swallow all import errors
    read_mrz = None
    logging.getLogger(__name__).info(
        "passporteye is not available; MRZ extraction will be skipped.")


# Keys every extraction returns. The wizard binds to these names.
RESULT_FIELDS = (
    'document_type',     # 'passport' / 'national_id' / ''
    'document_number',
    'surname',
    'given_names',
    'full_name',
    'sex',               # 'male' / 'female' / 'other' / ''
    'date_of_birth',     # date or False
    'nationality',       # ISO 3-letter code, upper
    'country_code',      # issuing country, ISO 3-letter, upper
    'issue_date',        # date or False
    'expiry_date',       # date or False
    'place_of_birth',
    'raw_text',          # whatever the source produced, for debugging
    'face_bbox',         # {'x','y','width','height'} as 0-1 floats, or None
)

SEX_MAP = {
    'M': 'male', 'MALE': 'male',
    'F': 'female', 'FEMALE': 'female',
    'X': 'other', 'O': 'other',
}

OCR_SYSTEM_PROMPT = """You are an OCR assistant that reads identity documents \
(passports, national ID cards, residence permits) and returns the holder's \
data as structured JSON.

Rules:
- Read only what is printed on the document. Do not invent or guess.
- For any field you cannot read with confidence, return an empty string \
(or null for dates).
- Dates MUST be in ISO format YYYY-MM-DD.
- "sex" MUST be one of: "male", "female", "other", or "".
- "nationality" and "country_code" MUST be ISO 3166-1 alpha-3 codes \
(e.g. "EGY", "USA", "GBR") if present on the document; otherwise "".
- "document_type" MUST be one of: "passport", "national_id", "residence_permit", \
"driver_license", "other".
- "given_names" is all given/middle names joined by a space.
- "full_name" is given_names + " " + surname.
- Output ONLY the JSON object, no commentary, no markdown fences."""

OCR_USER_PROMPT = """Extract the holder's identity data from this document image.

Also locate the holder's portrait photo on the document and return its
bounding box as relative coordinates: top-left ``x`` and ``y`` together
with ``width`` and ``height``, all as floats between 0 and 1 (fractions
of the image's width and height). If you cannot see a photo, return
``face_bbox`` as null.

Respond with ONLY a JSON object with exactly these keys:
{
  "document_type": "",
  "document_number": "",
  "surname": "",
  "given_names": "",
  "full_name": "",
  "sex": "",
  "date_of_birth": "",
  "nationality": "",
  "country_code": "",
  "issue_date": "",
  "expiry_date": "",
  "place_of_birth": "",
  "face_bbox": {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}
}"""


class MedicalIdOcrService(models.AbstractModel):
    """Stateless OCR helper used by the Scan ID wizard."""
    _name = 'medical.id.ocr.service'
    _description = 'Medical ID Document OCR Service'

    # ============================================================
    # Public entry point
    # ============================================================
    @api.model
    def extract(self, image_b64, mime_type='image/jpeg',
                prefer='auto', partner=None, patient=None):
        """Extract identity data from an ID document image.

        :param image_b64: base64-encoded image bytes (Odoo binary field format).
        :param mime_type: image MIME type (used by the AI fallback).
        :param prefer: ``'mrz'`` (MRZ only), ``'ai'`` (AI only), or
            ``'auto'`` (MRZ first, AI fallback).
        :param partner: optional res.partner to attach the AI log to.
        :param patient: optional medical.patient to attach the AI log to.
        :return: dict with the keys in :data:`RESULT_FIELDS`, plus a
            ``source`` key (``'mrz'`` / ``'ai'``) telling the caller which
            strategy produced the data.
        """
        if not image_b64:
            raise UserError(_("Please upload an image of the document first."))

        result = _empty_result()

        if prefer in ('auto', 'mrz'):
            mrz_data = self._extract_mrz(image_b64)
            if mrz_data:
                result.update(mrz_data)
                result['source'] = 'mrz'
                if prefer == 'mrz' or _is_complete(result):
                    return result

        if prefer in ('auto', 'ai'):
            ai_data = self._extract_ai(
                image_b64, mime_type, patient=patient)
            # Merge: AI fills anything MRZ left blank, doesn't overwrite
            # confident MRZ values.
            for key, value in ai_data.items():
                if not result.get(key) and value:
                    result[key] = value
            result['source'] = result.get('source') or 'ai'
            return result

        if prefer == 'mrz' and not result.get('source'):
            raise UserError(_(
                "No machine-readable zone (MRZ) could be detected on this "
                "image.\n\nMake sure the bottom of the passport (the two "
                "lines of '<' characters) is clearly visible, or switch the "
                "extraction mode to 'AI vision'."))
        return result

    # ============================================================
    # MRZ (offline) strategy
    # ============================================================
    @api.model
    def _extract_mrz(self, image_b64):
        """Try ``passporteye`` MRZ parse. Returns a partial result or ``{}``.

        Returns ``{}`` (not an exception) when the library is missing or the
        MRZ cannot be read — the caller falls back to AI.
        """
        if read_mrz is None:
            _logger.info(
                "passporteye is not installed; skipping MRZ extraction. "
                "Install it with: pip install passporteye")
            return {}
        try:
            mrz = read_mrz(BytesIO(base64.b64decode(image_b64)))
        except Exception as exc:  # noqa: BLE001
            _logger.info("MRZ parsing failed: %s", exc)
            return {}
        if mrz is None:
            return {}
        data = mrz.to_dict()
        if not data or data.get('valid_score', 0) < 30:
            return {}

        surname = (data.get('surname') or '').replace('<', ' ').strip()
        given = (data.get('names') or '').replace('<', ' ').strip()
        full_name = ' '.join(p for p in (given, surname) if p)
        sex = SEX_MAP.get((data.get('sex') or '').upper(), '')
        doc_type = (data.get('type') or '').upper()
        if doc_type.startswith('P'):
            doc_type_norm = 'passport'
        elif doc_type.startswith('I') or doc_type.startswith('A') \
                or doc_type.startswith('C'):
            doc_type_norm = 'national_id'
        else:
            doc_type_norm = ''

        return {
            'document_type': doc_type_norm,
            'document_number': (data.get('number') or '').replace('<', '').strip(),
            'surname': surname,
            'given_names': given,
            'full_name': full_name,
            'sex': sex,
            'date_of_birth': _parse_yymmdd(data.get('date_of_birth')),
            'nationality': (data.get('nationality') or '').upper(),
            'country_code': (data.get('country') or '').upper(),
            'issue_date': False,  # not in MRZ
            'expiry_date': _parse_yymmdd(
                data.get('expiration_date'), future=True),
            'place_of_birth': '',
            'raw_text': data.get('mrz_code') or '',
        }

    # ============================================================
    # AI vision strategy
    # ============================================================
    @api.model
    def _extract_ai(self, image_b64, mime_type, patient=None):
        """Call the configured vision provider and parse its JSON response."""
        service = self.env['medical.ai.service']
        # Use a generous output budget so reasoning-token consumption on
        # 'thinking' models (e.g. Gemini 2.5) doesn't starve the JSON body.
        text, _log = service._call_vision(
            feature='id_ocr',
            system_prompt=OCR_SYSTEM_PROMPT,
            user_prompt=OCR_USER_PROMPT,
            image_b64=image_b64,
            mime_type=mime_type,
            patient=patient,
            max_tokens=8000,
        )
        data = service._parse_json(text)

        return {
            'document_type': _normalize_doc_type(data.get('document_type')),
            'document_number': (data.get('document_number') or '').strip(),
            'surname': (data.get('surname') or '').strip(),
            'given_names': (data.get('given_names') or '').strip(),
            'full_name': (data.get('full_name')
                          or _join_name(data.get('given_names'),
                                        data.get('surname'))),
            'sex': _normalize_sex(data.get('sex')),
            'date_of_birth': _parse_iso(data.get('date_of_birth')),
            'nationality': (data.get('nationality') or '').upper().strip(),
            'country_code': (data.get('country_code') or '').upper().strip(),
            'issue_date': _parse_iso(data.get('issue_date')),
            'expiry_date': _parse_iso(data.get('expiry_date')),
            'place_of_birth': (data.get('place_of_birth') or '').strip(),
            'raw_text': text,
            'face_bbox': _normalize_bbox(data.get('face_bbox')),
        }


# ============================================================
# Helpers (module-level, no Odoo state)
# ============================================================
def _empty_result():
    blanks = {k: ('' if k != 'date_of_birth' and 'date' not in k else False)
              for k in RESULT_FIELDS}
    blanks['face_bbox'] = None
    return blanks


def _normalize_bbox(raw):
    """Return a sanitized ``{x, y, width, height}`` dict (floats 0..1)
    or ``None`` if the AI didn't report a usable face position."""
    if not isinstance(raw, dict):
        return None
    try:
        x = float(raw.get('x') or 0)
        y = float(raw.get('y') or 0)
        w = float(raw.get('width') or 0)
        h = float(raw.get('height') or 0)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    # Clamp into [0, 1] in case the model overshoots.
    x = max(0.0, min(1.0, x))
    y = max(0.0, min(1.0, y))
    w = max(0.0, min(1.0 - x, w))
    h = max(0.0, min(1.0 - y, h))
    if w < 0.02 or h < 0.02:
        # Too small to be a useful crop.
        return None
    return {'x': x, 'y': y, 'width': w, 'height': h}


def _is_complete(result):
    """A result is 'complete enough' to skip the AI fallback."""
    return bool(result.get('full_name')
                and result.get('date_of_birth')
                and result.get('document_number'))


def _normalize_sex(value):
    if not value:
        return ''
    return SEX_MAP.get(value.upper().strip(), '') or (
        value.lower() if value.lower() in ('male', 'female', 'other') else '')


def _normalize_doc_type(value):
    if not value:
        return ''
    v = value.lower().strip().replace(' ', '_').replace('-', '_')
    allowed = {'passport', 'national_id', 'residence_permit',
               'driver_license', 'other'}
    return v if v in allowed else ''


def _join_name(given, surname):
    return ' '.join(p for p in ((given or '').strip(),
                                (surname or '').strip()) if p)


def _parse_iso(value):
    """Parse an ISO date string into a ``date``; return ``False`` if invalid."""
    if not value or not isinstance(value, str):
        return False
    try:
        return datetime.strptime(value.strip()[:10], '%Y-%m-%d').date()
    except ValueError:
        return False


def _parse_yymmdd(value, future=False):
    """Parse the 6-digit ``YYMMDD`` MRZ date format.

    MRZ dates have no century. ``future=True`` (used for expiry dates) keeps
    the year in the next century when the two-digit year is in the past;
    otherwise (DOB) we assume the year is in the past.
    """
    if not value or len(value) != 6 or not value.isdigit():
        return False
    yy, mm, dd = int(value[0:2]), int(value[2:4]), int(value[4:6])
    today = date.today()
    century = today.year - (today.year % 100)
    year = century + yy
    if future:
        if year < today.year:
            year += 100
    else:
        if year > today.year:
            year -= 100
    try:
        return date(year, mm, dd)
    except ValueError:
        return False