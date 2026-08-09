from __future__ import annotations

import json
import hashlib
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Header, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse

from app.agents.marketplace_tools import check_permission, list_tools
from app.auth.service import auth_store, bearer_subject
from app.benchmark_runner import (
    run_collaboration_benchmark,
    run_llm_benchmark,
    run_mcp_benchmark,
    run_rag_benchmark,
    run_workflow_benchmark,
)
from app.business_scenarios import SCENARIOS, run_business_scenario
from app.graphs.project_analyzer_graph import project_analyzer_graph
from app.graphs.studio_graphs import (
    code_review_graph,
    collaboration_graph,
    learning_coach_graph,
    rag_process_graph,
)
from app.shopping.graph import shopping_decision_graph_runner
from app.shopping.store import final_price_from_breakdown, shopping_store
from app.shopping.vision import inspect_product_image
from app.shopping.reviews import analyze_reviews
from app.shopping.notifications import send_transactional_email
from app.shopping.providers import configured_providers
from app.shopping.catalog import commerce_catalog
from app.graphs.collaboration_runner import run_collaboration_task
from app.graphs.workflow_compiler import (
    resume_task_workflow,
    run_compiled_workflow,
    run_task_workflow,
    validate_workflow_definition,
)
from app.harness.events import utc_now_iso
from app.harness.policy import tool_policy
from app.harness.runtime import harness_runtime
from app.integrations.github import parse_pull_request_url, verify_webhook_signature
from app.marketplace.catalog import marketplace_catalog
from app.persistence.memory_store import memory_store
from app.marketplace.installer import install_marketplace_package, preview_marketplace_package, uninstall_marketplace_package
from app.persistence.rag_store import rag_store
from app.persistence.sqlite_store import task_store
from app.providers.llm_provider import llm_provider
from app.providers.mcp_provider import mcp_provider
from app.schemas.project import ProjectAnalyzeRequest, ProjectAnalyzeResponse
from app.core.config import settings
from app.core.infrastructure import publish_monitor_event
from app.core.object_storage import create_download_url, persist_upload
from app.schemas.shopping import (
    PriceMonitorCheckRequest,
    PriceMonitorCheckResponse,
    PriceMonitorCreateRequest,
    PriceMonitorResponse,
    PurchaseCreateRequest,
    PurchaseResponse,
    RegisterRequest,
    LoginRequest,
    PasswordResetRequest,
    PasswordResetConfirmRequest,
    EmailVerifyConfirmRequest,
    FamilyCreateRequest,
    FamilyInviteRequest,
    FamilyMemberRoleRequest,
    ReviewAnalysisRequest,
    ShoppingDecisionRequest,
    ShoppingExtensionCaptureRequest,
    ShoppingExtensionCaptureResponse,
    ShoppingImageResponse,
    ShoppingProductInput,
    ShoppingParseUrlRequest,
    ShoppingSearchRequest,
    ShoppingParseUrlResponse,
)
from app.skills.executor import ensure_builtin_skills_seeded, execute_skill
from app.skills.sandbox import python_skill_sandbox_status
from app.schemas.studio import (
    BenchmarkRunRequest,
    BenchmarkRunResponse,
    BusinessScenarioRequest,
    CodeReviewRequest,
    CodeReviewResponse,
    CollaborationRequest,
    CollaborationResponse,
    HumanReviewRequest,
    HumanReviewResponse,
    KnowledgeNoteRequest,
    KnowledgeNoteResponse,
    LearningCoachRequest,
    LearningCoachResponse,
    LearningChatRequest,
    LearningChatResponse,
    LearningPlanCreateRequest,
    LearningPlanResponse,
    LearningPlanStatusRequest,
    MemoryConfirmRequest,
    MemoryExtractRequest,
    MemoryRecordResponse,
    McpFileListRequest,
    McpFileReadRequest,
    McpGitRequest,
    McpServerConfigRequest,
    McpServerConfigResponse,
    McpToolApprovalRequest,
    McpToolCallRequest,
    McpToolToggleRequest,
    RagIngestRequest,
    RagIngestResponse,
    RagDocumentAclRequest,
    RagGoldCaseRequest,
    RagProcessRequest,
    RagProcessResponse,
    RagQueryRequest,
    RagQueryResponse,
    ReviewActionRequest,
    ReviewActionResponse,
    TaskRunRequest,
    TaskQuestionRequest,
    TaskQuestionResponse,
    TaskRunResponse,
    ToolPermissionRequest,
    ToolPermissionResponse,
    WorkflowRunRequest,
    WorkflowRunResponse,
    WorkflowSaveRequest,
    WorkflowSaveResponse,
    WorkflowValidateRequest,
    WorkflowValidateResponse,
)

router = APIRouter(prefix="/api/v1", tags=["ValuSee"])


def _request_user(authorization: str | None) -> str:
    try:
        return bearer_subject(
            authorization,
            allow_local=settings.app_env.lower() not in {"prod", "production"},
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc), headers={"WWW-Authenticate": "Bearer"}) from exc


def _require_admin(authorization: str | None) -> str:
    subject = _request_user(authorization)
    if subject == "local-user" and settings.app_env.lower() not in {"prod", "production"}:
        return subject
    user = auth_store.get_user(subject)
    allowed = {item.strip().lower() for item in os.getenv("VALUSee_ADMIN_EMAILS", "").split(",") if item.strip()}
    if not user or user.get("email", "").lower() not in allowed:
        raise HTTPException(status_code=403, detail="需要管理员账户")
    return subject


def _session_context(request: Request) -> tuple[str, str | None]:
    device = request.headers.get("user-agent", "浏览器")[:160]
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return device, forwarded or (request.client.host if request.client else None)


def _raw_bearer(authorization: str | None) -> str | None:
    return authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else None


@router.post("/auth/register", tags=["Account"])
def register_account(request_body: RegisterRequest, request: Request) -> dict[str, object]:
    try:
        user = auth_store.register(request_body.email, request_body.password, request_body.display_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    verify_token = auth_store.create_action_token(user["user_id"], "verify_email", ttl_minutes=1440)
    base_url = os.getenv("VALUSee_PUBLIC_BASE_URL", "http://127.0.0.1:8200").rstrip("/")
    send_transactional_email(user["email"], "验证你的 ValuSee 邮箱", f"请在 24 小时内打开：{base_url}/?verify_token={verify_token}")
    device, ip_address = _session_context(request)
    response: dict[str, object] = {"user": user, "access_token": auth_store.create_session(user["user_id"], device, ip_address), "token_type": "bearer"}
    if settings.app_env.lower() not in {"prod", "production"}:
        response["verification_token"] = verify_token
    return response


@router.post("/auth/login", tags=["Account"])
def login_account(request_body: LoginRequest, request: Request) -> dict[str, object]:
    user = auth_store.authenticate(request_body.email, request_body.password)
    if not user:
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    device, ip_address = _session_context(request)
    return {"user": user, "access_token": auth_store.create_session(user["user_id"], device, ip_address), "token_type": "bearer"}


@router.post("/auth/email/verify/request", tags=["Account"])
def request_email_verification(authorization: str | None = Header(default=None)) -> dict[str, object]:
    user_id = _request_user(authorization)
    user = auth_store.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="账户不存在")
    token = auth_store.create_action_token(user_id, "verify_email", ttl_minutes=1440)
    base_url = os.getenv("VALUSee_PUBLIC_BASE_URL", "http://127.0.0.1:8200").rstrip("/")
    send_transactional_email(user["email"], "验证你的 ValuSee 邮箱", f"请在 24 小时内打开：{base_url}/?verify_token={token}")
    return {"accepted": True, **({"verification_token": token} if settings.app_env.lower() not in {"prod", "production"} else {})}


@router.post("/auth/email/verify/confirm", tags=["Account"])
def confirm_email_verification(request: EmailVerifyConfirmRequest) -> dict[str, object]:
    user = auth_store.verify_email(request.token)
    if not user:
        raise HTTPException(status_code=422, detail="验证链接无效或已过期")
    return {"verified": True, "user": user}


@router.post("/auth/password/reset/request", tags=["Account"])
def request_password_reset(request: PasswordResetRequest) -> dict[str, object]:
    user = auth_store.get_user_by_email(request.email)
    response: dict[str, object] = {"accepted": True, "message": "如果该邮箱已注册，重置邮件将发送到该邮箱。"}
    if user:
        token = auth_store.create_action_token(user["user_id"], "reset_password", ttl_minutes=30)
        base_url = os.getenv("VALUSee_PUBLIC_BASE_URL", "http://127.0.0.1:8200").rstrip("/")
        send_transactional_email(user["email"], "重置 ValuSee 密码", f"请在 30 分钟内打开：{base_url}/?reset_token={token}")
        if settings.app_env.lower() not in {"prod", "production"}:
            response["reset_token"] = token
    return response


@router.post("/auth/password/reset/confirm", tags=["Account"])
def confirm_password_reset(request: PasswordResetConfirmRequest) -> dict[str, object]:
    try:
        updated = auth_store.reset_password(request.token, request.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=422, detail="重置链接无效或已过期")
    return {"updated": True}


@router.get("/auth/me", tags=["Account"])
def current_account(authorization: str | None = Header(default=None)) -> dict[str, object]:
    user_id = _request_user(authorization)
    user = auth_store.get_user(user_id)
    return {"user": user or {"user_id": user_id, "display_name": "本地账户", "status": "local"}}


@router.get("/auth/sessions", tags=["Account"])
def list_account_sessions(authorization: str | None = Header(default=None)) -> list[dict[str, object]]:
    return auth_store.list_sessions(_request_user(authorization), _raw_bearer(authorization))


