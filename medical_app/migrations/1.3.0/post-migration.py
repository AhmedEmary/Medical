# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Backfill medical_vitals.measured_by_employee_id from the legacy
    user-based measured_by column. Picks the employee linked to that user;
    if a user has multiple employees, the lowest id wins."""
    cr.execute("""
        UPDATE medical_vitals AS v
           SET measured_by_employee_id = sub.employee_id
          FROM (
              SELECT DISTINCT ON (user_id) user_id, id AS employee_id
                FROM hr_employee
               WHERE user_id IS NOT NULL
            ORDER BY user_id, id
          ) AS sub
         WHERE v.measured_by = sub.user_id
           AND v.measured_by_employee_id IS NULL
    """)