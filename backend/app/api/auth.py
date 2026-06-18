"""本地登录/注册路由。

账号只用于隔离本机学习数据。API/provider 凭证继续由 backend/.env 提供，不随账号保存。
"""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app import auth as auth_utils
from app.api import deps
from app.config import get_config
from app.container import Container
from app.models import PublicUser, UserAccount

router = APIRouter(prefix="/api/auth", tags=["auth"])

ContainerDep = Annotated[Container, Depends(deps.container)]
CurrentUserDep = Annotated[PublicUser, Depends(deps.current_user)]


class AuthRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: PublicUser


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(req: AuthRequest, c: ContainerDep) -> AuthResponse:
    users = deps.require_users(c)
    try:
        username = auth_utils.validate_username(req.username)
        auth_utils.validate_password(req.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if await users.get_by_username(username) is not None:
        raise HTTPException(status_code=409, detail="用户名已存在")

    user = UserAccount(username=username, password_hash=auth_utils.hash_password(req.password))
    try:
        await users.add(user)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="用户名已存在") from exc
    return _auth_response(user)


@router.post("/login")
async def login(req: AuthRequest, c: ContainerDep) -> AuthResponse:
    users = deps.require_users(c)
    username = auth_utils.normalize_username(req.username)
    user = await users.get_by_username(username)
    if user is None or not auth_utils.verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return _auth_response(user)


@router.get("/me")
async def me(user: CurrentUserDep) -> PublicUser:
    return user


def _auth_response(user: UserAccount) -> AuthResponse:
    config = get_config()
    token = auth_utils.create_access_token(
        user, secret=config.auth_secret, ttl_seconds=config.auth_token_ttl_seconds
    )
    return AuthResponse(access_token=token, user=PublicUser(id=user.id, username=user.username))
