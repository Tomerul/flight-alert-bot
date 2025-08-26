(async function () {
  const $ = (id) => document.getElementById(id);
  const status = $("status");
  const routeBox = $("routeBox");
  const offersBox = $("offersBox");
  const offersChartEl = $("offersChart");
  const histTable = $("historyTable");
  const histInfo = $("histInfo");
  const downloadCsvBtn = $("downloadCsv");
  const form = $("cfgForm");
  const saveMsg = $("saveMsg");

  // === ערכי גשר להפעלה מהדף (לא חובה אם לא משתמשים בטופס) ===
  const WORKER_URL = "https://flight-alert-bridge.tomerul85.workers.dev"; // <<< להחליף
  const OWNER = "tomerul";  // <<< להחליף
  const REPO  = "flight-alert-bot";   // שם הריפו
  const APP_SHARED_KEY = "FlightSecret123"; // <<< אותו ערך כמו ב-Worker env


  // ---- עזר ----
  const fetchJSON = async (path, fallback) => {
    try { const r = await fetch(path + "?t=" + Date.now(), { cache: "no-store" }); if (!r.ok) throw 0; return await r.json(); }
    catch { return fallback; }
  };
  const fmtPrice = (v) => (v == null ? "—" : Number(v).toFixed(0));
  const safe = (s) => (s ?? "").toString();

  // קישור Google Flights לכל הצעה
  function googleFlightsLink(o, d, dep, ret, a, c) {
    const flt = `${o}.${d}.${dep}*${d}.${o}.${ret}`;
    return `https://www.google.com/travel/flights?hl=he&curr=${c || "ILS"}&flt=${encodeURIComponent(flt)};tt=m;ad=${a || 1}`;
  }

  // ===== גרף הצעות (Bar) – עם השמדה לפני ציור =====
  let offersChart = null;
  function renderOffersChart(offers) {
    const ctx = offersChartEl.getContext("2d");
    // גובה קבוע למניעת "התארכות"
    offersChartEl.height = 300;

    if (offersChart) {
      offersChart.destroy();
      offersChart = null;
    }
    if (!offers || !offers.length) {
      ctx.clearRect(0, 0, offersChartEl.width, offersChartEl.height);
      return;
    }
    const labels = offers.map((o, i) => `#${i + 1} ${o._isDirect ? "ישירה" : "קונק'"} • ${o._airlineText || ""}`);
    const data = offers.map(o => Number(o.price));
    offersChart = new Chart(ctx, {
      type: "bar",
      data: { labels, datasets: [{ label: "מחיר (ILS)", data }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: { y: { beginAtZero: false } }
      }
    });
  }

  // =============== טעינה ראשונית ===============
  try {
    const [resData, historyRaw] = await Promise.all([
      fetchJSON("./results.json", null),
      fetchJSON("./history.json", [])
    ]);
    if (!resData) throw new Error("results.json לא נמצא");

    // מצב
    status.innerHTML = `עודכן לאחרונה: <code>${resData.generated_at}</code> · ENV: <code>${resData.amadeus_env || "?"}</code>`;

    // מסלול
    const route = resData.route || {};
    const search = resData.search || {};
    routeBox.classList.remove("hidden");
    routeBox.innerHTML = `
      <div class="row"><div>מסלול</div><div><strong>${route.origin} ⇄ ${route.destination}</strong></div></div>
      <div class="row"><div>נוסעים</div><div>${route.adults || 1} מבוגר/ים</div></div>
      <div class="row"><div>מטבע</div><div>${route.currency || "ILS"}</div></div>
      <div class="row"><div>טווח יציאה</div><div>מרכז: <code>${search.depart_center_date || "—"}</code> · ±<code>${search.depart_window_days ?? "0"}</code> ימים</div></div>
      <div class="row"><div>שהייה</div><div>מינ׳ <code>${search.min_stay_days ?? "—"}</code> · מקס׳ <code>${search.max_stay_days ?? "—"}</code> ימים</div></div>
    `;

    // ===== הצעות =====
    let offers = Array.isArray(resData.offers) ? resData.offers.slice() : [];
    if (!offers.length && resData.best) {
      const b = resData.best;
      offers = [{
        airlines: b.airlines || [],
        connections: b.connections ?? 0,
        depart: b.depart,
        depart_time: b.depart_time,
        return: b.return,
        return_time: b.return_time,
        price: b.price,
        currency: b.currency || route.currency || "ILS"
      }];
    }

    offers = offers
      .filter(o => o && o.price != null && !isNaN(Number(o.price)))
      .map((o, idx) => ({
        ...o,
        _idx: idx + 1,
        _airlineText: Array.isArray(o.airlines) ? o.airlines.join(", ") : safe(o.airlines),
        _isDirect: Number(o.connections || 0) === 0,
        _departFull: [safe(o.depart), safe(o.depart_time)].filter(Boolean).join(" "),
        _returnFull: [safe(o.return), safe(o.return_time)].filter(Boolean).join(" ")
      }))
      .sort((a, b) => Number(a.price) - Number(b.price))
      .slice(0, 10);

    // טבלה
    if (offers.length) {
      const rows = offers.map(o => `
        <tr class="${o._isDirect ? 'direct' : 'conn'}">
          <td>#${o._idx}</td>
          <td>${o._airlineText || "—"}</td>
          <td>${o._departFull || "—"}</td>
          <td>${o._returnFull || "—"}</td>
          <td class="price">${fmtPrice(o.price)} ${o.currency || route.currency || ""}</td>
          <td><a href="${googleFlightsLink(route.origin, route.destination, safe(o.depart), safe(o.return), route.adults, route.currency)}" target="_blank" rel="noopener">Google Flights</a></td>
        </tr>
      `).join("");

      offersBox.innerHTML = `
        <table>
          <thead>
            <tr><th>#</th><th>חברת תעופה</th><th>יציאה</th><th>חזרה</th><th>מחיר</th><th>לינק</th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
        <div class="dim" style="margin-top:6px">
          <span class="direct">ירוק = ישירה</span> · <span class="conn">אדום = עם קונקשן</span>
        </div>
      `;
    } else {
      offersBox.innerHTML = `<div class="dim">לא נמצאו הצעות להצגה.</div>`;
    }

    // גרף (עם destroy לפני יצירה)
    renderOffersChart(offers);

    // ===== היסטוריה =====
    const history = (historyRaw || []).filter(x => x && x.ts);
    histInfo.textContent = history.length ? `סך רשומות: ${history.length}` : "אין נתוני היסטוריה עדיין.";
    if (history.length) {
      const rows = history.slice().reverse().map(h => `
        <tr>
          <td><code>${h.ts}</code></td>
          <td>${h.origin} ⇄ ${h.destination}</td>
          <td>${h.depart || "—"} → ${h.return || "—"}</td>
          <td>${h.price != null ? fmtPrice(h.price) : "—"} ${h.currency || ""}</td>
          <td>${h.below_threshold ? "✅" : "—"}</td>
        </tr>
      `).join("");
      histTable.innerHTML = `
        <table>
          <thead><tr><th>זמן</th><th>מסלול</th><th>תאריכים</th><th>מחיר</th><th>מתחת לסף</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      `;
    } else {
      histTable.innerHTML = `<div class="dim">אין נתונים עדיין.</div>`;
    }

    // הורדת CSV
    downloadCsvBtn?.addEventListener("click", () => {
      const rows = [["timestamp","origin","destination","depart","return","price","currency","below_threshold"]];
      for (const h of history) rows.push([h.ts, h.origin, h.destination, h.depart || "", h.return || "", h.price ?? "", h.currency || "", h.below_threshold ? 1 : 0]);
      const csv = rows.map(r => r.map(x => `"${String(x).replaceAll('"','""')}"`).join(",")).join("\n");
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      a.download = "history.csv"; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 500);
    });

  } catch (err) {
    status.innerHTML = `<span class="badge err">שגיאה</span> ${String(err)}`;
    console.error(err);
  }

  // ===== שליחת הטופס (ללא ספינר/פולינג) =====
  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    saveMsg.textContent = "שולח בקשה…";

    const fd = new FormData(form);
    const inputs = {
      origin: fd.get("origin"),
      destination: fd.get("destination"),
      adults: String(fd.get("adults") || "1"),
      currency: fd.get("currency") || "ILS",
      depart_center_date: fd.get("depart_center_date"),
      depart_window_days: String(fd.get("depart_window_days") || "0"),
      min_stay_days: String(fd.get("min_stay_days") || "1"),
      max_stay_days: String(fd.get("max_stay_days") || "30"),
      airline: (fd.get("airline") || "").trim(),
      amadeus_env: fd.get("amadeus_env") || "test"
    };

    try {
      const r = await fetch(WORKER_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-app-key": APP_SHARED_KEY },
        body: JSON.stringify({ owner: OWNER, repo: REPO, inputs })
      });
      if (!r.ok) throw new Error(await r.text() || `HTTP ${r.status}`);
      saveMsg.textContent = "✅ נשלח. בדוק ב-Actions; כשהריצה מסתיימת—רענן את הדף.";
    } catch (err) {
      console.error(err);
      saveMsg.textContent = "❌ שגיאה בשליחה: " + String(err);
    }
  });
})();
