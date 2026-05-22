from odoo import api, fields, models


class MedicalDiagnosisCategory(models.Model):
    """ICD-10 chapter / disease grouping.

    Diagnoses are grouped under a fixed, curated set of categories
    instead of repeating the category name as free text on every
    diagnosis. This keeps grouping, filtering and statistics
    consistent and avoids typos splitting one category into several.
    """
    _name = 'medical.diagnosis.category'
    _description = 'Diagnosis Category'
    _order = 'sequence, code, name'

    name = fields.Char(string='Category', required=True, translate=True)
    code = fields.Char(
        string='ICD-10 Chapter',
        help="Roman-numeral ICD-10 chapter, e.g. IX.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    diagnosis_ids = fields.One2many(
        'medical.diagnosis', 'category_id', string='Diagnoses',
    )
    diagnosis_count = fields.Integer(
        string='# Diagnoses', compute='_compute_diagnosis_count',
    )

    _code_unique = models.Constraint(
        'unique(code)',
        'ICD-10 chapter must be unique.',
    )

    @api.depends('diagnosis_ids')
    def _compute_diagnosis_count(self):
        for rec in self:
            rec.diagnosis_count = len(rec.diagnosis_ids)

    def action_view_diagnoses(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'medical.diagnosis',
            'view_mode': 'list,form',
            'domain': [('category_id', '=', self.id)],
            'context': {'default_category_id': self.id},
        }


class MedicalDiagnosis(models.Model):
    """ICD-10 / local diagnosis catalog.

    Kept as a master table so encounters and history can reference
    structured codes rather than free text, which is critical for
    statistics, insurance claims, and AI safety checks.
    """
    _name = 'medical.diagnosis'
    _description = 'Medical Diagnosis (ICD-10)'
    _order = 'code'
    _rec_name = 'display_name'

    code = fields.Char(string='ICD-10 Code', required=True, index=True)
    name = fields.Char(string='Description', required=True, translate=True)
    category_id = fields.Many2one(
        'medical.diagnosis.category', string='Category',
        index=True, ondelete='restrict',
    )
    chapter = fields.Char(
        string='ICD Chapter', related='category_id.code',
        store=True, readonly=True,
    )
    display_name = fields.Char(compute='_compute_display_name', store=True)
    active = fields.Boolean(default=True)
    notes = fields.Text()

    _code_unique = models.Constraint(
        'unique(code)',
        'ICD-10 code must be unique.',
    )

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"[{rec.code}] {rec.name}" if rec.code else rec.name
