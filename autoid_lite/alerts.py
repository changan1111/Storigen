import json, os, smtplib, urllib.request
from email.message import EmailMessage

def send_alert(text: str):
    """Webhook (Teams/Slack-style {"text":...}) and/or email. Never raises."""
    url = os.getenv("ALERT_WEBHOOK_URL")
    if url:
        try: urllib.request.urlopen(urllib.request.Request(url, data=json.dumps({"text": "Auto-ID: " + text}).encode(),
                                    headers={"Content-Type": "application/json"}), timeout=10)
        except Exception: pass
    host, to = os.getenv("SMTP_HOST"), os.getenv("ALERT_EMAIL_TO")
    if host and to:
        try:
            m = EmailMessage(); m["Subject"] = "Auto-ID alert"; m["From"] = os.getenv("ALERT_EMAIL_FROM", "autoid@localhost"); m["To"] = to
            m.set_content(text)
            with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "25")), timeout=10) as s:
                if os.getenv("SMTP_STARTTLS") == "1": s.starttls()
                if os.getenv("SMTP_USER"): s.login(os.environ["SMTP_USER"], os.getenv("SMTP_PASSWORD", ""))
                s.send_message(m)
        except Exception: pass

def send_ready(text: str):
    """v10.2.0: tell a chat (Teams / Slack style webhook, {"text": ...}) that a clip is ready. Off unless READY_WEBHOOK_URL is set. It has its own address so the alert channel for failures stays quiet. Never raises."""
    url = os.getenv("READY_WEBHOOK_URL")
    if not url: return
    try: urllib.request.urlopen(urllib.request.Request(url, data=json.dumps({"text": text}).encode(), headers={"Content-Type": "application/json"}), timeout=10)
    except Exception: pass
