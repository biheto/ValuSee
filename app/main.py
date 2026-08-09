import html
import json
import logging
import os
import re
import secrets
import time
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.routes import router as project_router
from app.core.config import settings, validate_production_config
from app.core.database import database_health
from app.core.infrastructure import http_metrics, infrastructure_health, infrastructure_prometheus, rate_limiter
from app.shopping.store import shopping_store

validate_production_config()
app = FastAPI(title=settings.app_name, version="0.1.0")
request_logger = logging.getLogger("valuesee.http")

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
    started = time.perf_counter()
    status_code = 500
    supplied_request_id = request.headers.get("x-request-id", "")
    request_id = supplied_request_id if re.fullmatch(r"[A-Za-z0-9._-]{8,64}", supplied_request_id) else uuid4().hex
    try:
        if request.url.path.startswith("/api/"):
            # Uvicorn normalizes request.client only for explicitly trusted proxies.
            client_ip = request.client.host if request.client else "unknown"
            limit = 20 if request.url.path.startswith("/api/v1/auth/") else 120
            if not rate_limiter.allow(f"{client_ip}:{request.url.path}", limit=limit):
                response = JSONResponse({"detail": "请求过于频繁，请稍后重试"}, status_code=429)
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'"
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        route = request.scope.get("route")
        fallback = request.url.path if not request.url.path.startswith("/api/") else "/api/unmatched"
        route_path = getattr(route, "path", fallback)
        duration = time.perf_counter() - started
        http_metrics.observe(request.method, route_path, status_code, duration)
        request_logger.info(json.dumps({
            "event": "http_request", "request_id": request_id, "method": request.method,
            "route": route_path, "status": status_code, "duration_ms": round(duration * 1000, 2),
        }, separators=(",", ":")))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


@app.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> PlainTextResponse:
    expected = os.getenv("VALUSee_METRICS_TOKEN", "")
    if settings.app_env.lower() in {"prod", "production"} and (not expected or not secrets.compare_digest(request.headers.get("x-metrics-token", ""), expected)):
        return PlainTextResponse("forbidden\n", status_code=403)
    return PlainTextResponse(http_metrics.prometheus() + infrastructure_prometheus(), media_type="text/plain; version=0.0.4")


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

    public_dir = web_dist
    brand_dir = public_dir / "brand"
    if brand_dir.exists():
        app.mount("/brand", StaticFiles(directory=brand_dir), name="web-brand")

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def web_manifest() -> FileResponse:
        return FileResponse(public_dir / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/sw.js", include_in_schema=False)
    def web_service_worker() -> FileResponse:
        return FileResponse(public_dir / "sw.js", media_type="application/javascript")

    @app.get("/", include_in_schema=False)
    def web_index() -> FileResponse:
        return FileResponse(web_dist / "index.html")

    @app.get("/admin", include_in_schema=False)
    def admin_index() -> FileResponse:
        return FileResponse(web_dist / "index.html")

    @app.get("/product/{product_ref}", include_in_schema=False)
    def product_index(product_ref: str) -> FileResponse:
        del product_ref
        return FileResponse(web_dist / "index.html")

    @app.get("/content/{content_id}", include_in_schema=False)
    def content_index(content_id: str) -> HTMLResponse:
        item = shopping_store.get_content(content_id)
        document = (web_dist / "index.html").read_text(encoding="utf-8")
        if not item:
            return HTMLResponse(document, status_code=404)
        title = html.escape(str(item["title"]), quote=True)
        description = html.escape(str(item["summary"]), quote=True)
        document = document.replace("<title>ValuSee - 买之前，先看清价值</title>", f"<title>{title} - ValuSee</title>")
        document = document.replace('<meta property="og:title" content="ValuSee - 买之前，先看清价值" />', f'<meta property="og:title" content="{title}" />')
        document = document.replace('<meta property="og:description" content="识别真假同款、算清真实到手价，并持续管理降价与售后。" />', f'<meta property="og:description" content="{description}" />')
        return HTMLResponse(document)

    @app.get("/share/{share_token}", include_in_schema=False)
    def shared_decision_index(share_token: str) -> HTMLResponse:
        share = shopping_store.get_share(share_token)
        document = (web_dist / "index.html").read_text(encoding="utf-8")
        if not share:
            return HTMLResponse(document, status_code=404)
        title = html.escape(str(share.get("title") or "ValuSee 购物决策分享"), quote=True)
        description = html.escape("ValuSee 公开只读购物决策快照，价格与优惠请在下单前回到原平台核验。", quote=True)
        document = document.replace("<title>ValuSee - 买之前，先看清价值</title>", f"<title>{title} - ValuSee</title>")
        document = document.replace('<meta property="og:title" content="ValuSee - 买之前，先看清价值" />', f'<meta property="og:title" content="{title}" />')
        document = document.replace('<meta property="og:description" content="识别真假同款、算清真实到手价，并持续管理降价与售后。" />', f'<meta property="og:description" content="{description}" />')
        return HTMLResponse(document)
