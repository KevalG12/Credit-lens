/* CreditLens views: dashboard, score-from-form, calculators, offers.
   Loaded before app.js; uses its helpers (h, s, api, mount, money, gauge, sign, dir, fmtDate, toast, privacyCard, csvPanel). */
"use strict";
const C = window.CL_CALC;
const inr = n => "₹" + money(Math.round(n));
const shortDate = iso => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "2-digit" });
const BAND_FLOORS = [300, 500, 650, 750];

/* ================================================================== DASHBOARD */
function trendChart(points, min = 300, max = 900) {
  const W = 560, H = 230, L = 40, R = 14, T = 12, B = 30, iw = W - L - R, ih = H - T - B;
  const y = v => T + ih - (v - min) / (max - min) * ih;
  const x = i => points.length === 1 ? L + iw / 2 : L + iw * i / (points.length - 1);
  const bands = [[300, 500, "var(--poor)", "Poor"], [500, 650, "var(--fair)", "Fair"], [650, 750, "var(--goodband)", "Good"], [750, 900, "var(--excellent)", "Excellent"]];
  const kids = [];
  bands.forEach(([a, b, c, name]) => {
    kids.push(s("rect", { x: L, y: y(b), width: iw, height: y(a) - y(b), fill: c, "fill-opacity": 0.12 }));
    kids.push(s("text", { x: L + 6, y: y(b) + 13, "font-size": 10.5, fill: "var(--muted)" }, name));
  });
  [300, 500, 650, 750, 900].forEach(v => {
    kids.push(s("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), stroke: "var(--line)", "stroke-width": 1 }));
    kids.push(s("text", { x: L - 6, y: y(v) + 4, "font-size": 10.5, fill: "var(--muted)", "text-anchor": "end" }, String(v)));
  });
  if (points.length > 1)
    kids.push(s("path", { d: points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.score).toFixed(1)}`).join(" "), fill: "none", stroke: "var(--brand)", "stroke-width": 3, "stroke-linejoin": "round", "stroke-linecap": "round" }));
  points.forEach((p, i) => kids.push(s("circle", { cx: x(i), cy: y(p.score), r: i === points.length - 1 ? 6 : 4.5, fill: i === points.length - 1 ? "var(--brand)" : "var(--surface)", stroke: "var(--brand)", "stroke-width": 2.5 },
    s("title", {}, `${p.score} (${p.band}) on ${shortDate(p.created_at)}`))));
  kids.push(s("text", { x: x(0), y: H - 8, "font-size": 10.5, fill: "var(--muted)", "text-anchor": points.length === 1 ? "middle" : "start" }, shortDate(points[0].created_at)));
  if (points.length > 1) kids.push(s("text", { x: x(points.length - 1), y: H - 8, "font-size": 10.5, fill: "var(--muted)", "text-anchor": "end" }, shortDate(points.at(-1).created_at)));
  const last = points.at(-1);
  return s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", class: "trend", "aria-label": `Score trend over ${points.length} check${points.length > 1 ? "s" : ""}, latest ${last.score}` }, ...kids);
}

function factorMini(f) {
  return h("div", { class: "mini-factor" }, h("div", { class: "frow" }, h("span", {}, f.label), h("span", { class: "pts " + dir(f.points) }, sign(f.points) + " pts")),
    h("div", { class: "small muted" }, f.reason));
}

function goalCard(d) {
  const g = d.goal, cur = d.latest.score;
  if (g.kind === "maintain") {
    return h("div", { class: "card goal" }, h("h2", {}, "\u{1F3C6} Goal: stay Excellent"),
      h("p", {}, `You are ${g.points_above} points above the Excellent line (750). Keep paying on time and saving regularly.`));
  }
  const floor = [...BAND_FLOORS].reverse().find(f => f <= cur) ?? 300;
  const pct = Math.max(0, Math.min(100, (cur - floor) / (g.target - floor) * 100));
  return h("div", { class: "card goal" }, h("h2", {}, `\u{1F3AF} Goal: reach ${g.next_band} (${g.target})`),
    h("p", { class: "muted small" }, `${g.points_to_go} points to go. We applied your tips one by one and re-scored with the real model after each.`),
    h("div", { class: "progress", role: "progressbar", "aria-valuenow": Math.round(pct), "aria-valuemin": 0, "aria-valuemax": 100, "aria-label": `Progress to ${g.next_band}` },
      h("i", { style: `width:${pct}%` }), h("span", { class: "progress-l" }, String(floor)), h("span", { class: "progress-r" }, String(g.target))),
    g.steps.length ? h("ol", { class: "plan" }, g.steps.map(st => h("li", {}, h("div", {}, h("strong", {}, st.label), h("div", { class: "small muted" }, `${st.from} → ${st.to}`), h("div", { class: "small" }, st.advice)),
      h("span", { class: "gain" }, "→ " + st.score_after)))) : h("p", { class: "muted" }, "No single habit change gets you there yet. A longer, steadier history will."),
    g.steps.length && !g.reachable ? h("p", { class: "small muted" }, `These steps alone would lift you to ${g.final_score}. Keep going after that and check again.`) : null,
    g.reachable ? h("p", { class: "small", style: "color:var(--good);font-weight:600" }, `Doing all of this would put you at ${g.final_score}, in the ${g.next_band} band.`) : null);
}

async function viewDashboard() {
  const d = await api("/dashboard");
  if (!d.has_scores) {
    return mount(h("div", { class: "grid split" },
      h("section", { class: "auth-hero" }, h("h1", {}, "Welcome to your ", h("em", {}, "credit dashboard")),
        h("p", { class: "muted" }, "Get your first score and this page turns into a tracker: trend over time, a plan to reach the next band, alerts when something changes, and offers matched to you.")),
      h("div", { class: "card" }, h("h2", {}, "Get your first score"), h("p", { class: "muted small" }, "Type in a few months of figures, or upload a bank statement. Takes about two minutes."),
        h("a", { class: "btn primary wide", href: "#/new" }, "Calculate my score"),
        h("p", { class: "small muted", style: "margin-top:1rem" }, "Just want a quick sum? Try the ", h("a", { href: "#/tools" }, "calculators"), "."))));
  }
  const L = d.latest, ch = d.change;
  const alerts = d.alerts.length ? h("div", { class: "alerts", role: "list" }, d.alerts.map(a => h("div", { class: "alert " + a.level, role: "listitem" },
    h("span", { "aria-hidden": "true" }, a.level === "warn" ? "⚠️" : a.level === "good" ? "\u{1F389}" : "\u{1F4A1}"), h("span", {}, a.text)))) : null;
  const due = new Date(L.next_check_due);
  const checkNote = L.check_overdue ? `Re-check overdue (due ${shortDate(L.next_check_due)})` : `Next check due ${shortDate(L.next_check_due)}`;
  const delta = ch.vs_previous;
  const stat = (v, l) => h("div", { class: "stat" }, h("b", {}, v), h("span", {}, l));
  const o = d.offers;
  mount(
    h("div", { class: "page-actions" }, h("h1", { style: "margin:0" }, "Dashboard"),
      h("div", { class: "chips", style: "margin:0" }, h("a", { class: "btn", href: "#/score/" + L.id }, "Full breakdown"), h("a", { class: "btn primary", href: "#/new" }, "➕ Check again"))),
    alerts,
    h("div", { class: "grid hero" },
      h("div", { class: "card" }, gauge(L.score, L.score_min, L.score_max, L.band),
        delta != null ? h("p", { class: "delta " + dir(delta), style: "text-align:center;margin:.8rem 0 0" }, delta === 0 ? "No change since last check" : `${sign(delta)} points since last check`) : h("p", { class: "muted small", style: "text-align:center" }, "First check. Check again next month to see your trend."),
        h("p", { class: "small " + (L.check_overdue ? "overdue" : "muted"), style: "text-align:center;margin:.4rem 0 0" }, "\u{1F5D3}️ " + checkNote,
          h("span", { class: "sr-only" }, ` (${due.toDateString()})`))),
      h("div", { class: "card" }, h("h2", {}, "Score trend"), trendChart(d.trend),
        h("div", { class: "stats three" }, stat(String(d.stats.checks), "Checks so far"), stat(String(d.stats.best), "Best score"),
          stat(ch.vs_first == null ? "–" : sign(ch.vs_first), "Since your first check")))),
    goalCard(d),
    h("div", { class: "grid two" },
      h("div", { class: "card" }, h("h2", {}, "\u{1F44D} What's helping"), d.helping.length ? d.helping.map(factorMini) : h("p", { class: "muted small" }, "Nothing is clearly boosting your score yet.")),
      h("div", { class: "card" }, h("h2", {}, "\u{1F44E} What's hurting"), d.hurting.length ? d.hurting.map(factorMini) : h("p", { class: "muted small" }, "Nothing is dragging your score down. Nice."))),
    d.movers.length ? h("div", { class: "card" }, h("h2", {}, "What moved since your last check"),
      d.movers.map(m => h("div", { class: "frow mover" }, h("span", {}, m.label), h("span", { class: "pts " + dir(m.delta) }, sign(m.delta) + " pts")))) : null,
    h("div", { class: "grid two" },
      h("div", { class: "card" }, h("h2", {}, "\u{1F4B3} Offers for you"),
        h("p", {}, h("b", {}, `${o.eligible_loans} of ${o.total_loans}`), " loan products match your score today."),
        o.best_personal_rate != null ? h("p", { class: "small muted" }, `Best indicative personal-loan rate: ${o.best_personal_rate}% APR.`) : null,
        h("p", { class: "small" }, o.cards_verdict_title), o.top_card ? h("p", { class: "small muted" }, "Top card match: " + o.top_card) : null,
        h("a", { class: "btn", href: "#/offers/" + L.id }, "See loans and cards")),
      h("div", { class: "card" }, h("h2", {}, "\u{1F9EE} Calculators"), h("p", { class: "muted small" }, "Work out an EMI, how much you can borrow, a savings plan, or whether your budget is healthy."),
        h("div", { class: "chips" }, [["emi", "EMI"], ["afford", "How much can I borrow?"], ["goal", "Savings goal"], ["budget", "Budget check"]].map(([k, l]) => h("a", { class: "btn", href: "#/tools/" + k }, l))))),
    h("p", { class: "small muted" }, "Demo only: scores come from a model trained on synthetic data and are not real credit scores."));
}

/* ================================================================== NEW SCORE (form | csv) */
const FORM_FIELDS = [
  ["income", "Income", "Salary, stipend, gig payouts, pocket money"],
  ["rent", "Rent / hostel", "What you pay for a place to live"],
  ["emi", "Loan EMIs", "Instalments on any loan or BNPL"],
  ["bills", "Bills & recharges", "Electricity, mobile, internet"],
  ["food", "Food & groceries", "Eating out, delivery, groceries"],
  ["shopping", "Shopping & fun", "Clothes, gadgets, outings"],
  ["transport", "Transport & fuel", "Metro, cabs, petrol"],
  ["subscription", "Subscriptions", "OTT, apps, memberships"],
  ["other", "Other spending", "Anything else"],
  ["savings", "Saved / invested", "SIP, FD, recurring deposit, savings moved"],
];
const EXAMPLES = {
  intern: { label: "\u{1F393} Steady intern", note: "Fixed stipend, saves, pays on time", bills: 100, n: 6,
    rows: Array(6).fill({ income: 25000, rent: 8000, emi: 0, bills: 1500, food: 4500, shopping: 2000, transport: 1500, subscription: 500, other: 1500, savings: 5000 }) },
  gig: { label: "\u{1F6F5} Gig driver", note: "Income swings month to month", bills: 80, n: 6,
    rows: [18000, 31000, 12000, 26000, 9000, 29000].map(i => ({ income: i, rent: 6000, emi: 2500, bills: 1800, food: 4000, shopping: 1500, transport: 2500, subscription: 300, other: 1000, savings: i > 20000 ? 2000 : 0 })) },
  stretched: { label: "\u{1F4DA} Stretched student", note: "Tight budget, often late", bills: 45, n: 6,
    rows: Array(6).fill({ income: 21000, rent: 7500, emi: 4000, bills: 1800, food: 3500, shopping: 1500, transport: 1200, subscription: 400, other: 800, savings: 0 }) },
};
const PUNCTUAL = [[100, "Always on time"], [90, "Almost always"], [70, "Sometimes late"], [40, "Often late"]];

function numInput(value, onchange, label) {
  return h("input", { type: "number", class: "num", min: 0, step: 100, inputmode: "decimal", placeholder: "0", "aria-label": label, value: value ? String(value) : "",
    oninput: ev => onchange(Math.max(0, parseFloat(ev.target.value) || 0)) });
}

function viewNew(tab) {
  tab = tab === "csv" ? "csv" : "form";
  const tabs = h("div", { class: "tabs", role: "tablist" },
    h("a", { href: "#/new/form", role: "tab", class: tab === "form" ? "on" : "", "aria-selected": tab === "form" }, "✍️ Type in my figures"),
    h("a", { href: "#/new/csv", role: "tab", class: tab === "csv" ? "on" : "", "aria-selected": tab === "csv" }, "\u{1F4C4} Upload a statement"));
  mount(h("h1", {}, "Get your score"),
    h("p", { class: "muted", style: "max-width:62ch" }, tab === "form" ? "No statement needed. Enter your income and spending for a few months and we calculate the same score a statement would give."
      : "Upload a bank or UPI statement (CSV) and we read it for you."),
    tabs, tab === "form" ? manualForm() : csvPanel(), privacyCard());
}

function manualForm() {
  const st = { n: 6, vary: false, typical: { ...EXAMPLES.intern.rows[0], income: 0, rent: 0, bills: 0, food: 0, shopping: 0, transport: 0, subscription: 0, other: 0, savings: 0 }, rows: [], pct: 90, consent: false };
  const blank = () => Object.fromEntries(FORM_FIELDS.map(([k]) => [k, 0]));
  st.typical = blank();
  const body = h("div"), preview = h("div", { class: "card sticky-card", "aria-live": "polite" }), err = h("div", { class: "err", role: "alert" });
  const go = h("button", { class: "primary wide", type: "button", disabled: true }, "Calculate my score");
  const effective = () => st.vary ? st.rows.slice(0, st.n) : Array.from({ length: st.n }, () => ({ ...st.typical }));
  const problems = () => {
    const ms = effective(), out = [];
    if (!ms.some(m => m.income > 0)) out.push("Enter your income for at least one month.");
    if (ms.some(m => FORM_FIELDS.some(([k]) => m[k] > 1e8))) out.push("An amount is larger than ₹10 crore. Please check it.");
    return out;
  };
  const ensureRows = () => { while (st.rows.length < st.n) st.rows.push({ ...(st.rows.at(-1) || st.typical) }); };

  function drawPreview() {
    const ms = effective(), b = C.budgetRatios(ms), hl = C.ratioHealth(b), probs = problems();
    const meter = (label, val, health, hint) => h("div", { class: "ratio" }, h("div", { class: "frow" }, h("span", {}, label), h("span", { class: "chip-h " + health }, health === "good" ? "Healthy" : health === "ok" ? "Watch" : "Risky")),
      h("div", { class: "meter" }, h("i", { style: `width:${Math.min(100, val * 100)}%;background:var(--${health === "good" ? "good" : health === "ok" ? "fair" : "poor"})` })),
      h("div", { class: "small muted" }, hint));
    const has = b.avgIncome > 0;
    preview.replaceChildren(...[h("h2", {}, "Live check"), has ? [
      h("div", { class: "stats" }, h("div", { class: "stat" }, h("b", {}, inr(b.avgIncome)), h("span", {}, "Avg income / month")),
        h("div", { class: "stat" }, h("b", { style: b.leftover < 0 ? "color:var(--bad)" : "" }, (b.leftover < 0 ? "−" : "") + inr(Math.abs(b.leftover))), h("span", {}, b.leftover < 0 ? "Short each month" : "Left over / month"))),
      b.overspent ? h("p", { class: "warn small", style: "margin-top:.8rem" }, "Your spending and savings add up to more than your income. Double-check the figures.") : null,
      h("div", { style: "margin-top:.6rem" }, meter("Saved", b.savingsRatio, hl.savings, `${(b.savingsRatio * 100).toFixed(0)}% of income. Aim for 15%+.`),
        meter("Rent share", b.rentRatio, hl.rent, `${(b.rentRatio * 100).toFixed(0)}% of income. Under 30% is comfortable.`),
        meter("EMI burden", b.emiRatio, hl.emi, `${(b.emiRatio * 100).toFixed(0)}% of income. Under 25% is comfortable.`),
        n_gt1() ? meter("Income swings", Math.min(1, b.incomeCV), hl.income, `Month-to-month variation ${(b.incomeCV * 100).toFixed(0)}%. Steadier is better.`) : null)]
      : h("p", { class: "muted small" }, "Enter your income and we will show how your budget looks as you type."),
      probs.length ? h("ul", { class: "notes small" }, probs.map(p => h("li", {}, p))) : null].flat(Infinity).filter(Boolean));
    refresh();
  }
  const n_gt1 = () => st.vary && st.n > 1;
  const refresh = () => go.disabled = !(st.consent && !problems().length);

  function drawBody() {
    const monthsSel = h("select", { id: "n-months", "aria-label": "Number of months", onchange: ev => { st.n = +ev.target.value; if (st.vary) ensureRows(); drawBody(); drawPreview(); } },
      [3, 4, 6, 9, 12].map(n => h("option", { value: n, selected: n === st.n }, `${n} months`)));
    const toggle = h("label", { class: "check", style: "margin:.2rem 0" }, h("input", { type: "checkbox", checked: st.vary, onchange: ev => {
      if (ev.target.checked) { st.rows = Array.from({ length: 12 }, () => ({ ...st.typical })); }
      else { const ms = st.rows.slice(0, st.n); FORM_FIELDS.forEach(([k]) => st.typical[k] = Math.round(ms.reduce((a, m) => a + m[k], 0) / (ms.length || 1))); }
      st.vary = ev.target.checked; drawBody(); drawPreview(); } }),
      h("span", {}, h("b", {}, "My income or spending changes a lot from month to month"), h("br"), h("span", { class: "small muted" }, "Recommended for gig work, freelancing or irregular pay: enter each month separately.")));
    let inputs;
    if (!st.vary) {
      inputs = h("div", { class: "fgrid" }, FORM_FIELDS.map(([k, l, d]) => h("div", { class: "fcell" }, h("label", { style: "margin:0" }, l, h("span", { class: "small muted hint" }, d)),
        h("div", { class: "rupee" }, h("span", { "aria-hidden": "true" }, "₹"), numInput(st.typical[k], v => { st.typical[k] = v; drawPreview(); }, `${l} per month`)))));
    } else {
      ensureRows();
      inputs = h("div", { class: "scroll" }, h("table", { class: "mtable" },
        h("thead", {}, h("tr", {}, h("th", {}, "Month"), FORM_FIELDS.map(([, l]) => h("th", {}, l)))),
        h("tbody", {}, st.rows.slice(0, st.n).map((row, i) => h("tr", {}, h("th", { scope: "row" }, i === 0 ? "Oldest" : i === st.n - 1 ? "Latest" : `Month ${i + 1}`),
          FORM_FIELDS.map(([k, l]) => h("td", {}, numInput(row[k], v => { row[k] = v; drawPreview(); }, `${l}, month ${i + 1}`))))))));
    }
    const slider = h("input", { type: "range", min: 0, max: 100, step: 5, value: st.pct, "aria-label": "Share of bills paid on time",
      oninput: ev => { st.pct = +ev.target.value; out.textContent = st.pct + "%"; chips.forEach(([c, v]) => c.classList.toggle("on", v === st.pct)); } });
    const out = h("output", {}, st.pct + "%");
    const chips = PUNCTUAL.map(([v, l]) => [h("button", { type: "button", class: "persona small-chip" + (v === st.pct ? " on" : ""), onclick: () => { st.pct = v; slider.value = v; out.textContent = v + "%"; chips.forEach(([c, x]) => c.classList.toggle("on", x === v)); } }, l), v]);
    body.replaceChildren(
      h("div", { class: "card" }, h("h2", {}, h("span", { class: "step-n" }, "1"), "Try an example (optional)"),
        h("p", { class: "small muted" }, "Fills the form with realistic figures so you can see how it works. Edit anything afterwards."),
        h("div", { class: "chips" }, Object.entries(EXAMPLES).map(([k, ex]) => h("button", { type: "button", class: "persona", onclick: () => {
          st.n = ex.n; st.pct = ex.pct ?? ex.bills; st.vary = k === "gig"; st.rows = ex.rows.map(r => ({ ...r })); st.typical = { ...ex.rows[0] };
          drawBody(); drawPreview(); toast("Example loaded. Change any number you like."); } }, h("b", {}, ex.label), h("span", {}, ex.note))))),
      h("div", { class: "card" }, h("h2", {}, h("span", { class: "step-n" }, "2"), "Your money, per month"),
        h("div", { class: "form-top" }, h("label", { for: "n-months", style: "margin:0" }, "How many months are you entering?"), monthsSel),
        h("p", { class: "small muted" }, st.vary ? "Enter each month. Leave a box empty or 0 if it doesn't apply." : "Enter what a typical month looks like. Leave a box empty or 0 if it doesn't apply."),
        toggle, inputs),
      h("div", { class: "card" }, h("h2", {}, h("span", { class: "step-n" }, "3"), "Paying on time"),
        h("p", { class: "small muted" }, "Of your rent, EMI and bill payments over this period, how many did you pay by the due date? This is the single biggest factor in the score."),
        h("div", { class: "chips tight" }, chips.map(([c]) => c)),
        h("div", { class: "slider" }, h("div", { class: "top-row" }, h("label", { style: "margin:0" }, "On-time payments"), out), slider)));
  }

  const consent = h("input", { type: "checkbox", id: "mconsent", onchange: ev => { st.consent = ev.target.checked; refresh(); } });
  go.onclick = async () => {
    err.textContent = ""; go.disabled = true; const old = go.textContent; go.replaceChildren(h("span", { class: "spinner" }), " Calculating…");
    try {
      const r = await api("/score/manual", { method: "POST", json: { months: effective().map(m => Object.fromEntries(FORM_FIELDS.map(([k]) => [k, m[k] || 0]))), bills_on_time_pct: st.pct, consent: true } });
      location.hash = "#/score/" + r.id;
    } catch (e) { err.textContent = e.message; } finally { go.textContent = old; refresh(); }
  };
  drawBody(); drawPreview();
  return h("div", { class: "grid form-layout" }, body,
    h("aside", {}, preview, h("div", { class: "card" }, h("h2", {}, h("span", { class: "step-n" }, "4"), "Consent and calculate"),
      h("label", { class: "check", for: "mconsent" }, consent, h("span", {}, "I agree to CreditLens calculating a score from these figures. Only 7 derived ratios and the result are stored, not the figures themselves. I can erase everything any time.")),
      err, go)));
}

/* ================================================================== CALCULATORS */
function slideNum(label, o, onchange) {
  const id = "sn-" + Math.random().toString(36).slice(2, 8);
  let val = o.value;
  const fmt = o.fmt || (v => inr(v));
  const num = h("input", { type: "number", class: "num", id, min: o.min, max: o.hardMax ?? o.max, step: o.step, inputmode: "decimal", value: String(val) });
  const rng = h("input", { type: "range", min: o.min, max: o.max, step: o.step, value: val, "aria-label": label + " slider" });
  const shown = h("output", { class: "sn-out" }, fmt(val));
  const set = (v, from) => { val = v; if (from !== "num") num.value = String(v); if (from !== "rng") rng.value = String(Math.min(o.max, v)); shown.textContent = fmt(v); onchange(); };
  rng.oninput = () => set(+rng.value, "rng");
  num.oninput = () => { const v = parseFloat(num.value); set(Number.isFinite(v) ? Math.max(o.min, Math.min(o.hardMax ?? Infinity, v)) : 0, "num"); };
  return { el: h("div", { class: "slider" }, h("div", { class: "top-row" }, h("label", { for: id, style: "margin:0" }, label), shown), h("div", { class: "sn-row" }, rng, num)), get: () => val, set: v => set(v) };
}
const kpi = (v, l, cls = "") => h("div", { class: "stat kpi " + cls }, h("b", {}, v), h("span", {}, l));
function splitBar(parts) {
  const tot = parts.reduce((a, p) => a + p.v, 0) || 1;
  return h("div", null, h("div", { class: "splitbar", role: "img", "aria-label": parts.map(p => `${p.l} ${Math.round(p.v / tot * 100)}%`).join(", ") },
    parts.map(p => h("i", { style: `width:${p.v / tot * 100}%;background:${p.c}` }))),
    h("div", { class: "legend small" }, parts.map(p => h("span", {}, h("i", { style: `background:${p.c}` }), `${p.l} · ${inr(p.v)} (${Math.round(p.v / tot * 100)}%)`))));
}
const yrs = m => m % 12 === 0 ? `${m / 12} yr${m === 12 ? "" : "s"}` : m > 12 ? `${Math.floor(m / 12)} yr ${m % 12} mo` : `${m} mo`;

function calcEmi() {
  const out = h("div", { "aria-live": "polite" });
  const A = slideNum("Loan amount", { min: 5000, max: 2500000, step: 5000, value: 300000 }, run);
  const R = slideNum("Interest rate (per year)", { min: 1, max: 40, step: 0.1, value: 14, fmt: v => v.toFixed(1) + "%" }, run);
  const T = slideNum("Tenure", { min: 3, max: 120, step: 1, value: 36, fmt: v => `${v} months (${yrs(v)})` }, run);
  const X = slideNum("Extra you can pay each month (optional)", { min: 0, max: 50000, step: 500, value: 0 }, run);
  function run() {
    const P = A.get(), r = R.get(), n = T.get(), x = X.get();
    const base = C.amortise(P, r, n, 0), fast = x > 0 ? C.amortise(P, r, n, x) : null;
    const nodes = [h("div", { class: "stats three" }, kpi(inr(base.emi), "Monthly EMI", "big"), kpi(inr(base.totalInterest), "Total interest"), kpi(inr(base.totalPaid), "Total you pay")),
      h("div", { style: "margin:1rem 0" }, splitBar([{ l: "Principal", v: P, c: "var(--brand)" }, { l: "Interest", v: base.totalInterest, c: "var(--fair)" }]))];
    if (fast) nodes.push(h("div", { class: "note-good" }, h("b", {}, "Paying extra helps: "), `you finish ${base.months - fast.months} months sooner (${fast.months} instead of ${base.months}) and save ${inr(base.totalInterest - fast.totalInterest)} in interest.`));
    nodes.push(h("details", { style: "margin-top:1rem" }, h("summary", {}, "Year-by-year breakdown"),
      h("div", { class: "scroll" }, h("table", { class: "small" }, h("thead", {}, h("tr", {}, ["Year", "Principal paid", "Interest paid", "Balance left"].map(t => h("th", {}, t)))),
        h("tbody", {}, (fast || base).yearly.map(y => h("tr", {}, h("td", {}, String(y.year)), h("td", {}, inr(y.principal)), h("td", {}, inr(y.interest)), h("td", {}, inr(y.balance)))))))));
    out.replaceChildren(...nodes);
  }
  run();
  return h("div", { class: "grid two" }, h("div", { class: "card" }, h("h2", {}, "Loan details"), A.el, R.el, T.el, X.el),
    h("div", { class: "card" }, h("h2", {}, "Your repayment"), out, h("p", { class: "small muted", style: "margin-top:1rem" }, "Reducing-balance EMI, same formula lenders use. Processing fees are not included.")));
}

function calcAfford() {
  const out = h("div", { "aria-live": "polite" });
  const I = slideNum("Monthly income", { min: 5000, max: 300000, step: 1000, value: 30000, hardMax: 1e8 }, run);
  const E = slideNum("Existing EMIs per month", { min: 0, max: 100000, step: 500, value: 0, hardMax: 1e8 }, run);
  const R = slideNum("Expected interest rate", { min: 1, max: 40, step: 0.1, value: 14, fmt: v => v.toFixed(1) + "%" }, run);
  const T = slideNum("Tenure", { min: 6, max: 120, step: 1, value: 36, fmt: v => `${v} months (${yrs(v)})` }, run);
  function run() {
    const inc = I.get(), ex = E.get(), r = R.get(), n = T.get();
    const max = C.affordability(inc, ex, r, n), safe = C.affordability(inc, ex, r, n, 0.35);
    const used = inc > 0 ? ex / inc : 0;
    out.replaceChildren(
      h("div", { class: "stats three" }, kpi(inr(Math.floor(max.maxLoan / 1000) * 1000), "Most you could borrow", "big"), kpi(inr(Math.floor(safe.maxLoan / 1000) * 1000), "Comfortable amount"), kpi(inr(max.room), "Max EMI you can add")),
      h("p", { class: "small muted", style: "margin-top:1rem" }, `Lenders usually cap total EMIs at about 50% of income. "Comfortable" keeps them under 35%, which leaves room for emergencies. You already use ${(used * 100).toFixed(0)}% of your income on EMIs.`),
      used >= C.FOIR_CAP ? h("p", { class: "warn small" }, "Your existing EMIs already use up the usual limit, so a new loan is unlikely to be approved.") : null,
      max.maxLoan > 0 ? h("p", {}, h("a", { class: "btn", href: "#/tools/emi" }, "Work out the EMI for a specific amount")) : null);
  }
  run();
  return h("div", { class: "grid two" }, h("div", { class: "card" }, h("h2", {}, "Your situation"), I.el, E.el, R.el, T.el),
    h("div", { class: "card" }, h("h2", {}, "How much can I borrow?"), out));
}

function calcGoal() {
  const out = h("div", { "aria-live": "polite" });
  const G = slideNum("Goal amount", { min: 10000, max: 5000000, step: 10000, value: 200000 }, run);
  const Y = slideNum("Time to reach it", { min: 1, max: 20, step: 1, value: 3, fmt: v => `${v} year${v > 1 ? "s" : ""}` }, run);
  const Rt = slideNum("Expected yearly return", { min: 0, max: 15, step: 0.5, value: 6, fmt: v => v.toFixed(1) + "%" }, run);
  const S = slideNum("Already saved", { min: 0, max: 1000000, step: 5000, value: 0, hardMax: 1e8 }, run);
  function run() {
    const g = C.savingsGoal(G.get(), Y.get(), Rt.get(), S.get());
    out.replaceChildren(
      h("div", { class: "stats three" }, kpi(inr(Math.ceil(g.monthly)), "Save each month", "big"), kpi(inr(g.invested), "You put in"), kpi(inr(g.growth), "Growth earned")),
      g.invested + g.growth > 0 ? h("div", { style: "margin:1rem 0" }, splitBar([{ l: "Your savings", v: g.invested, c: "var(--brand)" }, { l: "Growth", v: g.growth, c: "var(--fair)" }])) : null,
      h("p", { class: "small muted" }, "Regular saving also improves your score: the share of income you save is one of the seven factors. Returns are an assumption, not a promise."));
  }
  run();
  return h("div", { class: "grid two" }, h("div", { class: "card" }, h("h2", {}, "Your goal"), G.el, Y.el, Rt.el, S.el),
    h("div", { class: "card" }, h("h2", {}, "What it takes"), out));
}

function calcBudget() {
  const out = h("div", { "aria-live": "polite" });
  const I = slideNum("Monthly income", { min: 5000, max: 300000, step: 1000, value: 25000, hardMax: 1e8 }, run);
  const Re = slideNum("Rent / hostel", { min: 0, max: 100000, step: 500, value: 8000, hardMax: 1e8 }, run);
  const Em = slideNum("Loan EMIs", { min: 0, max: 100000, step: 500, value: 0, hardMax: 1e8 }, run);
  const Es = slideNum("Other essentials (bills, food, transport)", { min: 0, max: 100000, step: 500, value: 8000, hardMax: 1e8 }, run);
  const Li = slideNum("Lifestyle (shopping, subscriptions, other)", { min: 0, max: 100000, step: 500, value: 4000, hardMax: 1e8 }, run);
  const Sv = slideNum("Saved / invested", { min: 0, max: 100000, step: 500, value: 3000, hardMax: 1e8 }, run);
  function run() {
    const inc = I.get(), m = { income: inc, rent: Re.get(), emi: Em.get(), bills: Es.get(), shopping: Li.get(), savings: Sv.get() };
    const b = C.budgetRatios([m]), hl = C.ratioHealth(b);
    const row = (label, val, health, hint) => h("div", { class: "ratio" }, h("div", { class: "frow" }, h("span", {}, label), h("span", { class: "chip-h " + health }, health === "good" ? "Healthy" : health === "ok" ? "Watch" : "Risky")),
      h("div", { class: "meter" }, h("i", { style: `width:${Math.min(100, val * 100)}%;background:var(--${health === "good" ? "good" : health === "ok" ? "fair" : "poor"})` })), h("div", { class: "small muted" }, hint));
    const needs = inc * 0.5, wants = inc * 0.3, save = inc * 0.2, haveNeeds = m.rent + m.emi + m.bills;
    out.replaceChildren(
      h("div", { class: "stats three" }, kpi((b.leftover < 0 ? "−" : "") + inr(Math.abs(b.leftover)), b.leftover < 0 ? "Over budget" : "Left over", b.leftover < 0 ? "bad" : ""), kpi(inr(b.avgSpend), "Total spending"), kpi((b.savingsRatio * 100).toFixed(0) + "%", "Saved")),
      h("div", { style: "margin-top:1rem" }, row("Savings rate", b.savingsRatio, hl.savings, "15%+ of income is a strong habit; under 5% hurts your score."),
        row("Rent share", b.rentRatio, hl.rent, `${(b.rentRatio * 100).toFixed(0)}% of income. Under 30% is comfortable.`),
        row("EMI burden", b.emiRatio, hl.emi, `${(b.emiRatio * 100).toFixed(0)}% of income. Lenders get nervous above 40%.`)),
      h("details", {}, h("summary", { class: "small" }, "Compare with the 50/30/20 guide"), h("p", { class: "small" }, `Needs ${inr(needs)} (you: ${inr(haveNeeds)}), wants ${inr(wants)} (you: ${inr(m.shopping)}), savings ${inr(save)} (you: ${inr(m.savings)}).`)),
      h("p", {}, h("a", { class: "btn primary", href: "#/new" }, "Turn this into my credit score")));
  }
  run();
  return h("div", { class: "grid two" }, h("div", { class: "card" }, h("h2", {}, "A typical month"), I.el, Re.el, Em.el, Es.el, Li.el, Sv.el),
    h("div", { class: "card" }, h("h2", {}, "Is it healthy?"), out));
}

const TOOLS = { emi: ["EMI calculator", calcEmi], afford: ["How much can I borrow?", calcAfford], goal: ["Savings goal", calcGoal], budget: ["Budget check", calcBudget] };
function viewTools(tab) {
  if (!TOOLS[tab]) tab = "emi";
  mount(h("h1", {}, "Calculators"), h("p", { class: "muted" }, "Quick, private sums. Nothing here is stored."),
    h("div", { class: "tabs", role: "tablist" }, Object.entries(TOOLS).map(([k, [l]]) => h("a", { href: "#/tools/" + k, role: "tab", class: k === tab ? "on" : "", "aria-selected": k === tab }, l))),
    TOOLS[tab][1]());
}

/* ================================================================== OFFERS */
const STATUS = { eligible: ["Eligible", "good"], close: ["Almost there", "ok"], not_yet: ["Not yet", "bad"] };
function statusTag(item) {
  const [t, c] = STATUS[item.status];
  return h("span", { class: "chip-h " + c }, item.status === "close" && item.points_needed ? `${t}: ${item.points_needed} pts` : t);
}
function loanCard(x) {
  return h("div", { class: "offer " + x.status },
    h("div", { class: "frow" }, h("div", {}, h("strong", {}, x.name), h("div", { class: "small muted" }, x.provider_type + (x.secured ? " · secured" : ""))), statusTag(x)),
    h("div", { class: "offer-stats" }, h("div", {}, h("b", {}, x.rate_apr + "%"), h("span", {}, "Indicative APR")), h("div", {}, h("b", {}, inr(x.emi_per_lakh)), h("span", {}, "EMI per ₹1 lakh (3 yr)")),
      h("div", {}, h("b", {}, `${inr(x.amount_range[0])} – ${inr(x.amount_range[1])}`), h("span", {}, "Amount")), h("div", {}, h("b", {}, `${x.tenure_months[0]}–${x.tenure_months[1]} mo`), h("span", {}, "Tenure"))),
    x.max_amount_for_you != null ? h("p", { class: "small", style: "margin:.4rem 0" }, "Based on your income you could borrow up to ", h("b", {}, inr(x.max_amount_for_you)), ".") : null,
    h("p", { class: "small muted", style: "margin:.2rem 0" }, `${x.best_for}. Fee ${x.fee_pct}%.`),
    x.blockers.length ? h("ul", { class: "notes small" }, x.blockers.map(b => h("li", {}, b))) : h("div", { class: "chips tight" }, x.perks.map(p => h("span", { class: "tag cat" }, p))));
}
function cardOffer(x) {
  const fee = x.annual_fee ? `${inr(x.annual_fee)}/yr` + (x.waiver_spend ? ` (waived above ${inr(x.waiver_spend)} spend)` : "") : "No annual fee";
  return h("div", { class: "offer " + x.status },
    h("div", { class: "frow" }, h("div", {}, h("strong", {}, x.name), h("div", { class: "small muted" }, x.issuer_type + (x.secured ? " · secured" : ""))),
      h("span", {}, x.recommended ? h("span", { class: "chip-h good", style: "margin-right:.4rem" }, "Top pick") : null, statusTag(x))),
    h("div", { class: "offer-stats" }, h("div", {}, h("b", {}, x.reward_rate_pct + "%"), h("span", {}, "Rewards on your spend")), h("div", {}, h("b", {}, x.interest_apr + "%"), h("span", {}, "Interest if unpaid")),
      h("div", {}, h("b", {}, x.limit), h("span", {}, "Limit")), h("div", {}, h("b", {}, x.net_annual_value != null ? inr(x.net_annual_value) : "–"), h("span", {}, "Net yearly value"))),
    h("div", { class: "meter", title: "How well the rewards fit your spending" }, h("i", { style: `width:${x.match_pct}%;background:var(--brand)` })),
    h("p", { class: "small muted", style: "margin:.2rem 0" }, `${x.best_for}. ${fee}.`),
    x.blockers.length ? h("ul", { class: "notes small" }, x.blockers.map(b => h("li", {}, b))) : h("div", { class: "chips tight" }, x.perks.map(p => h("span", { class: "tag cat" }, p))));
}
async function viewOffers(id) {
  if (!id) {
    const rows = await api("/scores");
    if (!rows.length) return mount(h("h1", {}, "Offers"), h("div", { class: "card empty" }, h("p", { class: "muted" }, "Get a score first and we will match loans and cards to it."), h("a", { class: "btn primary", href: "#/new" }, "Calculate my score")));
    id = rows[0].id;
  }
  let tab = "loans", income = "", spend = "";
  const body = h("div", { "aria-live": "polite" });
  async function load() {
    body.replaceChildren(h("div", { class: "card" }, h("div", { class: "skeleton" }), h("div", { class: "skeleton", style: "width:70%" })));
    try {
      if (tab === "loans") {
        const r = await api(`/scores/${id}/loans` + (income > 0 ? `?monthly_income=${income}` : ""));
        const sm = r.summary;
        body.replaceChildren(h("p", { class: "muted small" }, `${sm.eligible} eligible, ${sm.close} almost there, ${sm.not_yet} not yet for a score of ${r.score}.`), h("div", { class: "offers" }, r.loans.map(loanCard)), h("p", { class: "small muted" }, r.note));
      } else {
        const r = await api(`/scores/${id}/cards` + (spend > 0 ? `?monthly_spend=${spend}` : ""));
        const a = r.advice;
        body.replaceChildren(h("div", { class: "card advice " + a.verdict }, h("h2", {}, a.title), h("p", {}, a.summary),
          a.reasons.length ? h("ul", { class: "notes small" }, a.reasons.map(x => h("li", {}, x))) : null,
          h("details", {}, h("summary", { class: "small" }, "Healthy card habits"), h("ul", { class: "notes small" }, a.rules.map(x => h("li", {}, x))))),
          r.spend_share_is_default ? h("p", { class: "small muted" }, "Rewards are estimated with a typical student spending mix because this score was not built from a statement with categories.") : null,
          h("div", { class: "offers" }, r.cards.map(cardOffer)), h("p", { class: "small muted" }, r.note));
      }
    } catch (e) { body.replaceChildren(h("div", { class: "card" }, h("p", { class: "err" }, e.message))); }
  }
  const tabLink = (k, l) => h("a", { href: "javascript:void 0", role: "tab", class: tab === k ? "on" : "", onclick: ev => { ev.preventDefault(); tab = k; tabs.replaceChildren(...mk()); amount.replaceChildren(...mkAmt()); load(); } }, l);
  const mk = () => [tabLink("loans", "Loans"), tabLink("cards", "Credit cards")];
  const tabs = h("div", { class: "tabs", role: "tablist" }, ...mk());
  let timer;
  const mkAmt = () => [h("label", { for: "amt", style: "margin:0" }, tab === "loans" ? "Your monthly income (optional, sizes the loan, never stored)" : "Your monthly card spend (optional, estimates yearly value)"),
    h("input", { type: "number", class: "num", id: "amt", min: 0, step: 1000, inputmode: "decimal", placeholder: "e.g. 25000", value: (tab === "loans" ? income : spend) || "",
      oninput: ev => { const v = Math.max(0, parseFloat(ev.target.value) || 0); if (tab === "loans") income = v; else spend = v; clearTimeout(timer); timer = setTimeout(load, 350); } })];
  const amount = h("div", { class: "card amt" }, ...mkAmt());
  mount(h("div", { class: "page-actions" }, h("h1", { style: "margin:0" }, "Offers for you"), h("a", { class: "btn", href: "#/" }, "← Dashboard")),
    h("p", { class: "muted", style: "max-width:64ch" }, "Indicative terms from a sample catalogue, matched to your score. A better score unlocks lower rates. Final approval is always the lender's decision."),
    tabs, amount, body);
  await load();
}
