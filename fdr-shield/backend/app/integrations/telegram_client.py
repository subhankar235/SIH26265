"""Free replacement for paid WhatsApp APIs."""


async def send_message(chat_id: str, text: str) -> bool:
    # POST https://api.telegram.org/bot<TOKEN>/sendMessage via httpx
    import httpx
    from app.core.config import get_settings
    token=get_settings().telegram_bot_token
    if not token:return False
    async with httpx.AsyncClient(timeout=5) as c:
        try:r=await c.post(f'https://api.telegram.org/bot{token}/sendMessage',json={'chat_id':chat_id,'text':text});return r.is_success
        except Exception:return False
