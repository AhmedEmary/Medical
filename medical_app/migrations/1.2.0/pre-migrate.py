# -*- coding: utf-8 -*-
"""Split medical_encounter.doctor_id (hr.employee) into two fields:
  - doctor_id              -> res.users   (the recording user)
  - doctor_employee_id     -> hr.employee (the HR-side doctor record)

After 1.1.0, doctor_id holds employee ids and FKs to hr_employee. We:
  1. Add the new column doctor_employee_id (no FK yet — Odoo's schema sync
     will add it once it sees the new field definition).
  2. Copy current doctor_id (employee ids) into doctor_employee_id.
  3. Rewrite doctor_id with each employee's user_id (back to user ids).
  4. Drop the stale FK pointing at hr_employee so Odoo can recreate a FK
     to res_users when it loads the new model.

Idempotent: if doctor_employee_id already exists, the data swap is skipped.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        SELECT 1
          FROM information_schema.columns
         WHERE table_name  = 'medical_encounter'
           AND column_name = 'doctor_employee_id'
    """)
    if cr.fetchone():
        _logger.info(
            "medical_encounter.doctor_employee_id already present; skipping"
        )
        return

    cr.execute("""
        ALTER TABLE medical_encounter
        ADD COLUMN doctor_employee_id INTEGER
    """)

    cr.execute("""
        UPDATE medical_encounter
           SET doctor_employee_id = doctor_id
         WHERE doctor_id IS NOT NULL
    """)
    _logger.info(
        "medical_encounter.doctor_employee_id: copied %s employee ids "
        "from doctor_id",
        cr.rowcount,
    )

    cr.execute("""
        UPDATE medical_encounter e
           SET doctor_id = emp.user_id
          FROM hr_employee emp
         WHERE emp.id = e.doctor_id
           AND e.doctor_id IS NOT NULL
    """)
    _logger.info(
        "medical_encounter.doctor_id: remapped %s rows from employee back "
        "to user", cr.rowcount,
    )

    cr.execute("""
        UPDATE medical_encounter e
           SET doctor_id = NULL
         WHERE doctor_id IS NOT NULL
           AND NOT EXISTS (
               SELECT 1 FROM res_users u WHERE u.id = e.doctor_id
           )
    """)
    if cr.rowcount:
        _logger.warning(
            "medical_encounter.doctor_id: cleared %s rows whose employee "
            "had no linked user; doctor_employee_id is still set",
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
