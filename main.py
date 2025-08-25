from datetime import datetime, timedelta, date
import os, smtplib, ssl, requests, yaml, sys, traceback, time, json
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
def to_yyyy_mm_dd(value):
    """מחזיר YYYY-MM-DD גם אם value הוא str וגם אם הוא date/datetime"""
    if isinstance(value, str):
        return value
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    raise TypeError(f"Unsupported date type: {type(value)}")

def load_config():
    path = "config.yaml"
    if not os.path.exists(path):
        raise FileNotFoundError("לא נמצא config.yaml בשורש הריפו.")
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict) or "route" not in cfg or not isinstance(cfg["route"], dict):
        raise ValueError("config.yaml לא תקין (חסר מפתח route או מבנה לא נכון).")
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
    r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("לא התקבל access_token מאמדאוס.")
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
    r.raise_for_status()
    return r.json().get("data", []) or []

# ---------- Helpers (פרטים עשירים להצעה + היסטוריה) ----------
import re

def parse_iso_duration(dur):
    # "PT10H5M" -> דקות כוללות
    h = m = 0
    if not isinstance(dur, str):
        return 0
    mH = re.search(r'(\d+)H', dur)
    mM = re.search(r'(\d+)M', dur)
    if mH: h = int(mH.group(1))
    if mM: m = int(mM.group(1))
    return h*60 + m

def offer_details(offer):
    airlines = set()
    total_connections = 0
    total_minutes = 0
    for itin in (offer.get("itineraries") or []):
        total_minutes += parse_iso_duration(itin.get("duration"))
        segs = itin.get("segments") or []
        total_connections += max(0, len(segs) - 1)
        for s in segs:
            cc = s.get("carrierCode")
            if cc: airlines.add(cc)
    return {
        "airlines": sorted(airlines),
        "connections": total_connections,
        "total_duration_minutes": total_minutes
    }

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
    center_str = to_yyyy_mm_dd(center_iso)
    center = datetime.fromisoformat(center_str)
    return [(center + timedelta(days=off)).strftime("%Y-%m-%d")
            for off in range(-window_days, window_days + 1)]

