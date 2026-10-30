import asyncio
from app.services.notification_service import stage_for

def test_maturity_stage_boundaries():
    assert asyncio.run(stage_for(91)) is None
    assert asyncio.run(stage_for(90)).value=='T-90'
    assert asyncio.run(stage_for(30)).value=='T-30'
    assert asyncio.run(stage_for(0)).value=='T-0'
