"""Auth API — login and session endpoints."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from metronix.auth.jwt import create_token
from metronix.auth.passwords import validate_password, verify_password
from metronix.core.config import get_settings

logger = structlog.get_logger()

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user_id: str
    email: str = ""
    display_name: str = ""
    role: str
    must_change_password: bool = False


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ChangePasswordResponse(BaseModel):
    token: str


@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request) -> LoginResponse:
    """Authenticate with email + password against the user store."""
    settings = get_settings()

    user_store = getattr(request.app.state, "user_store", None)
    if not user_store:
        raise HTTPException(status_code=500, detail="User store not available")

    user = await user_store.get_user_by_email(req.email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account is disabled")

    if not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    workspace_ids = user.get("workspace_ids", []) or []
    # Admin role with no per-workspace confinement means "all workspaces".
    # Issuing `[]` would later 403 under the strict workspace resolver, so
    # normalise here at token-issue time (mirrored in OptionalAuthMiddleware
    # for older tokens already in circulation).
    if user["role"] == "admin" and not workspace_ids:
        workspace_ids = ["*"]
    must_change_password = bool(user.get("must_change_password", False))
    token = create_token(
        user_id=user["id"],
        role=user["role"],
        workspace_ids=workspace_ids,
        secret_key=settings.secret_key,
        expiry_hours=24,
        email=user["email"],
        must_change_password=must_change_password,
    )
    logger.info("auth.login.success", user_id=user["id"], email=user["email"])
    return LoginResponse(
        token=token,
        user_id=user["id"],
        email=user["email"],
        display_name=user.get("display_name", ""),
        role=user["role"],
        must_change_password=must_change_password,
    )


@router.get("/auth/me")
def me(request: Request) -> dict:
    """Return current user info from JWT."""
    user = getattr(request.state, "user", {})
    return {
        "status": "ok",
        "user_id": user.get("user_id", ""),
        "email": user.get("email", ""),
        "role": user.get("role", ""),
        "must_change_password": user.get("must_change_password", False),
    }


@router.post("/auth/change-password", response_model=ChangePasswordResponse)
async def change_password(req: ChangePasswordRequest, request: Request) -> ChangePasswordResponse:
    """Change the caller's own password and clear the must-change-password flag.

    Requires a valid Bearer token (enforced by OptionalAuthMiddleware for every
    non-public path when AUTH_ENABLED=true). Re-verifies the current password
    against the stored hash before allowing the change, then issues a fresh
    token so the caller doesn't need to log in again.
    """
    settings = get_settings()

    caller = getattr(request.state, "user", {})
    user_id = caller.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    user_store = getattr(request.app.state, "user_store", None)
    if not user_store:
        raise HTTPException(status_code=500, detail="User store not available")

    record = await user_store.get_user_by_email(caller.get("email", ""))
    if (
        not record
        or not record.get("password_hash")
        or not verify_password(req.current_password, record["password_hash"])
    ):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    try:
        validate_password(req.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await user_store.update_user(
        user_id,
        password=req.new_password,
        must_change_password=False,
    )

    token = create_token(
        user_id=user_id,
        role=record["role"],
        workspace_ids=caller.get("workspace_ids", []) or [],
        secret_key=settings.secret_key,
        expiry_hours=24,
        email=caller.get("email", ""),
        must_change_password=False,
    )
    logger.info("auth.change_password.success", user_id=user_id)
    return ChangePasswordResponse(token=token)
