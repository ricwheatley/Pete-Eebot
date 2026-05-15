from pete_e.api_routes.auth import router as auth_router
from pete_e.api_routes.logs_webhooks import router as logs_webhooks_router
from pete_e.api_routes.metrics import router as metrics_router
from pete_e.api_routes.nutrition import router as nutrition_router
from pete_e.api_routes.plan import router as plan_router
from pete_e.api_routes.root import router as root_router
from pete_e.api_routes.status_sync import router as status_sync_router
from pete_e.api_routes.web import router as web_router

__all__ = [
    "auth_router",
    "logs_webhooks_router",
    "metrics_router",
    "nutrition_router",
    "plan_router",
    "root_router",
    "status_sync_router",
    "web_router",
]
