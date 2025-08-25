(async function () {
  const $ = (id) => document.getElementById(id);
  const status = $("status");
  const bestBox = $("best");
  const details = $("details");
  const chartEl = $("chart");
  const histTable = $("historyTable");

  const fetchJSON = async (path, fallback) => {
    try {
      const r = await fetch(path, { cache: "no-store" });
      if (!r.ok) throw new Error();
      return await r.json();
    } catch (_) {
      return fallback;
    }
  };

  try {
    const [resData, history] = await Promise.all([
      fetchJSON("./results.json", null),
      fetchJSON("./history.json", [])
    ]);

    if (!resData) throw new Error("results.json לא נמצא");
    status.innerHTML = `עודכן לאחרונה: <code>${resData.generated_at}</code>`;

    const route = resData.route || {};
    const search = resData.search || {};
    const best = resData.best;

    // כרטיס עסקה עשיר
    bestBox.classList.remove("hidden");
    if (best) {
      const durMin = best.total_duration_minutes || 0;
      const durH = Math.floor(durMin / 60);
      const durM = durMin % 60;
      bestBox.innerHTML = `
        <div class="row"><div>מסלול</div><div><strong>${route.origin} ⇄ ${route.destination}</strong></div></div>
        <div class="row"><div>תאריכים</div><div>יציאה <code>${best.depart}</code> · חזרה <code>${best.return}</code></div></div>
        <div class="row"><div>מחיר</div>
          <div class="price">${Number(best.price).toFixed(0)} ${best.currency}
            <span class="dim">(סף: ${Number(resData.threshold).toFixed(0)} ${route.currency || best.currency})</span>
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
      `;
    } else {
      bestBox.innerHTML = `<div>לא נמצאו הצעות מתאימות בטווחים.</div>`;
    }

    // פרטי חיפוש
    details.classList.remove("hidden");
    details.innerHTML = `
      <div><strong>הגדרות חיפוש</strong></div>
      <div class="row"><div>נוסעים</div><div>${route.adults || 1} מבוגר/ים</div></div>
      <div class="row"><div>מטבע</div><div>${route.currency || 'ILS'}</div></div>
      <div class="row"><div>טווח יציאה</div>
        <div>מרכז: <code>${search.depart_center_date}</code> · ±<code>${search.depart_window_days}</code> ימים</div>
      </div>
      <div class="row"><div>טווח חזרה</div>
        <div>מרכז: <code>${search.return_center_date}</code> · ±<code>${search.return_window_days}</code> ימים</div>
      </div>
      <div class="row"><div>שהייה</div>
        <div>מינ׳ <code>${search.min_stay_days}</code> · מקס׳ <code>${search.max_stay_days}</code> ימים</div>
      </div>
    `;

    // === גרף היסטוריה (Canvas 2D בסיסי) ===
    const points = history
      .filter(x => x && typeof x.price === "number")
      .map(x => ({ t: new Date(x.ts).getTime(), y: x.price }))
      .sort((a,b) => a.t - b.t);

    const ctx = chartEl.getContext("2d");
    ctx.clearRect(0,0,chartEl.width,chartEl.height);
    if (points.length >= 2) {
      const pad = 30;
      const W = chartEl.width, H = chartEl.height;
      const minX = points[0].t, maxX = points[points.length-1].t;
      const minY = Math.min(...points.map(p => p.y));
      const maxY = Math.max(...points.map(p => p.y));
      const x = (t) => pad + (W-2*pad) * (t - minX) / Math.max(1,(maxX-minX));
      const y = (v) => H - pad - (H-2*pad) * (v - minY) / Math.max(1,(maxY-minY));

      // צירים
      ctx.strokeStyle = "#5a6473";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(pad, H-pad); ctx.lineTo(W-pad, H-pad); // X
      ctx.moveTo(pad, pad);   ctx.lineTo(pad,   H-pad); // Y
      ctx.stroke();

      // קו מחיר
      ctx.strokeStyle = "#a6c8ff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x(points[0].t), y(points[0].y));
      for (let i=1;i<points.length;i++){
        ctx.lineTo(x(points[i].t), y(points[i].y));
      }
      ctx.stroke();

      // נקודות
      ctx.fillStyle = "#d9e6ff";
      for (const p of points){
        ctx.beginPath();
        ctx.arc(x(p.t), y(p.y), 3, 0, Math.PI*2);
        ctx.fill();
      }
    } else {
      ctx.fillStyle = "#a9b4c3";
      ctx.fillText("לא נמצאו מספיק נתוני היסטוריה לגרף.", 10, 20);
    }

    // טבלת היסטוריה
    if (history.length) {
      const rows = history.slice().reverse().map(h => `
        <tr>
          <td><code>${h.ts}</code></td>
          <td>${h.origin} ⇄ ${h.destination}</td>
          <td>${h.depart || "—"} → ${h.return || "—"}</td>
          <td>${h.price != null ? Number(h.price).toFixed(0) : "—"} ${h.currency || ""}</td>
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
    }

  } catch (err) {
    status.innerHTML = `<span class="badge err">שגיאה</span> ${String(err)}`;
    console.error(err);
  }
})();
