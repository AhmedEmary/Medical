# -*- coding: utf-8 -*-
"""Scan ID Document wizard.

Reception uploads an image of a passport / national ID, the wizard runs OCR
(MRZ first, AI vision fallback) and shows the extracted fields. The user can
edit anything that looks off, then click Apply to write the data onto either
a patient record, a contact, or both.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DOC_TYPES = [
    ('passport', 'Passport'),
    ('national_id', 'National ID Card'),
    ('residence_permit', 'Residence Permit'),
    ('driver_license', 'Driver License'),
    ('other', 'Other'),
]

SEX_SELECTION = [
    ('male', 'Male'),
    ('female', 'Female'),
    ('other', 'Other'),
]

EXTRACTION_MODES = [
    ('auto', 'Auto (MRZ + AI fallback)'),
    ('mrz', 'MRZ only (offline, passports)'),
    ('ai', 'AI vision only'),
]


class MedicalIdScanWizard(models.TransientModel):
    """Scan an ID document and pre-fill patient / contact fields."""
    _name = 'medical.id.scan.wizard'
    _description = 'Scan ID Document'

    # ------------------------------------------------------------
    # Input
    # ------------------------------------------------------------
    # Image is intentionally NOT model-level required: we validate it in
    # action_scan so the user gets a clear "Please upload an image" message
    # instead of Odoo's generic "Missing required fields" form-save popup.
    image = fields.Binary(
        string='Document Image', attachment=False,
        help="Front side of the passport (with the MRZ visible) or "
             "national ID card.")
    image_filename = fields.Char()
    doc_type = fields.Selection(
        DOC_TYPES, string='Document Type', default='passport')
    extraction_mode = fields.Selection(
        EXTRACTION_MODES, string='Extraction Mode', default='auto',
        help="How to read the document. 'Auto' tries the offline MRZ parser "
             "first, then falls back to the configured AI vision provider.")

    # Targets — at most one of these is set at any time, depending on
    # where the wizard was opened from.
    patient_id = fields.Many2one('medical.patient', string='Patient')
    partner_id = fields.Many2one('res.partner', string='Contact')

    # ------------------------------------------------------------
    # Extracted (editable) fields
    # ------------------------------------------------------------
    state = fields.Selection([
        ('upload', 'Upload'),
        ('review', 'Review'),
    ], default='upload', required=True)
    source = fields.Selection([
        ('mrz', 'MRZ (offline)'),
        ('ai', 'AI vision'),
    ], readonly=True,
        help="Which strategy produced the extracted data.")

    surname = fields.Char()
    given_names = fields.Char()
    full_name = fields.Char(string='Full Name')
    sex = fields.Selection(SEX_SELECTION, string='Sex')
    date_of_birth = fields.Date()
    document_number = fields.Char(string='Document Number')
    nationality = fields.Char(help="ISO 3-letter country code.")
    country_id = fields.Many2one(
        'res.country', string='Issuing Country',
        help="Resolved from the document's country code.")
    issue_date = fields.Date()
    expiry_date = fields.Date()
    place_of_birth = fields.Char()
    raw_text = fields.Text(string='Raw OCR Output', readonly=True)

    # ============================================================
    # Default targets — populated from the action context
    # ============================================================
    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        ctx = self.env.context
        if ctx.get('default_patient_id') or ctx.get('active_patient_id'):
            vals['patient_id'] = (ctx.get('default_patient_id')
                                  or ctx.get('active_patient_id'))
        if ctx.get('default_partner_id') or ctx.get('active_partner_id'):
            vals['partner_id'] = (ctx.get('default_partner_id')
                                  or ctx.get('active_partner_id'))
        # Convenience: if opened from a patient, also resolve its partner so
        # the Apply step can update both records in one go.
        if vals.get('patient_id') and not vals.get('partner_id'):
            patient = self.env['medical.patient'].browse(vals['patient_id'])
            vals['partner_id'] = patient.partner_id.id
        return vals

    # ============================================================
    # Actions
    # ============================================================
    def action_scan(self):
        """Run OCR on the uploaded image and switch to review mode."""
        self.ensure_one()
        if not self.image:
            raise UserError(_("Please upload an image of the document."))
        if not self.doc_type:
            self.doc_type = 'passport'
        if not self.extraction_mode:
            self.extraction_mode = 'auto'

        mime_type = _guess_mime(self.image_filename)
        ocr = self.env['medical.id.ocr.service']
        result = ocr.extract(
            image_b64=self.image.decode() if isinstance(self.image, bytes)
            else self.image,
            mime_type=mime_type,
            prefer=self.extraction_mode,
            partner=self.partner_id or None,
            patient=self.patient_id or None,
        )

        # Resolve the country code (ISO alpha-3 or alpha-2) to a res.country.
        country = self._resolve_country(result.get('country_code')
                                        or result.get('nationality'))

        # Prefer an explicit document type if the user picked one; otherwise
        # take what the OCR returned (only if it matches our selection).
        doc_type = self.doc_type
        ocr_doc_type = result.get('document_type')
        if ocr_doc_type and ocr_doc_type in dict(DOC_TYPES):
            doc_type = ocr_doc_type

        self.write({
            'state': 'review',
            'source': result.get('source') or False,
            'surname': result.get('surname') or '',
            'given_names': result.get('given_names') or '',
            'full_name': result.get('full_name') or '',
            'sex': result.get('sex') or False,
            'date_of_birth': result.get('date_of_birth') or False,
            'document_number': result.get('document_number') or '',
            'nationality': result.get('nationality') or '',
            'country_id': country.id if country else False,
            'issue_date': result.get('issue_date') or False,
            'expiry_date': result.get('expiry_date') or False,
            'place_of_birth': result.get('place_of_birth') or '',
            'raw_text': result.get('raw_text') or '',
            'doc_type': doc_type,
        })
        return self._reopen()

    def action_apply(self):
        """Write the reviewed data onto the target record(s).

        Three entry points:

        - **Existing patient**: update both the patient and its contact.
        - **Existing contact** (not a patient): update the contact only.
        - **Standalone** (launched from the menu, no target): create a fresh
          contact AND a fresh ``medical.patient`` linked to it, so the
          operator lands on a ready-to-edit patient record.
        """
        self.ensure_one()
        partner_vals, patient_vals = self._build_write_vals()

        partner = self.partner_id
        patient = self.patient_id

        if not partner and not patient:
            if not partner_vals.get('name'):
                raise UserError(_(
                    "No name was extracted from the document. "
                    "Fill in 'Full Name' before applying."))
            partner_vals['is_patient'] = True
            partner = self.env['res.partner'].create(partner_vals)
            patient = self.env['medical.patient'].create({
                **patient_vals,
                'partner_id': partner.id,
            })
        else:
            if partner and partner_vals:
                partner.write(partner_vals)
            if patient and patient_vals:
                patient.write(patient_vals)

        # Attach the scanned image to the partner (and patient) so we keep
        # a copy of the source document on record.
        if self.image:
            self._attach_document(partner, patient)

        return self._open_target(partner, patient)

    def action_back_to_upload(self):
        """Go back to the upload screen to try a different image."""
        self.ensure_one()
        self.write({'state': 'upload'})
        return self._reopen()

    # ============================================================
    # Helpers
    # ============================================================
    def _build_write_vals(self):
        """Split the wizard fields into partner-side and patient-side vals."""
        partner_vals = {}
        patient_vals = {}

        full_name = (self.full_name or
                     ' '.join(p for p in (self.given_names, self.surname)
                              if p)).strip()
        if full_name:
            partner_vals['name'] = full_name
        if self.country_id:
            partner_vals['country_id'] = self.country_id.id

        if self.date_of_birth:
            patient_vals['date_of_birth'] = self.date_of_birth
        if self.sex:
            patient_vals['gender'] = self.sex
        if self.document_number:
            patient_vals['national_id'] = self.document_number

        return partner_vals, patient_vals

    def _resolve_country(self, code):
        """Find a res.country from an ISO alpha-3 or alpha-2 code.

        ``res.country`` only stores the alpha-2 ISO code, so alpha-3 codes
        (the format used by passport MRZ) are translated via :data:`ALPHA3_TO_ALPHA2`.
        """
        if not code:
            return self.env['res.country'].browse()
        code = code.upper().strip()
        if len(code) == 3:
            code = ALPHA3_TO_ALPHA2.get(code, '')
        if len(code) != 2:
            return self.env['res.country'].browse()
        return self.env['res.country'].search([('code', '=', code)], limit=1)

    def _attach_document(self, partner, patient):
        """Save the uploaded image as an ir.attachment on the target(s)."""
        Attachment = self.env['ir.attachment'].sudo()
        filename = self.image_filename or _('id_document')
        mime = _guess_mime(filename)
        common = {
            'name': filename,
            'datas': self.image,
            'mimetype': mime,
        }
        if partner:
            Attachment.create({**common,
                               'res_model': 'res.partner',
                               'res_id': partner.id})
        if patient:
            Attachment.create({**common,
                               'res_model': 'medical.patient',
                               'res_id': patient.id})

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Scan ID Document'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _open_target(self, partner, patient):
        """After Apply, navigate to whichever record the wizard updated."""
        if patient:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Patient'),
                'res_model': 'medical.patient',
                'res_id': patient.id,
                'view_mode': 'form',
            }
        if partner:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Contact'),
                'res_model': 'res.partner',
                'res_id': partner.id,
                'view_mode': 'form',
            }
        return {'type': 'ir.actions.act_window_close'}


def _guess_mime(filename):
    name = (filename or '').lower()
    if name.endswith('.png'):
        return 'image/png'
    if name.endswith('.webp'):
        return 'image/webp'
    if name.endswith('.heic') or name.endswith('.heif'):
        return 'image/heic'
    if name.endswith('.pdf'):
        return 'application/pdf'
    return 'image/jpeg'


# ISO 3166-1 alpha-3 → alpha-2 mapping for the country codes that appear on
# passport MRZ. ``res.country`` only stores alpha-2, so we translate here.
ALPHA3_TO_ALPHA2 = {
    'AFG': 'AF', 'ALB': 'AL', 'DZA': 'DZ', 'AND': 'AD', 'AGO': 'AO',
    'ATG': 'AG', 'ARG': 'AR', 'ARM': 'AM', 'AUS': 'AU', 'AUT': 'AT',
    'AZE': 'AZ', 'BHS': 'BS', 'BHR': 'BH', 'BGD': 'BD', 'BRB': 'BB',
    'BLR': 'BY', 'BEL': 'BE', 'BLZ': 'BZ', 'BEN': 'BJ', 'BTN': 'BT',
    'BOL': 'BO', 'BIH': 'BA', 'BWA': 'BW', 'BRA': 'BR', 'BRN': 'BN',
    'BGR': 'BG', 'BFA': 'BF', 'BDI': 'BI', 'CPV': 'CV', 'KHM': 'KH',
    'CMR': 'CM', 'CAN': 'CA', 'CAF': 'CF', 'TCD': 'TD', 'CHL': 'CL',
    'CHN': 'CN', 'COL': 'CO', 'COM': 'KM', 'COG': 'CG', 'COD': 'CD',
    'CRI': 'CR', 'CIV': 'CI', 'HRV': 'HR', 'CUB': 'CU', 'CYP': 'CY',
    'CZE': 'CZ', 'DNK': 'DK', 'DJI': 'DJ', 'DMA': 'DM', 'DOM': 'DO',
    'ECU': 'EC', 'EGY': 'EG', 'SLV': 'SV', 'GNQ': 'GQ', 'ERI': 'ER',
    'EST': 'EE', 'SWZ': 'SZ', 'ETH': 'ET', 'FJI': 'FJ', 'FIN': 'FI',
    'FRA': 'FR', 'GAB': 'GA', 'GMB': 'GM', 'GEO': 'GE', 'DEU': 'DE',
    'GHA': 'GH', 'GRC': 'GR', 'GRD': 'GD', 'GTM': 'GT', 'GIN': 'GN',
    'GNB': 'GW', 'GUY': 'GY', 'HTI': 'HT', 'HND': 'HN', 'HUN': 'HU',
    'ISL': 'IS', 'IND': 'IN', 'IDN': 'ID', 'IRN': 'IR', 'IRQ': 'IQ',
    'IRL': 'IE', 'ISR': 'IL', 'ITA': 'IT', 'JAM': 'JM', 'JPN': 'JP',
    'JOR': 'JO', 'KAZ': 'KZ', 'KEN': 'KE', 'KIR': 'KI', 'PRK': 'KP',
    'KOR': 'KR', 'KWT': 'KW', 'KGZ': 'KG', 'LAO': 'LA', 'LVA': 'LV',
    'LBN': 'LB', 'LSO': 'LS', 'LBR': 'LR', 'LBY': 'LY', 'LIE': 'LI',
    'LTU': 'LT', 'LUX': 'LU', 'MDG': 'MG', 'MWI': 'MW', 'MYS': 'MY',
    'MDV': 'MV', 'MLI': 'ML', 'MLT': 'MT', 'MHL': 'MH', 'MRT': 'MR',
    'MUS': 'MU', 'MEX': 'MX', 'FSM': 'FM', 'MDA': 'MD', 'MCO': 'MC',
    'MNG': 'MN', 'MNE': 'ME', 'MAR': 'MA', 'MOZ': 'MZ', 'MMR': 'MM',
    'NAM': 'NA', 'NRU': 'NR', 'NPL': 'NP', 'NLD': 'NL', 'NZL': 'NZ',
    'NIC': 'NI', 'NER': 'NE', 'NGA': 'NG', 'MKD': 'MK', 'NOR': 'NO',
    'OMN': 'OM', 'PAK': 'PK', 'PLW': 'PW', 'PSE': 'PS', 'PAN': 'PA',
    'PNG': 'PG', 'PRY': 'PY', 'PER': 'PE', 'PHL': 'PH', 'POL': 'PL',
    'PRT': 'PT', 'QAT': 'QA', 'ROU': 'RO', 'RUS': 'RU', 'RWA': 'RW',
    'KNA': 'KN', 'LCA': 'LC', 'VCT': 'VC', 'WSM': 'WS', 'SMR': 'SM',
    'STP': 'ST', 'SAU': 'SA', 'SEN': 'SN', 'SRB': 'RS', 'SYC': 'SC',
    'SLE': 'SL', 'SGP': 'SG', 'SVK': 'SK', 'SVN': 'SI', 'SLB': 'SB',
    'SOM': 'SO', 'ZAF': 'ZA', 'SSD': 'SS', 'ESP': 'ES', 'LKA': 'LK',
    'SDN': 'SD', 'SUR': 'SR', 'SWE': 'SE', 'CHE': 'CH', 'SYR': 'SY',
    'TWN': 'TW', 'TJK': 'TJ', 'TZA': 'TZ', 'THA': 'TH', 'TLS': 'TL',
    'TGO': 'TG', 'TON': 'TO', 'TTO': 'TT', 'TUN': 'TN', 'TUR': 'TR',
    'TKM': 'TM', 'TUV': 'TV', 'UGA': 'UG', 'UKR': 'UA', 'ARE': 'AE',
    'GBR': 'GB', 'USA': 'US', 'URY': 'UY', 'UZB': 'UZ', 'VUT': 'VU',
    'VAT': 'VA', 'VEN': 'VE', 'VNM': 'VN', 'YEM': 'YE', 'ZMB': 'ZM',
    'ZWE': 'ZW', 'HKG': 'HK', 'MAC': 'MO',
}