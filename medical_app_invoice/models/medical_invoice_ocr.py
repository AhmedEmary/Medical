# -*- coding: utf-8 -*-
"""Medical invoice OCR service.

Reads an invoice image (printed or scanned) using the configured AI vision
provider and returns a normalized dict that the Scan Invoice wizard can
preview and apply to an ``account.move``.

A single call can ingest multiple pages — for example a multi-page invoice
or an invoice plus a separate sheet with patient information — the AI
merges the data into one structured payload.
"""
import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


OCR_SYSTEM_PROMPT = """You are an OCR assistant that reads medical \
invoices and bills and extracts the data into strict JSON for a \
hospital ERP.

Rules:
- Read only what is printed on the images. NEVER invent line items, \
amounts, quantities, names or numbers.
- If a value cannot be read with confidence, leave it as an empty string \
(or null for numeric fields).
- The image typically contains a header (invoice number, dates, patient \
information, payment terms) and a table of invoice lines with columns \
such as DESCRIPTION, QUANTITY, UNIT PRICE and AMOUNT.
- Multiple images may be supplied (e.g. multi-page invoice or a separate \
patient information sheet). Merge data from ALL images into one payload \
— do not duplicate lines.
- All monetary amounts MUST be plain decimal numbers (no currency \
symbols, no thousand separators). For example "1,500.00" becomes 1500.00.
- Quantities are decimal numbers; default to 1.0 when not stated.
- For each invoice line, "description" is the line text exactly as \
printed, "quantity" and "price_unit" are numbers, and "amount" is \
quantity * price_unit. Skip rows that are subtotals / totals / taxes \
— include only actual product or service lines.
- "invoice_date" and "due_date" MUST be ISO format YYYY-MM-DD if \
readable; otherwise empty string.
- "currency" is the ISO 4217 code if you can identify it (e.g. "USD", \
"EUR", "EGP"); otherwise empty string.
- "patient_name", "patient_id_number", "hotel_name", "room_number" come \
from the patient block of the invoice, if present.
- Output ONLY the JSON object — no commentary, no markdown fences."""


OCR_USER_PROMPT = """Extract the invoice data from the attached image(s). \
Respond with ONLY a JSON object using exactly these keys:

{
  "invoice_number": "",
  "invoice_date": "",
  "due_date": "",
  "currency": "",
  "payment_terms": "",
  "patient_name": "",
  "patient_id_number": "",
  "hotel_name": "",
  "room_number": "",
  "narration": "",
  "lines": [
    {
      "description": "",
      "quantity": 1.0,
      "price_unit": 0.0,
      "amount": 0.0
    }
  ],
  "subtotal": null,
  "tax_total": null,
  "total": null
}

Notes on each field:
- "invoice_number": the bill / invoice number as printed.
- "invoice_date" / "due_date": ISO YYYY-MM-DD or empty.
- "payment_terms": the payment-terms phrase as printed (e.g.
  "Immediate Payment", "Net 30").
- "patient_name": the patient's full name if printed on the invoice.
- "patient_id_number": passport / national ID / MRN as printed.
- "hotel_name" / "room_number": only if the invoice shows them.
- "narration": any free-text notes / remarks printed on the invoice.
- "lines": one object per service or product line; leave [] if the
  invoice has no itemised lines."""


class MedicalInvoiceOcrService(models.AbstractModel):
    """Stateless OCR helper used by the Scan Invoice wizard."""
    _name = 'medical.invoice.ocr.service'
    _description = 'Medical Invoice Document OCR Service'

    @api.model
    def extract(self, images, move=None):
        """Extract invoice data from one or more document images.

        :param images: list of ``{'data': <base64-str>, 'mime_type': <str>}``
            dicts. Must contain at least one image.
        :param move: optional ``account.move`` the data will be applied
            to (used only to attach the AI log to the right patient
            audit trail).
        :return: normalized dict — see :data:`OCR_USER_PROMPT` for the
            shape. All keys are always present; missing values are empty
            strings, empty lists, or ``None``.
        """
        if not images:
            raise UserError(_("Please upload at least one invoice image."))

        primary = images[0]
        service = self.env['medical.ai.service']
        patient = move.patient_id if move and move.patient_id else None
        text, _log = service._call_vision(
            feature='invoice_ocr',
            system_prompt=OCR_SYSTEM_PROMPT,
            user_prompt=OCR_USER_PROMPT,
            image_b64=primary['data'],
            mime_type=primary.get('mime_type') or 'image/jpeg',
            extra_images=images[1:],
            patient=patient,
            max_tokens=4000,
        )
        data = service._parse_json(text)
        normalized = self._normalize(data)
        normalized['raw_text'] = text
        return normalized

    @api.model
    def _normalize(self, data):
        return {
            'invoice_number': (data.get('invoice_number') or '').strip(),
            'invoice_date': _iso_or_empty(data.get('invoice_date')),
            'due_date': _iso_or_empty(data.get('due_date')),
            'currency': (data.get('currency') or '').strip().upper(),
            'payment_terms': (data.get('payment_terms') or '').strip(),
            'patient_name': (data.get('patient_name') or '').strip(),
            'patient_id_number':
                (data.get('patient_id_number') or '').strip(),
            'hotel_name': (data.get('hotel_name') or '').strip(),
            'room_number': (data.get('room_number') or '').strip(),
            'narration': (data.get('narration') or '').strip(),
            'subtotal': _to_float(data.get('subtotal')),
            'tax_total': _to_float(data.get('tax_total')),
            'total': _to_float(data.get('total')),
            'lines': [
                self._normalize_line(line)
                for line in (data.get('lines') or [])
                if line and (line.get('description') or '').strip()
            ],
        }

    @api.model
    def _normalize_line(self, line):
        quantity = _to_float(line.get('quantity'))
        price_unit = _to_float(line.get('price_unit'))
        amount = _to_float(line.get('amount'))
        # Reconcile quantity/price_unit/amount: if one is missing but the
        # other two are present, derive it so the row is usable.
        if quantity is None and price_unit and amount:
            try:
                quantity = round(amount / price_unit, 4) if price_unit else None
            except ZeroDivisionError:
                quantity = None
        if price_unit is None and quantity and amount:
            try:
                price_unit = round(amount / quantity, 4) if quantity else None
            except ZeroDivisionError:
                price_unit = None
        return {
            'description': (line.get('description') or '').strip(),
            'quantity': quantity if quantity is not None else 1.0,
            'price_unit': price_unit if price_unit is not None else 0.0,
            'amount': amount if amount is not None else 0.0,
        }


def _iso_or_empty(value):
    if not value or not isinstance(value, str):
        return ''
    return value.strip()[:10]


def _to_float(value):
    if value in (None, '', False):
        return None
    if isinstance(value, str):
        cleaned = value.replace(',', '').strip()
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None