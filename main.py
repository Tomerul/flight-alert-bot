#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, json, time, traceback
from datetime import datetime, timedelta
import requests
from collections import defaultdict

CONFIG_PATH = os.environ.get("CFG_PATH", "config.yaml")
RESULTS_PATH = os.environ.get("RESULTS_PATH", "site/results.json")
HISTORY_PATH = os.environ.get("HISTORY_PATH", "site/history.json")

# -------------------- Utils --------------------

def log(*a):
    ts = datetime.utcnow().isoformat() + "Z"
    print(ts, *a, flush=True)

def load_yaml(path):
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def append_history(entry):
    try:
        if os.path.exists(HISTORY_PATH):
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                hist = json.load(f)
        else:
            hist = []
    except Exception:
        hist = []
    hist.append(entry)
    save_json(HISTORY_PATH, hist)

# -------------------- Amadeus --------------------

def amadeus_token(client_id, client_secret, env="test"):
    base = "https://test.api.amadeus.com" if env == "test" else "https://api.amadeus.com"
    r = requests.post(f"{base}/v1/security/oauth2/token",
                      data={"grant_type":"client_credentials",
                            "client_id":client_id, "client_secret":client_secret},
                      timeout=20)
    r.raise_for_status()
    return r.json()["access_token"], base

def simplify_offer(offer, origin, destination, currency, adults):
    """Extract key fields from Amadeus flight-offer object."""
    price = float(offer.get("price", {}).get("grandTotal", "0") or 0)
    carriers = set()
    depart_dt = ""
    return_dt = ""
    total_segments = 0

    itineraries = offer.get("itineraries", [])
    if itineraries:
        # OUTBOUND
        out_segs = itineraries[0].get("segments", []) if len(itineraries) > 0 else []
        total_segments += len(out_segs)
        if out_segs:
            depart_dt = out_segs[0]["departure"]["at"]  # 'YYYY-MM-DDTHH:MM:SS'
            for s in out_segs:
                carriers.add(s.get("carrierCode"))
        # INBOUND
        if len(itineraries) > 1:
            ret_segs = itineraries[1].get("segments", [])
            total_segments += len(ret_segs)
            if ret_segs:
                return_dt = ret_segs[0]["departure"]["at"]
                for s in ret_segs:
                    carriers.add(s.get("carrierCode"))

    # connections: segments per leg minus 1 (sum both legs)
    connections = 0
    if itineraries:
        if len(itineraries) >= 1:
            connections += max(0, len(itineraries[0].get("segments", [])) - 1)
        if len(itineraries) >= 2:
            connections += max(0, len(itineraries[1].get("segments", [])) - 1)

    # split ISO to date/time (client-side יודע לקבל גם ISO מלא; עדיין נפריד לנוחות)
    def split_dt(iso):
        if not iso:
            return "", ""
        try:
            dt = datetime.fromisoformat(iso.replace("Z",""))
            return dt.date().isoformat(), dt.strftime("%H:%M")
        except Exception:
            if "T" in iso:
                d,t = iso.split("T",1)
                return d, t[:5]
            return iso, ""

    d_date, d_time = split_dt(depart_dt)
    r_date, r_time = split_dt(return_dt)

    return {
        "airlines": sorted([c for c in carriers if c]),
        "connections": connections,
        "depart": d_date,
        "depart_time": d_time,
        "return": r_date,
        "return_time": r_time,
        "price": price,
        "currency": currency,
        "origin": origin,
        "destination": destination,
        "adults": adults
    }

def amadeus_search_offers(base, token, params, max_results=50, sort_by_price=True):
    """
    Call Amadeus Flight Offers Search; request up to `max_results` offers.
    TEST env לפעמים מחזיר מעט מאוד אופציות – זה תקין לסנדבוקס.
    """
    url = f"{base}/v2/shopping/flight-offers"
    q = {
        "originLocationCode": params["origin"],
        "destinationLocationCode": params["destination"],
        "departureDate": params["depart"],
        "adults": params.get("adults", 1),
        "currencyCode": params.get("currency", "ILS"),
        "max": max(1, min(int(max_results), 250))
    }
    if params.get("ret"):
        q["returnDate"] = params["ret"]
    if params.get("nonStop") is not None:
        q["nonStop"] = "true" if params["nonStop"] else "false"

    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, params=q, headers=headers, timeout=40)
    # אם הייתה חזרה 400/500 – ננסה ללוג ולזרוק חריגה
    try:
        r.raise_for_status()
    except Exception as e:
        log("Amadeus error", r.status_code, r.text[:200])
        raise

    data = r.json()
    offers = data.get("data", []) or []
    if sort_by_price:
        offers.sort(key=lambda o: float(o.get("price", {}).get("grandTotal", "inf")))
    return offers

# -------------------- Date helpers --------------------

