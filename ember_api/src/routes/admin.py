"""/api/admin: accounts, roles, permissions and invites (admin.manage only)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db_session, get_email_sender, get_otp_service, require_permission
from src.models import Account, InviteCode, Permission, Role
from src.services.admin_service import AdminError, AdminService, NotFoundError
from src.services.email_service import EmailDeliveryError, EmailSender
from src.services.otp_service import OtpService
from src.services.permissions import ADMIN_MANAGE, ADMIN_ROLE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

require_admin = require_permission(ADMIN_MANAGE)


def get_admin_service(session: AsyncSession = Depends(get_db_session)) -> AdminService:
    return AdminService(session)


def _http_error(error: AdminError) -> HTTPException:
    code = status.HTTP_404_NOT_FOUND if isinstance(error, NotFoundError) else status.HTTP_409_CONFLICT
    return HTTPException(code, str(error))


# --- response models ---------------------------------------------------------


class RoleRef(BaseModel):
    id: int
    name: str


class AdminAccountOut(BaseModel):
    id: int
    username: str
    email: str
    email_verified: bool
    is_active: bool
    # The bootstrap admin: can't be edited, deleted or lose roles.
    is_protected: bool
    created_at: datetime
    roles: list[RoleRef]

    @classmethod
    def of(cls, account: Account) -> AdminAccountOut:
        return cls(
            id=account.id,
            username=account.username,
            email=account.email,
            email_verified=account.email_verified,
            is_active=account.is_active,
            is_protected=account.is_protected,
            created_at=account.created_at,
            roles=[RoleRef(id=r.id, name=r.name) for r in sorted(account.roles, key=lambda r: r.name.lower())],
        )


class RoleOut(BaseModel):
    id: int
    name: str
    description: str | None
    # The Administrator role: can't be renamed, deleted or lose permissions.
    is_protected: bool
    permissions: list[str]
    account_count: int

    @classmethod
    def of(cls, role: Role) -> RoleOut:
        return cls(
            id=role.id,
            name=role.name,
            description=role.description,
            is_protected=role.name == ADMIN_ROLE,
            permissions=sorted(p.name for p in role.permissions),
            account_count=len(role.accounts),
        )


class PermissionOut(BaseModel):
    name: str
    description: str | None

    @classmethod
    def of(cls, permission: Permission) -> PermissionOut:
        return cls(name=permission.name, description=permission.description)


class EmailSentOut(BaseModel):
    sent: bool


class InviteOut(BaseModel):
    id: int
    invitee_email: str | None
    delivery_method: str
    created_at: datetime
    expires_at: datetime

    @classmethod
    def of(cls, invite: InviteCode) -> InviteOut:
        return cls(
            id=invite.id,
            invitee_email=invite.invitee_email,
            delivery_method=invite.delivery_method,
            created_at=invite.created_at,
            expires_at=invite.expires_at,
        )


class CreatedInviteOut(BaseModel):
    invite: InviteOut
    # Shown exactly once: only its hash is stored.
    code: str
    email_sent: bool
    email_error: str | None = None


# --- request models ----------------------------------------------------------


class UpdateAccountRequest(BaseModel):
    """Every field optional: only the ones sent change."""

    username: str | None = Field(default=None, min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    email: EmailStr | None = None
    is_active: bool | None = None


class CreateRoleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=255)


class UpdateRoleRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    # "" clears the description; omitted leaves it alone.
    description: str | None = Field(default=None, max_length=255)


class CreateInviteRequest(BaseModel):
    invitee_email: EmailStr | None = None
    delivery_method: Literal["manual", "email"] = "manual"


# --- accounts ----------------------------------------------------------------


@router.get("/accounts")
async def list_accounts(
    _admin: Account = Depends(require_admin),
    admin_service: AdminService = Depends(get_admin_service),
) -> list[AdminAccountOut]:
    return [AdminAccountOut.of(a) for a in await admin_service.accounts()]


@router.patch("/accounts/{account_id}")
async def update_account(
    account_id: int,
    body: UpdateAccountRequest,
    admin: Account = Depends(require_admin),
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminAccountOut:
    try:
        account = await admin_service.update_account(
            admin,
            await admin_service.account(account_id),
            username=body.username,
            email=str(body.email) if body.email else None,
            is_active=body.is_active,
        )
    except AdminError as error:
        raise _http_error(error) from error
    return AdminAccountOut.of(account)


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: int,
    admin: Account = Depends(require_admin),
    admin_service: AdminService = Depends(get_admin_service),
) -> Response:
    try:
        await admin_service.delete_account(admin, await admin_service.account(account_id))
    except AdminError as error:
        raise _http_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/accounts/{account_id}/roles/{role_id}")
async def assign_role(
    account_id: int,
    role_id: int,
    _admin: Account = Depends(require_admin),
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminAccountOut:
    try:
        account = await admin_service.assign_role(
            await admin_service.account(account_id), await admin_service.role(role_id)
        )
    except AdminError as error:
        raise _http_error(error) from error
    return AdminAccountOut.of(account)


@router.delete("/accounts/{account_id}/roles/{role_id}")
async def remove_role(
    account_id: int,
    role_id: int,
    admin: Account = Depends(require_admin),
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminAccountOut:
    try:
        account = await admin_service.remove_role(
            admin, await admin_service.account(account_id), await admin_service.role(role_id)
        )
    except AdminError as error:
        raise _http_error(error) from error
    return AdminAccountOut.of(account)


@router.post("/accounts/{account_id}/send-verification")
async def send_verification(
    account_id: int,
    _admin: Account = Depends(require_admin),
    admin_service: AdminService = Depends(get_admin_service),
    otp: OtpService = Depends(get_otp_service),
    email: EmailSender = Depends(get_email_sender),
) -> EmailSentOut:
    try:
        account = await admin_service.account(account_id)
    except AdminError as error:
        raise _http_error(error) from error
    if account.email_verified:
        raise HTTPException(status.HTTP_409_CONFLICT, f"'{account.username}' is already verified")
    row, code = await otp.create_email_verification(account)
    try:
        await email.send_email_verification(account.email, code, row.expires_at)
    except EmailDeliveryError as error:
        logger.warning("admin verification email to account %s failed: %s", account.id, error)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
    return EmailSentOut(sent=True)


# --- roles and permissions ---------------------------------------------------


@router.get("/roles")
async def list_roles(
    _admin: Account = Depends(require_admin),
    admin_service: AdminService = Depends(get_admin_service),
) -> list[RoleOut]:
    return [RoleOut.of(r) for r in await admin_service.roles()]


@router.post("/roles", status_code=status.HTTP_201_CREATED)
async def create_role(
    body: CreateRoleRequest,
    _admin: Account = Depends(require_admin),
    admin_service: AdminService = Depends(get_admin_service),
) -> RoleOut:
    name = body.name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Role name is required")
    try:
        role = await admin_service.create_role(name, (body.description or "").strip() or None)
    except AdminError as error:
        raise _http_error(error) from error
    return RoleOut.of(role)


@router.patch("/roles/{role_id}")
async def update_role(
    role_id: int,
    body: UpdateRoleRequest,
    _admin: Account = Depends(require_admin),
    admin_service: AdminService = Depends(get_admin_service),
) -> RoleOut:
    name = body.name.strip() if body.name is not None else None
    if name == "":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Role name is required")
    try:
        role = await admin_service.update_role(
            await admin_service.role(role_id),
            name=name,
            description=body.description.strip() if body.description is not None else None,
        )
    except AdminError as error:
        raise _http_error(error) from error
    return RoleOut.of(role)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: int,
    admin: Account = Depends(require_admin),
    admin_service: AdminService = Depends(get_admin_service),
) -> Response:
    try:
        await admin_service.delete_role(admin, await admin_service.role(role_id))
    except AdminError as error:
        raise _http_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/roles/{role_id}/permissions/{permission_name}")
async def grant_permission(
    role_id: int,
    permission_name: str,
    _admin: Account = Depends(require_admin),
    admin_service: AdminService = Depends(get_admin_service),
) -> RoleOut:
    try:
        role = await admin_service.grant_permission(await admin_service.role(role_id), permission_name)
    except AdminError as error:
        raise _http_error(error) from error
    return RoleOut.of(role)


@router.delete("/roles/{role_id}/permissions/{permission_name}")
async def revoke_permission(
    role_id: int,
    permission_name: str,
    admin: Account = Depends(require_admin),
    admin_service: AdminService = Depends(get_admin_service),
) -> RoleOut:
    try:
        role = await admin_service.revoke_permission(admin, await admin_service.role(role_id), permission_name)
    except AdminError as error:
        raise _http_error(error) from error
    return RoleOut.of(role)


@router.get("/permissions")
async def list_permissions(
    _admin: Account = Depends(require_admin),
    admin_service: AdminService = Depends(get_admin_service),
) -> list[PermissionOut]:
    return [PermissionOut.of(p) for p in await admin_service.permissions()]


# --- invites -----------------------------------------------------------------


@router.post("/invites", status_code=status.HTTP_201_CREATED)
async def create_invite(
    body: CreateInviteRequest,
    admin: Account = Depends(require_admin),
    otp: OtpService = Depends(get_otp_service),
    email: EmailSender = Depends(get_email_sender),
) -> CreatedInviteOut:
    if body.delivery_method == "email" and body.invitee_email is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invitee_email is required for email delivery")

    invitee = str(body.invitee_email) if body.invitee_email else None
    invite, code = await otp.create_invite(admin, invitee, body.delivery_method)

    error = None
    if body.delivery_method == "email" and invitee:
        try:
            await email.send_invite(invitee, code, invite.expires_at)
        except EmailDeliveryError as delivery_error:
            # The code is still returned, so the admin can pass it on by hand.
            logger.warning("invite email failed: %s", delivery_error)
            error = str(delivery_error)
    return CreatedInviteOut(
        invite=InviteOut.of(invite),
        code=code,
        email_sent=body.delivery_method == "email" and error is None,
        email_error=error,
    )


@router.get("/invites")
async def list_invites(
    _admin: Account = Depends(require_admin),
    otp: OtpService = Depends(get_otp_service),
) -> list[InviteOut]:
    """Unused, unexpired invites. Codes are never listed - only hashes exist."""
    return [InviteOut.of(i) for i in await otp.open_invites()]


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    invite_id: int,
    _admin: Account = Depends(require_admin),
    admin_service: AdminService = Depends(get_admin_service),
) -> Response:
    try:
        await admin_service.revoke_invite(invite_id)
    except AdminError as error:
        raise _http_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
