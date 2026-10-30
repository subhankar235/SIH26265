"""Demo WhatsApp gateway (prints/logs + stores to DB). Swap for Twilio/Gupshup later."""


async def send_whatsapp(phone: str, text: str) -> bool:
    # Log message, append to demo outbox table/file visible in UI; return True
    import json
    from pathlib import Path
    path=Path('/tmp/fdr-whatsapp-outbox.jsonl');path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8') as f:f.write(json.dumps({'phone':phone,'text':text})+'\n')
    return True
