"""Fixtures: async test client, in-memory/sqlite or test-postgres session, auth token factories per role."""
import os

# Never let developer .env credentials trigger real provider traffic during pytest.
os.environ['COMMAND_LLM_ENABLED'] = 'false'
os.environ['OCR_ENGINE'] = 'disabled'
os.environ.setdefault('JWT_SECRET', 'test-only-signing-secret-not-for-deployment-98f1')
