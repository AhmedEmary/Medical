# -*- coding: utf-8 -*-
from odoo import fields, models


class MedicalAISuggestionTimeline(models.TransientModel):
    """One reviewable AI-drafted timeline note, tied to a linked encounter.

    Used by the case-report suggestion wizard so the doctor can edit each
    per-encounter note before it is written to ``encounter.case_timeline_note``.
    """
    _name = 'medical.ai.suggestion.timeline'
    _description = 'AI Case Timeline Suggestion Line'
    _order = 'encounter_date, id'

    suggestion_id = fields.Many2one(
        'medical.ai.suggestion', string='Suggestion',
        required=True, ondelete='cascade')
    encounter_id = fields.Many2one(
        'medical.encounter', string='Encounter', required=True, readonly=True)
    encounter_date = fields.Datetime(
        related='encounter_id.encounter_date', string='Date', readonly=True)
    encounter_type = fields.Selection(
        related='encounter_id.encounter_type', string='Type', readonly=True)
    note = fields.Html(string='Timeline Note', sanitize=True)
