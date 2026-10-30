# AGENTS.md
Read 01_HLD_LLD.md and 02_MODULE_GUIDE.md before any change.
Rules:
- Backend: FastAPI, async SQLAlchemy 2.0. Routers -> services -> models/integrations. No DB calls in routers.
- Use enums from app/core/enums.py. Keep the data contracts in 02_MODULE_GUIDE.md section 4.2 unchanged.
- Only free/open-source tools. Bank access ONLY via backend/mock_bank_api (demo). Never call real bank or paid APIs.
- Every state change calls audit_service.record in the same transaction. audit_logs is append-only.
- After each module: run pytest (backend) and npm run build (frontend). Fix failures before moving on.
- Replace stubs completely; no leftover NotImplementedError or "Not implemented" in finished modules.
- Update the docs if you change a contract.