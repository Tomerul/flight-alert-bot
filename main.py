from datetime import datetime, timedelta
import os, smtplib, ssl, requests, yaml
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

def get_amadeus_token():
    url = "https://test.api.amadeus.com/v1/security/oauth2/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": os.environ["AMADEUS_API_KEY"],
        "client_secret": os.environ["AMADEUS_API_SECRET"],
    }
    r = requests.post(url, data=data, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]

def amadeus_roundtrip_offers(token, origin, destination, depart_date, return_date, adults=1, currency="ILS"):
    """
    בקשת הלוך-חזור: שני originDestinations — יציאה וחזרה.
    """
    url = "https://test.api.amadeus.com/v2/shopping/flight-offers"
    payload = {
        "currencyCode": currency,
        "originDestinations": [
            {   # יציאה
                "id": "1",
                "originLocationCode": origin,
                "destinationLocationCode": destination,
                "departureDateTimeRange": {"date": depart_date}
            },
            {   # חזרה
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
    r.raise_for_status()
    return r.json().get("data", []) or []

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

def main():
    # --- טוען קונפיג ---
    with open("config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    currency = cfg.get("currency", "ILS")
    adults = int(cfg.get("adults", 1))
    r = cfg.get("route", {})
    origin = r["origin"]
    destination = r["destination"]
    depart_center = r["depart_center_date"]
    depart_win = int(r.get("depart_window_days", 3))
    return_center = r["return_center_date"]
    return_win = int(r.get("return_window_days", 3))
    max_price = float(r["max_price"])
    airline = (r.get("airline") or "").strip()
    min_stay = int(r.get("min_stay_days", 0))
    max_stay = int(r.get("max_stay_days", 3650))  # ברירת מחדל: בלי מגבלה

    depart_days = date_list(depart_center, depart_win)
    return_days = date_list(return_center, return_win)

    token = get_amadeus_token()
    best = None

    for d_out in depart_days:
        d_out_dt = datetime.fromisoformat(d_out)
        for d_back in return_days:
            d_back_dt = datetime.fromisoformat(d_back)
            stay = (d_back_dt - d_out_dt).days
            if stay < min_stay or stay > max_stay:
                continue
            if d_back_dt <= d_out_dt:
                continue  # לא חוזרים לפני שיוצאים

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
        print("✅ נשלחה התראה במייל:", best)
    else:
        print("ℹ️ לא נמצאה עסקה מתחת לסף. Best:", best)

if __name__ == "__main__":
    main()
