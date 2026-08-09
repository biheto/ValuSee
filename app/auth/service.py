from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from app.harness.events import utc_now_iso
from app.core.database import connect_database, is_integrity_error


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class AuthStore:
    def __init__(self, db_path: str | Path = "data/valuesee.db"):
        self.db_path = Path(db_path)
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
            conn.execute("""CREATE TABLE IF NOT EXISTS valuesee_auth_token(
                token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,purpose TEXT NOT NULL,
                expires_at TEXT NOT NULL,used_at TEXT,created_at TEXT NOT NULL
            )""")
            if conn.backend == "postgresql":
                conn.execute("ALTER TABLE valuesee_user ADD COLUMN IF NOT EXISTS email_verified INTEGER NOT NULL DEFAULT 0")
            else:
                columns = [row["name"] for row in conn.execute("PRAGMA table_info(valuesee_user)").fetchall()]
                if "email_verified" not in columns:
                    conn.execute("ALTER TABLE valuesee_user ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")

    def register(self, email: str, password: str, display_name: str) -> dict[str, Any]:
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
                    (user_id, normalized, hash_password(password), display_name.strip() or normalized.split("@")[0], "active", now, 0),
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

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM valuesee_user WHERE user_id = ?", (user_id,)).fetchone()
        return _public_user(row) if row else None

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM valuesee_user WHERE email=? AND status='active'", (email.strip().lower(),)).fetchone()
        return _public_user(row) if row else None

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
        return True

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

    def export_account(self, user_id: str) -> dict[str, Any]:
        tables = {
            "monitors": ("shopping_price_monitor", "user_id"),
            "purchases": ("shopping_purchase_record", "user_id"),
            "captures": ("shopping_extension_capture", "user_id"),
            "price_snapshots": ("shopping_price_snapshot", "user_id"),
            "notifications": ("shopping_notification", "user_id"),
        }
        with self._session() as conn:
            result = {"user": self.get_user(user_id), "families": [], **{key: [] for key in tables}}
            result["families"] = [dict(row) for row in conn.execute("SELECT f.*,m.role FROM valuesee_family f JOIN valuesee_family_member m ON f.family_id=m.family_id WHERE m.user_id=?", (user_id,)).fetchall()]
            for key, (table, column) in tables.items():
                try:
                    result[key] = [dict(row) for row in conn.execute(f"SELECT * FROM {table} WHERE {column}=?", (user_id,)).fetchall()]
                except Exception as exc:
                    if exc.__class__.__name__ == "OperationalError":
                        result[key] = []
                    else:
                        raise
        return result

    def delete_account(self, user_id: str) -> None:
        if user_id == "local-user":
            raise ValueError("本地演示账户不能执行删除")
        tables = ("shopping_price_check", "shopping_price_monitor", "shopping_purchase_record", "shopping_extension_capture", "shopping_price_snapshot", "shopping_notification")
        with self._session() as conn:
            try:
                monitor_ids = [row["monitor_id"] for row in conn.execute("SELECT monitor_id FROM shopping_price_monitor WHERE user_id=?", (user_id,)).fetchall()]
            except Exception as exc:
                if exc.__class__.__name__ != "OperationalError":
                    raise
                monitor_ids = []
            for table in tables:
                if table == "shopping_price_check":
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
            conn.execute("DELETE FROM valuesee_family_member WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM valuesee_family WHERE owner_id=?", (user_id,))
            conn.execute("DELETE FROM valuesee_user WHERE user_id=?", (user_id,))


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


def issue_token(user_id: str, expires_seconds: int = 86_400) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({"sub": user_id, "iat": int(time.time()), "exp": int(time.time()) + expires_seconds}, separators=(",", ":")).encode())
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
