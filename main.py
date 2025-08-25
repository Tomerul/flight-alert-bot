from datetime import datetime, timedelta
import os, smtplib, ssl, requests
from email.message import EmailMessage

# ======= הגדרות מסלול (תעדכן לפי הצורך) =======
ORIGIN = "TLV"             # מוצא
DESTINATION = "LHR"        # יעד
CENTER_DATE = "2025-10-10" # תאריך מרכזי (YYYY-MM-DD)
WINDOW_DAYS = 3            # ± ימים סביב התאריך
MAX_PRICE = 1200           # סף מחיר ב-ILS
ADULTS = 1                 # מספר מבוגרים
CURRENCY = "ILS"
FILTER_AIRLINE = "LY"      # אל-על (LY). אם לא רוצים סינון - השאר ריק: ""
# ===============================================

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

def search_day(origin, destination, date_str, adults=1, currency="ILS"):
    """חיפוש הצעות ליום אחד, מחזיר רשימת offers (או ריק)."""
    token = get_amadeus_token()
    url = "https://test.api.amadeus.com/v2/shopping/flight-offers"
    payload = {
        "currencyCode": currency,
        "originDestinations": [{
            "id": "1",
            "originLocationCode": origin,
            "destinationLocationCode": destination,
            "departureDateTimeRange": { "date": date_str }
        }],
        "travelers": [{"id": "1", "travelerType": "ADULT"}] if adults == 1 else
                     [{"id": str(i+1), "travelerType": "ADULT"} for i in range(adults)],
        "sources": ["GDS"]
    }
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.post(url, json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json().get("data", []) or []

def is_offer_on_airline(offer, airline_code):
    """בודק אם ההצעה כוללת את חברת התעופה (למשל LY)."""
    if not airline_code:
        return True
    if airline_code in (offer.get("validatingAirlineCodes") or []):
        return True
    for itin in offer.get("itineraries", []):
        for seg in itin.get("segments", []):
            if seg.get("carrierCode") == airline_code:
                return True
    return False

def main():
    # בניית טווח תאריכים סביב CENTER_DATE
    center = datetime.fromisoformat(CENTER_DATE)
    days = [(center + timedelta(days=off)).strftime("%Y-%m-%d")
            for off in range(-WINDOW_DAYS, WINDOW_DAYS + 1)]

    best = None
    for d in days:
        try:
            offers = search_day(ORIGIN, DESTINATION, d, adults=ADULTS, currency=CURRENCY)
        except Exception as e:
            print(f"⚠️ שגיאה ביום {d}: {e}")
            continue

        for offer in offers:
            if not is_offer_on_airline(offer, FILTER_AIRLINE):
                continue
            price_str = offer.get("price", {}).get("grandTotal")
            if not price_str:
                continue
            price = float(price_str)
            if best is None or price < best["price"]:
                best = {"date": d, "price": price}

    if best and best["price"] <= MAX_PRICE:
        subject = "✈️ נמצא מחיר נמוך באל-על!"
        body = (
            f"מסלול: {ORIGIN} → {DESTINATION}\n"
            f"תאריך: {best['date']}\n"
            f"מחיר: {best['price']:.0f} {CURRENCY} (סף: {MAX_PRICE:.0f} {CURRENCY})\n"
            f"הודעה זו נשלחה אוטומטית מהבוט ב-GitHub Actions."
        )
        send_email(subject, body)
        print("✅ נשלחה התראה במייל:", best)
    else:
        print("ℹ️ לא נמצא מחיר נמוך מהסף. Best:", best)

if __name__ == "__main__":
    main()
