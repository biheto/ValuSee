import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.routes import router as project_router
from app.core.config import settings
from app.core.database import database_health
from app.core.infrastructure import infrastructure_health, rate_limiter

app = FastAPI(title=settings.app_name, version="0.1.0")

allowed_origins = [item.strip() for item in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if item.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
allowed_hosts = [item.strip() for item in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if item.strip()]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)


@app.middleware("http")
async def protect_api(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        client_ip = forwarded or (request.client.host if request.client else "unknown")
        limit = 20 if request.url.path.startswith("/api/v1/auth/") else 120
        if not rate_limiter.allow(f"{client_ip}:{request.url.path}", limit=limit):
            return JSONResponse({"detail": "请求过于频繁，请稍后重试"}, status_code=429)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'"
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


@app.get("/privacy", include_in_schema=False)
def privacy_policy() -> dict[str, object]:
    return {"title": "ValuSee 隐私政策", "version": "2026-08-09", "summary": "ValuSee 仅处理用户主动提交的商品信息、账户信息和用户创建的提醒；不以大规模后台爬虫作为数据来源。用户可通过账户接口导出或删除数据。", "contact": os.getenv("VALUSee_PRIVACY_CONTACT", "请在部署前配置客服邮箱")}


@app.get("/terms", include_in_schema=False)
def service_terms() -> dict[str, object]:
    return {"title": "ValuSee 用户服务协议", "version": "2026-08-09", "summary": "价格、优惠、风险和时机建议仅基于已获得的来源证据，不保证实时性或成交结果；下单、支付、退款和售后操作必须由用户确认并在平台完成。"}


@app.get("/ready")
def ready() -> JSONResponse:
    checks = {"database": database_health(), **infrastructure_health()}
    healthy = all(item["status"] == "ok" for item in checks.values())
    return JSONResponse({"status": "ok" if healthy else "error", "checks": checks}, status_code=200 if healthy else 503)


app.include_router(project_router)

web_dist = Path(__file__).resolve().parent.parent / "web" / "dist"
if web_dist.exists():
    assets_dir = web_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="web-assets")

    @app.get("/", include_in_schema=False)
    def web_index() -> FileResponse:
        return FileResponse(web_dist / "index.html")
