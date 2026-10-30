"""Opt-in live integration: FDR_INTEGRATION_URL=http://localhost:8000 pytest -q."""
import asyncio
import os

import pytest

from scripts import demo_flow


@pytest.mark.skipif(not os.getenv('FDR_INTEGRATION_URL'), reason='Live Compose services are not enabled')
def test_submit_verify_approve_alert_and_refund_live():
    demo_flow.API = os.environ['FDR_INTEGRATION_URL']
    demo_flow.MAILHOG = os.getenv('MAILHOG_URL', 'http://localhost:8025')
    asyncio.run(demo_flow.main())
