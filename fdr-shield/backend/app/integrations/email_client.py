"""SMTP email (Mailhog in dev, Gmail/Brevo free SMTP in prod)."""


async def send_email(to: str, subject: str, html_body: str) -> bool:
    # aiosmtplib send; return success flag
    import aiosmtplib
    from email.message import EmailMessage
    from app.core.config import get_settings
    msg=EmailMessage();msg['From']='fdr-shield@localhost';msg['To']=to;msg['Subject']=subject;msg.set_content('FDR Shield alert');msg.add_alternative(html_body,subtype='html')
    try: await aiosmtplib.send(msg,hostname=get_settings().smtp_host,port=get_settings().smtp_port);return True
    except Exception:return False
