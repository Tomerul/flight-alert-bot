(async function () {
  const $ = (id) => document.getElementById(id);
  const status = $("status"), bestBox = $("best"), details = $("details");
  const chartEl = $("priceChart"), histTable = $("historyTable"), histInfo = $("histInfo");
  const downloadCsvBtn = $("downloadCsv"), form = $("cfgForm"), saveMsg = $("saveMsg");
  const overlay = $("runOverlay"), runState = $("runState"), runLink = $("runLink"), closeOverlay = $("closeOverlay");

  const WORKER_URL = "https://flight-alert-bridge.tomerul85.workers.dev"; // <<< להחליף
  const OWNER = "tomerul";  // <<< להחליף
  const REPO  = "flight-alert-bot";   // שם הריפו
  const APP_SHARED_KEY = "FlightSecret123"; // <<< אותו ערך כמו ב-Worker env


  const fetchJSON = async (path, fallback) => {
    try { const r = await fetch(path + "?t=" + Date.now(), { cache: "no-store" }); if (!r.ok) throw 0; return await r.json(); }
    catch { return fallback; }
  };
  const fmt = (v) => (v == null ? "—" : Number(v).toFixed(0));

  // קישורי קנייה
  const gLink = (o,d,dep,ret,a,c) => `https://www.google.com/travel/flights?hl=he&curr=${c||"ILS"}&flt=${encodeURIComponent(`${o}.${d}.${dep}*${d}.${o}.${ret}`)};tt=m;ad=${a||1}`;
  const sLink = (o,d,dep,ret,a) => `https://www.skyscanner.com/transport/flights/${o.toLowerCase()}/${d.toLowerCase()}/${dep}/${ret}/?adultsv2=${a||1}`;
  const kLink = (o,d,dep,ret,a) => `https://www.kayak.com/flights/${o}-${d}/${dep}/${ret}?adults=${a||1}`;

  // Chart.js
  let chart;
  function renderChart(points) {
    const ctx = chartEl.getContext("2d");
    if (chart) chart.destroy();
    if (!points || points.length < 2) {
      ctx.clearRect(0,0,chartEl.width,chartEl.height);
      ctx.fillStyle = "#a9b4c3"; ctx.fillText("אין מספיק נתונים לגרף עדיין.", 10, 20);
      return;
    }
    chart = new Chart(ctx, {
      type: "line",
      data: { labels: points.map(p => new Date(p.t)), datasets: [{ label: "מחיר (ILS)", data: points.map(p => p.y), tension: .25 }] },
      options: {
        maintainAspectRatio:false,
        scales:{
          x:{type:"time",time:{unit:"day"},ticks:{color:"#a9b4c3"},grid:{color:"rgba(255,255,255,0.06)"}},
          y:{beginAtZero:false,ticks:{color:"#a9b4c3"},grid:{color:"rgba(255,255,255,0.06)"}}
        },
        plugins:{ legend:{labels:{color:"#e9eef6"}}, tooltip:{callbacks:{label:(c)=>` ${fmt(c.parsed.y)} ILS`}} },
        elements:{ point:{ radius:3 } }
      }
    });
  }

  // CSV
  function exportCsv(history) {
    const rows = [["timestamp","origin","destination","depart","return","price","currency","below_threshold"]];
    for (const h of history) rows.push([h.ts,h.origin,h.destination,h.depart||"",h.return||"",h.price??"",h.currency||"",h.below_threshold?1:0]);
    const csv = rows.map(r => r.map(x => `"${String(x).replaceAll('"','""')}"`).join(",")).join("\n");
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"}));
    a.download = "history.csv"; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 500);
  }

  // טעינה ראשונית
  try {
    const [resData, historyRaw] = await Promise.all([fetchJSON("./results.json", null), fetchJSON("./history.json", [])]);
    if (!resData) throw new Error("results.json לא נמצא");
    status.innerHTML = `עודכן לאחרונה: <code>${resData.generated_at}</code> · ENV: <code>${resData.amadeus_env || "?"}</code>`;

    const route = resData.route || {}, search = resData.search || {}, best = resData.best;

    // קלף עסקה
    bestBox.classList.remove("hidden");
    if (best) {
      const durMin = best.total_duration_minutes || 0, durH = Math.floor(durMin/60), durM = durMin%60;
      bestBox.innerHTML = `
        <div class="row"><div>מסלול</div><div><strong>${route.origin} ⇄ ${route.destination}</strong></div></div>
        <div class="row"><div>תאריכים</div><div>יציאה <code>${best.depart}</code> · חזרה <code>${best.return}</code></div></div>
        <div class="row"><div>מחיר</div><div class="price">${fmt(best.price)} ${best.currency}
          <span class="dim">(סף: ${fmt(resData.threshold)} ${route.currency || best.currency})</span></div></div>
        <div class="row"><div>חברות</div><div>${(best.airlines||[]).join(", ")||"—"}</div></div>
        <div class="row"><div>קונקשנים</div><div>${best.connections ?? 0}</div></div>
        <div class="row"><div>משך כולל</div><div>${durH}ש׳ ${durM}ד׳</div></div>
        <div class="row"><div>סטטוס</div><div><span class="badge ${resData.below_threshold?'ok':'err'}">${resData.below_threshold?'מתחת לסף ✅':'מעל הסף'}</span></div></div>
        <div class="btns">
          <a class="btn btn-primary" href="${gLink(route.origin,route.destination,best.depart,best.return,route.adults,route.currency)}" target="_blank" rel="noopener">פתח ב-Google Flights</a>
          <a class="btn btn-outline" href="${sLink(route.origin,route.destination,best.depart,best.return,route.adults)}" target="_blank" rel="noopener">Skyscanner</a>
          <a class="btn btn-outline" href="${kLink(route.origin,route.destination,best.depart,best.return,route.adults)}" target="_blank" rel="noopener">KAYAK</a>
        </div>`;
    } else {
      bestBox.innerHTML = `<div>לא נמצאו הצעות מתאימות בטווחים.</div>`;
    }

    // פרטי חיפוש
    details.classList.remove("hidden");
    details.innerHTML = `
      <div><strong>הגדרות חיפוש</strong></div>
      <div class="row"><div>נוסעים</div><div>${route.adults||1} מבוגר/ים</div></div>
      <div class="row"><div>מטבע</div><div>${route.currency||"ILS"}</div></div>
      <div class="row"><div>טווח יציאה</div><div>מרכז: <code>${search.depart_center_date}</code> · ±<code>${search.depart_window_days}</code> ימים</div></div>
      <div class="row"><div>שהייה</div><div>מינ׳ <code>${search.min_stay_days}</code> · מקס׳ <code>${search.max_stay_days}</code> ימים</div></div>`;

    // היסטוריה
    const history = (historyRaw||[]).filter(x => x && x.ts);
    histInfo.textContent = history.length ? `סך רשומות: ${history.length}` : "אין נתוני היסטוריה עדיין.";
    histTable.innerHTML = history.length ? `
      <div class="table"><table><thead>
        <tr><th>זמן</th><th>מסלול</th><th>תאריכים</th><th>מחיר</th><th>מתחת לסף</th></tr>
      </thead><tbody>
        ${history.slice().reverse().map(h=>`
          <tr>
            <td><code>${h.ts}</code></td>
            <td>${h.origin} ⇄ ${h.destination}</td>
            <td>${h.depart||"—"} → ${h.return||"—"}</td>
            <td>${h.price!=null?fmt(h.price):"—"} ${h.currency||""}</td>
            <td>${h.below_threshold?"✅":"—"}</td>
          </tr>`).join("")}
      </tbody></table></div>` : `<div class="dim">אין נתונים עדיין – בריצה הבאה ההיסטוריה תתחיל להתמלא.</div>`;

    const points = history
      .filter(x => x.price!=null && !isNaN(Number(x.price)))
      .map(x => ({ t: new Date(x.ts).getTime(), y: Number(x.price) }))
      .sort((a,b)=>a.t-b.t);
    renderChart(points);

    downloadCsvBtn.addEventListener("click", () => exportCsv(history));

  } catch (err) {
    status.innerHTML = `<span class="badge err">שגיאה</span> ${String(err)}`;
    console.error(err);
  }

  // הפעלה + ספינר + Polling
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    saveMsg.textContent = "שולח בקשה…";
    const fd = new FormData(form);
    const inputs = {
      origin: fd.get("origin"),
      destination: fd.get("destination"),
      adults: String(fd.get("adults")||"1"),
      currency: fd.get("currency")||"ILS",
      depart_center_date: fd.get("depart_center_date"),
      depart_window_days: String(fd.get("depart_window_days")||"0"),
      min_stay_days: String(fd.get("min_stay_days")||"1"),
      max_stay_days: String(fd.get("max_stay_days")||"30"),
      airline: (fd.get("airline")||"").trim(),
      amadeus_env: fd.get("amadeus_env")||"test"
    };

    const since = Date.now();
    try {
      const r = await fetch(WORKER_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-app-key": APP_SHARED_KEY },
        body: JSON.stringify({ owner: OWNER, repo: REPO, inputs })
      });
      if (!r.ok) throw new Error(await r.text() || `HTTP ${r.status}`);
      saveMsg.textContent = "✅ הבקשה נשלחה. מריץ…";
      overlay.classList.remove("hidden");
      runState.textContent = "בתור…";
      await pollRunUntilComplete(since);
    } catch (err) {
      console.error(err);
      saveMsg.textContent = "❌ שגיאה בשליחה: " + String(err);
      overlay.classList.add("hidden");
    }
  });

  closeOverlay.addEventListener("click", () => overlay.classList.add("hidden"));

  async function pollRunUntilComplete(sinceMs) {
    const POLL_MS = 5000, TIMEOUT_MS = 12*60*1000;
    const start = Date.now(); let lastUrl=null, seenCompleted=false;

    while (Date.now()-start < TIMEOUT_MS) {
      try {
        // בקשה עם since
        const qs = new URLSearchParams({ owner: OWNER, repo: REPO, workflow: "config-dispatch.yml", branch: "main", since: String(sinceMs) });
        const r = await fetch(`${WORKER_URL}/status?${qs}`, { headers: { "x-app-key": APP_SHARED_KEY } });
        if (!r.ok) throw new Error(`status HTTP ${r.status}`);
        const { ok, run, error } = await r.json();
        if (!ok) throw new Error(error || "status not ok");

        if (run && run.html_url && run.html_url !== lastUrl) { runLink.classList.remove("hidden"); runLink.href = run.html_url; lastUrl = run.html_url; }

        if (!run) {
          runState.textContent = "ממתין לתור…";
        } else if (run.status === "queued") {
          runState.textContent = "בתור…";
        } else if (run.status === "in_progress") {
          runState.textContent = "בתהליך…";
        } else if (run.status === "completed") {
          runState.textContent = run.conclusion === "success" ? "הושלם בהצלחה ✅" : `הושלם: ${run.conclusion || "?"}`;
          seenCompleted = true;
          setTimeout(() => location.reload(), 2000);
          return;
        }
      } catch (e) {
        console.debug("status poll error:", e);
        runState.textContent = "בודק סטטוס…";
      }
      await new Promise(res => setTimeout(res, POLL_MS));
    }

    // אם הגענו לפה – Timeout
    runState.textContent = "עבר הזמן המקסימלי לבדיקה. אפשר לפתוח את הלוגים.";
    runLink.classList.remove("hidden");
  }
})();