@router.delete("/auth/sessions/{session_id}", tags=["Account"])
def revoke_account_session(session_id: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    if not auth_store.revoke_session(_request_user(authorization), session_id):
        raise HTTPException(status_code=404, detail="会话不存在或已退出")
    return {"revoked": True, "session_id": session_id}


@router.get("/membership", tags=["Membership"])
def membership_status(authorization: str | None = Header(default=None)) -> dict[str, object]:
    return auth_store.subscription_status(_request_user(authorization))


@router.get("/membership/plans", tags=["Membership"])
def membership_plans() -> dict[str, object]:
    return {"plans": [{"code": "free", "name": "Free", "price": None, "benefits": ["每月 10 次对比", "3 个降价监控", "基础购买建议"]}, {"code": "pro", "name": "Pro", "price": None, "status": "coming_soon", "benefits": ["更高对比与监控额度", "深度评论风险分析", "家庭多人档案", "长期购买偏好"]}], "payment_available": False}


@router.post("/membership/upgrade-requests", tags=["Membership"])
def create_upgrade_request(payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    try:
        return auth_store.request_upgrade(_request_user(authorization), str(payload.get("plan_code") or "pro"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/families", tags=["Account"])
def create_family(request: FamilyCreateRequest, authorization: str | None = Header(default=None)) -> dict[str, object]:
    return auth_store.create_family(_request_user(authorization), request.name)


@router.get("/families", tags=["Account"])
def list_families(authorization: str | None = Header(default=None)) -> list[dict[str, object]]:
    return auth_store.list_families(_request_user(authorization))


@router.post("/families/invite", tags=["Account"])
def invite_family_member(request: FamilyInviteRequest, authorization: str | None = Header(default=None)) -> dict[str, object]:
    try:
        user_id = _request_user(authorization)
        auth_store.require_entitlement(user_id, "family_members")
        return auth_store.invite_family_member(user_id, request.family_id, request.email)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/families/{family_id}/members", tags=["Account"])
def list_family_members(family_id: str, authorization: str | None = Header(default=None)) -> list[dict[str, object]]:
    try:
        return auth_store.list_family_members(_request_user(authorization), family_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.patch("/families/{family_id}/members/{user_id}", tags=["Account"])
def update_family_member_role(family_id: str, user_id: str, request: FamilyMemberRoleRequest, authorization: str | None = Header(default=None)) -> dict[str, object]:
    try:
        return auth_store.set_family_member_role(_request_user(authorization), family_id, user_id, request.role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/families/{family_id}/members/{user_id}", tags=["Account"])
def delete_family_member(family_id: str, user_id: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    try:
        removed = auth_store.remove_family_member(_request_user(authorization), family_id, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"removed": removed, "user_id": user_id}


@router.get("/auth/export", tags=["Account"])
def export_account_data(authorization: str | None = Header(default=None)) -> dict[str, object]:
    user_id = _request_user(authorization)
    if user_id == "local-user":
        raise HTTPException(status_code=401, detail="请先登录后导出账户数据")
    return auth_store.export_account(user_id)


@router.delete("/auth/account", tags=["Account"])
def delete_account(authorization: str | None = Header(default=None)) -> dict[str, object]:
    user_id = _request_user(authorization)
    try:
        auth_store.delete_account(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"deleted": True, "user_id": user_id}


@router.post("/shopping/parse-url", response_model=ShoppingParseUrlResponse, tags=["Shopping Decision"])
def parse_shopping_url(request: ShoppingParseUrlRequest) -> ShoppingParseUrlResponse:
    parsed = urlparse(request.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="请输入有效的商品链接")

    host = parsed.netloc.lower().removeprefix("www.")
    platform = next(
        (name for key, name in (("jd.", "京东"), ("taobao.", "淘宝"), ("tmall.", "天猫"), ("pinduoduo.", "拼多多"), ("douyin.", "抖音")) if key in host),
        host,
    )
    slug = parsed.path.rstrip("/").split("/")[-1] or host
    title = request.title.strip() or f"来自 {platform} 的商品（待确认）"
    product = ShoppingProductInput(
        title=title,
        platform=platform,
        url=request.url,
        model=slug[:80],
        condition="new",
        notes="链接已保存。请确认商品标题、型号和页面价格后再分析。",
    )
    return ShoppingParseUrlResponse(
        product=product,
        source=host,
        message="已读取链接来源，商品价格和规格需要你确认。",
    )


@router.post("/shopping/parse-image", response_model=ShoppingImageResponse, tags=["Shopping Decision"])
async def parse_shopping_image(file: UploadFile = File(...)) -> ShoppingImageResponse:
    try:
        content = await file.read()
        result = inspect_product_image(content, file.content_type or "", file.filename or "product-image")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()
    return ShoppingImageResponse(**result)


@router.post("/shopping/extension/captures", response_model=ShoppingExtensionCaptureResponse, tags=["Shopping Decision"])
def create_extension_capture(request: ShoppingExtensionCaptureRequest, authorization: str | None = Header(default=None)) -> ShoppingExtensionCaptureResponse:
    if not request.product.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="扩展采集必须包含有效商品页面地址")
    user_id = _request_user(authorization)
    record = shopping_store.create_extension_capture(
        user_id=user_id,
        product=request.product.model_dump(),
        source=request.source,
        captured_at=request.captured_at,
    )
    if request.product.price > 0:
        breakdown = final_price_from_breakdown(request.product.model_dump())
        snapshot = shopping_store.record_price_snapshot(
            user_id=user_id,
            product=request.product.model_dump(),
            final_price=breakdown["final_price"],
            source=request.source,
            captured_at=request.captured_at,
        )
        publish_monitor_event({"type": "price_snapshot", "snapshot_id": snapshot["snapshot_id"]})
    return ShoppingExtensionCaptureResponse(**record)


@router.get("/shopping/extension/captures", response_model=list[ShoppingExtensionCaptureResponse], tags=["Shopping Decision"])
def list_extension_captures(user_id: str | None = None, authorization: str | None = Header(default=None)) -> list[ShoppingExtensionCaptureResponse]:
    del user_id
    subject = _request_user(authorization)
    return [ShoppingExtensionCaptureResponse(**item) for item in shopping_store.list_extension_captures(subject)]


@router.post("/shopping/extension/captures/{capture_id}/confirm", response_model=ShoppingExtensionCaptureResponse, tags=["Shopping Decision"])
def confirm_extension_capture(capture_id: str, authorization: str | None = Header(default=None)) -> ShoppingExtensionCaptureResponse:
    record = shopping_store.confirm_extension_capture(capture_id, _request_user(authorization))
    if not record:
        raise HTTPException(status_code=404, detail="扩展采集记录不存在")
    return ShoppingExtensionCaptureResponse(**record)


@router.get("/shopping/price-history", tags=["Shopping Monitor"])
def get_price_history(product_url: str, user_id: str | None = None, limit: int = 365, authorization: str | None = Header(default=None)) -> dict[str, object]:
    if not product_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="请输入有效商品链接")
    del user_id
    return shopping_store.price_history(product_url, user_id=_request_user(authorization), limit=max(1, min(limit, 1000)))


@router.get("/shopping/notifications", tags=["Shopping Monitor"])
def list_shopping_notifications(unread_only: bool = False, authorization: str | None = Header(default=None)) -> list[dict[str, object]]:
    return shopping_store.list_notifications(_request_user(authorization), unread_only=unread_only)


@router.patch("/shopping/notifications/{notification_id}/read", tags=["Shopping Monitor"])
def read_shopping_notification(notification_id: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    updated = shopping_store.mark_notification_read(_request_user(authorization), notification_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"updated": updated}


@router.post("/shopping/notifications/read-all", tags=["Shopping Monitor"])
def read_all_shopping_notifications(authorization: str | None = Header(default=None)) -> dict[str, object]:
    return {"updated": shopping_store.mark_notification_read(_request_user(authorization))}


@router.post("/shopping/reviews/analyze", tags=["Shopping Decision"])
def analyze_product_reviews(request: ReviewAnalysisRequest, authorization: str | None = Header(default=None)) -> dict[str, object]:
    user_id = _request_user(authorization)
    report = analyze_reviews([item.model_dump() for item in request.reviews])
    return {"user_id": user_id, "product": request.product.model_dump(), "report": report, "sources": sorted({item.source for item in request.reviews})}


@router.get("/shopping/providers", tags=["Shopping Integrations"])
def list_commerce_providers(authorization: str | None = Header(default=None)) -> dict[str, object]:
    _request_user(authorization)
    return {"providers": [{"name": item.name, "kind": item.kind} for item in configured_providers().values()]}


@router.post("/admin/providers/{provider_name}/health", tags=["Admin Console"])
def admin_provider_health(provider_name: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    provider = configured_providers().get(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail="Commerce provider is not configured")
    try:
        return provider.health_check()
    except Exception as exc:
        return {"provider": provider.name, "status": "unhealthy", "error": type(exc).__name__}


@router.get("/admin/prompts", tags=["Admin Console"])
def admin_prompts(agent: str | None = None, authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    return {"prompts": llm_provider.list_prompt_versions(agent), "active": llm_provider.active_prompt_map()}


@router.post("/admin/prompts", tags=["Admin Console"])
def admin_save_prompt(payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    agent = str(payload.get("agent") or "").strip()
    version = str(payload.get("prompt_version") or "").strip()
    title = str(payload.get("title") or "").strip()
    if not agent or not version or not title:
        raise HTTPException(status_code=422, detail="agent, prompt_version and title are required")
    prompt = llm_provider.save_prompt_version({**payload, "agent": agent, "prompt_version": version, "title": title})
    if payload.get("is_active"):
        prompt = llm_provider.set_active_prompt_version(agent, version) or prompt
    return {"prompt": prompt, "active": llm_provider.active_prompt_map()}


@router.post("/admin/prompts/active", tags=["Admin Console"])
def admin_activate_prompt(payload: dict[str, str], authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    agent, version = payload.get("agent"), payload.get("prompt_version")
    if not agent or not version:
        raise HTTPException(status_code=422, detail="agent and prompt_version are required")
    prompt = llm_provider.set_active_prompt_version(agent, version)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt version not found")
    return {"prompt": prompt, "active": llm_provider.active_prompt_map()}


@router.get("/admin/benchmarks", tags=["Admin Console"])
def admin_benchmarks(limit: int = 100, benchmark_type: str | None = None, authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    return {"runs": task_store.list_benchmark_runs(limit=max(1, min(limit, 500)), benchmark_type=benchmark_type)}


@router.post("/admin/benchmarks/run", tags=["Admin Console"])
def admin_run_benchmark(payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    benchmark_type = str(payload.get("benchmark_type") or "shopping").strip().lower()
    request = BenchmarkRunRequest(
        name=str(payload.get("name") or f"{benchmark_type.title()} Benchmark"),
        iterations=int(payload.get("iterations") or 1),
        cases=payload.get("cases") if isinstance(payload.get("cases"), list) else [],
    )
    runners = {
        "mcp": run_mcp_benchmark,
        "llm": run_llm_benchmark,
        "rag": run_rag_benchmark,
        "workflow": run_workflow_benchmark,
        "collaboration": run_collaboration_benchmark,
    }
    runner = runners.get(benchmark_type)
    if not runner:
        raise HTTPException(status_code=422, detail="benchmark_type must be mcp, llm, rag, workflow, or collaboration")
    try:
        return {"run": runner(request.model_dump())}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/admin/overview", tags=["Admin Console"])
def admin_overview(authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    tasks = task_store.list_tasks()
    monitors = shopping_store.list_monitors()
    traces = task_store.list_llm_traces(limit=20)
    benchmarks = task_store.list_benchmark_runs(limit=10)
    usage = llm_provider.usage_dashboard(limit=500)
    return {
        "product": "ValuSee / 见值",
        "health": {"tasks": len(tasks), "running_tasks": sum(1 for item in tasks if item.get("status") in {"running", "queued"}), "monitors": len(monitors), "active_monitors": sum(1 for item in monitors if item.get("status") in {"watching", "target_reached"}), "traces": len(traces), "benchmarks": len(benchmarks)},
        "tasks": tasks[:20],
        "monitors": monitors[:20],
        "traces": traces,
        "benchmarks": benchmarks,
        "llm_usage": usage,
        "mcp": mcp_provider.status(),
        "commerce_providers": [{"name": item.name, "kind": item.kind} for item in configured_providers().values()],
    }


@router.get("/admin/tasks", tags=["Admin Console"])
def admin_tasks(limit: int = 100, authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    return {"tasks": task_store.list_tasks()[:max(1, min(limit, 500))]}


@router.get("/admin/users", tags=["Admin Operations"])
def admin_users(limit: int = 500, authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    return {"users": auth_store.list_users(limit)}


@router.patch("/admin/users/{user_id}", tags=["Admin Operations"])
def admin_update_user(user_id: str, payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    actor_id = _require_admin(authorization)
    if actor_id == user_id:
        raise HTTPException(status_code=422, detail="不能在当前会话中停用自己的管理员账户")
    try:
        user = auth_store.update_user_status(user_id, str(payload.get("status") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    shopping_store.record_admin_audit(actor_id, "user.status.update", "user", user_id, {"status": user["status"]})
    return {"user": user}


@router.get("/admin/membership/upgrade-requests", tags=["Admin Operations"])
def admin_upgrade_requests(authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    return {"requests": auth_store.list_upgrade_requests()}


@router.patch("/admin/membership/upgrade-requests/{request_id}", tags=["Admin Operations"])
def admin_update_upgrade_request(request_id: str, payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    actor_id = _require_admin(authorization)
    try:
        record = auth_store.update_upgrade_request(request_id, str(payload.get("status") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not record:
        raise HTTPException(status_code=404, detail="升级申请不存在")
    shopping_store.record_admin_audit(actor_id, "membership.request.update", "upgrade_request", request_id, {"status": record["status"]})
    return {"request": record}


@router.get("/admin/campaigns", tags=["Admin Operations"])
def admin_campaigns(authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    return {"items": shopping_store.list_campaigns()}


@router.post("/admin/campaigns", tags=["Admin Operations"])
def admin_save_campaign(payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    actor_id = _require_admin(authorization)
    try:
        campaign = shopping_store.save_campaign(payload, str(payload.get("campaign_id") or "") or None)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    shopping_store.record_admin_audit(actor_id, "campaign.save", "campaign", campaign["campaign_id"], {"status": campaign["status"]})
    return {"campaign": campaign}


@router.delete("/admin/campaigns/{campaign_id}", tags=["Admin Operations"])
def admin_delete_campaign(campaign_id: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    actor_id = _require_admin(authorization)
    if not shopping_store.delete_campaign(campaign_id):
        raise HTTPException(status_code=404, detail="活动不存在")
    shopping_store.record_admin_audit(actor_id, "campaign.delete", "campaign", campaign_id)
    return {"deleted": True}


@router.get("/admin/risk-rules", tags=["Admin Operations"])
def admin_risk_rules(authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    return {"rules": shopping_store.list_risk_rules()}


@router.post("/admin/risk-rules", tags=["Admin Operations"])
def admin_save_risk_rule(payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    actor_id = _require_admin(authorization)
    try:
        rule = shopping_store.save_risk_rule(payload, str(payload.get("rule_id") or "") or None)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    shopping_store.record_admin_audit(actor_id, "risk_rule.save", "risk_rule", rule["rule_id"], {"enabled": bool(rule["enabled"])})
    return {"rule": rule}


@router.delete("/admin/risk-rules/{rule_id}", tags=["Admin Operations"])
def admin_delete_risk_rule(rule_id: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    actor_id = _require_admin(authorization)
    if not shopping_store.delete_risk_rule(rule_id):
        raise HTTPException(status_code=404, detail="风控规则不存在")
    shopping_store.record_admin_audit(actor_id, "risk_rule.delete", "risk_rule", rule_id)
    return {"deleted": True}


@router.get("/admin/shares", tags=["Admin Operations"])
def admin_shares(authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    return {"shares": shopping_store.list_all_shares()}


@router.delete("/admin/shares/{share_id}", tags=["Admin Operations"])
def admin_revoke_share(share_id: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    actor_id = _require_admin(authorization)
    if not shopping_store.admin_revoke_share(share_id):
        raise HTTPException(status_code=404, detail="分享不存在或已撤销")
    shopping_store.record_admin_audit(actor_id, "share.revoke", "share", share_id)
    return {"revoked": True}


@router.get("/admin/audits", tags=["Admin Operations"])
def admin_audits(limit: int = 500, authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    return {"audits": shopping_store.list_admin_audits(limit)}


@router.get("/admin/traces", tags=["Admin Console"])
def admin_traces(limit: int = 100, agent: str | None = None, authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    return {"traces": task_store.list_llm_traces(limit=max(1, min(limit, 500)), agent=agent)}


@router.get("/admin/catalog/products", tags=["Admin Catalog"])
def admin_catalog_products(query: str | None = None, limit: int = 200, authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    return {"products": commerce_catalog.list_products(query=query, limit=limit)}


@router.post("/admin/catalog/products", tags=["Admin Catalog"])
def admin_catalog_product_upsert(payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    try:
        return {"product": commerce_catalog.upsert_product(payload)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/admin/catalog/products/{product_id}", tags=["Admin Catalog"])
def admin_catalog_product_delete(product_id: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    if not commerce_catalog.delete_product(product_id):
        raise HTTPException(status_code=404, detail="Catalog product not found")
    return {"product_id": product_id, "deleted": True}


@router.post("/admin/catalog/skus", tags=["Admin Catalog"])
def admin_catalog_sku_upsert(payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    try:
        return {"sku": commerce_catalog.upsert_sku(payload)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/admin/catalog/skus/{sku_id}", tags=["Admin Catalog"])
def admin_catalog_sku_delete(sku_id: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    if not commerce_catalog.delete_sku(sku_id):
        raise HTTPException(status_code=404, detail="Catalog SKU not found")
    return {"sku_id": sku_id, "deleted": True}


@router.get("/admin/monitors", tags=["Admin Console"])
def admin_monitors(limit: int = 200, authorization: str | None = Header(default=None)) -> dict[str, object]:
    actor_id = _require_admin(authorization)
    return {
        "actor_id": actor_id,
        "monitors": shopping_store.list_monitors()[:max(1, min(limit, 1000))],
        "actions": shopping_store.list_monitor_actions(limit=max(1, min(limit, 1000))),
    }


@router.post("/admin/monitors/{monitor_id}/action", tags=["Admin Console"])
def admin_monitor_action(
    monitor_id: str,
    payload: dict[str, object],
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    actor_id = _require_admin(authorization)
    action = str(payload.get("action") or "").strip().lower()
    reason = str(payload.get("reason") or "").strip()
    if action == "delete":
        if not shopping_store.delete_monitor(monitor_id, actor_id=actor_id, reason=reason):
            raise HTTPException(status_code=404, detail="Monitor not found")
        return {"monitor_id": monitor_id, "action": action, "status": "deleted"}
    transitions = {"pause": "paused", "resume": "watching", "retry": "watching", "expire": "expired"}
    status = transitions.get(action)
    if not status:
        raise HTTPException(status_code=422, detail="action must be pause, resume, retry, expire, or delete")
    try:
        monitor = shopping_store.update_monitor_status(monitor_id, status, actor_id=actor_id, reason=reason, action=action)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return {"monitor_id": monitor_id, "action": action, "monitor": monitor}


@router.post("/shopping/providers/{provider_name}/lookup", tags=["Shopping Integrations"])
def lookup_commerce_product(provider_name: str, request: ShoppingParseUrlRequest, authorization: str | None = Header(default=None)) -> dict[str, object]:
    _request_user(authorization)
    if urlparse(request.url).scheme not in {"http", "https"}:
        raise HTTPException(status_code=422, detail="请输入有效的商品链接")
    provider = configured_providers().get(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail="平台适配器未配置或未获授权")
    try:
        return provider.lookup(request.url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"平台数据暂时不可用：{type(exc).__name__}") from exc


@router.post("/shopping/search", tags=["Shopping Integrations"])
def search_commerce_products(request: ShoppingSearchRequest, authorization: str | None = Header(default=None)) -> dict[str, object]:
    _request_user(authorization)
    providers = configured_providers()
    selected = [providers[request.provider]] if request.provider in providers else list(providers.values())
    if not selected:
        return {"query": request.query, "results": [], "sources": [], "message": "尚未配置已授权的商品搜索来源，请使用商品链接或浏览器扩展采集。"}
    results: list[dict[str, object]] = []
    source_status: list[dict[str, object]] = []
    for provider in selected:
        try:
            provider_results = provider.search(request.query, request.category, request.limit)
            results.extend(provider_results)
            source_status.append({"provider": provider.name, "status": "ok", "count": len(provider_results)})
        except Exception as exc:
            source_status.append({"provider": provider.name, "status": "error", "error": type(exc).__name__})
    return {"query": request.query, "results": results[:request.limit], "sources": source_status, "message": "结果均来自已授权平台，点击商品链接查看最新页面价格。"}


@router.get("/business-scenarios", tags=["Business Scenarios"])
def list_business_scenarios() -> dict[str, object]:
    return {"scenarios": [{"code": code, **item} for code, item in SCENARIOS.items()]}


@router.post("/integrations/github/webhook", tags=["GitHub Integration"])
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, object]:
    body = await request.body()
    if not verify_webhook_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid GitHub webhook signature")
    payload = json.loads(body.decode("utf-8"))
    action = str(payload.get("action") or "")
    pull_request = payload.get("pull_request") or {}
    if x_github_event != "pull_request" or action not in {"opened", "synchronize", "reopened"} or not pull_request:
        return {"accepted": True, "ignored": True, "reason": "event is not a supported pull_request action"}
    pr_url = str(pull_request.get("html_url") or "")
    parse_pull_request_url(pr_url)
    background_tasks.add_task(_run_github_webhook_review, pr_url, payload)
    return {"accepted": True, "ignored": False, "action": action, "pr_url": pr_url}


def _run_github_webhook_review(pr_url: str, payload: dict[str, object]) -> None:
    pull_request = payload.get("pull_request") or {}
    base = (pull_request.get("base") or {}).get("ref") if isinstance(pull_request, dict) else None
    head = (pull_request.get("head") or {}).get("ref") if isinstance(pull_request, dict) else None
    request = BusinessScenarioRequest(
        business_scenario="pr_review",
        project_path=None,
        goal=f"审查 GitHub PR: {pr_url}",
        pr_url=pr_url,
        pr_base=str(base) if base else None,
        pr_head=str(head) if head else None,
        require_human_review=True,
        post_comment=True,
    )
    run_business_scenario_api(request)


@router.post("/business-scenarios/run", response_model=TaskRunResponse, tags=["Business Scenarios"])
def run_business_scenario_api(request: BusinessScenarioRequest) -> TaskRunResponse:
    scenario = SCENARIOS.get(request.business_scenario)
    if not scenario:
        raise HTTPException(status_code=400, detail="Unsupported business scenario")
    goal = request.goal or scenario["description"]
    context = harness_runtime.create_context(
        goal=goal,
        project_path=request.project_path,
        variables={"business_scenario": request.business_scenario, "max_files": request.max_files},
    )
    try:
        result = harness_runtime.run_graph(context, run_business_scenario, {**request.model_dump(), "goal": goal})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TaskRunResponse(**result)


@router.post("/business-scenarios/run/stream", tags=["Business Scenarios"])
async def run_business_scenario_stream(request: BusinessScenarioRequest) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        try:
            response = run_business_scenario_api(request)
            for event in response.events:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            payload = {"type": "task_result", "task_id": response.task_id, "status": response.status, **response.result}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)}, ensure_ascii=False)}\n\n"
        finally:
            yield "data: {\"type\": \"complete\", \"completed\": true}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/shopping/decide", response_model=TaskRunResponse, tags=["Shopping Decision"])
def run_shopping_decision(request: ShoppingDecisionRequest, authorization: str | None = Header(default=None)) -> TaskRunResponse:
    goal = request.goal or "为商品候选生成购买决策"
    user_id = _request_user(authorization)
    context = harness_runtime.create_context(goal=goal, variables={"shopping": True})
    started = time.perf_counter()
    shopping_store.record_business_event(user_id, "analysis_started", context.task_id, idempotency_key=f"analysis-start:{context.task_id}")
    try:
        result = harness_runtime.run_graph(
            context,
            shopping_decision_graph_runner,
            {"goal": goal, **request.model_dump()},
        )
    except Exception as exc:
        shopping_store.record_business_event(user_id, "analysis_failed", context.task_id, metadata={"error": str(exc)}, idempotency_key=f"analysis-fail:{context.task_id}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response = TaskRunResponse(**result)
    shopping_store.save_report(user_id, response.task_id, goal, [item.model_dump() for item in request.products], response.result)
    shopping_store.record_business_event(user_id, "analysis_completed", response.task_id, metadata={"latency_ms": int((time.perf_counter() - started) * 1000)}, idempotency_key=f"analysis-complete:{response.task_id}")
    return response


@router.post("/shopping/decide/stream", tags=["Shopping Decision"])
async def run_shopping_decision_stream(
    request: ShoppingDecisionRequest,
    authorization: str | None = Header(default=None),
) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        try:
            response = run_shopping_decision(request, authorization)
            for event in response.events:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            payload = {"type": "task_result", "task_id": response.task_id, "status": response.status, **response.result}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)}, ensure_ascii=False)}\n\n"
        finally:
            yield "data: {\"type\": \"complete\", \"completed\": true}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/shopping/monitors", response_model=PriceMonitorResponse, tags=["Shopping Monitor"])
def create_price_monitor(request: PriceMonitorCreateRequest, authorization: str | None = Header(default=None)) -> PriceMonitorResponse:
    product = request.product.model_dump()
    breakdown = final_price_from_breakdown(product)
    user_id = _request_user(authorization)
    try:
        auth_store.require_entitlement(user_id, "active_monitors")
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    record = shopping_store.create_monitor(
        user_id=user_id,
        product=product,
        target_price=request.target_price,
        current_final_price=breakdown["final_price"],
        monitor_days=request.monitor_days,
        notify_channel=request.notify_channel,
    )
    return PriceMonitorResponse(**record)


@router.get("/shopping/monitors", response_model=list[PriceMonitorResponse], tags=["Shopping Monitor"])
def list_price_monitors(user_id: str | None = None, authorization: str | None = Header(default=None)) -> list[PriceMonitorResponse]:
    del user_id
    return [PriceMonitorResponse(**item) for item in shopping_store.list_monitors(user_id=_request_user(authorization))]


@router.patch("/shopping/monitors/{monitor_id}", tags=["Shopping Monitor"])
def update_price_monitor(monitor_id: str, payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    try:
        monitor = shopping_store.update_user_monitor(_request_user(authorization), monitor_id, target_price=float(payload["target_price"]) if payload.get("target_price") is not None else None, status=str(payload["status"]) if payload.get("status") else None)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not monitor: raise HTTPException(status_code=404, detail="Monitor not found")
    return monitor


@router.delete("/shopping/monitors/{monitor_id}", tags=["Shopping Monitor"])
def delete_price_monitor(monitor_id: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    if not shopping_store.delete_user_monitor(_request_user(authorization), monitor_id): raise HTTPException(status_code=404, detail="Monitor not found")
    return {"deleted": True, "monitor_id": monitor_id}


@router.get("/shopping/profile", tags=["Shopping Account"])
def get_shopping_profile(authorization: str | None = Header(default=None)) -> dict[str, object]:
    return shopping_store.get_profile(_request_user(authorization))


@router.get("/shopping/content", tags=["Shopping Discovery"])
def list_shopping_content(category: str | None = None, limit: int = 100) -> dict[str, object]:
    return {"items": shopping_store.list_content(category=category, limit=limit)}


@router.get("/shopping/campaigns", tags=["Shopping Discovery"])
def list_public_campaigns() -> dict[str, object]:
    return {"items": shopping_store.list_campaigns(public_only=True)}


@router.put("/shopping/profile", tags=["Shopping Account"])
def save_shopping_profile(payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    return shopping_store.save_profile(_request_user(authorization), payload)


@router.get("/shopping/dashboard", tags=["Shopping Account"])
def shopping_dashboard(authorization: str | None = Header(default=None)) -> dict[str, object]:
    return shopping_store.user_dashboard(_request_user(authorization))


@router.get("/shopping/saved", tags=["Shopping Account"])
def list_shopping_saved(item_type: str | None = None, authorization: str | None = Header(default=None)) -> list[dict[str, object]]:
    return shopping_store.list_saved_items(_request_user(authorization), item_type)


@router.post("/shopping/saved", tags=["Shopping Account"])
def save_shopping_item(payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    try:
        return shopping_store.save_item(_request_user(authorization), str(payload.get("item_type") or "favorite"), str(payload.get("reference_key") or ""), str(payload.get("label") or ""), payload.get("product") if isinstance(payload.get("product"), dict) else {})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/shopping/saved/{saved_id}", tags=["Shopping Account"])
def delete_shopping_saved(saved_id: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    if not shopping_store.delete_saved_item(_request_user(authorization), saved_id):
        raise HTTPException(status_code=404, detail="Saved item not found")
    return {"deleted": True}


@router.get("/shopping/comparisons", tags=["Shopping Decision"])
def list_shopping_comparisons(authorization: str | None = Header(default=None)) -> list[dict[str, object]]:
    return shopping_store.list_comparisons(_request_user(authorization))


@router.post("/shopping/comparisons", tags=["Shopping Decision"])
def save_shopping_comparison(payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    products = payload.get("products") if isinstance(payload.get("products"), list) else []
    try:
        user_id = _request_user(authorization)
        comparison_id = str(payload.get("comparison_id") or "") or None
        if not comparison_id:
            auth_store.require_entitlement(user_id, "monthly_comparisons")
        return shopping_store.save_comparison(user_id, str(payload.get("name") or "购物对比"), products, comparison_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.delete("/shopping/comparisons/{comparison_id}", tags=["Shopping Decision"])
def delete_shopping_comparison(comparison_id: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    if not shopping_store.delete_comparison(_request_user(authorization), comparison_id): raise HTTPException(status_code=404, detail="Comparison not found")
    return {"deleted": True, "comparison_id": comparison_id}


@router.post("/shopping/shares", tags=["Shopping Sharing"])
def create_shopping_share(payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    try:
        share = shopping_store.create_share(_request_user(authorization), str(payload.get("share_type") or "comparison"), str(payload.get("title") or "ValuSee 分享"), payload.get("payload") if isinstance(payload.get("payload"), dict) else {}, int(payload.get("expires_days") or 30))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**share, "share_url": f"/share/{share['share_token']}"}


@router.get("/shopping/shares", tags=["Shopping Sharing"])
def list_shopping_shares(authorization: str | None = Header(default=None)) -> list[dict[str, object]]:
    return shopping_store.list_shares(_request_user(authorization))


@router.delete("/shopping/shares/{share_id}", tags=["Shopping Sharing"])
def revoke_shopping_share(share_id: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    if not shopping_store.revoke_share(_request_user(authorization), share_id):
        raise HTTPException(status_code=404, detail="Share not found")
    return {"revoked": True, "share_id": share_id}


@router.get("/public/shares/{share_token}", tags=["Shopping Sharing"])
def get_public_shopping_share(share_token: str) -> dict[str, object]:
    share = shopping_store.get_share(share_token)
    if not share:
        raise HTTPException(status_code=404, detail="Share not found or expired")
    return share


@router.get("/shopping/reports", tags=["Shopping Decision"])
def list_shopping_reports(limit: int = 100, authorization: str | None = Header(default=None)) -> list[dict[str, object]]:
    return shopping_store.list_reports(_request_user(authorization), limit)


@router.post("/shopping/feedback", tags=["Shopping Feedback"])
def create_shopping_feedback(payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    try: return shopping_store.create_feedback(_request_user(authorization), payload)
    except ValueError as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/shopping/events", tags=["Shopping Feedback"])
def record_shopping_event(payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    event_type = str(payload.get("event_type") or "")
    if event_type not in {"recommendation_accepted", "recommendation_rejected"}:
        raise HTTPException(status_code=422, detail="unsupported shopping event")
    event = shopping_store.record_business_event(_request_user(authorization), event_type, str(payload.get("reference_id") or "") or None, idempotency_key=str(payload.get("idempotency_key") or "") or None)
    return event or {"duplicate": True}


@router.get("/admin/metrics", tags=["Admin Console"])
def admin_shopping_metrics(days: int = 30, authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    return shopping_store.business_metrics(days)


@router.get("/admin/content", tags=["Admin Console"])
def admin_list_content(authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    return {"items": shopping_store.list_content(status="all")}


@router.post("/admin/content", tags=["Admin Console"])
def admin_save_content(payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    try:
        return shopping_store.save_content(payload, str(payload.get("content_id") or "") or None)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/admin/content/{content_id}", tags=["Admin Console"])
def admin_delete_content(content_id: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    if not shopping_store.delete_content(content_id):
        raise HTTPException(status_code=404, detail="Content not found")
    return {"deleted": True, "content_id": content_id}


@router.get("/shopping/feedback", tags=["Shopping Feedback"])
def list_user_feedback(authorization: str | None = Header(default=None)) -> list[dict[str, object]]:
    return shopping_store.list_feedback(_request_user(authorization))


@router.get("/shopping/notification-preferences", tags=["Shopping Account"])
def get_notification_preferences(authorization: str | None = Header(default=None)) -> dict[str, object]:
    return shopping_store.get_notification_preference(_request_user(authorization))


@router.put("/shopping/notification-preferences", tags=["Shopping Account"])
def save_notification_preferences(payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    return shopping_store.save_notification_preference(_request_user(authorization), payload)


@router.get("/admin/feedback", tags=["Admin Console"])
def admin_feedback(limit: int = 200, authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    return {"feedback": shopping_store.list_feedback(limit=limit)}


@router.patch("/admin/feedback/{feedback_id}", tags=["Admin Console"])
def update_admin_feedback(feedback_id: str, payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    try:
        feedback = shopping_store.update_feedback_status(feedback_id, str(payload.get("status") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return feedback


@router.get("/shopping/monitors/{monitor_id}/checks", tags=["Shopping Monitor"])
def list_price_monitor_checks(monitor_id: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    monitor = shopping_store.get_monitor(monitor_id)
    if not monitor or monitor["user_id"] != _request_user(authorization):
        raise HTTPException(status_code=404, detail="Monitor not found")
    return {"monitor": monitor, "checks": shopping_store.list_price_checks(monitor_id)}


@router.post("/shopping/monitors/{monitor_id}/checks", response_model=PriceMonitorCheckResponse, tags=["Shopping Monitor"])
def record_price_monitor_check(monitor_id: str, request: PriceMonitorCheckRequest, authorization: str | None = Header(default=None)) -> PriceMonitorCheckResponse:
    _require_admin(authorization)
    breakdown = final_price_from_breakdown(request.model_dump())
    try:
        check = shopping_store.record_price_check(
            monitor_id=monitor_id,
            breakdown=breakdown,
            stock_status=request.stock_status,
            source=request.source,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Monitor not found") from exc
    monitor = shopping_store.get_monitor(monitor_id)
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return PriceMonitorCheckResponse(
        monitor=PriceMonitorResponse(**monitor),
        check=check,
        target_reached=check["target_reached"],
        message=check["message"],
    )


@router.post("/shopping/purchases", response_model=PurchaseResponse, tags=["Shopping Purchase"])
def create_purchase_record(request: PurchaseCreateRequest, authorization: str | None = Header(default=None)) -> PurchaseResponse:
    record = shopping_store.create_purchase(
        user_id=_request_user(authorization),
        product=request.product.model_dump(),
        paid_price=request.paid_price,
        platform=request.platform,
        store_name=request.store_name,
        purchased_at=request.purchased_at,
        price_protection_days=request.price_protection_days,
        return_days=request.return_days,
        warranty_months=request.warranty_months,
        consumable_cycle_days=request.consumable_cycle_days,
        notes=request.notes,
    )
    return PurchaseResponse(**record)


@router.get("/shopping/purchases", response_model=list[PurchaseResponse], tags=["Shopping Purchase"])
def list_purchase_records(user_id: str | None = None, authorization: str | None = Header(default=None)) -> list[PurchaseResponse]:
    del user_id
    return [PurchaseResponse(**item) for item in shopping_store.list_purchases(user_id=_request_user(authorization))]


@router.patch("/shopping/purchases/{purchase_id}", tags=["Shopping Purchase"])
def update_purchase_record(purchase_id: str, payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    try:
        purchase = shopping_store.update_purchase(_request_user(authorization), purchase_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not purchase:
        raise HTTPException(status_code=404, detail="Purchase not found")
    return purchase


@router.post("/shopping/purchases/{purchase_id}/attachments", tags=["Shopping Purchase"])
async def upload_purchase_attachment(purchase_id: str, file: UploadFile = File(...), attachment_type: str = "evidence", authorization: str | None = Header(default=None)) -> dict[str, object]:
    allowed = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    content_type = (file.content_type or "").lower()
    if content_type not in allowed:
        raise HTTPException(status_code=415, detail="仅支持 PDF、JPEG、PNG 和 WebP")
    content = await file.read(10 * 1024 * 1024 + 1)
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="附件不能为空且不能超过 10MB")
    signatures = {"application/pdf": content.startswith(b"%PDF-"), "image/jpeg": content.startswith(b"\xff\xd8\xff"), "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"), "image/webp": content.startswith(b"RIFF") and content[8:12] == b"WEBP"}
    if not signatures[content_type]:
        raise HTTPException(status_code=415, detail="文件内容与声明类型不一致")
    user_id = _request_user(authorization)
    upload_dir = Path.cwd() / "data" / "attachments"
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_path = upload_dir / f"{uuid4().hex}{allowed[content_type]}"
    stored_path.write_bytes(content)
    storage = persist_upload(stored_path, content_type, prefix="purchase-attachments")
    try:
        record = shopping_store.create_purchase_attachment(user_id, purchase_id, {"attachment_type": attachment_type[:40], "original_name": Path(file.filename or "attachment").name[:180], "content_type": content_type, "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(), "storage_backend": storage["backend"], "storage_key": storage["key"]})
    except ValueError as exc:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if storage["backend"] == "s3":
        stored_path.unlink(missing_ok=True)
    for private_key in ("user_id", "storage_backend", "storage_key"):
        record.pop(private_key, None)
    return record


@router.get("/shopping/purchases/{purchase_id}/attachments", tags=["Shopping Purchase"])
def list_purchase_attachments(purchase_id: str, authorization: str | None = Header(default=None)) -> list[dict[str, object]]:
    return shopping_store.list_purchase_attachments(_request_user(authorization), purchase_id)


@router.get("/shopping/attachments/{attachment_id}/download", tags=["Shopping Purchase"])
def download_purchase_attachment(attachment_id: str, authorization: str | None = Header(default=None)):
    record = shopping_store.get_purchase_attachment(_request_user(authorization), attachment_id)
    if not record:
        raise HTTPException(status_code=404, detail="附件不存在")
    target = create_download_url(str(record["storage_backend"]), str(record["storage_key"]))
    if not target:
        raise HTTPException(status_code=404, detail="附件文件不可用")
    if record["storage_backend"] == "s3":
        return RedirectResponse(target, status_code=307)
    return FileResponse(target, media_type=str(record["content_type"]), filename=str(record["original_name"]))


@router.post("/shopping/support/tickets", tags=["Customer Support"])
def create_support_ticket(payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    try:
        return shopping_store.create_support_ticket(_request_user(authorization), payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/shopping/support/tickets", tags=["Customer Support"])
def list_support_tickets(authorization: str | None = Header(default=None)) -> list[dict[str, object]]:
    return shopping_store.list_support_tickets(_request_user(authorization))


@router.get("/shopping/support/tickets/{ticket_id}", tags=["Customer Support"])
def get_support_ticket(ticket_id: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    ticket = shopping_store.get_support_ticket(_request_user(authorization), ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")
    return ticket


@router.post("/shopping/support/tickets/{ticket_id}/messages", tags=["Customer Support"])
def reply_support_ticket(ticket_id: str, payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    try:
        return shopping_store.reply_support_ticket(_request_user(authorization), ticket_id, str(payload.get("content") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/admin/support/tickets", tags=["Admin Support"])
def admin_list_support_tickets(authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin(authorization)
    return {"tickets": shopping_store.list_support_tickets()}


@router.post("/admin/support/tickets/{ticket_id}/messages", tags=["Admin Support"])
def admin_reply_support_ticket(ticket_id: str, payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    actor_id = _require_admin(authorization)
    try:
        ticket = shopping_store.reply_support_ticket(actor_id, ticket_id, str(payload.get("content") or ""), admin=True, status=str(payload.get("status") or "in_progress"))
        message_id = str(ticket.get("messages", [{}])[-1].get("message_id") or uuid4().hex)
        shopping_store.create_notification(user_id=str(ticket["user_id"]), kind="support", title=f"客服回复：{ticket['subject']}", message=str(payload.get("content") or "")[:500], idempotency_key=f"support:{ticket_id}:{message_id}")
        return ticket
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/projects/analyze", response_model=ProjectAnalyzeResponse, tags=["Project Analyzer"])
def analyze_project(request: ProjectAnalyzeRequest) -> ProjectAnalyzeResponse:
    try:
        result = project_analyzer_graph.invoke(request.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    scan = result["scan"]
    return ProjectAnalyzeResponse(
        project_path=scan["root"],
        project_name=scan["project_name"],
        file_count=len(scan["files"]),
        directory_count=len(scan["directories"]),
        tech_stack=result.get("tech_stack", []),
        key_files=scan.get("key_files", []),
        modules=result.get("modules", []),
        risks=result.get("risks", []),
        suggestions=result.get("suggestions", []),
        quality_score=result.get("quality_score", 0),
        report_markdown=result.get("report_markdown", ""),
    )


@router.post("/projects/analyze/stream", tags=["Project Analyzer"])
async def analyze_project_stream(request: ProjectAnalyzeRequest) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in project_analyzer_graph.astream_events(request.model_dump(), version="v2"):
                payload = {
                    "type": "graph_event",
                    "event": event.get("event", "unknown"),
                    "node": event.get("name", "graph"),
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)}, ensure_ascii=False)}\n\n"
        finally:
            yield "data: {\"type\": \"complete\", \"completed\": true}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/code/review", response_model=CodeReviewResponse, tags=["Code Review Agent"])
def review_code(request: CodeReviewRequest) -> CodeReviewResponse:
    try:
        result = code_review_graph.invoke(request.model_dump())["result"]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    scan = result["scan"]
    return CodeReviewResponse(
        project_path=scan["root"],
        reviewed_files=len(scan["files"]),
        findings=result["findings"],
        risks=result["risks"],
        suggestions=result["suggestions"],
        suggestion_records=result.get("suggestion_records", []),
        score=result["score"],
        report_markdown=result["report_markdown"],
    )


@router.post("/rag/process", response_model=RagProcessResponse, tags=["RAG Knowledge Agent"])
def process_rag(request: RagProcessRequest) -> RagProcessResponse:
    try:
        result = rag_process_graph.invoke(request.model_dump())["result"]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    scan = result["scan"]
    return RagProcessResponse(
        project_path=scan["root"],
        document_count=len(result["documents"]),
        chunk_count=len(result["chunks"]),
        keywords=result["keywords"],
        faq=result["faq"],
        report_markdown=result["report_markdown"],
    )


@router.post("/rag/ingest", response_model=RagIngestResponse, tags=["RAG Knowledge Agent"])
def ingest_rag(request: RagIngestRequest) -> RagIngestResponse:
    try:
        result = rag_process_graph.invoke(request.model_dump())["result"]
        saved = rag_store.ingest(request.collection, result["documents"], result["chunks"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RagIngestResponse(
        collection=request.collection,
        document_count=saved["document_count"],
        chunk_count=saved["chunk_count"],
        changed_document_count=saved.get("changed_document_count", saved["document_count"]),
        changed_chunk_count=saved.get("changed_chunk_count", saved["chunk_count"]),
        keywords=result["keywords"],
    )


@router.post("/rag/query", response_model=RagQueryResponse, tags=["RAG Knowledge Agent"])
def query_rag(request: RagQueryRequest, x_devagent_actor: str = Header("local-user")) -> RagQueryResponse:
    actor_id = request.actor_id or x_devagent_actor
    results = rag_store.query(request.collection, request.question, request.limit, actor_id=actor_id)
    return RagQueryResponse(collection=request.collection, question=request.question, results=results)


@router.get("/rag/documents", tags=["RAG Knowledge Agent"])
def list_rag_documents(collection: str | None = None, x_devagent_actor: str = Header("local-user")) -> dict[str, object]:
    return {"documents": rag_store.list_documents(collection, actor_id=x_devagent_actor)}


@router.post("/rag/documents/acl", tags=["RAG Knowledge Agent"])
def set_rag_document_acl(request: RagDocumentAclRequest) -> dict[str, object]:
    if not hasattr(rag_store, "set_document_acl"):
        raise HTTPException(status_code=501, detail="Document ACL is not supported by the active RAG store")
    if not rag_store.set_document_acl(request.collection, request.path, request.principals):
        raise HTTPException(status_code=404, detail="Current document version not found")
    return {"collection": request.collection, "path": request.path, "principals": request.principals}


@router.get("/rag/gold-cases", tags=["RAG Knowledge Agent"])
def list_rag_gold_cases(collection: str | None = None, include_disabled: bool = True) -> dict[str, object]:
    return {"cases": rag_store.list_gold_cases(collection, include_disabled=include_disabled)}


@router.post("/rag/gold-cases", tags=["RAG Knowledge Agent"])
def save_rag_gold_case(request: RagGoldCaseRequest) -> dict[str, object]:
    case = rag_store.save_gold_case(request.model_dump())
    return {"case": case}


@router.delete("/rag/gold-cases/{case_id}", tags=["RAG Knowledge Agent"])
def delete_rag_gold_case(case_id: str) -> dict[str, object]:
    if not rag_store.delete_gold_case(case_id):
        raise HTTPException(status_code=404, detail="Gold case not found")
    return {"case_id": case_id, "deleted": True}


@router.get("/rag/status", tags=["RAG Knowledge Agent"])
def get_rag_status() -> dict[str, object]:
    status = rag_store.status() if hasattr(rag_store, "status") else {"kind": "unknown"}
    return {"store": status}


@router.post("/learning/coach/plan", response_model=LearningCoachResponse, tags=["Learning Coach Agent"])
def create_learning_plan(request: LearningCoachRequest) -> LearningCoachResponse:
    result = learning_coach_graph.invoke(request.model_dump())["result"]
    return LearningCoachResponse(
        topic=request.topic,
        level=request.level,
        days=request.days,
        plan=result["plan"],
        quiz=result["quiz"],
        report_markdown=result["report_markdown"],
    )


@router.post("/tasks/{task_id}/learning-plan", response_model=LearningPlanResponse, tags=["Learning Coach Agent"])
def create_task_learning_plan(task_id: str, request: LearningPlanCreateRequest) -> LearningPlanResponse:
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    goal = request.goal or str(task.get("goal") or "")
    result = learning_coach_graph.invoke(
        {
            "topic": request.topic,
            "level": request.level,
            "days": request.days,
            "goal": goal,
        }
    )["result"]
    plan_id = f"lp_{uuid4().hex}"
    saved = task_store.save_learning_plan(
        plan_id=plan_id,
        task_id=task_id,
        topic=request.topic,
        level=request.level,
        plan=result["plan"],
        quiz=result["quiz"],
        report_markdown=result["report_markdown"],
    )
    task_store.append_event(
        {
            "event_id": f"evt_{uuid4().hex}",
            "task_id": task_id,
            "type": "learning_plan",
            "node": "learning_coach",
            "agent": "learning_coach",
            "status": "active",
            "content": f"Learning plan created: {request.topic}",
            "data": {
                "plan_id": plan_id,
                "topic": request.topic,
                "level": request.level,
                "days": request.days,
                "comment": request.comment,
            },
        }
    )
    task_store.save_artifact(task_id, "learning_plan", request.topic, saved)
    rag_store.add_note("project-memory", f"learning/{plan_id}", result["report_markdown"])
    return LearningPlanResponse(plan=saved)


@router.get("/learning/plans", tags=["Learning Coach Agent"])
def list_learning_plans(task_id: str | None = None) -> dict[str, object]:
    return {"plans": task_store.list_learning_plans(task_id)}


@router.patch("/learning/plans/{plan_id}", response_model=LearningPlanResponse, tags=["Learning Coach Agent"])
def update_learning_plan(plan_id: str, request: LearningPlanStatusRequest) -> LearningPlanResponse:
    if request.status not in {"active", "completed", "paused"}:
        raise HTTPException(status_code=400, detail="status must be active, completed, or paused")
    updated = task_store.update_learning_plan_status(plan_id, request.status)
    if not updated:
        raise HTTPException(status_code=404, detail="Learning plan not found")
    task_store.append_event(
        {
            "event_id": f"evt_{uuid4().hex}",
            "task_id": updated["task_id"],
            "type": "learning_plan_status",
            "node": "learning_coach",
            "agent": "learning_coach",
            "status": request.status,
            "content": f"Learning plan status updated to {request.status}: {updated['topic']}",
            "data": {"plan_id": plan_id, "status": request.status},
        }
    )
    return LearningPlanResponse(plan=updated)


@router.get("/skills/plugins", tags=["Skills"])
def list_skill_plugins() -> dict[str, object]:
    ensure_builtin_skills_seeded()
    return {"plugins": task_store.list_skill_plugins()}


@router.get("/skills", tags=["Skills"])
def list_skills(category: str | None = None) -> dict[str, object]:
    ensure_builtin_skills_seeded()
    return {"skills": task_store.list_skills(category)}


@router.get("/skills/approvals", tags=["Skills"])
def list_skill_approvals(agent_code: str | None = None) -> dict[str, object]:
    ensure_builtin_skills_seeded()
    return {"approvals": task_store.list_skill_approvals(agent_code)}


@router.get("/skills/execution-logs", tags=["Skills"])
def list_skill_execution_logs(limit: int = 100, skill_code: str | None = None) -> dict[str, object]:
    ensure_builtin_skills_seeded()
    return {"logs": task_store.list_skill_execution_logs(limit=limit, skill_code=skill_code)}


@router.get("/skills/sandbox/status", tags=["Skills"])
def get_skill_sandbox_status() -> dict[str, object]:
    return python_skill_sandbox_status()


@router.get("/skills/{skill_code}/versions", tags=["Skills"])
def list_skill_versions(skill_code: str) -> dict[str, object]:
    ensure_builtin_skills_seeded()
    if not task_store.get_skill(skill_code):
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"versions": task_store.list_skill_versions(skill_code)}


@router.post("/skills/{skill_code}/rollback", tags=["Skills"])
def rollback_skill_version(skill_code: str, payload: dict[str, object]) -> dict[str, object]:
    ensure_builtin_skills_seeded()
    version = str(payload.get("version") or "").strip()
    if not version:
        raise HTTPException(status_code=400, detail="version is required")
    skill = task_store.rollback_skill_version(skill_code, version)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill version not found")
    return {"skill": skill}


@router.post("/skills/{skill_code}/enabled", tags=["Skills"])
def set_skill_enabled(skill_code: str, payload: dict[str, object]) -> dict[str, object]:
    ensure_builtin_skills_seeded()
    skill = task_store.update_skill_enabled(skill_code, bool(payload.get("enabled")))
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"skill": skill}


@router.post("/skills/{skill_code}/approval", tags=["Skills"])
def set_skill_approval(skill_code: str, payload: dict[str, object]) -> dict[str, object]:
    ensure_builtin_skills_seeded()
    if not task_store.get_skill(skill_code):
        raise HTTPException(status_code=404, detail="Skill not found")
    agent_code = str(payload.get("agent_code") or "skill_console").strip()
    approval = task_store.set_skill_approval(
        skill_code,
        agent_code,
        bool(payload.get("allowed")),
        str(payload.get("reason") or "").strip() or None,
    )
    return {"approval": approval}


@router.post("/skills/{skill_code}/execute", tags=["Skills"])
def execute_skill_api(skill_code: str, payload: dict[str, object]) -> dict[str, object]:
    try:
        result = execute_skill(
            skill_code,
            payload.get("input") if isinstance(payload.get("input"), dict) else {},
            agent_code=str(payload.get("agent_code") or "skill_console"),
            task_id=str(payload.get("task_id") or "") or None,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.post("/skills/{skill_code}/test", tags=["Skills"])
def test_skill_api(skill_code: str, payload: dict[str, object]) -> dict[str, object]:
    ensure_builtin_skills_seeded()
    skill = task_store.get_skill(skill_code)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    tests = skill.get("tests") if isinstance(skill.get("tests"), list) else []
    if payload.get("test") and isinstance(payload.get("test"), dict):
        tests = [payload["test"]]
    if not tests:
        tests = [{"name": "default", "input": skill.get("default_input") or {}}]
    results = []
    agent_code = str(payload.get("agent_code") or "skill_console")
    for test in tests:
        case_input = test.get("input") if isinstance(test, dict) and isinstance(test.get("input"), dict) else {}
        name = str(test.get("name") or test.get("case_id") or "test") if isinstance(test, dict) else "test"
        try:
            run = execute_skill(skill_code, case_input, agent_code=agent_code)
            results.append({"name": name, "status": "passed", "output": run.get("output"), "latency_ms": run.get("latency_ms")})
        except Exception as exc:
            results.append({"name": name, "status": "failed", "error_message": str(exc)})
    return {
        "skill_code": skill_code,
        "total": len(results),
        "passed": len([item for item in results if item["status"] == "passed"]),
        "failed": len([item for item in results if item["status"] == "failed"]),
        "results": results,
    }


@router.delete("/skills/plugins/{plugin_id}", tags=["Skills"])
def uninstall_skill_plugin_api(plugin_id: str) -> dict[str, object]:
    ensure_builtin_skills_seeded()
    try:
        result = task_store.uninstall_skill_plugin(plugin_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Skill plugin not found")
    return {"uninstall": result}


@router.get("/marketplace/catalog", tags=["Plugin Marketplace"])
def get_marketplace_catalog() -> dict[str, object]:
    return {"items": marketplace_catalog()}


@router.get("/marketplace/installs", tags=["Plugin Marketplace"])
def list_marketplace_installs(limit: int = 80, package_type: str | None = None) -> dict[str, object]:
    return {"installs": task_store.list_marketplace_installs(limit=limit, package_type=package_type)}


@router.post("/marketplace/preview", tags=["Plugin Marketplace"])
def preview_marketplace(payload: dict[str, object]) -> dict[str, object]:
    source_url = str(payload.get("source_url") or "").strip()
    try:
        return preview_marketplace_package(source_url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/marketplace/install", tags=["Plugin Marketplace"])
def install_marketplace(payload: dict[str, object]) -> dict[str, object]:
    source_url = str(payload.get("source_url") or "").strip()
    try:
        install = install_marketplace_package(source_url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ensure_builtin_skills_seeded()
    return {"install": install}


@router.delete("/marketplace/packages/{package_id}", tags=["Plugin Marketplace"])
def uninstall_marketplace(package_id: str) -> dict[str, object]:
    try:
        uninstall = uninstall_marketplace_package(package_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ensure_builtin_skills_seeded()
    return {"uninstall": uninstall}


@router.get("/mcp/tools", tags=["MCP Tool Marketplace"])
def get_tools() -> dict[str, object]:
    return {
        "provider": mcp_provider.status(),
        "tools": list_tools(),
        "registered_tools": mcp_provider.real.list_tools(),
    }


@router.get("/mcp/status", tags=["MCP Tool Marketplace"])
def get_mcp_status() -> dict[str, object]:
    return mcp_provider.status()


@router.get("/mcp/servers", tags=["MCP Tool Marketplace"])
def list_mcp_servers() -> dict[str, object]:
    return {"servers": mcp_provider.real.list_servers()}


@router.post("/mcp/servers", response_model=McpServerConfigResponse, tags=["MCP Tool Marketplace"])
def save_mcp_server(request: McpServerConfigRequest) -> McpServerConfigResponse:
    server = mcp_provider.real.save_server(request.model_dump())
    return McpServerConfigResponse(server=server)


@router.post("/mcp/servers/{server_id}/enabled", tags=["MCP Tool Marketplace"])
def set_mcp_server_enabled(server_id: str, request: McpToolToggleRequest) -> dict[str, object]:
    server = mcp_provider.real.set_server_enabled(server_id, request.enabled)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return {"server": server}


@router.post("/mcp/servers/{server_id}/discover", tags=["MCP Tool Marketplace"])
def discover_mcp_server_tools(server_id: str) -> dict[str, object]:
    try:
        return mcp_provider.real.discover_tools(server_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/mcp/registered-tools", tags=["MCP Tool Marketplace"])
def list_registered_mcp_tools(server_id: str | None = None, agent_code: str = "workflow_runner") -> dict[str, object]:
    tools = []
    for tool in mcp_provider.real.list_tools(server_id):
        approval = mcp_provider.real.check_approval(agent_code, tool["server_id"], tool["name"])
        stored_approval = task_store.get_mcp_tool_approval(agent_code, tool["server_id"], tool["name"])
        tools.append(
            {
                **tool,
                "approval_agent_code": agent_code,
                "approval_allowed": approval["allowed"],
                "approval_reason": approval["reason"],
                "approval_updated_at": stored_approval.get("updated_at") if stored_approval else None,
                "approval_recorded": stored_approval is not None,
            }
        )
    return {"tools": tools}


@router.post("/mcp/registered-tools/{server_id}/{tool_name}/enabled", tags=["MCP Tool Marketplace"])
def set_registered_mcp_tool_enabled(server_id: str, tool_name: str, request: McpToolToggleRequest) -> dict[str, object]:
    tool = mcp_provider.real.set_tool_enabled(server_id, tool_name, request.enabled)
    if not tool:
        raise HTTPException(status_code=404, detail="MCP tool not found")
    return {"tool": tool}


@router.post("/mcp/tools/approval", tags=["MCP Tool Marketplace"])
def set_mcp_tool_approval(request: McpToolApprovalRequest) -> dict[str, object]:
    return {"approval": mcp_provider.real.set_approval(request.agent_code, request.server_id, request.tool_name, request.allowed, request.reason)}


@router.post("/mcp/tools/call", tags=["MCP Tool Marketplace"])
def call_mcp_tool(request: McpToolCallRequest) -> dict[str, object]:
    try:
        return mcp_provider.call_tool(
            request.tool_name,
            request.arguments,
            server_id=request.server_id,
            agent_code=request.agent_code,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/mcp/tool-call-logs", tags=["MCP Tool Marketplace"])
def list_mcp_tool_call_logs(limit: int = 100, server_id: str | None = None) -> dict[str, object]:
    return {"logs": mcp_provider.real.list_call_logs(limit=limit, server_id=server_id)}


@router.post("/benchmarks/mcp/run", response_model=BenchmarkRunResponse, tags=["Benchmark"])
def run_mcp_benchmark_api(request: BenchmarkRunRequest) -> BenchmarkRunResponse:
    try:
        run = run_mcp_benchmark(request.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BenchmarkRunResponse(run=run)


@router.post("/benchmarks/llm/run", response_model=BenchmarkRunResponse, tags=["Benchmark"])
def run_llm_benchmark_api(request: BenchmarkRunRequest) -> BenchmarkRunResponse:
    try:
        run = run_llm_benchmark(request.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BenchmarkRunResponse(run=run)


@router.post("/benchmarks/rag/run", response_model=BenchmarkRunResponse, tags=["Benchmark"])
def run_rag_benchmark_api(request: BenchmarkRunRequest) -> BenchmarkRunResponse:
    try:
        run = run_rag_benchmark(request.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BenchmarkRunResponse(run=run)


@router.post("/benchmarks/workflow/run", response_model=BenchmarkRunResponse, tags=["Benchmark"])
def run_workflow_benchmark_api(request: BenchmarkRunRequest) -> BenchmarkRunResponse:
    try:
        run = run_workflow_benchmark(request.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BenchmarkRunResponse(run=run)


@router.post("/benchmarks/collaboration/run", response_model=BenchmarkRunResponse, tags=["Benchmark"])
def run_collaboration_benchmark_api(request: BenchmarkRunRequest) -> BenchmarkRunResponse:
    try:
        run = run_collaboration_benchmark(request.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BenchmarkRunResponse(run=run)


@router.get("/benchmarks", tags=["Benchmark"])
def list_benchmarks(limit: int = 50, benchmark_type: str | None = None) -> dict[str, object]:
    return {"runs": task_store.list_benchmark_runs(limit=limit, benchmark_type=benchmark_type)}


@router.get("/benchmarks/{run_id}", tags=["Benchmark"])
def get_benchmark(run_id: str) -> dict[str, object]:
    run = task_store.get_benchmark_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Benchmark run not found")
    return {"run": run}


@router.get("/llm/status", tags=["LLM Provider"])
def get_llm_status() -> dict[str, object]:
    return llm_provider.status()


@router.get("/llm/traces", tags=["LLM Provider"])
def list_llm_traces(limit: int = 50, agent: str | None = None) -> dict[str, object]:
    return {"traces": task_store.list_llm_traces(limit=limit, agent=agent)}


@router.get("/llm/prompts", tags=["LLM Provider"])
def list_llm_prompts(agent: str | None = None) -> dict[str, object]:
    return {"prompts": llm_provider.list_prompt_versions(agent)}


@router.post("/llm/prompts", tags=["LLM Provider"])
def save_llm_prompt(payload: dict[str, object]) -> dict[str, object]:
    agent = str(payload.get("agent") or "").strip()
    prompt_version = str(payload.get("prompt_version") or "").strip()
    title = str(payload.get("title") or "").strip()
    if not agent or not prompt_version or not title:
        raise HTTPException(status_code=400, detail="agent, prompt_version and title are required")
    prompt = llm_provider.save_prompt_version(
        {
            "agent": agent,
            "prompt_family": str(payload.get("prompt_family") or "").strip() or None,
            "prompt_version": prompt_version,
            "title": title,
            "description": str(payload.get("description") or "").strip(),
            "system_suffix": str(payload.get("system_suffix") or "").strip(),
            "is_active": bool(payload.get("is_active")),
        }
    )
    if payload.get("is_active"):
        prompt = llm_provider.set_active_prompt_version(agent, prompt_version) or prompt
    return {"prompt": prompt}


@router.post("/llm/prompts/active", tags=["LLM Provider"])
def set_active_llm_prompt(payload: dict[str, str]) -> dict[str, object]:
    agent = payload.get("agent")
    prompt_version = payload.get("prompt_version")
    if not agent or not prompt_version:
        raise HTTPException(status_code=400, detail="agent and prompt_version are required")
    prompt = llm_provider.set_active_prompt_version(agent, prompt_version)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt version not found")
    return {"prompt": prompt, "active_prompts": llm_provider.active_prompt_map()}


@router.post("/llm/prompts/ab-test", tags=["LLM Provider"])
def run_llm_prompt_ab_test(payload: dict[str, object]) -> dict[str, object]:
    agent = str(payload.get("agent") or "").strip()
    prompt_a = str(payload.get("prompt_a") or "").strip()
    prompt_b = str(payload.get("prompt_b") or "").strip()
    user_prompt = str(payload.get("user_prompt") or "").strip()
    if not agent or not prompt_a or not prompt_b or not user_prompt:
        raise HTTPException(status_code=400, detail="agent, prompt_a, prompt_b and user_prompt are required")
    result = llm_provider.run_prompt_ab_test(
        agent=agent,
        prompt_a=prompt_a,
        prompt_b=prompt_b,
        system_prompt=str(
            payload.get("system_prompt")
            or "你是 ValuSee 的 Prompt A/B 测试执行器。请基于输入给出结构清晰、可验证、可行动的中文回答。"
        ).strip(),
        user_prompt=user_prompt,
        fallback=str(payload.get("fallback") or "LLM 未配置或调用失败，返回 fallback。").strip(),
    )
    return result


@router.get("/llm/usage", tags=["LLM Provider"])
def get_llm_usage(limit: int = 500, agent: str | None = None) -> dict[str, object]:
    return llm_provider.usage_dashboard(limit=limit, agent=agent)


@router.post("/mcp/tools/allow-check", response_model=ToolPermissionResponse, tags=["MCP Tool Marketplace"])
def allow_check(request: ToolPermissionRequest) -> ToolPermissionResponse:
    return ToolPermissionResponse(**check_permission(request.agent_code, request.tool_code))


@router.post("/mcp/filesystem/list", tags=["MCP Tool Marketplace"])
def mcp_list_files(request: McpFileListRequest) -> dict[str, object]:
    tool_policy.require("project_analyzer", "file_scan")
    return mcp_provider.list_files(request.root_path, request.max_files)


@router.post("/mcp/filesystem/read", tags=["MCP Tool Marketplace"])
def mcp_read_file(request: McpFileReadRequest) -> dict[str, object]:
    tool_policy.require("project_analyzer", "file_scan")
    return mcp_provider.read_file(request.root_path, request.file_path, request.max_chars)


@router.post("/mcp/git/status", tags=["MCP Tool Marketplace"])
def mcp_git_status(request: McpGitRequest) -> dict[str, object]:
    tool_policy.require("code_reviewer", "git_read")
    return mcp_provider.git_status(request.repo_path)


@router.post("/mcp/git/log", tags=["MCP Tool Marketplace"])
def mcp_git_log(request: McpGitRequest) -> dict[str, object]:
    tool_policy.require("code_reviewer", "git_read")
    return mcp_provider.git_log(request.repo_path, request.limit)


@router.post("/workflows/run", response_model=WorkflowRunResponse, tags=["Workflow Runner"])
def run_visual_workflow(request: WorkflowRunRequest) -> WorkflowRunResponse:
    result = run_compiled_workflow(
        request.workflow_name,
        request.input_text,
        [node.model_dump() for node in request.nodes],
        [edge.model_dump() for edge in request.edges],
    )
    return WorkflowRunResponse(**result)


@router.post("/workflows/validate", response_model=WorkflowValidateResponse, tags=["Workflow Runner"])
def validate_visual_workflow(request: WorkflowValidateRequest) -> WorkflowValidateResponse:
    result = validate_workflow_definition(
        [node.model_dump() for node in request.nodes],
        [edge.model_dump() for edge in request.edges],
    )
    return WorkflowValidateResponse(**result)


@router.get("/workflows", tags=["Workflow Runner"])
def list_workflows() -> dict[str, object]:
    return {"workflows": task_store.list_workflows()}


@router.post("/workflows", response_model=WorkflowSaveResponse, tags=["Workflow Runner"])
def create_workflow(request: WorkflowSaveRequest) -> WorkflowSaveResponse:
    workflow = task_store.save_workflow(
        request.workflow_id,
        request.name,
        request.description,
        request.nodes,
        request.edges,
    )
    return WorkflowSaveResponse(workflow=workflow)


@router.get("/workflows/{workflow_id}", tags=["Workflow Runner"])
def get_workflow(workflow_id: str) -> dict[str, object]:
    workflow = task_store.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"workflow": workflow}


@router.put("/workflows/{workflow_id}", response_model=WorkflowSaveResponse, tags=["Workflow Runner"])
def update_workflow(workflow_id: str, request: WorkflowSaveRequest) -> WorkflowSaveResponse:
    workflow = task_store.save_workflow(
        workflow_id,
        request.name,
        request.description,
        request.nodes,
        request.edges,
    )
    return WorkflowSaveResponse(workflow=workflow)


@router.post("/agents/collaborate", response_model=CollaborationResponse, tags=["Multi-Agent Collaboration"])
def run_collaboration(request: CollaborationRequest) -> CollaborationResponse:
    result = collaboration_graph.invoke(request.model_dump())["result"]
    return CollaborationResponse(**result)


@router.post("/tasks/run", response_model=TaskRunResponse, tags=["Task Runtime"])
def run_task(request: TaskRunRequest) -> TaskRunResponse:
    workflow_payload = _resolve_task_workflow(request)
    context = harness_runtime.create_context(
        goal=request.goal,
        project_path=request.project_path,
        variables={
            "max_files": request.max_files,
            "require_human_review": request.require_human_review,
            "execution_mode": request.execution_mode,
            "workflow_id": request.workflow_id,
        },
    )
    try:
        result = harness_runtime.run_graph(context, run_task_workflow, workflow_payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TaskRunResponse(**result)


@router.post("/tasks/run/stream", tags=["Task Runtime"])
async def run_task_stream(request: TaskRunRequest) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        try:
            response = run_task(request)
            for event in response.events:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            payload = {
                "type": "task_result",
                "task_id": response.task_id,
                "status": response.status,
                "final_report": response.result.get("final_report"),
                "mermaid": response.result.get("mermaid"),
                "suggestions": response.result.get("suggestions"),
                "suggestion_records": response.result.get("suggestion_records"),
                "risk_level": response.result.get("risk_level"),
                "review_required": response.result.get("review_required"),
                "next_actions": response.result.get("next_actions"),
                "governance": response.result.get("governance"),
                "tool_calls": response.result.get("tool_calls"),
                "agent_outputs": response.result.get("agent_outputs"),
                "human_review_required": response.result.get("human_review_required"),
                "planned_workflow": response.result.get("planned_workflow"),
                "validation": response.result.get("validation"),
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)}, ensure_ascii=False)}\n\n"
        finally:
            yield "data: {\"type\": \"complete\", \"completed\": true}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/tasks/collaborate", response_model=TaskRunResponse, tags=["Task Runtime"])
def run_collaboration_task_api(request: TaskRunRequest) -> TaskRunResponse:
    context = harness_runtime.create_context(
        goal=request.goal,
        project_path=request.project_path,
        variables={
            "max_files": request.max_files,
            "require_human_review": request.require_human_review,
            "execution_mode": "collaboration",
        },
    )
    input_state = {
        "goal": request.goal,
        "project_path": request.project_path,
        "max_files": request.max_files,
        "require_human_review": request.require_human_review,
        "input_text": request.input_text or request.goal,
    }
    try:
        result = harness_runtime.run_graph(context, run_collaboration_task, input_state)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TaskRunResponse(**result)


@router.post("/tasks/collaborate/stream", tags=["Task Runtime"])
async def run_collaboration_task_stream(request: TaskRunRequest) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        try:
            response = run_collaboration_task_api(request)
            for event in response.events:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            payload = {
                "type": "task_result",
                "task_id": response.task_id,
                "status": response.status,
                "final_report": response.result.get("final_report"),
                "mermaid": response.result.get("mermaid"),
                "suggestions": response.result.get("suggestions"),
                "suggestion_records": response.result.get("suggestion_records"),
                "risk_level": response.result.get("risk_level"),
                "review_required": response.result.get("review_required"),
                "next_actions": response.result.get("next_actions"),
                "governance": response.result.get("governance"),
                "tool_calls": response.result.get("tool_calls"),
                "agent_outputs": response.result.get("agent_outputs"),
                "human_review_required": response.result.get("human_review_required"),
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)}, ensure_ascii=False)}\n\n"
        finally:
            yield "data: {\"type\": \"complete\", \"completed\": true}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/tasks", tags=["Task Runtime"])
def list_tasks() -> dict[str, object]:
    return {"tasks": task_store.list_tasks()}


@router.get("/tasks/{task_id}", tags=["Task Runtime"])
def get_task(task_id: str) -> dict[str, object]:
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task": task, "artifacts": task_store.get_artifacts(task_id)}


@router.get("/tasks/{task_id}/events", tags=["Task Runtime"])
def get_task_events(task_id: str) -> dict[str, object]:
    if not task_store.get_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"events": task_store.get_events(task_id)}


@router.get("/tasks/{task_id}/report", tags=["Task Runtime"])
def get_task_report(task_id: str) -> dict[str, object]:
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task_id": task_id, "final_report": task.get("final_report")}


@router.post("/tasks/{task_id}/ask", response_model=TaskQuestionResponse, tags=["Task Runtime"])
def ask_task(task_id: str, request: TaskQuestionRequest) -> TaskQuestionResponse:
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    events = task_store.get_events(task_id)
    report = task.get("final_report") or ""
    sources = rag_store.query(request.collection, request.question, 5)
    memory_store.extract_candidates(request.question, source_ref=f"task/{task_id}/ask")
    answer = _answer_from_task_context(request.question, report, events, sources)
    return TaskQuestionResponse(
        task_id=task_id,
        question=request.question,
        answer=answer["text"],
        answer_source=answer["answer_source"],
        sources=sources,
    )


@router.get("/tasks/{task_id}/events/{event_id}", tags=["Task Runtime"])
def get_task_event_detail(task_id: str, event_id: str) -> dict[str, object]:
    if not task_store.get_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    event = next((item for item in task_store.get_events(task_id) if item.get("event_id") == event_id), None)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"event": event, "detail": _event_detail(event)}


@router.post("/tasks/{task_id}/review-action", response_model=ReviewActionResponse, tags=["Task Runtime"])
def apply_review_action(task_id: str, request: ReviewActionRequest) -> ReviewActionResponse:
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    action = request.action
    message = _review_action_message(action, request.payload)
    status = "waiting_review" if action in {"rerun_analysis", "focus_module", "save_knowledge", "learning_task"} else task["status"]
    if action == "save_knowledge":
        content = request.comment or task.get("final_report") or message
        rag_store.add_note("project-memory", f"review/{task_id}", content)
        message = "Review note saved into project-memory knowledge collection."
    task_store.record_review_action(task_id, action, request.comment)
    task_store.update_task(task_id, status)
    task_store.append_event(
        {
            "event_id": f"evt_{uuid4().hex}",
            "task_id": task_id,
            "type": "review_action",
            "node": "human_review",
            "agent": "human_reviewer",
            "status": status,
            "content": message,
            "data": {"action": action, "comment": request.comment, "payload": request.payload},
        }
    )
    return ReviewActionResponse(task_id=task_id, status=status, action=action, message=message)


@router.post("/knowledge/notes", response_model=KnowledgeNoteResponse, tags=["RAG Knowledge Agent"])
def add_knowledge_note(request: KnowledgeNoteRequest) -> KnowledgeNoteResponse:
    saved = rag_store.add_note(request.collection, request.path, request.content)
    return KnowledgeNoteResponse(**saved)


@router.post("/memories/extract", response_model=list[MemoryRecordResponse], tags=["RAG Knowledge Agent"])
def extract_memory_candidates(
    request: MemoryExtractRequest,
    x_devagent_actor: str | None = Header(default=None),
    x_devagent_role: str | None = Header(default=None),
) -> list[dict[str, object]]:
    try:
        _authorize_memory(request.scope, request.scope_id, "extract", x_devagent_actor, x_devagent_role)
        return memory_store.extract_candidates(
            request.text,
            scope=request.scope,
            scope_id=request.scope_id,
            source_type=request.source_type,
            source_ref=request.source_ref,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/memories", response_model=list[MemoryRecordResponse], tags=["RAG Knowledge Agent"])
def list_memories(
    scope: str | None = None,
    scope_id: str | None = None,
    status: str | None = None,
    x_devagent_actor: str | None = Header(default=None),
    x_devagent_role: str | None = Header(default=None),
) -> list[dict[str, object]]:
    actor, role = _memory_actor(x_devagent_actor, x_devagent_role)
    if scope in {"project", "team"}:
        _authorize_memory(scope, scope_id or "default", "list", actor, role)
    elif role != "admin":
        scope = "user"
        scope_id = actor
    return memory_store.list_memories(scope=scope, scope_id=scope_id, status=status)


@router.post("/memories/{memory_id}/confirm", response_model=MemoryRecordResponse, tags=["RAG Knowledge Agent"])
def confirm_memory(
    memory_id: str,
    request: MemoryConfirmRequest,
    x_devagent_actor: str | None = Header(default=None),
    x_devagent_role: str | None = Header(default=None),
) -> dict[str, object]:
    memory = memory_store.get_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    _authorize_memory(memory["scope"], memory["scope_id"], "confirm", x_devagent_actor, x_devagent_role)
    collection = request.collection or ("project-memory" if memory["scope"] == "project" else f"user-memory/{memory['scope_id']}")
    saved = rag_store.add_note(collection, f"memory/{memory_id}", memory["content"])
    confirmed = memory_store.confirm(memory_id, saved["path"])
    if not confirmed:
        raise HTTPException(status_code=404, detail="Memory not found")
    return confirmed


@router.post("/memories/{memory_id}/reject", response_model=MemoryRecordResponse, tags=["RAG Knowledge Agent"])
def reject_memory(
    memory_id: str,
    x_devagent_actor: str | None = Header(default=None),
    x_devagent_role: str | None = Header(default=None),
) -> dict[str, object]:
    memory = memory_store.get_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    _authorize_memory(memory["scope"], memory["scope_id"], "reject", x_devagent_actor, x_devagent_role)
    rejected = memory_store.reject(memory_id)
    if not rejected:
        raise HTTPException(status_code=404, detail="Memory not found")
    return rejected


@router.delete("/memories/{memory_id}", tags=["RAG Knowledge Agent"])
def delete_memory(
    memory_id: str,
    x_devagent_actor: str | None = Header(default=None),
    x_devagent_role: str | None = Header(default=None),
) -> dict[str, bool]:
    memory = memory_store.get_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    _authorize_memory(memory["scope"], memory["scope_id"], "delete", x_devagent_actor, x_devagent_role)
    if memory.get("rag_path"):
        collection = "project-memory" if memory["scope"] == "project" else f"user-memory/{memory['scope_id']}"
        rag_store.delete_note(collection, memory["rag_path"])
    if not memory_store.delete(memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"deleted": True}


def _memory_actor(actor: str | None, role: str | None) -> tuple[str, str]:
    return (actor or "local-user", (role or "member").lower())


def _authorize_memory(scope: str, scope_id: str, action: str, actor: str | None, role: str | None) -> None:
    actor_id, actor_role = _memory_actor(actor, role)
    if scope == "user":
        if actor_id != scope_id and actor_role != "admin":
            raise HTTPException(status_code=403, detail="User memory is isolated by actor identity.")
        return
    if scope == "project" and actor_role not in {"editor", "admin"}:
        raise HTTPException(status_code=403, detail="Project memory requires editor or admin role.")
    if scope == "team" and action in {"confirm", "reject", "delete"} and actor_role != "admin":
        raise HTTPException(status_code=403, detail="Team memory confirmation requires admin role.")
    if scope not in {"user", "project", "team"}:
        raise HTTPException(status_code=422, detail="Unknown memory scope.")


@router.post("/learning/coach/chat", response_model=LearningChatResponse, tags=["Learning Coach Agent"])
def chat_learning_coach(request: LearningChatRequest) -> LearningChatResponse:
    task = task_store.get_task(request.task_id) if request.task_id else None
    memory_store.extract_candidates(request.answer or request.question, source_ref=f"learning/{request.task_id or 'general'}/{request.turn}")
    stage = _learning_stage_context(request)
    reply = _learning_reply(request, task, stage)
    next_questions = _learning_next_questions(request, task, stage)
    return LearningChatResponse(
        reply=reply["text"],
        next_questions=next_questions["questions"],
        answer_source="llm" if reply["answer_source"] == "llm" or next_questions["answer_source"] == "llm" else "fallback",
        day=stage.get("day"),
        theme=stage.get("theme"),
    )


@router.post("/tasks/{task_id}/approve", response_model=HumanReviewResponse, tags=["Task Runtime"])
def approve_task(task_id: str, request: HumanReviewRequest) -> HumanReviewResponse:
    checkpoint = _latest_resume_checkpoint(task_id)
    if checkpoint:
        return _resume_after_human_review(task_id, checkpoint, "approved", request.comment)
    task = task_store.get_task(task_id)
    if task and task.get("status") == "waiting_review" and _is_visual_workflow_task(task_id):
        raise HTTPException(status_code=409, detail="Workflow is waiting for review but no resume checkpoint was found.")
    return _record_human_review(task_id, "approved", "completed", request.comment)


@router.post("/tasks/{task_id}/reject", response_model=HumanReviewResponse, tags=["Task Runtime"])
def reject_task(task_id: str, request: HumanReviewRequest) -> HumanReviewResponse:
    checkpoint = _latest_resume_checkpoint(task_id)
    if checkpoint and _retry_pre_run_confirmation(task_id, checkpoint, "rejected", request.comment):
        return HumanReviewResponse(task_id=task_id, status="waiting_review", action="rejected", comment=request.comment)
    return _record_human_review(task_id, "rejected", "rejected", request.comment)


@router.post("/tasks/{task_id}/revise", response_model=HumanReviewResponse, tags=["Task Runtime"])
def revise_task(task_id: str, request: HumanReviewRequest) -> HumanReviewResponse:
    checkpoint = _latest_resume_checkpoint(task_id)
    if checkpoint and _retry_pre_run_confirmation(task_id, checkpoint, "revised", request.comment):
        return HumanReviewResponse(task_id=task_id, status="waiting_review", action="revised", comment=request.comment)
    return _record_human_review(task_id, "revised", "waiting_review", request.comment)


def _resolve_task_workflow(request: TaskRunRequest) -> dict[str, object]:
    workflow_name = request.workflow_name or f"{request.execution_mode}_workflow"
    nodes = [node.model_dump() for node in request.nodes]
    edges = [edge.model_dump() for edge in request.edges]
    planned_workflow: dict[str, object] | None = None

    if request.workflow_id:
        workflow = task_store.get_workflow(request.workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        workflow_name = workflow["name"]
        nodes = workflow["nodes"]
        edges = workflow["edges"]

    if request.execution_mode == "planner":
        workflow_name = "planner_generated_workflow"
        nodes, edges = _planned_nodes_for_goal(request.goal, request.require_human_review)
        planned_workflow = {"nodes": nodes, "edges": edges}
    elif not nodes:
        nodes, edges = _default_nodes_for_mode(request.execution_mode)

    return {
        "goal": request.goal,
        "project_path": request.project_path,
        "max_files": request.max_files,
        "require_human_review": request.require_human_review,
        "workflow_id": request.workflow_id,
        "workflow_name": workflow_name,
        "input_text": request.input_text or request.goal,
        "nodes": nodes,
        "edges": edges,
        "planned_workflow": planned_workflow,
    }


def _default_nodes_for_mode(mode: str) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    if mode == "agent":
        nodes: list[dict[str, object]] = [
            {"id": "plan", "type": "planner", "name": "任务规划", "config": {}},
            {"id": "agent", "type": "agent", "name": "项目分析 Agent", "config": {"agent_type": "project_analyzer"}},
            {"id": "report", "type": "reporter", "name": "报告生成", "config": {}},
        ]
    elif mode == "tool":
        nodes = [
            {"id": "plan", "type": "planner", "name": "任务规划", "config": {}},
            {"id": "tool", "type": "mcp_tool", "name": "文件工具", "config": {"tool_name": "filesystem.list"}},
            {"id": "report", "type": "reporter", "name": "报告生成", "config": {}},
        ]
    elif mode == "knowledge":
        nodes = [
            {"id": "plan", "type": "planner", "name": "任务规划", "config": {}},
            {"id": "knowledge", "type": "rag", "name": "知识检索", "config": {"collection": "default", "top_k": 5}},
            {"id": "report", "type": "reporter", "name": "报告生成", "config": {}},
        ]
    else:
        nodes = [
            {"id": "plan", "type": "planner", "name": "任务规划", "config": {}},
            {"id": "analyze", "type": "agent", "name": "项目分析", "config": {"agent_type": "project_analyzer"}},
            {"id": "review", "type": "human_review", "name": "人工审核", "config": {}},
            {"id": "report", "type": "reporter", "name": "报告生成", "config": {}},
        ]
    edges = [
        {"source": str(nodes[index]["id"]), "target": str(nodes[index + 1]["id"])}
        for index in range(len(nodes) - 1)
    ]
    return nodes, edges


def _planned_nodes_for_goal(goal: str, require_review: bool) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    text = goal.lower()
    nodes: list[dict[str, object]] = [
        {"id": "plan", "type": "planner", "name": "Planner", "x": 64, "y": 92, "config": {}},
        {
            "id": "analyze",
            "type": "agent",
            "name": "Project Analyzer",
            "x": 292,
            "y": 92,
            "config": {"agent_type": "project_analyzer"},
        },
    ]

    if any(keyword in text for keyword in ["review", "audit", "risk", "security", "bug", "refactor", "重构", "审查", "风险", "安全"]):
        nodes.append(
            {
                "id": "code_review",
                "type": "agent",
                "name": "Code Review",
                "x": 520,
                "y": 92,
                "config": {"agent_type": "code_reviewer"},
            }
        )

    if any(keyword in text for keyword in ["rag", "knowledge", "doc", "document", "学习", "知识", "文档", "检索"]):
        nodes.append(
            {
                "id": "rag_process",
                "type": "agent",
                "name": "RAG Processor",
                "x": 748,
                "y": 92,
                "config": {"agent_type": "rag_processor"},
            }
        )

    if any(keyword in text for keyword in ["git", "file", "filesystem", "tool", "status", "文件", "工具"]):
        nodes.append(
            {
                "id": "tool",
                "type": "mcp_tool",
                "name": "Filesystem Tool",
                "x": 976,
                "y": 92,
                "config": {"tool_name": "filesystem.list"},
            }
        )

    nodes.append({"id": "supervisor", "type": "supervisor", "name": "Supervisor", "x": 1204, "y": 92, "config": {}})
    if require_review:
        nodes.append(
            {
                "id": "human_review",
                "type": "human_review",
                "name": "Human Review",
                "x": 1432,
                "y": 92,
                "config": {},
            }
        )
    nodes.append({"id": "report", "type": "reporter", "name": "Reporter", "x": 1660, "y": 92, "config": {}})

    compact_nodes = []
    for index, node in enumerate(nodes):
        item = dict(node)
        item["x"] = 64 + index * 228
        compact_nodes.append(item)
    edges = [
        {"source": str(compact_nodes[index]["id"]), "target": str(compact_nodes[index + 1]["id"])}
        for index in range(len(compact_nodes) - 1)
    ]
    return compact_nodes, edges


def _record_human_review(task_id: str, action: str, status: str, comment: str | None) -> HumanReviewResponse:
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task_store.record_review_action(task_id, action, comment)
    task_store.update_task(task_id, status)
    task_store.append_event(
        {
            "event_id": f"evt_{uuid4().hex}",
            "task_id": task_id,
            "type": "human_review",
            "node": "human_review",
            "agent": "human_reviewer",
            "status": status,
            "content": _review_content(action, comment),
            "data": {"action": action, "comment": comment},
        }
    )
    return HumanReviewResponse(task_id=task_id, status=status, action=action, comment=comment)


def _latest_resume_checkpoint(task_id: str) -> dict[str, object] | None:
    task = task_store.get_task(task_id)
    if not task or task.get("status") != "waiting_review":
        return None
    for artifact in reversed(task_store.get_artifacts(task_id)):
        content = artifact.get("content")
        if not isinstance(content, dict):
            continue
        checkpoint = content.get("resume_checkpoint")
        if isinstance(checkpoint, dict) and checkpoint.get("paused_node_id"):
            return checkpoint
        if artifact.get("artifact_type") == "workflow_checkpoint" and content.get("paused_node_id"):
            return content
    return None


def _is_visual_workflow_task(task_id: str) -> bool:
    for artifact in reversed(task_store.get_artifacts(task_id)):
        content = artifact.get("content")
        if not isinstance(content, dict):
            continue
        if content.get("workflow_name") or content.get("workflow_events") or content.get("validation"):
            return True
    return False


def _retry_pre_run_confirmation(
    task_id: str,
    checkpoint: dict[str, object],
    action: str,
    comment: str | None,
) -> bool:
    paused_node_id = str(checkpoint.get("paused_node_id") or "")
    paused_node = _checkpoint_node(checkpoint, paused_node_id)
    config = paused_node.get("config") if isinstance(paused_node.get("config"), dict) else {}
    if not config.get("confirm_before_run"):
        return False
    retry_count = int(config.get("retry_count") or 0)
    if retry_count <= 0:
        return False

    state = checkpoint.get("state") if isinstance(checkpoint.get("state"), dict) else {}
    review_retries = dict(state.get("review_retries") or {})
    used = int(review_retries.get(paused_node_id) or 0)
    if used >= retry_count:
        return False

    next_used = used + 1
    review_retries[paused_node_id] = next_used
    next_checkpoint = {
        **checkpoint,
        "state": {
            **state,
            "review_retries": review_retries,
        },
        "retry_attempt": next_used,
    }
    task_store.record_review_action(task_id, action, comment)
    task_store.update_task(task_id, "waiting_review")
    task_store.save_artifact(task_id, "workflow_checkpoint", "resume", next_checkpoint)
    task_store.append_event(
        {
            "event_id": f"evt_{uuid4().hex}",
            "task_id": task_id,
            "type": "human_review",
            "node": paused_node_id,
            "agent": "human_reviewer",
            "status": action,
            "content": _review_content(action, comment),
            "data": {
                "action": action,
                "comment": comment,
                "retry_attempt": next_used,
                "max_retries": retry_count,
            },
        }
    )
    task_store.append_event(
        {
            "event_id": f"evt_{uuid4().hex}",
            "task_id": task_id,
            "type": "workflow_node",
            "node": paused_node_id,
            "agent": str(paused_node.get("type") or "workflow"),
            "status": "retrying",
            "content": f"Pre-run confirmation rejected; retry {next_used}/{retry_count} is waiting for review.",
            "data": {
                "node_id": paused_node_id,
                "node_type": paused_node.get("type"),
                "node_name": paused_node.get("name") or paused_node_id,
                "retry_attempt": next_used,
                "max_retries": retry_count,
            },
        }
    )
    return True


def _checkpoint_node(checkpoint: dict[str, object], node_id: str) -> dict[str, object]:
    for node in checkpoint.get("nodes", []):
        if isinstance(node, dict) and node.get("id") == node_id:
            return node
    return {}


def _resume_after_human_review(
    task_id: str,
    checkpoint: dict[str, object],
    action: str,
    comment: str | None,
) -> HumanReviewResponse:
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task_store.record_review_action(task_id, action, comment)
    review_event = {
        "event_id": f"evt_{uuid4().hex}",
        "task_id": task_id,
        "type": "human_review",
        "node": str(checkpoint.get("paused_node_id") or "human_review"),
        "agent": "human_reviewer",
        "status": "approved",
        "content": _review_content(action, comment),
        "data": {"action": action, "comment": comment, "resume": True},
    }
    task_store.append_event(review_event)
    task_store.update_task(task_id, "running")
    task_store.append_event(
        {
            "event_id": f"evt_{uuid4().hex}",
            "task_id": task_id,
            "type": "task",
            "node": "workflow_resume",
            "agent": "harness_runtime",
            "status": "running",
            "content": "Workflow resume started from approved checkpoint.",
            "data": {"paused_node_id": checkpoint.get("paused_node_id")},
        }
    )

    try:
        result = resume_task_workflow(checkpoint, action, comment)
    except Exception as exc:
        task_store.update_task(task_id, "failed")
        task_store.append_event(
            {
                "event_id": f"evt_{uuid4().hex}",
                "task_id": task_id,
                "type": "error",
                "node": "workflow_resume",
                "agent": "harness_runtime",
                "status": "failed",
                "content": str(exc),
                "data": {"paused_node_id": checkpoint.get("paused_node_id")},
            }
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    public_result = result.get("result", {})
    final_report = str(result.get("final_report") or public_result.get("final_report") or "")
    next_status = "waiting_review" if public_result.get("human_review_required") and public_result.get("human_review_packet") else "completed"
    resume_events = [event for event in result.get("events", []) if event.get("task_id")]
    task_store.save_artifact(
        task_id,
        "workflow_resume",
        str(checkpoint.get("paused_node_id") or "resume"),
        {
            "task_id": task_id,
            "resumed_from": checkpoint.get("paused_node_id"),
            "action": action,
            "comment": comment,
            "status": next_status,
            "before_state": checkpoint.get("state", {}),
            "after_events": resume_events,
            "created_at": utc_now_iso(),
        },
    )
    task_store.save_artifact(task_id, "graph_result", "result", public_result)
    if public_result.get("resume_checkpoint"):
        task_store.save_artifact(task_id, "workflow_checkpoint", "resume", public_result["resume_checkpoint"])
    task_store.update_task(task_id, next_status, final_report)
    for event in resume_events:
        task_store.append_event(event)
    task_store.append_event(
        {
            "event_id": f"evt_{uuid4().hex}",
            "task_id": task_id,
            "type": "task",
            "node": "workflow_resume",
            "agent": "harness_runtime",
            "status": next_status,
            "content": "Workflow resume completed." if next_status == "completed" else "Workflow paused again for human review.",
            "data": {"paused_node_id": checkpoint.get("paused_node_id")},
        }
    )
    return HumanReviewResponse(task_id=task_id, status=next_status, action=action, comment=comment)


def _answer_from_task_context(
    question: str,
    report: str,
    events: list[dict[str, object]],
    sources: list[dict[str, object]],
) -> dict[str, str]:
    fallback = _fallback_task_answer(question, report, events, sources)
    facts = {
        "question": question,
        "report_excerpt": report[:6000],
        "events": [
            {
                "type": event.get("type"),
                "node": event.get("node"),
                "agent": event.get("agent"),
                "status": event.get("status"),
                "content": event.get("content"),
            }
            for event in events[-20:]
        ],
        "sources": sources[:5],
    }
    return llm_provider.generate_with_status(
        "你是 ValuSee 的项目追问助手。请只基于任务报告、事件和给定知识来源回答，不要编造未出现的事实。",
        (
            "请用中文 Markdown 回答用户问题，结构要清楚，并在信息不足时说明还需要哪个 Agent 输出。\n"
            f"上下文：{facts}"
        ),
        fallback,
        agent="task_qa",
        prompt_version="task_qa.v1",
    )


def _fallback_task_answer(
    question: str,
    report: str,
    events: list[dict[str, object]],
    sources: list[dict[str, object]],
) -> str:
    q = question.lower()
    lines = ["## 追问回答", ""]
    if any(keyword in q for keyword in ["风险", "risk", "问题", "安全"]):
        lines.append(_extract_section(report, "风险") or _extract_section(report, "Risk") or "当前报告没有明确风险段落。")
    elif any(keyword in q for keyword in ["学习", "先看", "路线", "理解"]):
        lines.append("建议先从项目入口、路由/API、核心服务、数据层、测试或配置文件依次阅读。")
        lines.append("")
        lines.append(_extract_section(report, "建议") or _extract_section(report, "Suggestions") or "")
    elif any(keyword in q for keyword in ["模块", "结构", "架构"]):
        lines.append(_extract_section(report, "项目") or _extract_section(report, "Agent Outputs") or "可以从时间线中的 Project Analyzer 节点查看结构摘要。")
    else:
        first_event = next((event for event in events if event.get("content")), None)
        lines.append("我会基于当前任务报告、执行事件和项目知识库回答。")
        if first_event:
            lines.append(f"- 任务过程线索：{first_event.get('content')}")
        if report:
            lines.append(f"- 报告摘要：{report.replace(chr(10), ' ')[:260]}")
    if sources:
        lines.extend(["", "## 知识库来源"])
        for source in sources[:3]:
            lines.append(f"- `{source.get('path')}` / {source.get('chunk_id')}: {str(source.get('content', ''))[:160]}")
    return "\n".join(line for line in lines if line is not None)


def _extract_section(report: str, keyword: str) -> str:
    if not report:
        return ""
    lines = report.splitlines()
    for index, line in enumerate(lines):
        if keyword.lower() in line.lower():
            section = []
            for item in lines[index : index + 8]:
                if section and item.startswith("## "):
                    break
                section.append(item)
            return "\n".join(section)
    return ""


def _event_detail(event: dict[str, object]) -> dict[str, object]:
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    return {
        "node": event.get("node"),
        "agent": event.get("agent"),
        "status": event.get("status"),
        "summary": event.get("content"),
        "node_name": data.get("node_name") if isinstance(data, dict) else None,
        "output": data.get("output") if isinstance(data, dict) else None,
        "hint": "可以基于这个节点输出继续追问、要求重新分析某个模块，或保存为项目知识。",
    }


def _review_action_message(action: str, payload: dict[str, object]) -> str:
    labels = {
        "rerun_analysis": "Requested a deeper re-analysis checkpoint.",
        "focus_module": f"Requested focused analysis for module: {payload.get('module', 'unspecified')}.",
        "save_knowledge": "Requested saving this review into project memory.",
        "learning_task": "Requested generating a follow-up learning task.",
        "lower_risk": "Reviewer lowered risk level after manual judgment.",
    }
    return labels.get(action, f"Recorded review action: {action}.")


def _learning_stage_context(request: LearningChatRequest) -> dict[str, object]:
    if request.day or request.theme:
        return {"day": request.day, "theme": request.theme}
    if not request.task_id:
        return {}
    plans = task_store.list_learning_plans(request.task_id)
    active_plan = next((plan for plan in plans if plan.get("status") == "active"), plans[0] if plans else None)
    if not active_plan:
        return {}
    steps = active_plan.get("plan") or []
    if not steps:
        return {"plan_id": active_plan.get("plan_id"), "topic": active_plan.get("topic")}
    index = min(max(request.turn, 0), len(steps) - 1)
    step = steps[index] if isinstance(steps[index], dict) else {}
    return {
        "plan_id": active_plan.get("plan_id"),
        "topic": active_plan.get("topic"),
        "day": step.get("day"),
        "theme": step.get("theme"),
        "tasks": step.get("tasks", []),
        "output": step.get("output"),
    }


def _learning_reply(request: LearningChatRequest, task: dict[str, object] | None, stage: dict[str, object]) -> dict[str, str]:
    fallback = _fallback_learning_reply(request, task)
    if stage.get("day") or stage.get("theme"):
        fallback = f"Current learning stage: Day {stage.get('day') or '-'} / {stage.get('theme') or 'untitled'}\n\n{fallback}"
    task_context = {"task": task, "learning_stage": stage}
    request = request.model_copy(update={"question": f"{request.question}\nTask context: {task_context}"})
    return llm_provider.generate_with_status(
        "你是 ValuSee 的学习陪练 Agent。请根据用户回答进行启发式追问、纠错和学习路径引导。",
        (
            "请输出中文，语气像教练，不要直接给长篇标准答案。"
            "先反馈用户回答，再给一个下一步挑战。\n"
            f"主题：{request.topic}\n"
            f"水平：{request.level}\n"
            f"轮次：{request.turn}\n"
            f"任务：{task}\n"
            f"问题：{request.question}\n"
            f"用户回答：{request.answer}"
        ),
        fallback,
        agent="learning_coach",
        prompt_version="learning_coach.reply.v1",
    )


def _fallback_learning_reply(request: LearningChatRequest, task: dict[str, object] | None) -> str:
    answer = (request.answer or "").strip()
    topic = request.topic or "当前项目"
    task_goal = str(task.get("goal")) if task else ""
    if not answer:
        base = f"我们先围绕 `{topic}` 做一次项目陪练。"
        if task:
            base += f" 当前任务是：{task_goal}。"
        return base + " 请先说说你对项目入口、核心模块和你最困惑的点，我会根据你的回答继续追问。"

    lower = answer.lower()
    feedback_parts: list[str] = []
    if len(answer) < 30:
        feedback_parts.append("你的回答还比较短，可以继续补充入口文件、核心模块、数据流和不理解的点。")
    if any(word in lower for word in ["api", "route", "fastapi", "接口", "路由"]):
        feedback_parts.append("你已经注意到接口层，下一步可以把 API 请求如何进入 Agent/Workflow 运行链路说清楚。")
    if any(word in lower for word in ["graph", "langgraph", "workflow", "节点", "图"]):
        feedback_parts.append("你抓到了图和工作流，这是理解本项目的关键。建议继续区分固定协作图和可视化画布图。")
    if any(word in lower for word in ["harness", "runtime", "任务", "事件", "历史"]):
        feedback_parts.append("你提到了 Harness/任务运行层，这说明你开始理解项目的治理价值，而不只是代码审查。")
    if any(word in lower for word in ["rag", "知识", "检索", "切片"]):
        feedback_parts.append("你注意到了知识沉淀部分。下一步可以说明 RAG 加工和项目记忆库分别解决什么问题。")
    if any(word in lower for word in ["风险", "审查", "review", "安全", "质量"]):
        feedback_parts.append("你把风险审查纳入理解范围了。建议继续说明风险如何触发人工审核或后续治理动作。")
    if not feedback_parts:
        feedback_parts.append("你的回答给出了方向，但还没有点出项目里的关键机制。建议围绕 API、Graph、Harness、RAG、人工审核选两个展开。")

    challenge = _learning_challenge(answer, task_goal, topic, request.turn)
    return "\n".join(feedback_parts) + f"\n\n下一步挑战：{challenge}"


def _learning_next_questions(request: LearningChatRequest, task: dict[str, object] | None, stage: dict[str, object]) -> dict[str, object]:
    fallback_questions = _fallback_learning_next_questions(request, task)
    task_context = {"task": task, "learning_stage": stage}
    request = request.model_copy(update={"answer": f"{request.answer}\nTask context: {task_context}"})
    result = llm_provider.generate_with_status(
        "你是 ValuSee 的学习陪练 Agent。请基于当前项目任务和用户回答，生成 3 个递进式追问。",
        (
            "只输出 3 行，每行一个问题，不要编号，不要解释。\n"
            f"主题：{request.topic}\n任务：{task}\n用户回答：{request.answer}\n轮次：{request.turn}"
        ),
        "\n".join(fallback_questions),
        agent="learning_coach",
        prompt_version="learning_coach.questions.v1",
    )
    generated_questions = [line.strip("- 0123456789.、").strip() for line in result["text"].splitlines() if line.strip()]
    return {"questions": generated_questions[:3] or fallback_questions, "answer_source": result["answer_source"]}
    questions = [line.strip("- 0123456789.、").strip() for line in text.splitlines() if line.strip()]
    return questions[:3] or fallback_questions


def _fallback_learning_next_questions(request: LearningChatRequest, task: dict[str, object] | None) -> list[str]:
    answer = (request.answer or "").lower()
    topic = request.topic or "当前项目"
    if any(word in answer for word in ["api", "route", "fastapi", "接口", "路由"]):
        if request.turn % 2 == 1:
            return [
                "请指出前端请求体里最关键的 3 个字段，并说明它们如何影响后端执行路径。",
                "如果用户选择 Collab 模式，为什么不应该继续发送画布节点？",
                "你会如何验证一个任务是否真的进入了 HarnessRuntime？",
            ]
        return [
            "从前端点击运行到 FastAPI 路由，中间传了哪些关键字段？",
            "哪个接口负责普通 Workflow，哪个接口负责 Collab？",
            "如果接口失败，事件和任务状态会怎么记录？",
        ]
    if any(word in answer for word in ["graph", "workflow", "langgraph", "节点", "图"]):
        if request.turn % 2 == 1:
            return [
                "请用 state 的角度解释节点之间如何传递信息。",
                "为什么 Workflow 模式和 Planner 模式都能产生图，但来源不同？",
                "如果一个节点失败，时间线应该展示哪些信息才方便用户判断？",
            ]
        return [
            "固定 collaboration_graph 和可视化 Workflow 图有什么区别？",
            "节点之间是直接互相调用，还是通过 state 传递信息？",
            "Planner 模式生成的 Workflow 应该如何被用户确认？",
        ]
    if any(word in answer for word in ["rag", "知识", "检索", "切片"]):
        if request.turn % 2 == 1:
            return [
                "哪些内容适合手动保存为项目知识，而不是自动切片？",
                "如果知识库没有命中，用户下一步应该怎么补充上下文？",
                "项目知识库如何帮助新用户持续理解同一个项目？",
            ]
        return [
            "RAG Processor 和 Knowledge Query 的职责有什么不同？",
            "什么内容适合保存到 project-memory？",
            "回答项目问题时，为什么需要展示知识来源？",
        ]
    if any(word in answer for word in ["harness", "runtime", "事件", "历史", "任务"]):
        if request.turn % 2 == 1:
            return [
                "请区分 graph state、task status 和 SQLite 历史记录。",
                "为什么事件回放比只保存最终报告更适合研发治理？",
                "你会把哪些人工审核动作设计成必须留痕？",
            ]
        return [
            "HarnessRuntime 相比直接 graph.invoke 多解决了什么产品问题？",
            "事件回放对项目治理有什么价值？",
            "人工审核状态为什么应该进入任务生命周期？",
        ]
    seed = (sum(ord(ch) for ch in (request.answer or topic)) + request.turn) % 3
    pools = [
        [f"你能用自己的话解释 {topic} 的核心流程吗？", "这个项目最值得先读的 3 个文件是什么？", "你现在最不确定的是哪个模块？"],
        ["项目分析、代码审查、知识加工分别产出什么？", "如果你是新同学，会从哪个页面开始使用？", "这个平台和普通代码审查工具有什么差别？"],
        ["请说出一个你会保存到项目知识库的结论。", "你会在哪个节点加入人工审核？为什么？", "你希望下一步看结构、风险还是学习路线？"],
    ]
    return pools[seed]


def _learning_challenge(answer: str, task_goal: str, topic: str, turn: int) -> str:
    seed = (sum(ord(ch) for ch in answer) + len(task_goal) + len(topic) + turn) % 5
    challenges = [
        f"用 3 句话说明 `{topic}` 的入口、核心流程和最终产物。",
        "画一条从用户点击运行到最终报告生成的数据流，并标出 HarnessRuntime 的位置。",
        "选一个你提到的模块，说明它的输入、输出和风险点。",
        "把你的理解整理成一条可保存到 project-memory 的知识笔记。",
        "提出一个你还不确定的问题，然后说明你会从哪个 Agent 输出里寻找答案。",
    ]
    return challenges[seed]


def _review_content(action: str, comment: str | None) -> str:
    labels = {
        "approved": "人工审核已通过",
        "rejected": "人工审核已拒绝",
        "revised": "人工审核要求修改",
    }
    suffix = f"：{comment}" if comment else ""
    return f"{labels[action]}{suffix}"
