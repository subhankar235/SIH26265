import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.core.middleware import AuditMiddleware, CSRFMiddleware, add_request_id
from app.core.exceptions import register_exception_handlers
from app.api.v1.router import api_router

logger = logging.getLogger(__name__)

async def on_startup():
    try:
        import asyncio
        from app.integrations.storage_client import ensure_bucket
        await asyncio.to_thread(ensure_bucket)
    except Exception:
        logger.exception('Document storage initialization failed.')
        raise
async def health(): return {'status':'ok'}
def create_app()->FastAPI:
    app=FastAPI(title='NidhiTrack',version='1.0.0')
    settings=get_settings()
    origins={x.strip() for x in settings.cors_origins.split(',') if x.strip()}
    if settings.frontend_origin.strip():
        origins.add(settings.frontend_origin.strip())
    app.add_middleware(AuditMiddleware); app.add_middleware(CSRFMiddleware); app.middleware('http')(add_request_id)
    app.add_middleware(CORSMiddleware,allow_origins=sorted(origins),allow_credentials=True,allow_methods=['GET','POST','PUT','PATCH','DELETE','OPTIONS'],allow_headers=['*'],expose_headers=['X-Request-ID','Authorization'],max_age=86400)
    register_exception_handlers(app); app.include_router(api_router,prefix='/api/v1')
    app.add_api_route('/health',health,methods=['GET']); app.add_event_handler('startup',on_startup)
    return app
app=create_app()
