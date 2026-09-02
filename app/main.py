import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.knowledge import router as knowledge_router
from app.api.search import router as search_router
from app.api.strategies import router as strategies_router
from app.api.tags import router as tags_router
from app.api.system import router as system_router
from app.common.handler import register_handlers
from app.common.response import R
from app.core.database import check_database, get_connection
from app.core.redis_client import check_redis, init_redis


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(_: FastAPI):
    with get_connection(max_retries=10):
        pass
    init_redis()
    logger.info("PostgreSQL 和 Redis 连接成功")
    yield


app = FastAPI(
    title="AlphaHub",
    version="0.1.0",
    lifespan=lifespan,
)
register_handlers(app)
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(knowledge_router)
app.include_router(search_router)
app.include_router(strategies_router)
app.include_router(tags_router)
app.include_router(system_router)
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")


@app.get("/api/health")
def health() -> R[dict[str, object]]:
    services = {
        "postgres": check_database(),
        "redis": check_redis(),
    }
    return R.ok({
        "status": "ok" if all(services.values()) else "degraded",
        "services": services,
    })


@app.get("/", include_in_schema=False)
def login_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "login.html")


@app.get("/login.html", include_in_schema=False)
def login_html() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "login.html")


@app.get("/dashboard.html", include_in_schema=False)
def dashboard_html() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "dashboard.html")
