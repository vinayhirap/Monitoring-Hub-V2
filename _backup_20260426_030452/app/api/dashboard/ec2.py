# app/api/dashboard/ec2.py

from fastapi import APIRouter
from app.db import get_connection

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

@router.get("/ec2")
def dashboard_ec2():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
SELECT
  r.resource_id AS instance_id,
  r.name,
  JSON_UNQUOTE(JSON_EXTRACT(r.tags,'$.environment')) AS environment,
  ROUND(m.metric_value,2) AS cpu,
  CASE
    WHEN m.metric_value < 60 THEN 'OK'
    WHEN m.metric_value < 80 THEN 'WARNING'
    ELSE 'CRITICAL'
  END AS status
FROM resources r
JOIN metrics m ON m.resource_id = r.id
JOIN (
  SELECT resource_id, MAX(metric_timestamp) ts
  FROM metrics
  WHERE metric_name = 'cpuutilization'
  GROUP BY resource_id
) latest
  ON latest.resource_id = m.resource_id
 AND latest.ts = m.metric_timestamp
WHERE r.resource_type='ec2'
ORDER BY cpu DESC;
    """)

    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows