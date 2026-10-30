"""Aggregates all v1 routers."""

from fastapi import APIRouter
from . import auth, admin, institutions, fdrs, documents, verification, notifications, refunds, dashboard, audit, workflows, commands


api_router = APIRouter()
api_router.include_router(auth.router,prefix='/auth',tags=['auth'])
api_router.include_router(admin.router,prefix='/admin',tags=['admin'])
api_router.include_router(workflows.router,prefix='/workflows',tags=['workflows'])
api_router.include_router(commands.router,prefix='/commands',tags=['commands'])
api_router.include_router(institutions.router,prefix='/institutions',tags=['institutions'])
api_router.include_router(institutions.router,prefix='/institution',tags=['institution'])
api_router.include_router(fdrs.router,prefix='/fdrs',tags=['fdrs'])
api_router.include_router(documents.router,prefix='/documents',tags=['documents'])
api_router.include_router(verification.router,prefix='/verification',tags=['verification'])
api_router.include_router(notifications.router,prefix='/notifications',tags=['notifications'])
api_router.include_router(refunds.router,prefix='/refunds',tags=['refunds'])
api_router.include_router(dashboard.router,prefix='/dashboard',tags=['dashboard'])
api_router.include_router(audit.router,prefix='/audit',tags=['audit'])
