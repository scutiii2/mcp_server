"""Account, role and invite management for the Admin page (mirrors
chat_app/src/services/admin_service.py).

Same protections as chat_app: the bootstrap admin account (is_protected)
can't be edited, deleted or stripped of roles, and the Administrator role
can't be renamed, deleted or lose permissions. ember_api adds two of its
own: an admin can't delete or disable their own account, and no change may
take admin.manage away from the admin making it - so nobody locks
themselves out by accident.

Permissions themselves are defined in code (permissions.ALL_PERMISSIONS),
so there's nothing here to create, rename or delete them.
"""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Account, AuthSession, InviteCode, Permission, Role
from src.services.permissions import ADMIN_MANAGE, ADMIN_ROLE, ALL_PERMISSIONS


class AdminError(Exception):
    """A request the rules refuse (maps to 409)."""


class NotFoundError(AdminError):
    """The row doesn't exist (maps to 404)."""


class AdminService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- lookups -----------------------------------------------------------

    async def accounts(self) -> list[Account]:
        return list(await self._session.scalars(select(Account).order_by(func.lower(Account.username))))

    async def roles(self) -> list[Role]:
        return list(await self._session.scalars(select(Role).order_by(func.lower(Role.name))))

    async def permissions(self) -> list[Permission]:
        """Only permissions the code still knows about."""
        rows = await self._session.scalars(select(Permission).order_by(Permission.name))
        return [p for p in rows if p.name in ALL_PERMISSIONS]

    async def account(self, account_id: int) -> Account:
        return await self._get(Account, account_id, "Account")

    async def role(self, role_id: int) -> Role:
        return await self._get(Role, role_id, "Role")

    # --- accounts ----------------------------------------------------------

    async def update_account(
        self,
        actor: Account,
        account: Account,
        *,
        username: str | None = None,
        email: str | None = None,
        is_active: bool | None = None,
    ) -> Account:
        """Applies only the fields given; all checks run before anything changes."""
        if account.is_protected:
            raise AdminError(f"Account '{account.username}' is protected and cannot be edited")
        if username is not None and username != account.username:
            await self._ensure_unique(Account.username, username, account.id, f"Username '{username}' is already in use")
        if email is not None and email.lower() != account.email.lower():
            await self._ensure_unique(Account.email, email, account.id, f"Email '{email}' is already in use")
        if is_active is False and account.id == actor.id:
            raise AdminError("You cannot disable your own account")

        if username is not None:
            account.username = username
        if email is not None:
            account.email = email
        if is_active is not None:
            account.is_active = is_active
            if not is_active:
                # SessionService.resolve already refuses inactive accounts;
                # dropping the rows makes the logout immediate and final.
                await self._session.execute(delete(AuthSession).where(AuthSession.account_id == account.id))
        await self._session.commit()
        return account

    async def delete_account(self, actor: Account, account: Account) -> None:
        if account.is_protected:
            raise AdminError(f"Account '{account.username}' is protected and cannot be deleted")
        if account.id == actor.id:
            raise AdminError("You cannot delete your own account")
        await self._session.delete(account)
        await self._session.commit()

    async def assign_role(self, account: Account, role: Role) -> Account:
        if role not in account.roles:
            account.roles.append(role)
            await self._session.commit()
        return account

    async def remove_role(self, actor: Account, account: Account, role: Role) -> Account:
        if account.is_protected:
            raise AdminError(f"Account '{account.username}' is protected; its roles cannot be removed")
        if account.id == actor.id:
            self._ensure_keeps_admin(actor, [r for r in actor.roles if r.id != role.id])
        account.roles = [r for r in account.roles if r.id != role.id]
        await self._session.commit()
        return account

    # --- roles ---------------------------------------------------------------

    async def create_role(self, name: str, description: str | None) -> Role:
        await self._ensure_unique(Role.name, name, None, f"Role name '{name}' is already in use")
        role = Role(name=name, description=description)
        self._session.add(role)
        await self._session.commit()
        # Fresh row: load its (empty) relationships so callers can read them.
        await self._session.refresh(role, ["accounts", "permissions"])
        return role

    async def update_role(self, role: Role, *, name: str | None = None, description: str | None = None) -> Role:
        if name is not None and name != role.name:
            if role.name == ADMIN_ROLE:
                raise AdminError(f"Role '{ADMIN_ROLE}' cannot be renamed")
            await self._ensure_unique(Role.name, name, role.id, f"Role name '{name}' is already in use")
            role.name = name
        if description is not None:
            role.description = description or None
        await self._session.commit()
        return role

    async def delete_role(self, actor: Account, role: Role) -> None:
        if role.name == ADMIN_ROLE:
            raise AdminError(f"Role '{ADMIN_ROLE}' cannot be deleted")
        self._ensure_keeps_admin(actor, [r for r in actor.roles if r.id != role.id])
        await self._session.delete(role)
        await self._session.commit()

    async def grant_permission(self, role: Role, permission_name: str) -> Role:
        if permission_name not in ALL_PERMISSIONS:
            raise NotFoundError(f"Unknown permission: {permission_name}")
        permission = await self._session.scalar(select(Permission).where(Permission.name == permission_name))
        if permission is None:  # known to the code but not seeded yet
            permission = Permission(name=permission_name, description=ALL_PERMISSIONS[permission_name])
            self._session.add(permission)
        if permission not in role.permissions:
            role.permissions.append(permission)
            await self._session.commit()
        return role

    async def revoke_permission(self, actor: Account, role: Role, permission_name: str) -> Role:
        if role.name == ADMIN_ROLE:
            raise AdminError(f"Role '{ADMIN_ROLE}' always holds every permission")
        if permission_name == ADMIN_MANAGE and any(r.id == role.id for r in actor.roles):
            others = [r for r in actor.roles if r.id != role.id]
            if not any(ADMIN_MANAGE in {p.name for p in r.permissions} for r in others):
                raise AdminError("That would remove your own admin access")
        role.permissions = [p for p in role.permissions if p.name != permission_name]
        await self._session.commit()
        return role

    # --- invites -------------------------------------------------------------

    async def revoke_invite(self, invite_id: int) -> None:
        invite = await self._get(InviteCode, invite_id, "Invite")
        if invite.used_at is not None:
            raise AdminError("That invite was already used")
        await self._session.delete(invite)
        await self._session.commit()

    # --- helpers -------------------------------------------------------------

    async def _get(self, model, row_id: int, label: str):
        # A query, not session.get(): get() returns an identity-map hit as is,
        # and a Role first loaded through account.roles has its own
        # relationships unloaded (selectin stops at the cycle). A query runs
        # the selectin loaders for whatever is still missing.
        row = await self._session.scalar(select(model).where(model.id == row_id))
        if row is None:
            raise NotFoundError(f"{label} not found")
        return row

    async def _ensure_unique(self, column, value: str, own_id: int | None, message: str) -> None:
        query = select(column.class_.id).where(func.lower(column) == value.lower())
        if own_id is not None:
            query = query.where(column.class_.id != own_id)
        if await self._session.scalar(query) is not None:
            raise AdminError(message)

    @staticmethod
    def _ensure_keeps_admin(actor: Account, remaining_roles: list[Role]) -> None:
        if ADMIN_MANAGE not in {p.name for r in remaining_roles for p in r.permissions}:
            raise AdminError("That would remove your own admin access")
