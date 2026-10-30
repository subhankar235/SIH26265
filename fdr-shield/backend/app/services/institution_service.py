"""Institution business logic."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func
from app.models.institution import Institution
from app.models.fdr import FDR
from app.models.user import User
from app.core.enums import Role
from app.services.audit_service import record
from app.core.exceptions import NotFound
from app.schemas.institution import InstitutionCreate
from app.core.deps import Pagination


async def create_institution(session: AsyncSession, data: InstitutionCreate, actor: User) -> Institution:
    # Create the organization and send a single-use invitation instead of assigning a shared password.
    from app.schemas.auth import AdminUserCreate
    from app.services.user_admin_service import create_user
    inst=Institution(**data.model_dump(), status='active');session.add(inst);await session.flush()
    await create_user(session, AdminUserCreate(email=inst.contact_email, full_name=inst.head_name,
        role=Role.INSTITUTION.value, institution_id=inst.id), actor)
    await record(session,actor.id,'institution',inst.id,'created','',{'aicte_id':[None,inst.aicte_id]});return inst


async def search_institutions(session: AsyncSession, q: str | None, state: str | None, page: Pagination) -> list[Institution]:
    # ILIKE search + aggregate fdr_count / total_value
    term=q; stmt=select(Institution)
    if state:stmt=stmt.where(Institution.state.ilike(f'%{state}%'))
    if term:stmt=stmt.where(or_(Institution.name.ilike(f'%{term}%'),Institution.aicte_id.ilike(f'%{term}%')))
    return list((await session.scalars(stmt.offset(page.skip).limit(page.limit))).all())


async def get_institution(session: AsyncSession, institution_id: int) -> Institution:
    # Load or raise NotFound
    item=await session.get(Institution,institution_id)
    if not item:raise NotFound('Institution not found')
    return item


async def list_institution_fdrs(session: AsyncSession, institution_id: int, page: Pagination) -> list[FDR]:
    query = select(FDR).where(FDR.institution_id == institution_id).order_by(FDR.maturity_date)
    return list((await session.scalars(query.offset(page.skip).limit(page.limit))).all())
