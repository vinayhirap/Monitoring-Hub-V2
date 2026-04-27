from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.db import get_connection
import json
import asyncio
import datetime   # ✅ Step 1: add import

router = APIRouter()


# ✅ Step 2: helper inside SAME FILE
def serialize(row):
    data = dict(row)
    for k, v in data.items():
        if isinstance(v, (datetime.datetime, datetime.date)):
            data[k] = v.isoformat()
    return data


def fetch_active_alerts():
    """
    Fetch active, unacked, unmuted alerts.
    """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            id,
            resource_id,
            metric_name,
            severity,
            environment,
            triggered_at
        FROM alerts
        WHERE status = 'ACTIVE'
          AND acked = 0
          AND (muted_until IS NULL OR muted_until < NOW())
        ORDER BY triggered_at DESC
    """)

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return rows


@router.websocket("/ws/alerts")
async def alerts_ws(websocket: WebSocket):
    await websocket.accept()
    print("WS HANDLER HIT")

    try:
        while True:
            alerts = fetch_active_alerts()

            if alerts:
                # ✅ Step 3: SAFE SEND (ONLY CHANGE)
                safe_payload = [serialize(a) for a in alerts]
                await websocket.send_text(json.dumps(safe_payload))

            await asyncio.sleep(5)

    except WebSocketDisconnect:
        print("WS client disconnected")

    except Exception as e:
        print("WS ERROR:", e)

    finally:
        try:
            await websocket.close()
        except Exception:
            pass

        print("WS handler stopped")
