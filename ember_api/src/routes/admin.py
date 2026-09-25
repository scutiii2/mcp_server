"""/api/admin: invite management (admin.manage only)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from src.deps import get_email_sender, get_otp_service, require_permission
from src.models import Account, InviteCode
from src.services.email_service import EmailDeliveryError, EmailSender
from src.services.otp_service import OtpService
from src.services.permissions import ADMIN_MANAGE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

require_admin = require_permission(ADMIN_MANAGE)


class CreateInviteRequest(BaseModel):
    invitee_email: EmailStr | None = None
    delivery_method: Literal["manual", "email"] = "manual"


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
