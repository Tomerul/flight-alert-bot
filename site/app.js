(async function () {
  const $ = (id) => document.getElementById(id);
  const status = $("status");
  const bestBox = $("best");
  const details = $("details");
  const chartEl = $("priceChart");
  const histTable = $("historyTable");
  const histInfo = $("histInfo");
  const downloadCsvBtn = $("downloadCsv");

  // --- קריאה לקבצים (ללא cache) ---
  const fetchJSON = async (path, fallback) => {
    try {
      const r = await fetch(path + "?t=" + Date.now(), { cache: "no-store" });
      if (!r.ok) throw new Error();
      return await r.json();
    } catch (_) {
      return fallback;
    }
  };

  // --- פערי אבטחה בדפדפן? מוודא מספר ל-ILS ---
  const fmt = (v) => (v == null ? "—" : Number(v).toFixed(0));

  // --- בניית לינקי חיפוש קנייה ---
  function buildGoogleFlightsLink(origin, destination, depart, ret, adults, currency) {
    const hl = "he";
    const curr = (currency || "ILS");
    // פורמט: TLV.HKT.YYYY-MM-DD*HKT.TLV.YYYY-MM-DD
    const flt = `${origin}.${destination}.${depart}*${destination}.${origin}.${ret}`;
    return `https://www.google.com/travel/flights?hl=${hl}&curr=${curr}&flt=${encodeURIComponent(flt)};tt=m;ad=${adults || 1}`;
  }
  function buildSkyscannerLink(origin, destination, depart, ret, adults) {
    // פורמט: /transport/flights/tlv/hkt/2025-12-20/2026-01-02/?adultsv2=2
    return `https://www.skyscanner.com/transport/flights/${origin.toLowerCase()}/${destination.toLowerCase()}/${depart}/${ret}/?adultsv2=${adults || 1}`;
  }
  function buildKayakLink(origin, destination, depart, ret, adults) {
    // פורמט kayak: /flights/TLV-HKT/2025-12-20/2026-01-02?adults=2
    return `https://www.kayak.com/flights/${origin}-${destination}/${depart}/${ret}?adults=${adults || 1}`;
  }

  // --- ציור גרף עם Chart.js ---
  let chart;
  function renderChart(points) {
    if (chart) { chart.destroy(); }
    const labels = points.map(p => new Date(p.t));
    const data = points.map(p => p.y);
    const ctx = chartEl.getContext("2d");
    chart = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [{
          label: "מחיר (ILS)",
          data,
          tension: 0.25
        }]
      },
      options: {
        maintainAspectRatio: false,
        scales: {
          x: { type: "time", time: { unit: "day" }, ticks: { color: "#a9b4c3" }, grid: { color: "rgba(255,255,255,0.06)" } },
          y: { beginAtZero: false, ticks: { color: "#a9b4c3" }, grid: { color: "rgba(255,255,255,0.06)" } }
        },
        plugins: {
          legend: { labels: { color: "#e9eef6" } },
          tooltip: {
            callbacks: {
              label: (ctx) => ` ${fmt(ctx.parsed.y)} ILS`
            }
          }
        },
        elements: { point: { radius: 3 } }
      }
    });
  }

  // --- יצוא CSV מהיסטוריה ---
  function exportCsv(history) {
    const rows = [["timestamp","origin","destination","depart","return","price","currency","below_threshold"]];
    for (const h of history) {
      rows.push([h.ts, h.origin, h.destination, h.depart || "", h.return || "", h.price ?? "", h.currency || "", h.below_threshold ? 1 : 0]);
    }
    const csv = rows.map(r => r.map(x => `"${String(x).replaceAll('"','""')}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "history.csv";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 500);
  }

  try {
    const [resData, historyRaw] = await Promise.all([
      fetchJSON("./results.json", null),
      fetchJSON("./history.json", [])
    ]);

    if (!resData) throw new Error("results.json לא נמצא");
    status.innerHTML = `עודכן לאחרונה: <code>${resData.generated_at}</code> · ENV: <code>${resData.amadeus_env || "?"}</code>`;

    const route = resData.route || {};
    const search = resData.search || {};
    const best = resData.best;

    // ----- קלף עסקה -----
    bestBox.classList.remove("hidden");
    if (best) {
      const durMin = best.total_duration_minutes || 0;
      const durH = Math.floor(durMin / 60);
      const durM = durMin % 60;
      const gLink = buildGoogleFlightsLink(route.origin, route.destination, best.depart, best.return, route.adults, route.currency);
      const sLink = buildSkyscannerLink(route.origin, route.destination, best.depart, best.return, route.adults);
      const kLink = buildKayakLink(route.origin, route.destination, best.depart, best.return, route.adults);

      bestBox.innerHTML = `
        <div class="row"><div>מסלול</div><div><strong>${route.origin} ⇄ ${route.destination}</strong></div></div>
        <div class="row"><div>תאריכים</div><div>יציאה <code>${best.depart}</code> · חזרה <code>${best.return}</code></div></div>
        <div class="row"><div>מחיר</div>
          <div class="price">${fmt(best.price)} ${best.currency}
            <span class="dim">(סף: ${fmt(resData.threshold)} ${route.currency || best.currency})</span>
          </div>
        </div>
        <div class="row"><div>חברות</div><div>${(best.airlines || []).join(", ") || "—"}</div></div>
        <div class="row"><div>קונקשנים</div><div>${best.connections ?? 0}</div></div>
        <div class="row"><div>משך כולל</div><div>${durH}ש׳ ${durM}ד׳</div></div>
        <div class="row"><div>סטטוס</div>
          <div><span class="badge ${resData.below_threshold ? 'ok' : 'err'}">
            ${resData.below_threshold ? 'מתחת לסף ✅' : 'מעל הסף'}
          </span></div>
        </div>
        <div class="btns">
          <a class="btn btn-primary" href="${gLink}" target="_blank" rel="noopener">פתח ב-Google Flights</a>
          <a class="btn btn-outline" href="${sLink}" target="_blank" rel="noopener">Skyscanner</a>
          <a class="btn btn-outline" href="${kLink}" target="_blank" rel="noopener">KAYAK</a>
        </div>
      `;
    } else {
      bestBox.innerHTML = `<div>לא נמצאו הצעות מתאימות בטווחים.</div>`;
    }

    // ----- פרטי חיפוש -----
    details.classList.remove("hidden");
    details.innerHTML = `
      <div><strong>הגדרות חיפוש</strong></div>
      <div class="row"><div>נוסעים</div><div>${route.adults || 1} מבוגר/ים</div></div>
      <div class="row"><div>מטבע</div><div>${route.currency || 'ILS'}</div></div>
      <div class="row"><div>טווח יציאה</div>
        <div>מרכז: <code>${search.depart_center_date}</code> · ±<code>${search.depart_window_days}</code> ימים</div>
      </div>
      <div class="row"><div>שהייה</div>
        <div>מינ׳ <code>${search.min_stay_days}</code> · מקס׳ <code>${search.max_stay_days}</code> ימים</div>
      </div>
    `;

    // ----- היסטוריה + גרף -----
    const history = (historyRaw || []).filter(x => x && x.ts);
    histInfo.textContent = history.length ? `סך רשומות: ${history.length}` : "אין נתוני היסטוריה עדיין.";

    // טבלת היסטוריה
    if (history.length) {
      const rows = history.slice().reverse().map(h => `
        <tr>
          <td><code>${h.ts}</code></td>
          <td>${h.origin} ⇄ ${h.destination}</td>
          <td>${h.depart || "—"} → ${h.return || "—"}</td>
          <td>${h.price != null ? fmt(h.price) : "—"} ${h.currency || ""}</td>
          <td>${h.below_threshold ? "✅" : "—"}</td>
        </tr>
      `).join("");
      histTable.innerHTML = `
        <div class="table">
          <table>
            <thead>
              <tr><th>זמן</th><th>מסלול</th><th>תאריכים</th><th>מחיר</th><th>מתחת לסף</th></tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      `;
    } else {
      histTable.innerHTML = `<div class="dim">אין נתונים עדיין – בריצה הבאה ההיסטוריה תתחיל להתמלא.</div>`;
    }

    // גרף—מחיר לפי זמן (לוקח את כל הרשומות שיש להן price)
    const points = history
      .filter(x => typeof x.price === "number")
      .map(x => ({ t: new Date(x.ts).getTime(), y: x.price }))
      .sort((a,b) => a.t - b.t);

    if (points.length >= 2) {
      renderChart(points);
    } else {
      // אם אין מספיק נקודות לגרף—ננקה קנבס
      const ctx = chartEl.getContext("2d");
      ctx.clearRect(0,0,chartEl.width,chartEl.height);
      ctx.fillStyle = "#a9b4c3";
      ctx.fillText("אין מספיק נתונים לגרף עדיין.", 10, 20);
    }

    // הורדת CSV
    downloadCsvBtn.addEventListener("click", () => exportCsv(history));

  } catch (err) {
    status.innerHTML = `<span class="badge err">שגיאה</span> ${String(err)}`;
    console.error(err);
  }
})();
