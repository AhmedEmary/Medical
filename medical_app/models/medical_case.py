# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Patient categories treated as "corporate" — medical cases are only for
# company employees, not hotel guests or one-off external patients.
CORPORATE_CATEGORIES = ('employee', 'non_hotel_employee')


class MedicalCase(models.Model):
    """A medical case (episode) grouping several encounters for one problem.

    Corporate/employee patients often return several times for the same
    underlying problem — e.g. a bus-accident injury: an initial consultation,
    then imaging, then follow-ups. Each visit is still its own
    ``medical.encounter``; the case ties them together so the whole history of
    one problem lives in one place and can be printed as a single
    "Medical Condition Report".
    """
    _name = 'medical.case'
    _description = 'Medical Case'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'
    _rec_name = 'reference'

    # ------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------
    reference = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        default=lambda self: _('New'), index=True, tracking=True,
    )
    name = fields.Char(
        string='Case Title', required=True, tracking=True,
        help="Short description of the problem, e.g. "
             "'Bus accident — multiple injuries'.",
    )
    patient_id = fields.Many2one(
        'medical.patient', required=True, ondelete='restrict',
        index=True, tracking=True,
        domain="[('patient_category', 'in', "
               "['employee', 'non_hotel_employee'])]",
        help="Medical cases are only for corporate/company employees.",
    )
    doctor_id = fields.Many2one(
        'res.users', string='Medical Consultant',
        default=lambda self: self.env.user, tracking=True,
        help="Consultant responsible for the case; signs the report.",
    )
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(default=True, tracking=True)

    # ------------------------------------------------------------
    # Case narrative (editable; can be AI-drafted in medical_app_ai)
    # ------------------------------------------------------------
    onset_date = fields.Date(
        string='Complaint Start Date', tracking=True,
        help="When the problem / injury started.",
    )
    cause = fields.Html(
        string='Cause of Injury / Illness',
        help="How the problem started. Printed on the Medical Condition Report.",
    )
    initial_diagnosis = fields.Html(
        string='Initial Medical Diagnosis',
        help="The working diagnosis at the start of the case.",
    )
    current_complaint = fields.Html(
        string='Current Medical Complaint',
        help="The patient's current status / remaining complaint.",
    )
    sick_leave_note = fields.Html(
        string='Sick Leave',
        help="Sick-leave status for this case.",
    )

    # ------------------------------------------------------------
    # Linked encounters
    # ------------------------------------------------------------
    encounter_ids = fields.One2many(
        'medical.encounter', 'case_id', string='Encounters',
    )
    encounter_count = fields.Integer(compute='_compute_encounter_count')
    encounter_to_link_id = fields.Many2one(
        'medical.encounter', string='Link Existing Encounter',
        help="Pick one of this patient's encounters that is not yet on a "
             "case, then click Link to attach it.",
    )

    # ------------------------------------------------------------
    # Workflow state
    # ------------------------------------------------------------
    state = fields.Selection([
        ('open', 'Open'),
        ('closed', 'Closed'),
    ], default='open', required=True, tracking=True, index=True)

    # ============================================================
    # Computed
    # ============================================================
    @api.depends('encounter_ids')
    def _compute_encounter_count(self):
        for rec in self:
            rec.encounter_count = len(rec.encounter_ids)

    # ============================================================
    # CRUD
    # ============================================================
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('reference', _('New')) == _('New'):
                vals['reference'] = self.env['ir.sequence'].next_by_code(
                    'medical.case') or _('New')
        return super().create(vals_list)

    @api.constrains('patient_id')
    def _check_patient_corporate(self):
        for rec in self:
            if (rec.patient_id and
                    rec.patient_id.patient_category not in CORPORATE_CATEGORIES):
                raise ValidationError(_(
                    "Medical cases are only for corporate/company employees. "
                    "'%s' is not an employee patient.", rec.patient_id.name))

    # ============================================================
    # Actions
    # ============================================================
    def action_view_encounters(self):
        """Stat button: open this case's encounters."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Encounters'),
            'res_model': 'medical.encounter',
            'view_mode': 'list,form',
            'domain': [('case_id', '=', self.id)],
            'context': {
                'default_case_id': self.id,
                'default_patient_id': self.patient_id.id,
            },
        }

    def action_link_encounter(self):
        """Attach the picked existing encounter to this case."""
        self.ensure_one()
        enc = self.encounter_to_link_id
        if not enc:
            return
        if enc.patient_id != self.patient_id:
            raise ValidationError(_(
                "That encounter belongs to a different patient."))
        enc.case_id = self.id
        self.encounter_to_link_id = False

    def action_close(self):
        self.write({'state': 'closed'})

    def action_reopen(self):
        self.write({'state': 'open'})

    # ============================================================
    # Report helpers
    # ============================================================
    def _report_employee_data(self):
        """Corporate/employee identity printed on the Medical Condition Report.

        ``job_title`` is defined by the optional ``medical_app_entity`` module,
        so it's read defensively via ``getattr``. The Hotel ID also falls back
        to that module's ``employee_code`` when present, so either data source
        works.
        """
        self.ensure_one()
        patient = self.patient_id
        return {
            'hotel_id_number': (patient.hotel_id_number
                                or getattr(patient, 'employee_code', False)),
            'age': patient.age,
            'department': patient.department,
            'job_title': getattr(patient, 'job_title', False),
            'hire_date': patient.hire_date,
            'hotel_name': patient.hotel_name,
            'contact': patient.mobile or patient.phone,
        }

    def _report_encounters(self):
        """Linked encounters in chronological order for the timeline table."""
        self.ensure_one()
        return self.encounter_ids.sorted(
            key=lambda e: (e.encounter_date or fields.Datetime.now()))
