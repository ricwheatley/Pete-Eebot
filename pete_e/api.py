from fastapi import FastAPI

from pete_e.api_routes import (
    logs_webhooks_router,
    metrics_router,
    plan_router,
    root_router,
    status_sync_router,
)

app = FastAPI(title="Pete-Eebot API")

app.include_router(root_router)
app.include_router(metrics_router)
app.include_router(plan_router)
app.include_router(status_sync_router)
app.include_router(logs_webhooks_router)
