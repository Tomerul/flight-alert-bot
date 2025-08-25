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
    r = cfg["route"]
    required = ["origin", "destination", "depart_center_date", "depart_window_days",
                "return_center_date", "return_window_days", "max_price"]
    missing = [k for k in required if k not in r]
    if missing:
        raise ValueError(f"missing keys in route: {missing}\nדוגמה:\n" + expect_config_example())
    return cfg

# ---------- Amadeus ----------
def get_amadeus_token():
    url = "https://test.api.amadeus.com/v1/security/oauth2/token"
    cid = os.environ.get("AMADEUS_API_KEY", "")
    csec = os.environ.get("AMADEUS_API_SECRET", "")
    if not cid or not csec:
        raise RuntimeError("חסרים AMADEUS_API_KEY / AMADEUS_API_SECRET ב-Secrets של GitHub.")
    data = {"grant_type": "client_credentials", "client_id": cid, "client_secret": csec}
    r = requests.post(url, data=data, timeout=30)
    if r.status_code >= 400:
        print("❌ כשל בקבלת טוקן מאמדאוס", r.status_code, r.text[:500])
        r.raise_for_status()
    j = r.json()
    token = j.get("access_token")
    if not token:
        raise RuntimeError(f"לא התקבל access_token מאמדאוס: {j}")
    return token

def amadeus_roundtrip_offers(token, origin, destination, depart_date, return_date, adults=1, currency="ILS"):
    url = "https://test.api.amadeus.com/v2/shopping/flight-offers"
    payload = {
        "currencyCode": currency,
        "originDestinations": [
            {
                "id": "1",
                "originLocationCode": origin,
                "destinationLocationCode": destination,
                "departureDateTimeRange": {"date": depart_date}
            },
            {
                "id": "2",
                "originLocationCode": destination,
                "destinationLocationCode": origin,
                "departureDateTimeRange": {"date": return_date}
            }
        ],
        "travelers": [{"id": str(i+1), "travelerType": "ADULT"} for i in range(adults)],
        "sources": ["GDS"]
    }
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.post(url, json=payload, headers=headers, timeout=60)
    if r.status_code >= 400:
        print(f"❌ כשל בבקשת offers {depart_date}->{return_date}", r.status_code, r.text[:500])
        r.raise_for_status()
    return r.json().get("data", []) or []

# ---------- Helpers ----------
def is_offer_on_airline(offer, airline_code):
    if not airline_code:
        return True
    if airline_code in (offer.get("validatingAirlineCodes") or []):
        return True
    for itin in offer.get("itineraries", []):
        for seg in itin.get("segments", []):
            if seg.get("carrierCode") == airline_code:
                return True
    return False

def date_list(center_iso, window_days):
    center = datetime.fromisoformat(center_iso)
    return [(center + timedelta(days=off)).strftime("%Y-%m-%d")
            for off in range(-window_days, window_days + 1)]

# ---------- Main ----------
def main():
    print("▶️ התחלת ריצה:", datetime.utcnow().isoformat() + "Z")

    cfg = load_config()
    print("DEBUG cfg loaded ok.")

    currency = cfg.get("currency", "ILS")
    adults = int(cfg.get("adults", 1))
    r = cfg["route"]
    origin = r["origin"]
    destination = r["destination"]
    depart_center = r["depart_center_date"]
    depart_win = int(r["depart_window_days"])
    return_center = r["return_center_date"]
    return_win = int(r["return_window_days"])
    max_price = float(r["max_price"])
    airline = (r.get("airline") or "").strip()
    min_stay = int(r.get("min_stay_days", 0))
    max_stay = int(r.get("max_stay_days", 3650))

    depart_days = date_list(depart_center, depart_win)
    return_days = date_list(return_center, return_win)

    token = get_amadeus_token()

    best = None
    for d_out in depart_days:
        d_out_dt = datetime.fromisoformat(d_out)
        for d_back in return_days:
            d_back_dt = datetime.fromisoformat(d_back)
            stay = (d_back_dt - d_out_dt).days
            if d_back_dt <= d_out_dt:      # לא חוזרים לפני שיוצאים
                continue
            if stay < min_stay or stay > max_stay:
                continue

            try:
                offers = amadeus_roundtrip_offers(
                    token, origin, destination, d_out, d_back, adults=adults, currency=currency
                )
            except Exception as e:
                print(f"⚠️ שגיאה בצירוף {d_out}→{d_back}: {e}")
                continue

            for offer in offers:
                if not is_offer_on_airline(offer, airline):
                    continue
                price_str = offer.get("price", {}).get("grandTotal")
                if not price_str:
                    continue
                price = float(price_str)
                if best is None or price < best["price"]:
                    best = {
                        "depart": d_out,
                        "return": d_back,
                        "price": price,
                        "currency": currency
                    }

    if best:
        print(f"BEST found: {origin} ⇄ {destination} | {best['depart']} → {best['return']} | {best['price']} {best['currency']}")
    else:
        print("ℹ️ לא נמצאו הצעות מתאימות בטווחים.")

    if best and best["price"] <= max_price:
        subject = "✈️ נמצא מחיר נמוך (הלוך-חזור)"
        body = (
            f"מסלול: {origin} ⇄ {destination}\n"
            f"תאריכים: יציאה {best['depart']} | חזרה {best['return']}\n"
            f"מחיר כולל: {best['price']:.0f} {best['currency']} (סף: {max_price:.0f} {currency})\n"
            f"נוסעים: {adults} מבוגר/ים\n"
            f"\nנשלח אוטומטית מהבוט (GitHub Actions)."
        )
        send_email(subject, body)
        print("✅ נשלחה התראה במייל.")
    else:
        print("ℹ️ לא נמצאה עסקה מתחת לסף.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("🔥 ERROR:", repr(e))
        traceback.print_exc()
        sys.exit(1)
