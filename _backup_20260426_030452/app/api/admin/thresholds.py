from fastapi import APIRouter, HTTPException
from app.db import get_connection

router = APIRouter(prefix="/admin/thresholds", tags=["Admin - Thresholds"])


@router.get("")
def list_thresholds():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            t.id,
            a.account_name,
            t.resource_type,
            m.metric_name,
            t.warning_value,
            t.critical_value,
            t.comparison,
            t.evaluation_period,
            t.enabled
        FROM thresholds t
        JOIN aws_accounts a ON a.id = t.aws_account_id
        JOIN metric_catalog m ON m.id = t.metric_id
        ORDER BY a.account_name, m.metric_name
    """)

    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows