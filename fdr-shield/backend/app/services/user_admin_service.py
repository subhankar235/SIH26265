"""Admin-only user and institution-registration lifecycle operations."""
from datetime import timedelta
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import AccountStatus, Role
from app.core.exceptions import NotFound, InvalidStateTransition, PermissionDenied
from app.core.config import get_settings
from app.models.auth_records import RefreshToken
from app.models.institution import Institution
from app.models.user import User
from app.schemas.auth import AdminUserCreate, AdminUserUpdate
from app.services import auth_service
from app.services.audit_service import record
from app.integrations.email_client import send_email


def validate_role_institution(role: str, institution_id: int | None) -> None:
    if role not in {item.value for item in Role}:
        raise ValueError('Unknown role.')
    if (role == Role.INSTITUTION.value) != (institution_id is not None):
        raise ValueError('Institution accounts require an institution; staff accounts must not have one.')


async def _invite(session: AsyncSession, user: User) -> None:
    token = await auth_service.issue_one_time_token(session, user, 'INVITE', timedelta(hours=72))
    cfg = get_settings()
    await send_email(user.email, 'FDR-Shield account invitation',
        f'<p>Set your password: <a href="{cfg.frontend_origin}/accept-invite?token={token}">Accept invitation</a></p>')


async def create_user(session: AsyncSession, data: AdminUserCreate, actor: User) -> User:
    email = str(data.email).lower()
    validate_role_institution(data.role, data.institution_id)
    if await session.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise ValueError('An account with this email already exists.')
    if data.institution_id and not await session.get(Institution, data.institution_id):
        raise NotFound('Institution not found.')
    user = User(email=email, full_name=data.full_name, password_hash=None, role=data.role,
        institution_id=data.institution_id, status=AccountStatus.INVITED.value,
        is_active=False, created_by=actor.id)
    session.add(user)
    await session.flush()
    await _invite(session, user)
    await record(session, actor.id, 'user', user.id, 'USER_INVITED', '', {'role': [None, user.role], 'status': [None, user.status]})
    return user


async def list_users(session: AsyncSession, role: str | None, status: str | None,
                     query: str | None, page) -> list[User]:
    stmt = select(User).order_by(User.id.desc())
    if role: stmt = stmt.where(User.role == role)
    if status: stmt = stmt.where(User.status == status)
    if query:
        term = f'%{query.strip()}%'
        stmt = stmt.where((User.email.ilike(term)) | (User.full_name.ilike(term)))
    return list((await session.scalars(stmt.offset(page.skip).limit(page.limit))).all())


async def list_pending_registrations(session: AsyncSession, role: str, page, *, include_decided: bool = False) -> list[User]:
    if role not in {Role.INSTITUTION.value, Role.AICTE_OFFICIAL.value}:
        raise ValueError('Only Institution and AICTE Official applications are reviewable.')
    stmt = select(User).where(User.role == role)
    if include_decided:
        stmt = stmt.where(User.created_by.is_(None))
    else:
        stmt = stmt.where(User.status.in_([
            AccountStatus.PENDING_APPROVAL.value,
            AccountStatus.PENDING_EMAIL_VERIFY.value,
        ]))
    stmt = stmt.order_by(User.created_at, User.id)
    return list((await session.scalars(stmt.offset(page.skip).limit(page.limit))).all())


async def list_institution_registration_history(session: AsyncSession, page) -> list[User]:
    """Return public Institution applications for Super Admin oversight."""
    stmt = select(User).where(User.role == Role.INSTITUTION.value,
        User.created_by.is_(None)).order_by(User.created_at.desc(), User.id.desc())
    return list((await session.scalars(stmt.offset(page.skip).limit(page.limit))).all())


