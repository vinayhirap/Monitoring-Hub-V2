from fastapi import FastAPI

app = FastAPI(
    title="Monitoring Hub API",
    version="0.1.0",
    description="Internal Cloud & Server Monitoring Hub"
)

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "monitoring-hub",
        "message": "API is running"
    }