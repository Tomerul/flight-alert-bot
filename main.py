#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, json, traceback
from datetime import datetime, timedelta
import requests

CONFIG_PATH  = os.environ.get("CFG_PATH", "config.yaml")
RESULTS_PATH = os.environ.get("RESULTS_PATH", "site/results.json")
HISTORY_PATH = os.environ.get("HISTORY_PATH", "site/history.json")

# -------------------- Utils --------------------

def log(*a):
    print(datetime.utcnow().isoformat() + "Z", *a, flush=True)

def load_yaml(path):
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def read_history():
    try:
        if os.path.exists(HISTORY_PATH):
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return []

def append_history(entry):
    hist = read_history()
    hist.append(entry)
    save_json(HISTORY_PATH, hist)

# -------------------- Amadeus --------------------

def amadeus_token(client_id, client_secret, env="test"):
    base = "https://test.api.amadeus.com" if env == "test" else "https://api.amadeus.com"
    log(f"amadeus_token: env={env}, base={base}, id_present={bool(client_id)}, secret_present={bool(client_secret)}")
    r = requests.post(
        f"{base}/v1/security/oauth2/token",
        data={"grant_type":"client_credentials","client_id":client_id,"client_secret":client_secret},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=25
    )
    if not r.ok:
        try: body = r.json()
        except Exception: body = r.text[:500]
        log("amadeus_token HTTP error:", r.status_code, body)
        r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        log("amadeus_token parse error:", r.text[:500])
        raise RuntimeError("No access_token in Amadeus response")
    return token, base

def simplify_offer(offer, origin, destination, currency, adults):
    price = float(offer.get("price", {}).get("grandTotal", "0") or 0)
    carriers = set()
    depart_dt, return_dt = "", ""

    itineraries = offer.get("itineraries", []) or []
    if len(itineraries) >= 1:
        out_segs = itineraries[0].get("segments", []) or []
        if out_segs:
            depart_dt = out_segs[0]["departure"]["at"]
            for s in out_segs:
                c = s.get("carrierCode")
                if c: carriers.add(c)
    if len(itineraries) >= 2:
        ret_segs = itineraries[1].get("segments", []) or []
        if ret_segs:
            return_dt = ret_segs[0]["departure"]["at"]
            for s in ret_segs:
                c = s.get("carrierCode")
                if c: carriers.add(c)

    connections = 0
    if len(itineraries) >= 1:
        connections += max(0, len(itineraries[0].get("segments", []) or []) - 1)
    if len(itineraries) >= 2:
        connections += max(0, len(itineraries[1].get("segments", []) or []) - 1)

    def split_dt(iso):
        if not iso: return "", ""
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

def amadeus_search_offers(base, token, params, max_results=50):
    url = f"{base}/v2/shopping/flight-offers"
    q = {
        "originLocationCode": params["origin"],
        "destinationLocationCode": params["destination"],
        "departureDate": params["depart"],
        "adults": params.get("adults", 1),
        "currencyCode": params.get("currency", "ILS"),
        "max": max(1, min(int(max_results), 250))
    }
    if params.get("ret"): q["returnDate"] = params["ret"]
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, params=q, headers=headers, timeout=40)
    if not r.ok:
        try: body = r.json()
        except Exception: body = r.text[:500]
        log("amadeus_search_offers HTTP error:", r.status_code, body)
        r.raise_for_status()
    data = r.json()
    offers = data.get("data", []) or []
    offers.sort(key=lambda o: float(o.get("price", {}).get("grandTotal", "inf")))
    return offers

# -------------------- Date helpers --------------------

def date_range(center_iso, window_days):
    if not center_iso: return []
    center = datetime.fromisoformat(str(center_iso))
    window = int(window_days or 0)
    return [(center + timedelta(days=d)).date().isoformat() for d in range(-window, window+1)]

# -------------------- Main --------------------

def main():
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
    airline_filter = (route.get("airline") or "").strip()
    threshold = float(route.get("max_price", 1e12))

    amadeus_env = (os.environ.get("AMADEUS_ENV") or cfg.get("amadeus_env", "test")).lower()
    amadeus_id = os.environ.get("AMADEUS_CLIENT_ID") or cfg.get("amadeus_client_id")
    amadeus_secret = os.environ.get("AMADEUS_CLIENT_SECRET") or cfg.get("amadeus_client_secret")

    if not (origin and destination and depart_center):
        raise RuntimeError("config.yaml חסר origin/destination/depart_center_date")

    depart_days = date_range(depart_center, depart_window)

    # Token
    token, base = amadeus_token(amadeus_id, amadeus_secret, amadeus_env)
    log("token ok")

    all_offers = []

    for dep in depart_days:
        base_dep = datetime.fromisoformat(dep)
        for stay in range(min_stay, max_stay + 1):
            ret = (base_dep + timedelta(days=stay)).date().isoformat()
            try:
                raw = amadeus_search_offers(
                    base, token,
                    {"origin": origin, "destination": destination, "depart": dep, "ret": ret,
                     "adults": adults, "currency": currency},
                    max_results=50
                )
            except Exception as e:
                log(f"warn: search {dep}->{ret} failed:", repr(e))
                continue
            for o in raw:
                s = simplify_offer(o, origin, destination, currency, adults)
                if airline_filter:
                    airs = [a.upper() for a in s["airlines"]]
                    if airline_filter.upper() not in airs:
                        continue
                all_offers.append(s)

    # בניית תוצאה לפי הסכימה
    all_offers.sort(key=lambda x: x["price"])
    top = all_offers[:50]
    best = top[0] if top else None
    below = bool(best and best["price"] <= threshold)

    results = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "amadeus_env": amadeus_env.upper(),
        "route": {"origin": origin, "destination": destination, "adults": adults, "currency": currency},
        "search": {
            "depart_center_date": depart_center,
            "depart_window_days": depart_window,
            "min_stay_days": min_stay,
            "max_stay_days": max_stay
        },
        "offers": top,
        "best": best,
        "threshold": threshold,
        "below_threshold": below
    }
    save_json(RESULTS_PATH, results)

    # היסטוריה: שומר רק את המחיר הכי טוב בריצה הזו
    append_history({
        "ts": datetime.utcnow().isoformat() + "Z",
        "origin": origin, "destination": destination,
        "depart": best["depart"] if best else None,
        "return": best["return"] if best else None,
        "price": best["price"] if best else None,
        "currency": currency,
        "below_threshold": below
    })

    log(f"done. found={len(all_offers)} saved={len(top)} best={best['price'] if best else '—'} {currency}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("🔥 ERROR:", repr(e))
        traceback.print_exc()
        sys.exit(1)