async def update_user(session: AsyncSession, user_id: int, data: AdminUserUpdate, actor: User) -> User:
    target = await session.get(User, user_id)
    if not target: raise NotFound('User not found.')
    updates = data.model_dump(exclude_unset=True)
    next_role = updates.get('role', target.role)
    next_institution = updates.get('institution_id', target.institution_id)
    validate_role_institution(next_role, next_institution)
    if target.id == actor.id and ('role' in updates or 'institution_id' in updates):
        raise InvalidStateTransition('You cannot change your own role or institution.')
    if target.role == Role.ADMIN.value and next_role != Role.ADMIN.value and target.status == AccountStatus.ACTIVE.value:
        admins = await session.scalar(select(func.count(User.id)).where(
            User.role == Role.ADMIN.value, User.status == AccountStatus.ACTIVE.value, User.is_active.is_(True)))
        if (admins or 0) <= 1:
            raise InvalidStateTransition('Cannot remove the last active Admin.')
    if next_institution and not await session.get(Institution, next_institution):
        raise NotFound('Institution not found.')
    old = {'full_name': target.full_name, 'role': target.role, 'institution_id': target.institution_id}
    if 'full_name' in updates: target.full_name = updates['full_name']
    target.role, target.institution_id = next_role, next_institution
    if old['role'] != target.role or old['institution_id'] != target.institution_id:
        target.session_version += 1
    action = 'ROLE_CHANGED' if old['role'] != target.role else 'USER_UPDATED'
    await record(session, actor.id, 'user', target.id, action, '',
        {key: [old[key], getattr(target, key)] for key in old if old[key] != getattr(target, key)})
    return target


async def set_user_active(session: AsyncSession, user_id: int, active: bool, actor: User) -> User:
    target = await session.get(User, user_id)
    if not target: raise NotFound('User not found.')
    if active and target.status not in {AccountStatus.DISABLED.value, AccountStatus.SUSPENDED.value, AccountStatus.ACTIVE.value}:
        raise InvalidStateTransition('Only disabled or suspended accounts can be re-enabled; pending, rejected, and locked accounts must follow their dedicated workflow.')
    if target.id == actor.id and not active:
        raise InvalidStateTransition('You cannot disable your own account.')
    if not active and target.role == Role.ADMIN.value and target.status == AccountStatus.ACTIVE.value:
        admins = await session.scalar(select(func.count(User.id)).where(
            User.role == Role.ADMIN.value, User.status == AccountStatus.ACTIVE.value, User.is_active.is_(True)))
        if (admins or 0) <= 1:
            raise InvalidStateTransition('Cannot disable the last active Admin.')
    previous = target.status
    target.status = AccountStatus.ACTIVE.value if active else AccountStatus.DISABLED.value
    target.is_active = active
    target.session_version += 1
    if not active:
        await session.execute(RefreshToken.__table__.update().where(RefreshToken.user_id == target.id,
            RefreshToken.revoked_at.is_(None)).values(revoked_at=auth_service.utcnow()))
    await record(session, actor.id, 'user', target.id, 'USER_ENABLED' if active else 'USER_DISABLED', '',
        {'status': [previous, target.status]})
    return target


async def suspend_user(session: AsyncSession, user_id: int, actor: User) -> User:
    target = await session.get(User, user_id)
    if not target: raise NotFound('User not found.')
    if target.id == actor.id:
        raise InvalidStateTransition('You cannot suspend your own account.')
    if target.role == Role.ADMIN.value and target.status == AccountStatus.ACTIVE.value:
        count = await session.scalar(select(func.count(User.id)).where(
            User.role == Role.ADMIN.value, User.status == AccountStatus.ACTIVE.value, User.is_active.is_(True)))
        if (count or 0) <= 1:
            raise InvalidStateTransition('Cannot suspend the last active Super Admin.')
    previous = target.status
    target.status = AccountStatus.SUSPENDED.value
    target.is_active = False
    target.session_version += 1
    await session.execute(RefreshToken.__table__.update().where(RefreshToken.user_id == target.id,
        RefreshToken.revoked_at.is_(None)).values(revoked_at=auth_service.utcnow()))
    await record(session, actor.id, 'user', target.id, 'USER_SUSPENDED', '',
        {'status': [previous, target.status]})
    return target


async def unlock_user(session: AsyncSession, user_id: int, actor: User) -> User:
    target = await session.get(User, user_id)
    if not target: raise NotFound('User not found.')
    if target.status == AccountStatus.LOCKED.value:
        target.status = AccountStatus.ACTIVE.value
        target.is_active = True
        target.failed_login_count = 0
        target.locked_until = None
    await record(session, actor.id, 'user', target.id, 'ACCOUNT_UNLOCKED', '', {})
    return target