def date_range(center_iso, window_days):
    """Create list of dates (YYYY-MM-DD) for ±window around center date."""
    if not center_iso:
        return []
    if isinstance(center_iso, (datetime,)):
        center = center_iso
    else:
        center = datetime.fromisoformat(str(center_iso))
    window = int(window_days or 0)
    dates = []
    for d in range(-window, window+1):
        day = (center + timedelta(days=d)).date().isoformat()
        dates.append(day)
    return dates

# -------------------- Main --------------------

def main():
    import yaml

    log("▶️ start run")
    cfg = load_yaml(CONFIG_PATH)
    log("cfg loaded")

    currency = cfg.get("currency", "ILS")
    adults = int(cfg.get("adults", 1))
    route = cfg.get("route", {})
    origin = route.get("origin")
    destination = route.get("destination")
    depart_center = route.get("depart_center_date")
    depart_window = int(route.get("depart_window_days", 0))
    min_stay = int(route.get("min_stay_days", 1))
    max_stay = int(route.get("max_stay_days", 30))
    airline_filter = route.get("airline") or ""  # אם ר空 – בלי סינון
    threshold = float(route.get("max_price", 1e12))

    amadeus_env = os.environ.get("AMADEUS_ENV", cfg.get("amadeus_env", "test")).lower()
    amadeus_id = os.environ.get("AMADEUS_CLIENT_ID") or cfg.get("amadeus_client_id")
    amadeus_secret = os.environ.get("AMADEUS_CLIENT_SECRET") or cfg.get("amadeus_client_secret")

    if not (origin and destination and depart_center):
        raise RuntimeError("config.yaml חסר origin/destination/depart_center_date")

    # תאריכי יציאה לפי ±חלון; תאריכי חזרה נגזרים מטווח שהייה
    depart_days = date_range(depart_center, depart_window)

    token, base = amadeus_token(amadeus_id, amadeus_secret, amadeus_env)
    log("token ok")

    all_offers = []
    # נרוץ על כל תאריך יציאה, ונבנה טווחי חזרה בין min_stay ל-max_stay
    for dep in depart_days:
        for stay in range(min_stay, max_stay + 1):
            ret = (datetime.fromisoformat(dep) + timedelta(days=stay)).date().isoformat()
            try:
                raw = amadeus_search_offers(
                    base, token,
                    {"origin":origin, "destination":destination, "depart":dep, "ret":ret,
                     "adults":adults, "currency":currency},
                    max_results=50, sort_by_price=True
                )
            except Exception as e:
                log(f"warn: search {dep}->{ret} failed:", repr(e))
                continue

            # פישוט והוספה לרשימה
            for o in raw:
                simplified = simplify_offer(o, origin, destination, currency, adults)
                # סינון חברת תעופה אם ביקשת
                if airline_filter:
                    airs = [a.upper() for a in simplified["airlines"]]
                    if airline_filter.upper() not in airs:
                        continue
                all_offers.append(simplified)

    if not all_offers:
        log("no offers found")
        results = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "amadeus_env": amadeus_env.upper(),
            "route": {"origin":origin, "destination":destination, "adults":adults, "currency":currency},
            "search": {
                "depart_center_date": depart_center,
                "depart_window_days": depart_window,
                "min_stay_days": min_stay,
                "max_stay_days": max_stay
            },
            "offers": [],
            "best": None,
            "threshold": threshold,
            "below_threshold": False
        }
        save_json(RESULTS_PATH, results)
        append_history({
            "ts": datetime.utcnow().isoformat() + "Z",
            "origin": origin, "destination": destination,
            "depart": None, "return": None,
            "price": None, "currency": currency,
            "below_threshold": False
        })
        return

    # מיין לפי מחיר וקח עד 50 להצגה; best = הראשונה
    all_offers.sort(key=lambda x: x["price"])
    top = all_offers[:50]  # client מציג 10, נשמור קצת יותר קדימה
    best = top[0]
    below = best["price"] <= threshold

    results = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "amadeus_env": amadeus_env.upper(),
        "route": {"origin":origin, "destination":destination, "adults":adults, "currency":currency},
        "search": {
            "depart_center_date": depart_center,
            "depart_window_days": depart_window,
            "min_stay_days": min_stay,
            "max_stay_days": max_stay
        },
        "offers": top,   # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<< חשוב
        "best": best,    # תאימות אחורה
        "threshold": threshold,
        "below_threshold": below
    }
    save_json(RESULTS_PATH, results)

    append_history({
        "ts": datetime.utcnow().isoformat() + "Z",
        "origin": origin, "destination": destination,
        "depart": best["depart"], "return": best["return"],
        "price": best["price"], "currency": currency,
        "below_threshold": below
    })

    log(f"done. found={len(all_offers)} saved={len(top)} best={best['price']} {currency}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("🔥 ERROR:", repr(e))
        traceback.print_exc()
        sys.exit(1)
