from datetime import datetime, timedelta
import os, smtplib, ssl, requests, yaml, sys, traceback
from email.message import EmailMessage

# ---------- Email ----------
def send_email(subject: str, body: str):
    host = os.environ.get("EMAIL_HOST", "")
    port = int(os.environ.get("EMAIL_PORT", "465"))
    user = os.environ.get("EMAIL_USER", "")
    password = os.environ.get("EMAIL_PASS", "")
    to_addr = os.environ.get("EMAIL_TO", "")
    from_addr = os.environ.get("EMAIL_FROM", user or "bot@example.com")

    if not all([host, user, password, to_addr]):
        print("⚠️ חסרים פרטי SMTP (EMAIL_*). לא נשלח מייל.")
        print(f"host={bool(host)}, user={bool(user)}, pass={bool(password)}, to={bool(to_addr)}")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=context) as server:
        server.login(user, password)
        server.send_message(msg)

# ---------- Config ----------
def expect_config_example():
    return """\
currency: ILS
adults: 2
route:
  origin: TLV
  destination: JFK
  depart_center_date: 2025-11-20
  depart_window_days: 3
  return_center_date: 2025-12-05
  return_window_days: 3
  max_price: 2300
  airline: LY
  min_stay_days: 1
  max_stay_days: 30
"""

def load_config():
    path = "config.yaml"
    if not os.path.exists(path):
        raise FileNotFoundError("לא נמצא config.yaml בשורש הריפו.\nדוגמה נכונה:\n" + expect_config_example())
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict) or "route" not in cfg or not isinstance(cfg["route"], dict):
        raise ValueError("config.yaml לא תקין (חסר מפתח route או מבנה לא נכון).\nדוגמה:\n" + expect_config_example())
    # בדיקה בסיסית למפתחות חיוניים
