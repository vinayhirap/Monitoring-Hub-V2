# monitoring-hub/app/main.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import logging

from app.api.alerts import router as alerts_router
from app.api.ec2 import router as ec2_router
from app.api.admin.accounts import router as admin_accounts_router
from app.api.admin.thresholds import router as admin_thresholds_router
from app.api.dashboard.overview import router as dashboard_overview_router
from app.api.dashboard.ec2 import router as dashboard_ec2_router
from app.api.ws.alerts import router as ws_alerts_router
from app.api.auth import router as auth_router
from app.api.admin.users import router as admin_users_router
from app.api.settings import router as settings_router
from app.api.live_data import router as live_data_router
from app.api.audit_logs import router as audit_logs_router

from app.ws.manager import ws_manager
from app.ws.pusher import redis_listener

logger = logging.getLogger(__name__)

app = FastAPI(title="Monitoring Hub API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    async def safe_redis_listener():
        try:
            await redis_listener()
        except Exception as e:
            logger.warning(f"Redis listener crashed (server continues): {e}")

    async def scheduled_collector():
        from app.collector.scheduler import run
        import concurrent.futures
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        loop = asyncio.get_event_loop()
        while True:
            try:
                logger.info("Running scheduled collector...")
                await loop.run_in_executor(executor, run)
            except Exception as e:
                logger.error(f"Collector error: {e}")
            await asyncio.sleep(300)  # runs every 5 minutes

    asyncio.create_task(safe_redis_listener())
    asyncio.create_task(scheduled_collector())
    logger.info("Application startup complete")

@app.get("/")
def root():
    return {"status": "ok", "version": "0.2.0"}


@app.websocket("/ws/{channel}")
async def websocket_endpoint(websocket: WebSocket, channel: str):
    await ws_manager.connect(websocket, channel)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, channel)


@app.get("/ws/status")
async def ws_status():
    return {"connections": ws_manager.connection_count()}


app.include_router(alerts_router, prefix="/api")
app.include_router(ec2_router)
app.include_router(admin_accounts_router)
app.include_router(admin_thresholds_router)
app.include_router(dashboard_overview_router)
app.include_router(dashboard_ec2_router)
app.include_router(ws_alerts_router)
app.include_router(auth_router)
app.include_router(admin_users_router)
app.include_router(live_data_router)
app.include_router(audit_logs_router)
app.include_router(settings_router)
