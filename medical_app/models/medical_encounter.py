# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MedicalEncounter(models.Model):
    """A clinical encounter (visit/consultation).

    Central transactional document tying together the patient, doctor,
    vitals, diagnoses, prescriptions, and the printed medical report.

    State machine: draft -> in_progress -> completed (or cancelled).
    """
    _name = 'medical.encounter'
    _description = 'Clinical Encounter'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'encounter_date desc, id desc'
    _rec_name = 'reference'

    # ------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------
    reference = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        default=lambda self: _('New'), index=True, tracking=True,
    )
    patient_id = fields.Many2one(
        'medical.patient', required=True, ondelete='restrict',
        index=True, tracking=True,
    )
    doctor_id = fields.Many2one(
        'res.users', string='Doctor',
        domain=lambda self: [
            ('all_group_ids', 'in', self.env.ref('medical_app.group_medical_doctor').id)
        ] if self.env.ref('medical_app.group_medical_doctor', raise_if_not_found=False) else [],
        default=lambda self: self.env.user,
        tracking=True,
    )
    doctor_employee_id = fields.Many2one(
        'hr.employee', string='DoctorI have',
        default=lambda self: self.env.user.employee_id,
        tracking=True,
        help="HR employee record for the doctor — used for job title, "
             "work email and other HR-side data on reports.",
    )
    encounter_date = fields.Datetime(
        string='Date & Time', required=True,
        default=fields.Datetime.now, tracking=True,
    )

    # ------------------------------------------------------------
    # Clinical inputs (free-text on the encounter)
    # ------------------------------------------------------------
    encounter_type = fields.Selection([
        ('consultation', 'Consultation'),
        ('follow_up', 'Follow-up'),
        ('emergency', 'Emergency'),
        ('procedure', 'Procedure'),
        ('checkup', 'Check-up'),
    ], default='consultation', required=True, tracking=True)

    chief_complaint = fields.Text(
        string='Chief Complaint',
        help="The main reason the patient is presenting today, in their own words.",
    )
    history_present_illness = fields.Html(string='History of Present Illness')
    physical_exam = fields.Html(string='Physical Examination')
    assessment = fields.Html(string='Assessment')
    plan = fields.Html(string='Plan')

    diagnosis_ids = fields.Many2many(
        'medical.diagnosis', string='Diagnoses',
        help="ICD-10 coded diagnoses for this encounter.",
    )

    # ------------------------------------------------------------
    # Related clinical records
    # ------------------------------------------------------------
    vitals_ids = fields.One2many(
        'medical.vitals', 'encounter_id', string='Vitals',
    )
    vitals_count = fields.Integer(compute='_compute_vitals_count')

    prescription_line_ids = fields.One2many(
        'medical.prescription.line', 'encounter_id',
        string='Prescription',
    )
    prescription_count = fields.Integer(compute='_compute_prescription_count')
    prescription_warning_count = fields.Integer(
        compute='_compute_prescription_warning',
    )
    prescription_warning_severity = fields.Selection([
        ('ok', 'OK'),
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('danger', 'Critical'),
    ], compute='_compute_prescription_warning', default='ok')
    prescription_warning_html = fields.Html(
        compute='_compute_prescription_warning', sanitize=False,
    )

    # Patient context (related, for the encounter form)
    patient_age = fields.Integer(related='patient_id.age', readonly=True)
    patient_gender = fields.Selection(related='patient_id.gender', readonly=True)
    patient_blood_type = fields.Selection(
        related='patient_id.blood_type', readonly=True,
    )
    patient_allergy_ids = fields.One2many(
        related='patient_id.allergy_ids', readonly=True,
    )
    patient_active_medication_ids = fields.One2many(
        related='patient_id.active_medication_ids', readonly=True,
    )
    patient_has_critical_allergy = fields.Boolean(
        related='patient_id.has_critical_allergy', readonly=True,
    )

    # ------------------------------------------------------------
    # Workflow state
    # ------------------------------------------------------------
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True, index=True)

    # ------------------------------------------------------------
    # Counts & attachments
    # ------------------------------------------------------------
    attachment_count = fields.Integer(
        string='Documents', compute='_compute_attachment_count',
    )

    # ============================================================
    # Computes
    # ============================================================
    @api.depends('vitals_ids')
    def _compute_vitals_count(self):
        for rec in self:
            rec.vitals_count = len(rec.vitals_ids)

    @api.depends('prescription_line_ids')
    def _compute_prescription_count(self):
        for rec in self:
            rec.prescription_count = len(rec.prescription_line_ids)

    @api.depends('prescription_line_ids.warning_severity',
                 'prescription_line_ids.warning_message',
                 'prescription_line_ids.product_name')
    def _compute_prescription_warning(self):
        """Aggregate per-line warnings into a banner shown on the form
        and a styled block printed at the top of the prescription PDF
        section."""
        order = {'ok': 0, 'info': 1, 'warning': 2, 'danger': 3}
        palette = {
            'info': ('#1565c0', '#e3f2fd'),
            'warning': ('#8a6d3b', '#fff8e1'),
            'danger': ('#c62828', '#fdecea'),
        }
        for rec in self:
            offending = rec.prescription_line_ids.filtered('has_warning')
            rec.prescription_warning_count = len(offending)
            top = 'ok'
            blocks = []
            for line in offending:
                if order.get(line.warning_severity, 0) > order[top]:
                    top = line.warning_severity
                fg, bg = palette.get(line.warning_severity,
                                     ('#475569', '#eef2f5'))
                items = ''.join(
                    f"<li>{frag.lstrip('• ').strip()}</li>"
                    for frag in (line.warning_message or '').splitlines()
                    if frag.strip())
                blocks.append(
                    f'<div style="margin:6px 0; padding:10px 14px; '
                    f'border-left:4px solid {fg}; background:{bg}; '
                    f'border-radius:4px;">'
                    f'<strong style="color:{fg};">'
                    f'{line.product_name or "—"}</strong>'
                    f'<ul style="margin:6px 0 0 18px; padding:0;">'
                    f'{items}</ul></div>')
            rec.prescription_warning_severity = top
            rec.prescription_warning_html = (
                '\n'.join(blocks) if blocks else False)

    def _compute_attachment_count(self):
        """Count attachments linked to this encounter.

        No ``@api.depends``: attachment creation/removal is not
        propagated through ORM dependencies, so the value is
        recomputed on cache miss rather than dependency-tracked.
        A single grouped read avoids one query per record.
        """
        counts = {}
        if self.ids:
            grouped = self.env['ir.attachment']._read_group(
                [('res_model', '=', 'medical.encounter'),
                 ('res_id', 'in', self.ids)],
                groupby=['res_id'], aggregates=['__count'],
            )
            counts = {res_id: count for res_id, count in grouped}
        for rec in self:
            rec.attachment_count = counts.get(rec.id, 0)

    # ============================================================
    # CRUD
    # ============================================================
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('reference', _('New')) == _('New'):
                vals['reference'] = self.env['ir.sequence'].next_by_code(
                    'medical.encounter') or _('New')
        return super().create(vals_list)

    # ============================================================
    # State transitions
    # ============================================================
    def action_start(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft encounters can be started."))
            rec.state = 'in_progress'

    def action_complete(self):
        for rec in self:
            if rec.state not in ('draft', 'in_progress'):
                raise UserError(
                    _("Only draft or in-progress encounters can be completed."))
            if not rec.chief_complaint:
                raise UserError(
                    _("Please document at least the chief complaint "
                      "before completing the encounter."))
            rec.state = 'completed'

    def action_reopen(self):
        for rec in self:
            rec.state = 'in_progress'

    def action_cancel(self):
        for rec in self:
            rec.state = 'cancelled'

    def action_draft(self):
        for rec in self:
            if rec.state == 'cancelled':
                rec.state = 'draft'

    # ============================================================
    # Quick actions
    # ============================================================
    def action_add_vitals(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Add Vitals'),
            'res_model': 'medical.vitals',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_encounter_id': self.id,
            },
        }

    def action_view_prescription(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Prescription'),
            'res_model': 'medical.prescription.line',
            'view_mode': 'list,form',
            'domain': [('encounter_id', '=', self.id)],
            'context': {'default_encounter_id': self.id},
        }

    def action_view_attachments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Documents'),
            'res_model': 'ir.attachment',
            'view_mode': 'kanban,list,form',
            'domain': [
                ('res_model', '=', 'medical.encounter'),
                ('res_id', '=', self.id),
            ],
            'context': {
                'default_res_model': 'medical.encounter',
                'default_res_id': self.id,
            },
        }
