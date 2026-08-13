"""Typed contracts for SAP user creation - approval-gated by design.

Two-phase on purpose (see domain.py's module docstring for the full
reasoning): ``RequestSapUserCreation`` is what the chat-exposed tool
takes and only ever produces a pending approval request, never a real
account. Execution after approval takes just a token, not a repeat of
the whole request - the payload it needs already lives in the pending
request record (infra/pending_requests.py), keyed by that token.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RequestSapUserCreation(BaseModel):
    sid: str
    user_id: str = Field(..., description="Target SAP username to create, e.g. JDOE")
    first_name: str
    last_name: str
    email: str
    user_type: str = Field("A", description="A=Dialog, C=Communication, S=System, L=Service")
    roles: list[str] = Field(default_factory=list, description="PFCG role names to assign")
    requested_by: str = Field(..., description="Name or email of the person requesting this account")


class RequestSapUserCreationResult(BaseModel):
    sid: str
    user_id: str
    token: str | None = None
    roles_validated: list[str] = []
    roles_invalid: list[str] = []
    approval_requested: bool
    message: str


class ExecuteApprovedUserCreationResult(BaseModel):
    sid: str
    user_id: str
    success: bool
    user_created: bool
    roles_assigned: list[str] = []
    roles_failed: list[str] = []
    message: str