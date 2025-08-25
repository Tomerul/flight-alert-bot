from datetime import datetime
import os, smtplib, ssl
from email.message import EmailMessage

def send_email(subject: str, body: str):
    host = os.environ["EMAIL_HOST"]
    port = int(os.environ.get("EMAIL_PORT", "465"))
    user = os.environ["EMAIL_USER"]
    password = os.environ["EMAIL_PASS"]
    to_addr = os.environ["EMAIL_TO"]
    from_addr = os.environ.get("EMAIL_FROM", user)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=context) as server:
        server.login(user, password)
        server.send_message(msg)

if __name__ == "__main__":
    ts = datetime.utcnow().isoformat() + "Z"
    subject = "Flight bot test"
    body = f"✅ GitHub Actions ran at {ts} (UTC)"
    send_email(subject, body)
    print("✅ Test email sent")