async def decide_registration(session: AsyncSession, user_id: int, approved: bool,
                              reason: str | None, actor: User, *, override: bool = False) -> User:
    target = await session.scalar(select(User).where(User.id == user_id).with_for_update())
    if not target or target.role not in {Role.INSTITUTION.value, Role.AICTE_OFFICIAL.value}:
        raise NotFound('Registration application not found.')
    if target.role == Role.AICTE_OFFICIAL.value and actor.role != Role.ADMIN.value:
        raise PermissionDenied('Only a Super Admin may review AICTE Official applications.')
    if target.role == Role.INSTITUTION.value and actor.role not in {Role.ADMIN.value, Role.AICTE_OFFICIAL.value}:
        raise PermissionDenied('Only an AICTE Official or Super Admin may review Institution applications.')
    previous_status = target.status
    if override:
        if actor.role != Role.ADMIN.value:
            raise PermissionDenied('Only a Super Admin may override an application decision.')
        if target.role not in {Role.INSTITUTION.value, Role.AICTE_OFFICIAL.value}:
            raise InvalidStateTransition('Only public applications can be overridden.')
        if target.created_by is not None:
            raise InvalidStateTransition('Only a public application may be overridden.')
        if target.status not in {AccountStatus.ACTIVE.value, AccountStatus.REJECTED.value, AccountStatus.DISABLED.value,
                                 AccountStatus.PENDING_APPROVAL.value}:
            raise InvalidStateTransition('Only a previously reviewed application can be overridden.')
    elif target.status not in {
        AccountStatus.PENDING_APPROVAL.value,
        AccountStatus.PENDING_EMAIL_VERIFY.value,
    }:
        raise NotFound('Pending registration not found.')

    institution = await session.get(Institution, target.institution_id) if target.role == Role.INSTITUTION.value else None
    if target.role == Role.INSTITUTION.value and not institution:
        raise NotFound('Institution registration record not found.')
    if approved:
        target.status = AccountStatus.ACTIVE.value
        target.is_active = True
        if institution:
            institution.status = 'active'
        if previous_status != AccountStatus.ACTIVE.value:
            target.session_version += 1
        await send_email(target.email, 'FDR-Shield account approved',
            '<p>Your application is approved. You may now sign in.</p>')
    else:
        target.status = AccountStatus.REJECTED.value
        target.is_active = False
        if institution: institution.status = 'rejected'
        target.session_version += 1
        await session.execute(RefreshToken.__table__.update().where(RefreshToken.user_id == target.id,
            RefreshToken.revoked_at.is_(None)).values(revoked_at=auth_service.utcnow()))
        await send_email(target.email, 'FDR-Shield registration update',
            f'<p>Your registration was not approved. Reason: {reason or "Not specified"}</p>')
    action = ('REGISTRATION_DECISION_OVERRIDDEN' if override else
              'REGISTRATION_APPROVED' if approved else 'REGISTRATION_REJECTED')
    await record(session, actor.id, 'user', target.id, action, '',
        {'status': [previous_status, target.status], 'decision': [None, 'approve' if approved else 'reject'],
         'reason': [None, reason], 'role': [target.role, target.role]})
    return target


async def approve_registration(session: AsyncSession, user_id: int, approved: bool,
                               reason: str | None, actor: User) -> User:
    """Compatibility wrapper for existing admin Institution-registration endpoints."""
    return await decide_registration(session, user_id, approved, reason, actor)


async def reset_user_password(session: AsyncSession, user_id: int, actor: User) -> None:
    target = await session.get(User, user_id)
    if not target: raise NotFound('User not found.')
    raw = await auth_service.issue_one_time_token(session, target, 'RESET_PASSWORD', timedelta(minutes=30))
    cfg = get_settings()
    await send_email(target.email, 'Reset your FDR-Shield password',
        f'<p>Reset your password: <a href="{cfg.frontend_origin}/reset-password?token={raw}">Reset password</a></p>')
    await record(session, actor.id, 'user', target.id, 'PASSWORD_RESET_REQUESTED', '', {})


async def revoke_sessions(session: AsyncSession, user_id: int, actor: User) -> None:
    target = await session.get(User, user_id)
    if not target: raise NotFound('User not found.')
    target.session_version += 1
    await session.execute(RefreshToken.__table__.update().where(RefreshToken.user_id == target.id,
        RefreshToken.revoked_at.is_(None)).values(revoked_at=auth_service.utcnow()))
    await record(session, actor.id, 'user', target.id, 'SESSIONS_REVOKED', '', {})
