# app/api/dashboard.py
from fastapi import APIRouter, HTTPException
from app.db import get_connection

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/overview")
def dashboard_overview():
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
                            WITH cpu_thresholds AS (
                SELECT
                    t.warning_value,
                    t.critical_value
                FROM thresholds t
                JOIN metric_catalog mc ON mc.id = t.metric_id
                WHERE mc.metric_name = 'cpuutilization'
                    AND t.resource_type = 'ec2'
                    AND t.enabled = 1
                LIMIT 1
                ),
                latest_cpu AS (
                SELECT m.*
                FROM metrics m
                JOIN (
                    SELECT resource_id, MAX(metric_timestamp) AS latest
                    FROM metrics
                    WHERE metric_name = 'cpu'
                    GROUP BY resource_id
                ) latest
                    ON m.resource_id = latest.resource_id
                AND m.metric_timestamp = latest.latest
                )
                SELECT
                SUM(CASE
                        WHEN latest_cpu.metric_value < cpu_thresholds.warning_value THEN 1
                        ELSE 0
                    END) AS ok_count,
                SUM(CASE
                        WHEN latest_cpu.metric_value >= cpu_thresholds.warning_value
                        AND latest_cpu.metric_value < cpu_thresholds.critical_value THEN 1
                        ELSE 0
                    END) AS warning_count,
                SUM(CASE
                        WHEN latest_cpu.metric_value >= cpu_thresholds.critical_value THEN 1
                        ELSE 0
                    END) AS critical_count
                FROM resources r
                JOIN latest_cpu ON r.id = latest_cpu.resource_id
                CROSS JOIN cpu_thresholds
                WHERE r.resource_type = 'ec2';
        """)

        row = cursor.fetchone() or {}

        return {
            "service": "EC2",
            "ok": row.get("ok_count", 0),
            "warning": row.get("warning_count", 0),
            "critical": row.get("critical_count", 0),
        }

    except Exception as e:
        print("DASHBOARD ERROR:", e)
        raise HTTPException(status_code=500, detail="Failed to load dashboard")

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@router.get("/instances/{resource_id}/metrics")
def ec2_cpu_history(resource_id: int):
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                metric_value,
                metric_timestamp
            FROM metrics
            WHERE resource_id = %s
              AND metric_name = 'cpu'
            ORDER BY metric_timestamp DESC
            LIMIT 30
        """, (resource_id,))

        rows = cursor.fetchall()

        return list(reversed(rows))  # oldest → newest

    except Exception as e:
        print("CPU HISTORY ERROR:", e)
        raise HTTPException(status_code=500, detail="Failed to load CPU history")

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
