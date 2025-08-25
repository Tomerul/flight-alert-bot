(async function () {
  const status = document.getElementById("status");
  const bestBox = document.getElementById("best");
  const details = document.getElementById("details");

  try {
    // results.json יפורסם לצד הקבצים בדף (נביא אותו משורש האתר)
    const res = await fetch("./results.json", { cache: "no-store" });
    if (!res.ok) throw new Error("results.json לא נמצא");
    const data = await res.json();

    status.innerHTML = `עודכן לאחרונה: <code>${data.generated_at}</code>`;
    const route = data.route || {};
    const search = data.search || {};
    const best = data.best;

    // כרטיס עסקה
    if (best) {
      bestBox.classList.remove("hidden");
      bestBox.innerHTML = `
        <div class="row"><div>מסלול</div><div><strong>${route.origin} ⇄ ${route.destination}</strong></div></div>
        <div class="row"><div>תאריכים</div><div>יציאה <code>${best.depart}</code> · חזרה <code>${best.return}</code></div></div>
        <div class="row"><div>מחיר</div>
          <div class="price">${Number(best.price).toFixed(0)} ${best.currency}
            <span class="dim">(סף: ${Number(data.threshold).toFixed(0)} ${route.currency || best.currency})</span>
          </div>
        </div>
        <div class="row"><div>סטטוס</div>
          <div><span class="badge ${data.below_threshold ? 'ok' : 'err'}">
            ${data.below_threshold ? 'מתחת לסף ✅' : 'מעל הסף'}
          </span></div>
        </div>
      `;
    } else {
      bestBox.classList.remove("hidden");
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
  } catch (err) {
    status.innerHTML = `<span class="badge err">שגיאה</span> ${String(err)}`;
    console.error(err);
  }
})();
