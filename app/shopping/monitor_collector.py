from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.shopping.public_pages import fetch_public_product, platform_for_url
from app.shopping.store import ShoppingStore, shopping_store

FREQUENCY_HOURS = {"realtime": 6, "daily": 24, "weekly": 24 * 7}


def collect_public_monitor_updates(
    store: ShoppingStore = shopping_store,
    *,
    fetcher: Callable[[str], dict[str, Any]] = fetch_public_product,
    now: datetime | None = None,
    max_checks: int | None = None,
) -> dict[str, int]:
    current_time = now or datetime.now(UTC)
    check_limit = (
        max_checks if max_checks is not None else int(os.getenv("VALUSee_MONITOR_BATCH_SIZE", "5"))
    )
    check_limit = min(20, max(1, check_limit))
    counts = {
        "public_checked": 0,
        "public_failed": 0,
        "pending_confirmations": 0,
        "recapture_reminders": 0,
    }
    for monitor in store.list_monitors():
        if monitor["status"] != "watching":
            continue
        url = str(monitor["product"].get("url") or "")
        if not platform_for_url(url) or not _poll_due(
            store.get_monitor_poll(monitor["monitor_id"]),
            monitor.get("frequency", "daily"),
            current_time,
        ):
            continue
        if counts["public_checked"] >= check_limit:
            break
        counts["public_checked"] += 1
        try:
            result = fetcher(url)
        except Exception as exc:  # noqa: BLE001 - isolate each external page/provider failure
            counts["public_failed"] += 1
            result = {
                "fetch_status": "unavailable",
                "price": 0,
                "notes": f"collector error: {type(exc).__name__}",
            }
        status = str(result.get("fetch_status") or "unavailable")
        price = float(result.get("price") or 0)
        store.record_monitor_poll(
            monitor["monitor_id"],
            checked_at=current_time.isoformat(),
            status=status,
            observed_price=price,
            message=str(result.get("notes") or status),
        )
        if status in {"blocked", "unavailable"} or price <= 0:
            created = store.create_notification(
                user_id=monitor["user_id"],
                kind="recapture_required",
                title=f"{monitor['product'].get('title', '关注商品')} 需要重新采集",
                message="公开页面未返回可确认价格。请打开商品页，用 ValuSee 扩展重新读取当前 SKU、地区和会员优惠。",
                idempotency_key=f"recapture:{monitor['monitor_id']}:{current_time.date().isoformat()}",
            )
            counts["recapture_reminders"] += 1 if created else 0
            continue
        current_price = float(monitor.get("current_final_price") or 0)
        if current_price > 0 and abs(price - current_price) < 0.01:
            continue
        candidate = {
            **monitor["product"],
            **{
                key: value
                for key, value in result.items()
                if key not in {"fetch_status", "cached", "fetch_error"}
            },
            "observation_status": "requires_confirmation",
            "evidence": {
                **(result.get("evidence") if isinstance(result.get("evidence"), dict) else {}),
                "monitor_id": monitor["monitor_id"],
                "public_poll_at": current_time.isoformat(),
            },
            "notes": "后台公开页低频检查发现价格变化；请使用扩展确认当前 SKU、地区、会员条件和实际到手价。",
        }
        store.create_extension_capture(
            user_id=monitor["user_id"],
            product=candidate,
            source="public_monitor_refresh",
            captured_at=current_time.isoformat(),
        )
        hint = "可能已达到目标价" if price <= float(monitor["target_price"]) else "公开价格发生变化"
        store.create_notification(
            user_id=monitor["user_id"],
            kind="price_confirmation_required",
            title=f"{monitor['product'].get('title', '关注商品')} {hint}",
            message=f"公开页面显示 ¥{price:.2f}，但尚未核对登录状态、SKU 和优惠资格。请打开扩展确认后再决定。",
            idempotency_key=f"public-price:{monitor['monitor_id']}:{current_time.date().isoformat()}:{price:.2f}",
        )
        counts["pending_confirmations"] += 1
    return counts


def _poll_due(last_poll: dict[str, Any] | None, frequency: str, now: datetime) -> bool:
    if not last_poll:
        return True
    try:
        checked_at = datetime.fromisoformat(str(last_poll["checked_at"]))
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=UTC)
    except (KeyError, ValueError):
        return True
    return (now - checked_at).total_seconds() >= FREQUENCY_HOURS.get(frequency, 24) * 3600