def write_results_json(origin, destination, adults, currency,
                       depart_center, depart_win, return_center, return_win,
                       min_stay, max_stay, best, max_price):
    summary = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "route": {
            "origin": origin,
            "destination": destination,
            "adults": adults,
            "currency": currency
        },
        "search": {
            "depart_center_date": depart_center,
            "depart_window_days": depart_win,
            "return_center_date": return_center,
            "return_window_days": return_win,
            "min_stay_days": min_stay,
            "max_stay_days": max_stay
        },
        "best": best,  # dict או None
        "threshold": max_price,
        "below_threshold": bool(best and best["price"] <= max_price)
    }
    with open("results.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("📝 wrote results.json")

def append_history(entry):
    hist_path = "history.json"
    try:
        history = []
        if os.path.exists(hist_path):
            with open(hist_path, "r", encoding="utf-8") as f:
                history = json.load(f) or []
        history.append(entry)
        history = history[-200:]  # שומר אחרונים
        with open(hist_path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        print(f"🧾 appended to history.json (len: {len(history)})")
    except Exception as e:
        print("⚠️ history append failed:", e)

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
    depart_center = to_yyyy_mm_dd(r["depart_center_date"])
    depart_win = int(r["depart_window_days"])
    return_center = to_yyyy_mm_dd(r["return_center_date"])
    return_win = int(r["return_window_days"])
    max_price = float(r["max_price"])
    airline = (r.get("airline") or "").strip()
    min_stay = int(r.get("min_stay_days", 0))
    max_stay = int(r.get("max_stay_days", 3650))

    depart_days = date_list(depart_center, depart_win)
    return_days = date_list(return_center, return_win)

    total = len(depart_days) * len(return_days)
    print(f"⏱️ נבדוק עד {total} צירופים (יציאה×חזרה).")

    token = get_amadeus_token()

    # דד-ליין פנימי כדי לא להתקע (4 דק')
    deadline = time.monotonic() + 240
    checked = 0

    best = None
    for d_out in depart_days:
        d_out_dt = datetime.fromisoformat(d_out)
        for d_back in return_days:
            if time.monotonic() > deadline:
                print("⏹️ עצרנו בגלל limit של 4 דקות כדי לא להיתקע.")
                # כתיבת תוצאות והיסטוריה לפני יציאה
                write_results_json(origin, destination, adults, currency,
                                   depart_center, depart_win, return_center, return_win,
                                   min_stay, max_stay, best, max_price)
                append_history({
                    "ts": datetime.utcnow().isoformat() + "Z",
                    "origin": origin, "destination": destination,
                    "depart": best["depart"] if best else None,
                    "return": best["return"] if best else None,
                    "price": best["price"] if best else None,
                    "currency": currency,
                    "threshold": max_price,
                    "below_threshold": bool(best and best["price"] <= max_price)
                })
                # אם כבר יש מתחת לסף — שלח מייל לפני היציאה
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
                    print("✅ נשלחה התראה במייל (לפני דד-ליין).")
                else:
                    print("ℹ️ לא נמצאה עסקה מתחת לסף עד הדד-ליין.")
                return

            d_back_dt = datetime.fromisoformat(d_back)
            stay = (d_back_dt - d_out_dt).days
            if d_back_dt <= d_out_dt:
                continue
            if stay < min_stay or stay > max_stay:
                continue

            checked += 1
            if checked % 5 == 0 or checked == 1:
                print(f"…מתקדם: {checked}/{total} (כעת: {d_out}→{d_back})")

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
                det = offer_details(offer)
                if best is None or price < best["price"]:
                    best = {
                        "depart": d_out,
                        "return": d_back,
                        "price": price,
                        "currency": currency,
                        **det
                    }
                # יציאה מוקדמת אם יש מחיר מתחת לסף
                if best and best["price"] <= max_price:
                    print(f"🎯 נמצא מחיר מתחת לסף: {best['depart']}→{best['return']} ({best['price']} {currency}) — יוצאים מוקדם.")
                    write_results_json(origin, destination, adults, currency,
                                       depart_center, depart_win, return_center, return_win,
                                       min_stay, max_stay, best, max_price)
                    append_history({
                        "ts": datetime.utcnow().isoformat() + "Z",
                        "origin": origin, "destination": destination,
                        "depart": best["depart"], "return": best["return"],
                        "price": best["price"], "currency": currency,
                        "threshold": max_price, "below_threshold": True
                    })
                    subject = "✈️ נמצא מחיר נמוך (הלוך-חזור)"
                    body = (
                        f"מסלול: {origin} ⇄ {destination}\n"
                        f"תאריכים: יציאה {best['depart']} | חזרה {best['return']}\n"
                        f"מחיר כולל: {best['price']:.0f} {best['currency']} (סף: {max_price:.0f} {currency})\n"
                        f"נוסעים: {adults} מבוגר/ים\n"
                        f"\nנשלח אוטומטית מהבוט (GitHub Actions)."
                    )
                    send_email(subject, body)
                    print("✅ נשלחה התראה במייל (יציאה מוקדמת).")
                    return

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

    # כתיבת results.json + הוספת שורה להיסטוריה (תמיד)
    write_results_json(origin, destination, adults, currency,
                       depart_center, depart_win, return_center, return_win,
                       min_stay, max_stay, best, max_price)
    append_history({
        "ts": datetime.utcnow().isoformat() + "Z",
        "origin": origin, "destination": destination,
        "depart": best["depart"] if best else None,
        "return": best["return"] if best else None,
        "price": best["price"] if best else None,
        "currency": currency,
        "threshold": max_price,
        "below_threshold": bool(best and best["price"] <= max_price)
    })

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("🔥 ERROR:", repr(e))
        traceback.print_exc()
        sys.exit(1)
