"""DeepCoke 后端鉴权模块。

提供:
- UserToken 表（记录每个登录会话签发的 token）
- issue_token(): 登录时签发新 token
- verify_token(): FastAPI Depends，校验 Authorization: Bearer <token>

设计:
- token 用 secrets.token_urlsafe(32) 生成，~43 字符
- 默认有效期 30 天（可配置 AUTH_TOKEN_TTL_DAYS）
- 校验时只查表，O(1)；过期 token 不自动清理（数据量小，无所谓）
- 失败：401 + WWW-Authenticate: Bearer

兼容:
- 老前端发的固定字符串 'I have login' 也兼容一段时间（避免老 sessionStorage 立刻失效）
  通过 LEGACY_BYPASS_TOKEN 控制；上线公网时务必关掉
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import Column, Integer, String, TIMESTAMP
from sqlalchemy.orm import Session

# AUTH 配置
AUTH_TOKEN_TTL_DAYS = int(os.getenv("AUTH_TOKEN_TTL_DAYS", "30"))
# 旧固定 token 兼容开关：默认 false(安全优先);开发调试需要时显式设 AUTH_LEGACY_BYPASS=true
LEGACY_BYPASS_TOKEN = os.getenv("AUTH_LEGACY_BYPASS", "false").lower() in ("1", "true", "yes")
LEGACY_TOKEN_VALUE = "I have login"


def make_user_token_model(Base):
    """构造 UserToken ORM 类。Base 由调用方传入（test.py 里的 declarative_base 实例）。"""

    class UserToken(Base):
        __tablename__ = "user_tokens"
        id = Column(Integer, primary_key=True, autoincrement=True)
        user_id = Column(String(50), nullable=False, index=True)
        token = Column(String(64), unique=True, nullable=False, index=True)
        created_at = Column(TIMESTAMP, nullable=False)
        expires_at = Column(TIMESTAMP, nullable=False)

    return UserToken


def issue_token(db: Session, UserToken, user_id: str) -> str:
    """签发新 token 并入库。返回 token 字符串。"""
    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    rec = UserToken(
        user_id=user_id,
        token=token,
        created_at=now,
        expires_at=now + timedelta(days=AUTH_TOKEN_TTL_DAYS),
    )
    db.add(rec)
    db.commit()
    return token


def revoke_user_tokens(db: Session, UserToken, user_id: str) -> int:
    """注销某用户所有 token（登出/改密时调用）。返回删除条数。"""
    n = db.query(UserToken).filter(UserToken.user_id == user_id).delete(synchronize_session=False)
    db.commit()
    return n


def make_verify_token(SessionLocal, UserToken):
    """工厂：返回一个 FastAPI dependency，闭包绑定 SessionLocal 和 UserToken。

    用法（在 test.py 里）：
        verify_token = make_verify_token(SessionLocal, UserToken)
        app = FastAPI(dependencies=[Depends(verify_token)])
    或者单个端点豁免：
        @app.post("/login", dependencies=[])
    """

    async def verify_token(authorization: str | None = Header(default=None)) -> dict:
        """校验 Authorization: Bearer <token>。返回 {user_id, token}。失败抛 401。"""
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing or malformed Authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = authorization.split(" ", 1)[1].strip()

        # 兼容老固定 token —— 公网上线前必须关掉
        if LEGACY_BYPASS_TOKEN and token == LEGACY_TOKEN_VALUE:
            return {"user_id": "_legacy_", "token": token}

        # 查表
        db = SessionLocal()
        try:
            rec = db.query(UserToken).filter(UserToken.token == token).first()
            if not rec:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="invalid token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            if rec.expires_at < datetime.utcnow():
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="token expired",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return {"user_id": rec.user_id, "token": token}
        finally:
            db.close()

    return verify_token


def make_verify_token_optional(SessionLocal, UserToken):
    """同上但失败不抛异常，返回 None。给 PDF/静态资源这种可选鉴权的接口用。"""
    verify = make_verify_token(SessionLocal, UserToken)

    async def verify_optional(authorization: str | None = Header(default=None)):
        if not authorization:
            return None
        try:
            return await verify(authorization=authorization)
        except HTTPException:
            return None

    return verify_optional


# ── 全局中间件方式（推荐）── ──────────────────────────────────────
# 公开路径列表 — 这些路径不需要 Authorization
PUBLIC_PATHS = {
    "/login", "/register",
    "/health", "/healthz",
    "/docs", "/redoc", "/openapi.json",
    "/docs/oauth2-redirect",
}

# 公开路径前缀（如 /papers/{id}/pdf 给 iframe 用，不能加 header）
PUBLIC_PREFIXES = ("/docs",)


def _is_public_path(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    for prefix in PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    # PDF 直链：/papers/{id}/pdf 用 query 参数带 token（前端构造）
    # 这里仍允许无 header 访问，依靠 query token；公网生产再收紧
    if path.startswith("/papers/") and path.endswith("/pdf"):
        return True
    # 图片直链：/papers/{id}/figure 给 <img> 用，带不了 header，同 PDF 豁免
    if path.startswith("/papers/") and path.endswith("/figure"):
        return True
    return False


def make_auth_middleware(SessionLocal, UserToken):
    """返回一个 FastAPI starlette 中间件函数（用 @app.middleware('http') 注册）。

    路径在 PUBLIC_PATHS / PUBLIC_PREFIXES 里则跳过；否则要 Bearer token。
    LEGACY_BYPASS_TOKEN=true 时兼容老前端的 'I have login' 固定字符串。
    """
    from starlette.responses import JSONResponse

    async def auth_middleware(request, call_next):
        path = request.url.path

        # OPTIONS 预检永远放行（CORS）
        if request.method == "OPTIONS":
            return await call_next(request)

        if _is_public_path(path):
            return await call_next(request)

        auth = request.headers.get("authorization") or ""
        if not auth.lower().startswith("bearer "):
            return JSONResponse(
                {"detail": "missing Authorization header"},
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = auth.split(" ", 1)[1].strip()

        if LEGACY_BYPASS_TOKEN and token == LEGACY_TOKEN_VALUE:
            return await call_next(request)

        db = SessionLocal()
        try:
            rec = db.query(UserToken).filter(UserToken.token == token).first()
            if not rec:
                return JSONResponse(
                    {"detail": "invalid token"},
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    headers={"WWW-Authenticate": "Bearer"},
                )
            if rec.expires_at < datetime.utcnow():
                return JSONResponse(
                    {"detail": "token expired"},
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    headers={"WWW-Authenticate": "Bearer"},
                )
            # 把 user_id 写到 request.state 给下游用
            request.state.user_id = rec.user_id
            request.state.token = token
        finally:
            db.close()

        return await call_next(request)

    return auth_middleware
