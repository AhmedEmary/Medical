# -*- coding: utf-8 -*-
"""Remap medical_encounter.doctor_id from res.users -> hr.employee.

Runs BEFORE Odoo loads the new field definition, so the column still
holds the old user ids and the FK still points at res_users. We:

  1. For each non-null doctor_id, find the user's linked employee
     (hr_employee.user_id) and rewrite the column with the employee id.
  2. Null out any value we cannot remap (user has no employee record) —
     the value would have become a dangling reference otherwise.
  3. Drop the FK constraint to res_users so Odoo can recreate it
     against hr_employee when the new schema is applied.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = 'medical_encounter'
           AND column_name = 'doctor_id'
    """)
    if not cr.fetchone():
        return

    cr.execute("""
        UPDATE medical_encounter e
           SET doctor_id = emp.id
          FROM hr_employee emp
         WHERE emp.user_id = e.doctor_id
           AND e.doctor_id IS NOT NULL
    """)
    _logger.info(
        "medical_encounter.doctor_id: remapped %s rows from user to employee",
        cr.rowcount,
    )

    cr.execute("""
        UPDATE medical_encounter e
           SET doctor_id = NULL
         WHERE doctor_id IS NOT NULL
           AND NOT EXISTS (
               SELECT 1 FROM hr_employee emp WHERE emp.id = e.doctor_id
           )
    """)
    if cr.rowcount:
        _logger.warning(
            "medical_encounter.doctor_id: cleared %s rows whose user had no "
            "employee record; reassign manually after upgrade",
            cr.rowcount,
        )

    cr.execute("""
        SELECT conname
          FROM pg_constraint
         WHERE conrelid = 'medical_encounter'::regclass
           AND contype  = 'f'
           AND conname LIKE '%doctor_id%'
    """)
    for (conname,) in cr.fetchall():
        cr.execute(
            'ALTER TABLE medical_encounter DROP CONSTRAINT "%s"' % conname
        )
        _logger.info("Dropped stale FK constraint %s on medical_encounter", conname)
