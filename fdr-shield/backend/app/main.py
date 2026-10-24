from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.core.database import init_db
from app.core.middleware import AuditMiddleware, add_request_id
from app.core.exceptions import register_exception_handlers
from app.api.v1.router import api_router

async def on_startup():
    await init_db()
    try:
        import asyncio
        from app.integrations.storage_client import ensure_bucket
        await asyncio.to_thread(ensure_bucket)
    except Exception: pass
async def health(): return {'status':'ok'}
def create_app()->FastAPI:
    app=FastAPI(title='FDR-Shield',version='1.0.0')
    settings=get_settings()
    app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in settings.cors_origins.split(',')],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])
    app.add_middleware(AuditMiddleware); app.middleware('http')(add_request_id)
    register_exception_handlers(app); app.include_router(api_router,prefix='/api/v1')
    app.add_api_route('/health',health,methods=['GET']); app.add_event_handler('startup',on_startup)
    return app
app=create_app()
