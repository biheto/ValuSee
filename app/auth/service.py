from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from app.harness.events import utc_now_iso
from app.core.database import connect_database, is_integrity_error
from app.core.object_storage import delete_stored_object
from app.core.paths import resolve_runtime_path


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class AuthStore:
    def __init__(self, db_path: str | Path = "data/valuesee.db"):
        self.db_path = resolve_runtime_path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _session(self) -> Iterator[Any]:
        conn = connect_database(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._session() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS valuesee_user(
                user_id TEXT PRIMARY KEY,email TEXT NOT NULL UNIQUE,password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS valuesee_family(
                family_id TEXT PRIMARY KEY,name TEXT NOT NULL,owner_id TEXT NOT NULL,created_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS valuesee_family_member(
                family_id TEXT NOT NULL,user_id TEXT NOT NULL,role TEXT NOT NULL,created_at TEXT NOT NULL,
                PRIMARY KEY(family_id,user_id)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS valuesee_family_invitation(
                invitation_id TEXT PRIMARY KEY,family_id TEXT NOT NULL,inviter_id TEXT NOT NULL,email TEXT NOT NULL,
                role TEXT NOT NULL,status TEXT NOT NULL,expires_at TEXT NOT NULL,created_at TEXT NOT NULL,responded_at TEXT
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS valuesee_family_asset(
                asset_id TEXT PRIMARY KEY,family_id TEXT NOT NULL,name TEXT NOT NULL,category TEXT NOT NULL,
                brand TEXT,model TEXT,purchased_at TEXT,warranty_deadline TEXT,notes TEXT,created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS valuesee_family_budget(
                family_id TEXT PRIMARY KEY,monthly_budget REAL NOT NULL,annual_budget REAL NOT NULL,currency TEXT NOT NULL,
                updated_by TEXT NOT NULL,updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS valuesee_auth_token(
                token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,purpose TEXT NOT NULL,
                expires_at TEXT NOT NULL,used_at TEXT,created_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS valuesee_email_code(
                email TEXT NOT NULL,purpose TEXT NOT NULL,code_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,attempts INTEGER NOT NULL,created_at TEXT NOT NULL,
                last_sent_at TEXT NOT NULL,PRIMARY KEY(email,purpose)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS valuesee_session(
                session_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,token_hash TEXT NOT NULL UNIQUE,
                device_name TEXT NOT NULL,ip_address TEXT,status TEXT NOT NULL,created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,expires_at TEXT NOT NULL,revoked_at TEXT
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS valuesee_subscription(
                user_id TEXT PRIMARY KEY,plan_code TEXT NOT NULL,status TEXT NOT NULL,
                current_period_end TEXT,provider TEXT,external_reference TEXT,updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS valuesee_upgrade_request(
                request_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,plan_code TEXT NOT NULL,
                status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS valuesee_billing_order(
                order_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,plan_code TEXT NOT NULL,billing_cycle TEXT NOT NULL,
                amount REAL NOT NULL,currency TEXT NOT NULL,status TEXT NOT NULL,payment_provider TEXT,
                external_reference TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_billing_order_owner ON valuesee_billing_order(user_id,created_at)")
            conn.execute("""CREATE TABLE IF NOT EXISTS valuesee_admin_mfa(
                user_id TEXT PRIMARY KEY,encrypted_secret TEXT NOT NULL,enabled INTEGER NOT NULL,
                recovery_codes_json TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS valuesee_user_profile(
                user_id TEXT PRIMARY KEY,bio TEXT NOT NULL,locale TEXT NOT NULL,currency TEXT NOT NULL,
                avatar_backend TEXT,avatar_key TEXT,avatar_content_type TEXT,avatar_sha256 TEXT,updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS valuesee_user_audit(
                audit_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,action TEXT NOT NULL,metadata_json TEXT NOT NULL,created_at TEXT NOT NULL
            )""")
            if conn.backend == "postgresql":
                conn.execute("ALTER TABLE valuesee_user ADD COLUMN IF NOT EXISTS email_verified INTEGER NOT NULL DEFAULT 0")
                conn.execute("ALTER TABLE valuesee_session ADD COLUMN IF NOT EXISTS mfa_verified INTEGER NOT NULL DEFAULT 0")
            else:
                columns = [row["name"] for row in conn.execute("PRAGMA table_info(valuesee_user)").fetchall()]
                if "email_verified" not in columns:
                    conn.execute("ALTER TABLE valuesee_user ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")
                session_columns = [row["name"] for row in conn.execute("PRAGMA table_info(valuesee_session)").fetchall()]
                if "mfa_verified" not in session_columns:
                    conn.execute("ALTER TABLE valuesee_session ADD COLUMN mfa_verified INTEGER NOT NULL DEFAULT 0")

    def register(
        self,
        email: str,
        password: str,
        display_name: str,
        *,
        email_verified: bool = False,
    ) -> dict[str, Any]:
        normalized = email.strip().lower()
        if "@" not in normalized or len(normalized) > 254:
            raise ValueError("请输入有效邮箱")
        if len(password) < 8:
            raise ValueError("密码至少需要 8 个字符")
        user_id, now = f"usr_{uuid4().hex}", utc_now_iso()
        with self._session() as conn:
            try:
                conn.execute(
                    "INSERT INTO valuesee_user(user_id,email,password_hash,display_name,status,created_at,email_verified) VALUES(?,?,?,?,?,?,?)",
                    (
                        user_id,
                        normalized,
                        hash_password(password),
                        display_name.strip() or normalized.split("@")[0],
                        "active",
                        now,
                        1 if email_verified else 0,
                    ),
                )
            except Exception as exc:
                if is_integrity_error(exc):
                    raise ValueError("该邮箱已注册") from exc
                raise
        return self.get_user(user_id) or {}

    def authenticate(self, email: str, password: str) -> dict[str, Any] | None:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM valuesee_user WHERE email = ? AND status = 'active'", (email.strip().lower(),)).fetchone()
        if not row or not verify_password(password, row["password_hash"]):
            return None
        return _public_user(row)

    def verify_user_password(self, user_id: str, password: str) -> bool:
        if not password:
            return False
        with self._session() as conn:
            row = conn.execute(
                "SELECT password_hash FROM valuesee_user WHERE user_id=? AND status='active'",
                (user_id,),
            ).fetchone()
        return bool(row and verify_password(password, str(row["password_hash"])))

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM valuesee_user WHERE user_id = ?", (user_id,)).fetchone()
        return _public_user(row) if row else None

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM valuesee_user WHERE email=? AND status='active'", (email.strip().lower(),)).fetchone()
        return _public_user(row) if row else None

    def issue_email_code(
        self,
        email: str,
        purpose: str,
        *,
        ttl_minutes: int = 10,
        cooldown_seconds: int = 60,
    ) -> str:
        normalized = email.strip().lower()
        if "@" not in normalized or len(normalized) > 254:
            raise ValueError("请输入有效邮箱")
        now = datetime.now(timezone.utc)
        with self._session() as conn:
            previous = conn.execute(
                "SELECT last_sent_at FROM valuesee_email_code WHERE email=? AND purpose=?",
                (normalized, purpose),
            ).fetchone()
            if previous and (now - _parse_utc(previous["last_sent_at"])).total_seconds() < cooldown_seconds:
                raise ValueError("验证码发送过于频繁，请稍后再试")
            code = f"{secrets.randbelow(1_000_000):06d}"
            expires_at = (now + timedelta(minutes=max(5, min(ttl_minutes, 30)))).replace(
                microsecond=0
            ).isoformat().replace("+00:00", "Z")
            sent_at = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            conn.execute(
                """INSERT INTO valuesee_email_code(
                    email,purpose,code_hash,expires_at,attempts,created_at,last_sent_at
                ) VALUES(?,?,?,?,?,?,?) ON CONFLICT(email,purpose) DO UPDATE SET
                    code_hash=excluded.code_hash,expires_at=excluded.expires_at,
                    attempts=0,created_at=excluded.created_at,last_sent_at=excluded.last_sent_at""",
                (
                    normalized,
                    purpose,
                    _email_code_hash(normalized, purpose, code),
                    expires_at,
                    0,
                    sent_at,
                    sent_at,
                ),
            )
        return code

    def consume_email_code(self, email: str, purpose: str, code: str) -> bool:
        normalized = email.strip().lower()
        supplied = code.strip()
        now = datetime.now(timezone.utc)
        with self._session() as conn:
            row = conn.execute(
                "SELECT code_hash,expires_at,attempts FROM valuesee_email_code WHERE email=? AND purpose=?",
                (normalized, purpose),
            ).fetchone()
            if not row or int(row["attempts"]) >= 5 or _parse_utc(row["expires_at"]) < now:
                return False
            expected = _email_code_hash(normalized, purpose, supplied)
            if not hmac.compare_digest(str(row["code_hash"]), expected):
                conn.execute(
                    "UPDATE valuesee_email_code SET attempts=attempts+1 WHERE email=? AND purpose=?",
                    (normalized, purpose),
                )
                return False
            conn.execute(
                "DELETE FROM valuesee_email_code WHERE email=? AND purpose=?",
                (normalized, purpose),
            )
        return True

    def delete_email_code(self, email: str, purpose: str) -> None:
        with self._session() as conn:
            conn.execute(
                "DELETE FROM valuesee_email_code WHERE email=? AND purpose=?",
                (email.strip().lower(), purpose),
            )

    def account_profile(self, user_id: str) -> dict[str, Any]:
        user = self.get_user(user_id)
        if not user:
            raise ValueError("user not found")
        with self._session() as conn:
            row = conn.execute("SELECT * FROM valuesee_user_profile WHERE user_id=?", (user_id,)).fetchone()
        profile = dict(row) if row else {"user_id": user_id, "bio": "", "locale": "zh-CN", "currency": "CNY", "avatar_backend": None, "avatar_key": None, "avatar_content_type": None, "avatar_sha256": None, "updated_at": None}
        profile["display_name"] = user["display_name"]
        profile["email"] = user["email"]
        profile["email_verified"] = user["email_verified"]
        profile["avatar_url"] = "/api/v1/auth/profile/avatar" if profile["avatar_key"] else None
        for key in ("avatar_backend", "avatar_key", "avatar_sha256"):
            profile.pop(key, None)
        return profile

    def update_account_profile(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        display_name = str(payload.get("display_name") or "").strip()[:60]
        bio = str(payload.get("bio") or "").strip()[:300]
        locale = str(payload.get("locale") or "zh-CN")
        currency = str(payload.get("currency") or "CNY").upper()
        if not display_name or locale not in {"zh-CN", "en-US"} or currency not in {"CNY", "USD", "EUR", "JPY"}:
            raise ValueError("invalid account profile")
        now = utc_now_iso()
        with self._session() as conn:
            if not conn.execute("SELECT 1 FROM valuesee_user WHERE user_id=?", (user_id,)).fetchone():
                raise ValueError("user not found")
            conn.execute("UPDATE valuesee_user SET display_name=? WHERE user_id=?", (display_name, user_id))
            old = conn.execute("SELECT avatar_backend,avatar_key,avatar_content_type,avatar_sha256 FROM valuesee_user_profile WHERE user_id=?", (user_id,)).fetchone()
            avatar = tuple(old[key] for key in ("avatar_backend", "avatar_key", "avatar_content_type", "avatar_sha256")) if old else (None, None, None, None)
            conn.execute("INSERT INTO valuesee_user_profile(user_id,bio,locale,currency,avatar_backend,avatar_key,avatar_content_type,avatar_sha256,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET bio=excluded.bio,locale=excluded.locale,currency=excluded.currency,updated_at=excluded.updated_at", (user_id, bio, locale, currency, *avatar, now))
        self.record_user_audit(user_id, "profile.updated", {"locale": locale, "currency": currency})
        return self.account_profile(user_id)

    def set_account_avatar(self, user_id: str, metadata: dict[str, str]) -> dict[str, Any]:
        now = utc_now_iso()
        with self._session() as conn:
            old = conn.execute("SELECT avatar_backend,avatar_key FROM valuesee_user_profile WHERE user_id=?", (user_id,)).fetchone()
            profile = conn.execute("SELECT bio,locale,currency FROM valuesee_user_profile WHERE user_id=?", (user_id,)).fetchone()
            base = (profile["bio"], profile["locale"], profile["currency"]) if profile else ("", "zh-CN", "CNY")
            conn.execute("INSERT INTO valuesee_user_profile(user_id,bio,locale,currency,avatar_backend,avatar_key,avatar_content_type,avatar_sha256,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET avatar_backend=excluded.avatar_backend,avatar_key=excluded.avatar_key,avatar_content_type=excluded.avatar_content_type,avatar_sha256=excluded.avatar_sha256,updated_at=excluded.updated_at", (user_id, *base, metadata["backend"], metadata["key"], metadata["content_type"], metadata["sha256"], now))
        self.record_user_audit(user_id, "avatar.updated", {"content_type": metadata["content_type"]})
        return {"old_backend": old["avatar_backend"] if old else None, "old_key": old["avatar_key"] if old else None, **self.account_profile(user_id)}

    def account_avatar(self, user_id: str) -> dict[str, Any] | None:
        with self._session() as conn:
            row = conn.execute("SELECT avatar_backend,avatar_key,avatar_content_type FROM valuesee_user_profile WHERE user_id=? AND avatar_key IS NOT NULL", (user_id,)).fetchone()
        return dict(row) if row else None

    def account_bindings(self, user_id: str) -> list[dict[str, Any]]:
        user = self.get_user(user_id)
        return [{"provider": "email", "account_hint": user["email"] if user else "", "status": "verified" if user and user["email_verified"] else "pending"}]

    def record_user_audit(self, user_id: str, action: str, metadata: dict[str, Any] | None = None) -> None:
        with self._session() as conn:
            conn.execute("INSERT INTO valuesee_user_audit(audit_id,user_id,action,metadata_json,created_at) VALUES(?,?,?,?,?)", (f"uaudit_{uuid4().hex}", user_id, action, json.dumps(metadata or {}, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))

    def list_user_audits(self, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute("SELECT audit_id,action,metadata_json,created_at FROM valuesee_user_audit WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, max(1, min(limit, 200)))).fetchall()
        return [{**dict(row), "metadata": json.loads(row["metadata_json"])} for row in rows]

    def list_users(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute("SELECT user_id,email,display_name,status,email_verified,created_at FROM valuesee_user ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 1000)),)).fetchall()
        return [{**dict(row), "email_verified": bool(row["email_verified"])} for row in rows]

    def update_user_status(self, user_id: str, status: str) -> dict[str, Any] | None:
        if status not in {"active", "suspended"}:
            raise ValueError("invalid user status")
        with self._session() as conn:
            if not conn.execute("SELECT 1 FROM valuesee_user WHERE user_id=?", (user_id,)).fetchone():
                return None
            conn.execute("UPDATE valuesee_user SET status=? WHERE user_id=?", (status, user_id))
            if status == "suspended":
                conn.execute("UPDATE valuesee_session SET status='revoked',revoked_at=? WHERE user_id=? AND status='active'", (utc_now_iso(), user_id))
        return self.get_user(user_id)

    def list_upgrade_requests(self) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute("SELECT r.*,u.email,u.display_name FROM valuesee_upgrade_request r JOIN valuesee_user u ON u.user_id=r.user_id ORDER BY r.updated_at DESC LIMIT 500").fetchall()
        return [dict(row) for row in rows]

    def update_upgrade_request(self, request_id: str, status: str) -> dict[str, Any] | None:
        if status not in {"pending", "contacted", "rejected"}:
            raise ValueError("invalid upgrade request status")
        with self._session() as conn:
            conn.execute("UPDATE valuesee_upgrade_request SET status=?,updated_at=? WHERE request_id=?", (status, utc_now_iso(), request_id))
            row = conn.execute("SELECT * FROM valuesee_upgrade_request WHERE request_id=?", (request_id,)).fetchone()
        return dict(row) if row else None

    def create_action_token(self, user_id: str, purpose: str, ttl_minutes: int = 30) -> str:
        raw = secrets.token_urlsafe(32)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        now = datetime.now(timezone.utc)
        expires = now + timedelta(minutes=max(5, min(ttl_minutes, 1440)))
        with self._session() as conn:
            conn.execute("DELETE FROM valuesee_auth_token WHERE user_id=? AND purpose=? AND used_at IS NULL", (user_id, purpose))
            conn.execute(
                "INSERT INTO valuesee_auth_token(token_hash,user_id,purpose,expires_at,used_at,created_at) VALUES(?,?,?,?,?,?)",
                (digest, user_id, purpose, expires.replace(microsecond=0).isoformat().replace("+00:00", "Z"), None, utc_now_iso()),
            )
        return raw

    def consume_action_token(self, raw: str, purpose: str) -> str | None:
        digest = hashlib.sha256(raw.encode()).hexdigest()
        now = datetime.now(timezone.utc)
        with self._session() as conn:
            row = conn.execute("SELECT * FROM valuesee_auth_token WHERE token_hash=? AND purpose=? AND used_at IS NULL", (digest, purpose)).fetchone()
            if not row or _parse_utc(row["expires_at"]) < now:
                return None
            conn.execute("UPDATE valuesee_auth_token SET used_at=? WHERE token_hash=?", (utc_now_iso(), digest))
            return str(row["user_id"])

    def verify_email(self, raw: str) -> dict[str, Any] | None:
        user_id = self.consume_action_token(raw, "verify_email")
        if not user_id:
            return None
        with self._session() as conn:
            conn.execute("UPDATE valuesee_user SET email_verified=1 WHERE user_id=?", (user_id,))
        return self.get_user(user_id)

    def reset_password(self, raw: str, password: str) -> bool:
        if len(password) < 8:
            raise ValueError("密码至少需要 8 个字符")
        user_id = self.consume_action_token(raw, "reset_password")
        if not user_id:
            return False
        with self._session() as conn:
            conn.execute("UPDATE valuesee_user SET password_hash=? WHERE user_id=?", (hash_password(password), user_id))
            conn.execute("UPDATE valuesee_session SET status='revoked',revoked_at=? WHERE user_id=? AND status='active'", (utc_now_iso(), user_id))
        return True

    def create_session(self, user_id: str, device_name: str = "浏览器", ip_address: str | None = None, expires_seconds: int = 86_400, mfa_verified: bool = False) -> str:
        session_id = f"ses_{uuid4().hex}"
        token = issue_token(user_id, expires_seconds=expires_seconds, session_id=session_id)
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(seconds=expires_seconds)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        with self._session() as conn:
            conn.execute(
                "INSERT INTO valuesee_session(session_id,user_id,token_hash,device_name,ip_address,status,created_at,last_seen_at,expires_at,revoked_at,mfa_verified) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (session_id, user_id, hashlib.sha256(token.encode()).hexdigest(), device_name.strip()[:160] or "浏览器", ip_address, "active", utc_now_iso(), utc_now_iso(), expires_at, None, 1 if mfa_verified else 0),
            )
        return token

    def admin_mfa_status(self, user_id: str) -> dict[str, Any]:
        with self._session() as conn:
            row = conn.execute("SELECT enabled,created_at,updated_at FROM valuesee_admin_mfa WHERE user_id=?", (user_id,)).fetchone()
        return {"configured": bool(row), "enabled": bool(row["enabled"]) if row else False, "created_at": row["created_at"] if row else None, "updated_at": row["updated_at"] if row else None}

    def setup_admin_mfa(self, user_id: str, email: str) -> dict[str, Any]:
        secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
        recovery_codes = [f"{secrets.token_hex(4)}-{secrets.token_hex(4)}" for _ in range(8)]
        hashes = [_recovery_hash(code) for code in recovery_codes]
        now = utc_now_iso()
        with self._session() as conn:
            conn.execute("INSERT INTO valuesee_admin_mfa(user_id,encrypted_secret,enabled,recovery_codes_json,created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET encrypted_secret=excluded.encrypted_secret,enabled=0,recovery_codes_json=excluded.recovery_codes_json,updated_at=excluded.updated_at", (user_id, _encrypt_mfa_secret(secret), 0, json.dumps(hashes), now, now))
        issuer = "ValuSee"
        label = f"{issuer}:{email}"
        return {"secret": secret, "otpauth_uri": f"otpauth://totp/{label}?secret={secret}&issuer={issuer}&digits=6&period=30", "recovery_codes": recovery_codes, "enabled": False}

    def confirm_admin_mfa(self, user_id: str, code: str) -> bool:
        if not self._verify_admin_mfa(user_id, code, allow_recovery=False):
            return False
        with self._session() as conn:
            conn.execute("UPDATE valuesee_admin_mfa SET enabled=1,updated_at=? WHERE user_id=?", (utc_now_iso(), user_id))
            conn.execute("UPDATE valuesee_session SET status='revoked',revoked_at=? WHERE user_id=? AND status='active'", (utc_now_iso(), user_id))
        return True

    def verify_admin_mfa(self, user_id: str, code: str) -> bool:
        status = self.admin_mfa_status(user_id)
        return not status["enabled"] or self._verify_admin_mfa(user_id, code, allow_recovery=True)

    def _verify_admin_mfa(self, user_id: str, code: str, *, allow_recovery: bool) -> bool:
        value = code.strip().replace(" ", "")
        with self._session() as conn:
            row = conn.execute("SELECT encrypted_secret,recovery_codes_json FROM valuesee_admin_mfa WHERE user_id=?", (user_id,)).fetchone()
            if not row:
                return False
            secret = _decrypt_mfa_secret(str(row["encrypted_secret"]))
            if _verify_totp(secret, value):
                return True
            if allow_recovery:
                digest = _recovery_hash(value)
                hashes = json.loads(row["recovery_codes_json"])
                if digest in hashes:
                    hashes.remove(digest)
                    conn.execute("UPDATE valuesee_admin_mfa SET recovery_codes_json=?,updated_at=? WHERE user_id=?", (json.dumps(hashes), utc_now_iso(), user_id))
                    return True
        return False

    def disable_admin_mfa(self, user_id: str, code: str = "", password: str = "") -> bool:
        verified = self._verify_admin_mfa(user_id, code, allow_recovery=True) if code.strip() else False
        if not verified and not self.verify_user_password(user_id, password):
            return False
        with self._session() as conn:
            conn.execute("DELETE FROM valuesee_admin_mfa WHERE user_id=?", (user_id,))
        return True

    def session_mfa_verified(self, token: str) -> bool:
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._session() as conn:
            row = conn.execute("SELECT mfa_verified,status FROM valuesee_session WHERE token_hash=?", (digest,)).fetchone()
        return bool(row and row["status"] == "active" and row["mfa_verified"])

    def validate_session(self, session_id: str, token: str) -> bool:
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._session() as conn:
            row = conn.execute("SELECT status,expires_at,token_hash FROM valuesee_session WHERE session_id=?", (session_id,)).fetchone()
            if not row or row["status"] != "active" or not hmac.compare_digest(str(row["token_hash"]), digest) or _parse_utc(row["expires_at"]) < datetime.now(timezone.utc):
                return False
            conn.execute("UPDATE valuesee_session SET last_seen_at=? WHERE session_id=?", (utc_now_iso(), session_id))
        return True

    def list_sessions(self, user_id: str, current_token: str | None = None) -> list[dict[str, Any]]:
        current_hash = hashlib.sha256(current_token.encode()).hexdigest() if current_token else ""
        with self._session() as conn:
            rows = conn.execute("SELECT session_id,device_name,ip_address,status,created_at,last_seen_at,expires_at,revoked_at,token_hash FROM valuesee_session WHERE user_id=? ORDER BY last_seen_at DESC", (user_id,)).fetchall()
        return [{**{key: row[key] for key in ("session_id", "device_name", "ip_address", "status", "created_at", "last_seen_at", "expires_at", "revoked_at")}, "current": bool(current_hash and hmac.compare_digest(str(row["token_hash"]), current_hash))} for row in rows]

    def revoke_session(self, user_id: str, session_id: str) -> bool:
        with self._session() as conn:
            return conn.execute("UPDATE valuesee_session SET status='revoked',revoked_at=? WHERE session_id=? AND user_id=? AND status='active'", (utc_now_iso(), session_id, user_id)).rowcount > 0

    def subscription_status(self, user_id: str) -> dict[str, Any]:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM valuesee_subscription WHERE user_id=?", (user_id,)).fetchone()
        plan = str(row["plan_code"]) if row and row["status"] == "active" else "free"
        limits = {"free": {"active_monitors": 3, "monthly_comparisons": 10, "family_members": 2}, "pro": {"active_monitors": 100, "monthly_comparisons": 1000, "family_members": 6}}
        return {"plan_code": plan, "status": str(row["status"]) if row else "active", "current_period_end": row["current_period_end"] if row else None, "provider": row["provider"] if row else None, "limits": limits[plan]}

    def entitlement_usage(self, user_id: str) -> dict[str, int]:
        month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        usage = {"active_monitors": 0, "monthly_comparisons": 0, "family_members": 1}
        with self._session() as conn:
            queries = {
                "active_monitors": ("SELECT COUNT(*) AS total FROM shopping_price_monitor WHERE user_id=? AND status IN ('watching','paused','target_reached')", (user_id,)),
                "monthly_comparisons": ("SELECT COUNT(*) AS total FROM shopping_comparison_list WHERE user_id=? AND created_at>=?", (user_id, month_start)),
                "family_members": ("SELECT COALESCE(MAX(member_total),1) AS total FROM (SELECT COUNT(*) AS member_total FROM valuesee_family_member WHERE family_id IN (SELECT family_id FROM valuesee_family WHERE owner_id=?) GROUP BY family_id) counts", (user_id,)),
            }
            for key, (sql, params) in queries.items():
                try:
                    row = conn.execute(sql, params).fetchone()
                    usage[key] = int(row["total"] if row and row["total"] is not None else usage[key])
                except Exception as exc:
                    if exc.__class__.__name__ != "OperationalError":
                        raise
        return usage

    def require_entitlement(self, user_id: str, entitlement: str) -> None:
        membership = self.subscription_status(user_id)
        limits, usage = membership["limits"], self.entitlement_usage(user_id)
        if entitlement not in limits:
            raise ValueError("unknown entitlement")
        if usage[entitlement] >= int(limits[entitlement]):
            labels = {"active_monitors": "降价监控", "monthly_comparisons": "本月对比", "family_members": "家庭成员"}
            raise ValueError(f"{labels[entitlement]}已达到 {membership['plan_code'].upper()} 方案额度")

    def request_upgrade(self, user_id: str, plan_code: str) -> dict[str, Any]:
        if plan_code != "pro":
            raise ValueError("unsupported plan")
        now, request_id = utc_now_iso(), f"upgrade_{uuid4().hex}"
        with self._session() as conn:
            existing = conn.execute("SELECT * FROM valuesee_upgrade_request WHERE user_id=? AND plan_code=? AND status='pending'", (user_id, plan_code)).fetchone()
            if existing:
                return dict(existing)
            conn.execute("INSERT INTO valuesee_upgrade_request VALUES(?,?,?,?,?,?)", (request_id, user_id, plan_code, "pending", now, now))
        return {"request_id": request_id, "user_id": user_id, "plan_code": plan_code, "status": "pending", "created_at": now, "updated_at": now}

    def create_billing_order(self, user_id: str, plan_code: str, billing_cycle: str) -> dict[str, Any]:
        prices = {("pro", "monthly"): 19.0, ("pro", "yearly"): 168.0}
        if (plan_code, billing_cycle) not in prices:
            raise ValueError("unsupported plan or billing cycle")
        now, order_id = utc_now_iso(), f"bill_{uuid4().hex}"
        with self._session() as conn:
            existing = conn.execute("SELECT * FROM valuesee_billing_order WHERE user_id=? AND plan_code=? AND billing_cycle=? AND status='pending_external_payment' ORDER BY created_at DESC LIMIT 1", (user_id, plan_code, billing_cycle)).fetchone()
            if existing:
                return dict(existing)
            conn.execute("INSERT INTO valuesee_billing_order VALUES(?,?,?,?,?,?,?,?,?,?,?)", (order_id, user_id, plan_code, billing_cycle, prices[(plan_code, billing_cycle)], "CNY", "pending_external_payment", None, None, now, now))
            row = conn.execute("SELECT * FROM valuesee_billing_order WHERE order_id=?", (order_id,)).fetchone()
        return dict(row)

    def list_billing_orders(self, user_id: str) -> list[dict[str, Any]]:
        with self._session() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM valuesee_billing_order WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()]

    def cancel_billing_order(self, user_id: str, order_id: str) -> dict[str, Any] | None:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM valuesee_billing_order WHERE order_id=? AND user_id=?", (order_id, user_id)).fetchone()
            if not row:
                return None
            if row["status"] != "pending_external_payment":
                raise ValueError("only pending payment orders can be cancelled")
            conn.execute("UPDATE valuesee_billing_order SET status='cancelled',updated_at=? WHERE order_id=?", (utc_now_iso(), order_id))
            updated = conn.execute("SELECT * FROM valuesee_billing_order WHERE order_id=?", (order_id,)).fetchone()
        return dict(updated)

    def create_family(self, owner_id: str, name: str) -> dict[str, Any]:
        family_id, now = f"fam_{uuid4().hex}", utc_now_iso()
        with self._session() as conn:
            conn.execute("INSERT INTO valuesee_family VALUES(?,?,?,?)", (family_id, name.strip() or "我的家庭", owner_id, now))
            conn.execute("INSERT INTO valuesee_family_member VALUES(?,?,?,?)", (family_id, owner_id, "owner", now))
        return {"family_id": family_id, "name": name.strip() or "我的家庭", "owner_id": owner_id, "role": "owner", "created_at": now}

    def list_families(self, user_id: str) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute("""SELECT f.*,m.role FROM valuesee_family f JOIN valuesee_family_member m
                ON f.family_id=m.family_id WHERE m.user_id=? ORDER BY f.created_at DESC""", (user_id,)).fetchall()
        return [dict(row) for row in rows]

    def invite_family_member(self, owner_id: str, family_id: str, email: str) -> dict[str, Any]:
        normalized = email.strip().lower()
        with self._session() as conn:
            family = conn.execute("SELECT * FROM valuesee_family WHERE family_id=? AND owner_id=?", (family_id, owner_id)).fetchone()
            member = conn.execute("SELECT user_id FROM valuesee_user WHERE email=? AND status='active'", (normalized,)).fetchone()
            if not family:
                raise ValueError("只有家庭所有者可以管理成员")
            if not member:
                raise ValueError("该邮箱尚未注册 ValuSee 账户")
            now = utc_now_iso()
            try:
                conn.execute("INSERT INTO valuesee_family_member VALUES(?,?,?,?)", (family_id, member["user_id"], "member", now))
            except Exception as exc:
                if is_integrity_error(exc):
                    raise ValueError("该用户已经在家庭中") from exc
                raise
        return {"family_id": family_id, "user_id": member["user_id"], "email": normalized, "role": "member", "created_at": now}

    def create_family_invitation(self, owner_id: str, family_id: str, email: str, role: str = "member") -> dict[str, Any]:
        normalized = email.strip().lower()
        if role not in {"member", "editor"}:
            raise ValueError("invalid invitation role")
        now = datetime.now(timezone.utc)
        with self._session() as conn:
            family = conn.execute("SELECT 1 FROM valuesee_family WHERE family_id=? AND owner_id=?", (family_id, owner_id)).fetchone()
            target = conn.execute("SELECT user_id FROM valuesee_user WHERE email=? AND status='active'", (normalized,)).fetchone()
            if not family:
                raise ValueError("只有家庭所有者可以邀请成员")
            if not target:
                raise ValueError("该邮箱尚未注册 ValuSee 账户")
            if conn.execute("SELECT 1 FROM valuesee_family_member WHERE family_id=? AND user_id=?", (family_id, target["user_id"])).fetchone():
                raise ValueError("该用户已经在家庭中")
            existing = conn.execute("SELECT * FROM valuesee_family_invitation WHERE family_id=? AND email=? AND status='pending'", (family_id, normalized)).fetchone()
            if existing:
                return dict(existing)
            record = {"invitation_id": f"invite_{uuid4().hex}", "family_id": family_id, "inviter_id": owner_id, "email": normalized, "role": role, "status": "pending", "expires_at": (now + timedelta(days=7)).isoformat(), "created_at": now.isoformat(), "responded_at": None}
            conn.execute("INSERT INTO valuesee_family_invitation(invitation_id,family_id,inviter_id,email,role,status,expires_at,created_at,responded_at) VALUES(?,?,?,?,?,?,?,?,?)", tuple(record.values()))
        return record

    def list_family_invitations(self, user_id: str) -> list[dict[str, Any]]:
        user = self.get_user(user_id)
        if not user:
            return []
        with self._session() as conn:
            rows = conn.execute("SELECT i.*,f.name AS family_name FROM valuesee_family_invitation i JOIN valuesee_family f ON f.family_id=i.family_id WHERE i.email=? AND i.status='pending' ORDER BY i.created_at DESC", (user["email"],)).fetchall()
        return [dict(row) for row in rows]

    def respond_family_invitation(self, user_id: str, invitation_id: str, accept: bool) -> dict[str, Any]:
        user = self.get_user(user_id)
        now = datetime.now(timezone.utc)
        with self._session() as conn:
            row = conn.execute("SELECT * FROM valuesee_family_invitation WHERE invitation_id=? AND status='pending'", (invitation_id,)).fetchone()
            if not row or not user or row["email"] != user["email"]:
                raise ValueError("邀请不存在或不属于当前账户")
            if datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00")) <= now:
                conn.execute("UPDATE valuesee_family_invitation SET status='expired',responded_at=? WHERE invitation_id=?", (now.isoformat(), invitation_id))
                raise ValueError("邀请已过期")
            status = "accepted" if accept else "declined"
            if accept:
                conn.execute("INSERT INTO valuesee_family_member(family_id,user_id,role,created_at) VALUES(?,?,?,?)", (row["family_id"], user_id, row["role"], now.isoformat()))
            conn.execute("UPDATE valuesee_family_invitation SET status=?,responded_at=? WHERE invitation_id=?", (status, now.isoformat(), invitation_id))
        return {"invitation_id": invitation_id, "status": status, "family_id": row["family_id"]}

    def _family_role(self, conn: Any, user_id: str, family_id: str) -> str | None:
        row = conn.execute("SELECT role FROM valuesee_family_member WHERE family_id=? AND user_id=?", (family_id, user_id)).fetchone()
        return str(row["role"]) if row else None

    def list_family_assets(self, user_id: str, family_id: str) -> list[dict[str, Any]]:
        with self._session() as conn:
            if not self._family_role(conn, user_id, family_id):
                raise ValueError("无权查看该家庭物品")
            rows = conn.execute("SELECT * FROM valuesee_family_asset WHERE family_id=? ORDER BY updated_at DESC", (family_id,)).fetchall()
        return [dict(row) for row in rows]

    def save_family_asset(self, user_id: str, family_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now, asset_id = utc_now_iso(), str(payload.get("asset_id") or f"asset_{uuid4().hex}")
        with self._session() as conn:
            if self._family_role(conn, user_id, family_id) not in {"owner", "editor"}:
                raise ValueError("只有所有者或编辑者可以维护家庭物品")
            name = str(payload.get("name") or "").strip()
            if not name:
                raise ValueError("物品名称不能为空")
            old = conn.execute("SELECT created_at,created_by FROM valuesee_family_asset WHERE asset_id=? AND family_id=?", (asset_id, family_id)).fetchone()
            values = (asset_id, family_id, name, str(payload.get("category") or "其他"), str(payload.get("brand") or ""), str(payload.get("model") or ""), payload.get("purchased_at"), payload.get("warranty_deadline"), str(payload.get("notes") or ""), old["created_by"] if old else user_id, old["created_at"] if old else now, now)
            conn.execute("""INSERT INTO valuesee_family_asset(asset_id,family_id,name,category,brand,model,purchased_at,warranty_deadline,notes,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(asset_id) DO UPDATE SET name=excluded.name,category=excluded.category,brand=excluded.brand,model=excluded.model,purchased_at=excluded.purchased_at,warranty_deadline=excluded.warranty_deadline,notes=excluded.notes,updated_at=excluded.updated_at""", values)
            row = conn.execute("SELECT * FROM valuesee_family_asset WHERE asset_id=?", (asset_id,)).fetchone()
        return dict(row)

    def family_budget(self, user_id: str, family_id: str) -> dict[str, Any]:
        with self._session() as conn:
            if not self._family_role(conn, user_id, family_id):
                raise ValueError("无权查看家庭预算")
            row = conn.execute("SELECT * FROM valuesee_family_budget WHERE family_id=?", (family_id,)).fetchone()
        return dict(row) if row else {"family_id": family_id, "monthly_budget": 0, "annual_budget": 0, "currency": "CNY"}

    def save_family_budget(self, user_id: str, family_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._session() as conn:
            if self._family_role(conn, user_id, family_id) not in {"owner", "editor"}:
                raise ValueError("只有所有者或编辑者可以维护家庭预算")
            values = (family_id, max(0, float(payload.get("monthly_budget") or 0)), max(0, float(payload.get("annual_budget") or 0)), str(payload.get("currency") or "CNY")[:3].upper(), user_id, utc_now_iso())
            conn.execute("INSERT INTO valuesee_family_budget(family_id,monthly_budget,annual_budget,currency,updated_by,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(family_id) DO UPDATE SET monthly_budget=excluded.monthly_budget,annual_budget=excluded.annual_budget,currency=excluded.currency,updated_by=excluded.updated_by,updated_at=excluded.updated_at", values)
        return self.family_budget(user_id, family_id)

    def list_family_members(self, actor_id: str, family_id: str) -> list[dict[str, Any]]:
        with self._session() as conn:
            allowed = conn.execute("SELECT 1 FROM valuesee_family_member WHERE family_id=? AND user_id=?", (family_id, actor_id)).fetchone()
            if not allowed:
                raise ValueError("无权查看该家庭")
            rows = conn.execute("""SELECT m.family_id,m.user_id,m.role,m.created_at,u.email,u.display_name
                FROM valuesee_family_member m JOIN valuesee_user u ON u.user_id=m.user_id
                WHERE m.family_id=? ORDER BY CASE m.role WHEN 'owner' THEN 0 ELSE 1 END,m.created_at""", (family_id,)).fetchall()
        return [dict(row) for row in rows]

    def set_family_member_role(self, owner_id: str, family_id: str, user_id: str, role: str) -> dict[str, Any]:
        if role not in {"member", "editor"}:
            raise ValueError("role must be member or editor")
        with self._session() as conn:
            family = conn.execute("SELECT 1 FROM valuesee_family WHERE family_id=? AND owner_id=?", (family_id, owner_id)).fetchone()
            member = conn.execute("SELECT role FROM valuesee_family_member WHERE family_id=? AND user_id=?", (family_id, user_id)).fetchone()
            if not family:
                raise ValueError("只有家庭所有者可以管理成员")
            if not member or member["role"] == "owner":
                raise ValueError("成员不存在或不能修改所有者角色")
            conn.execute("UPDATE valuesee_family_member SET role=? WHERE family_id=? AND user_id=?", (role, family_id, user_id))
        return next(item for item in self.list_family_members(owner_id, family_id) if item["user_id"] == user_id)

    def remove_family_member(self, owner_id: str, family_id: str, user_id: str) -> bool:
        with self._session() as conn:
            family = conn.execute("SELECT 1 FROM valuesee_family WHERE family_id=? AND owner_id=?", (family_id, owner_id)).fetchone()
            member = conn.execute("SELECT role FROM valuesee_family_member WHERE family_id=? AND user_id=?", (family_id, user_id)).fetchone()
            if not family:
                raise ValueError("只有家庭所有者可以管理成员")
            if not member or member["role"] == "owner":
                raise ValueError("成员不存在或不能移除家庭所有者")
            cursor = conn.execute("DELETE FROM valuesee_family_member WHERE family_id=? AND user_id=?", (family_id, user_id))
            return cursor.rowcount > 0

    def export_account(self, user_id: str) -> dict[str, Any]:
        tables = {
            "monitors": ("shopping_price_monitor", "user_id"),
            "purchases": ("shopping_purchase_record", "user_id"),
            "captures": ("shopping_extension_capture", "user_id"),
            "price_snapshots": ("shopping_price_snapshot", "user_id"),
            "notifications": ("shopping_notification", "user_id"),
            "profile": ("shopping_user_profile", "user_id"),
            "comparisons": ("shopping_comparison_list", "user_id"),
            "reports": ("shopping_decision_report", "user_id"),
            "feedback": ("shopping_feedback", "user_id"),
            "notification_preferences": ("shopping_notification_preference", "user_id"),
            "business_events": ("shopping_business_event", "user_id"),
            "saved_items": ("shopping_saved_item", "user_id"),
            "saved_groups": ("shopping_saved_group", "user_id"),
            "saved_group_items": ("shopping_saved_group_item", "user_id"),
            "product_records": ("shopping_product_record", "user_id"),
            "product_versions": ("shopping_product_version", "user_id"),
            "price_anomalies": ("shopping_price_anomaly", "user_id"),
            "review_reports": ("shopping_review_report", "user_id"),
            "notification_deliveries": ("shopping_notification_delivery", "user_id"),
            "shares": ("shopping_share", "user_id"),
            "purchase_attachments": ("shopping_purchase_attachment", "user_id"),
            "price_protection_claims": ("shopping_price_protection_claim", "user_id"),
            "support_tickets": ("shopping_support_ticket", "user_id"),
            "sessions": ("valuesee_session", "user_id"),
            "subscriptions": ("valuesee_subscription", "user_id"),
            "upgrade_requests": ("valuesee_upgrade_request", "user_id"),
            "billing_orders": ("valuesee_billing_order", "user_id"),
            "account_profile": ("valuesee_user_profile", "user_id"),
            "account_audits": ("valuesee_user_audit", "user_id"),
            "monitor_preferences": ("shopping_monitor_preference", "user_id"),
            "budget_pools": ("shopping_budget_pool", "user_id"),
            "savings_ledger": ("shopping_savings_ledger", "user_id"),
        }
        with self._session() as conn:
            result = {"user": self.get_user(user_id), "families": [], "family_assets": [], "family_budgets": [], "family_invitations": [], "support_messages": [], "support_cases": [], **{key: [] for key in tables}}
            result["families"] = [dict(row) for row in conn.execute("SELECT f.*,m.role FROM valuesee_family f JOIN valuesee_family_member m ON f.family_id=m.family_id WHERE m.user_id=?", (user_id,)).fetchall()]
            family_ids = [item["family_id"] for item in result["families"]]
            for family_id in family_ids:
                result["family_assets"].extend(dict(row) for row in conn.execute("SELECT * FROM valuesee_family_asset WHERE family_id=?", (family_id,)).fetchall())
                budget = conn.execute("SELECT * FROM valuesee_family_budget WHERE family_id=?", (family_id,)).fetchone()
                if budget:
                    result["family_budgets"].append(dict(budget))
            user = result["user"] or {}
            result["family_invitations"] = [dict(row) for row in conn.execute("SELECT * FROM valuesee_family_invitation WHERE inviter_id=? OR email=?", (user_id, user.get("email", ""))).fetchall()]
            for key, (table, column) in tables.items():
                try:
                    result[key] = [dict(row) for row in conn.execute(f"SELECT * FROM {table} WHERE {column}=?", (user_id,)).fetchall()]
                    if key == "sessions":
                        for session in result[key]:
                            session.pop("token_hash", None)
                except Exception as exc:
                    if exc.__class__.__name__ == "OperationalError":
                        result[key] = []
                    else:
                        raise
            try:
                result["support_messages"] = [dict(row) for row in conn.execute("SELECT m.* FROM shopping_support_message m JOIN shopping_support_ticket t ON t.ticket_id=m.ticket_id WHERE t.user_id=? ORDER BY m.created_at", (user_id,)).fetchall()]
                result["support_cases"] = [dict(row) for row in conn.execute("SELECT c.* FROM shopping_support_case c JOIN shopping_support_ticket t ON t.ticket_id=c.ticket_id WHERE t.user_id=? ORDER BY c.updated_at", (user_id,)).fetchall()]
            except Exception as exc:
                if exc.__class__.__name__ != "OperationalError":
                    raise
        return result

    def delete_account(self, user_id: str) -> None:
        if user_id == "local-user":
            raise ValueError("本地演示账户不能执行删除")
        tables = (
            "shopping_price_check", "shopping_monitor_action", "shopping_price_monitor",
            "shopping_purchase_record", "shopping_extension_capture", "shopping_price_snapshot",
            "shopping_notification", "shopping_user_profile", "shopping_comparison_list",
            "shopping_decision_report", "shopping_feedback", "shopping_notification_preference",
            "shopping_business_event",
            "shopping_saved_group_item", "shopping_saved_group", "shopping_saved_item",
            "shopping_product_record", "shopping_review_report", "shopping_notification_delivery",
            "shopping_product_version", "shopping_price_anomaly",
            "shopping_share",
            "shopping_purchase_attachment", "shopping_price_protection_claim", "shopping_support_ticket",
            "valuesee_session", "valuesee_subscription", "valuesee_upgrade_request", "valuesee_billing_order",
            "valuesee_user_profile", "valuesee_user_audit", "valuesee_admin_mfa",
            "shopping_monitor_preference", "shopping_budget_pool", "shopping_savings_ledger",
        )
        attachment_objects: list[tuple[str, str]] = []
        with self._session() as conn:
            owned_family_ids = [row["family_id"] for row in conn.execute("SELECT family_id FROM valuesee_family WHERE owner_id=?", (user_id,)).fetchall()]
            user_row = conn.execute("SELECT email FROM valuesee_user WHERE user_id=?", (user_id,)).fetchone()
            try:
                attachment_objects = [(str(row["storage_backend"]), str(row["storage_key"])) for row in conn.execute("SELECT storage_backend,storage_key FROM shopping_purchase_attachment WHERE user_id=?", (user_id,)).fetchall()]
            except Exception as exc:
                if exc.__class__.__name__ != "OperationalError":
                    raise
            try:
                avatar = conn.execute("SELECT avatar_backend,avatar_key FROM valuesee_user_profile WHERE user_id=? AND avatar_key IS NOT NULL", (user_id,)).fetchone()
                if avatar:
                    attachment_objects.append((str(avatar["avatar_backend"]), str(avatar["avatar_key"])))
            except Exception as exc:
                if exc.__class__.__name__ != "OperationalError":
                    raise
            try:
                ticket_ids = [row["ticket_id"] for row in conn.execute("SELECT ticket_id FROM shopping_support_ticket WHERE user_id=?", (user_id,)).fetchall()]
                for ticket_id in ticket_ids:
                    conn.execute("DELETE FROM shopping_support_message WHERE ticket_id=?", (ticket_id,))
                    conn.execute("DELETE FROM shopping_support_case WHERE ticket_id=?", (ticket_id,))
            except Exception as exc:
                if exc.__class__.__name__ != "OperationalError":
                    raise
            try:
                monitor_ids = [row["monitor_id"] for row in conn.execute("SELECT monitor_id FROM shopping_price_monitor WHERE user_id=?", (user_id,)).fetchall()]
            except Exception as exc:
                if exc.__class__.__name__ != "OperationalError":
                    raise
                monitor_ids = []
            for table in tables:
                if table in {"shopping_price_check", "shopping_monitor_action"}:
                    for monitor_id in monitor_ids:
                        try:
                            conn.execute("DELETE FROM shopping_price_check WHERE monitor_id=?", (monitor_id,))
                        except Exception as exc:
                            if exc.__class__.__name__ != "OperationalError":
                                raise
                else:
                    try:
                        conn.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
                    except Exception as exc:
                        if exc.__class__.__name__ != "OperationalError":
                            raise
            for family_id in owned_family_ids:
                conn.execute("DELETE FROM valuesee_family_asset WHERE family_id=?", (family_id,))
                conn.execute("DELETE FROM valuesee_family_budget WHERE family_id=?", (family_id,))
                conn.execute("DELETE FROM valuesee_family_invitation WHERE family_id=?", (family_id,))
                conn.execute("DELETE FROM valuesee_family_member WHERE family_id=?", (family_id,))
            conn.execute("DELETE FROM valuesee_family_invitation WHERE inviter_id=? OR email=?", (user_id, user_row["email"] if user_row else ""))
            conn.execute("DELETE FROM valuesee_family_member WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM valuesee_family WHERE owner_id=?", (user_id,))
            conn.execute("DELETE FROM valuesee_auth_token WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM valuesee_user WHERE user_id=?", (user_id,))
        for backend, key in attachment_objects:
            delete_stored_object(backend, key)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, iterations, salt, expected = encoded.split("$", 3)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), _unb64(salt), int(iterations))
        return hmac.compare_digest(_b64(digest), expected)
    except (TypeError, ValueError):
        return False


def _mfa_cipher():
    from cryptography.fernet import Fernet

    configured = os.getenv("VALUSee_MFA_ENCRYPTION_KEY", "").strip()
    key = configured.encode("ascii") if configured else base64.urlsafe_b64encode(hashlib.sha256(_jwt_secret() + b":admin-mfa").digest())
    return Fernet(key)


def _encrypt_mfa_secret(secret: str) -> str:
    return _mfa_cipher().encrypt(secret.encode("ascii")).decode("ascii")


def _decrypt_mfa_secret(encrypted: str) -> str:
    return _mfa_cipher().decrypt(encrypted.encode("ascii")).decode("ascii")


def _totp(secret: str, at: int | None = None) -> str:
    padded = secret + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded, casefold=True)
    counter = int(at if at is not None else time.time()) // 30
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{value:06d}"


def _verify_totp(secret: str, code: str, at: int | None = None) -> bool:
    if len(code) != 6 or not code.isdigit():
        return False
    current = int(at if at is not None else time.time())
    return any(hmac.compare_digest(_totp(secret, current + offset * 30), code) for offset in (-1, 0, 1))


def _recovery_hash(code: str) -> str:
    return hmac.new(_jwt_secret(), f"recovery:{code.strip().lower()}".encode(), hashlib.sha256).hexdigest()


def _email_code_hash(email: str, purpose: str, code: str) -> str:
    value = f"email-code:{email.strip().lower()}:{purpose}:{code.strip()}".encode()
    return hmac.new(_jwt_secret(), value, hashlib.sha256).hexdigest()


def issue_token(user_id: str, expires_seconds: int = 86_400, session_id: str | None = None) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims: dict[str, Any] = {"sub": user_id, "iat": int(time.time()), "exp": int(time.time()) + expires_seconds}
    if session_id:
        claims["sid"] = session_id
    payload = _b64(json.dumps(claims, separators=(",", ":")).encode())
    signature = _b64(hmac.new(_jwt_secret(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def verify_token(token: str) -> str:
    try:
        header, payload, signature = token.split(".")
        expected = _b64(hmac.new(_jwt_secret(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        body = json.loads(_unb64(payload))
        if int(body["exp"]) < int(time.time()):
            raise ValueError("expired")
        if not body.get("sid") or not auth_store.validate_session(str(body["sid"]), token):
            raise ValueError("revoked session")
        return str(body["sub"])
    except Exception as exc:
        raise ValueError("登录状态无效或已过期") from exc


def bearer_subject(authorization: str | None, *, allow_local: bool = True) -> str:
    if authorization and authorization.startswith("Bearer "):
        return verify_token(authorization[7:].strip())
    if allow_local:
        return "local-user"
    raise ValueError("请先登录")


def _jwt_secret() -> bytes:
    secret = os.getenv("VALUSee_JWT_SECRET", "valuesee-dev-secret-change-before-production")
    if os.getenv("APP_ENV", "dev").lower() in {"prod", "production"} and secret == "valuesee-dev-secret-change-before-production":
        raise RuntimeError("生产环境必须配置 VALUSee_JWT_SECRET")
    return secret.encode("utf-8")


def _public_user(row: Any) -> dict[str, Any]:
    keys = set(row.keys())
    return {"user_id": row["user_id"], "email": row["email"], "display_name": row["display_name"], "status": row["status"], "email_verified": bool(row["email_verified"]) if "email_verified" in keys else False, "created_at": row["created_at"]}


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


auth_store = AuthStore()
