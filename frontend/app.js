/* CreditLens frontend: dependency-free SPA. Same-origin API by default;
   override with ?api=http://host:8000 or window.CREDITLENS_API. */
"use strict";
const API = (new URLSearchParams(location.search).get("api") || window.CREDITLENS_API || "").replace(/\/$/, "");
const $app = document.getElementById("app"), $nav = document.getElementById("nav"), $toast = document.getElementById("toast");
const store = {
  get() { try { return localStorage.getItem("cl_token"); } catch { return null; } },
  set(t) { try { t ? localStorage.setItem("cl_token", t) : localStorage.removeItem("cl_token"); } catch {} },
};
let token = store.get(), me = null, featureMeta = null;

// Make replaceChildren tolerant like h(): flatten nested arrays and skip null/false instead of printing them.
(() => { const orig = Element.prototype.replaceChildren;
  Element.prototype.replaceChildren = function (...kids) { return orig.apply(this, kids.flat(Infinity).filter(k => k != null && k !== false)); }; })();

/* ---------- helpers ---------- */
function h(tag, attrs = {}, ...kids) {           // safe DOM builder: text is never parsed as HTML
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k in el && k !== "list") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(kid));
  return el;
}
const mount = (...nodes) => $app.replaceChildren(...nodes.flat(Infinity).filter(x => x != null && x !== false));   // never render null/false as text
const svgNS = "http://www.w3.org/2000/svg";
function s(tag, attrs = {}, ...kids) {
  const el = document.createElementNS(svgNS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  kids.flat().forEach(k => el.append(k.nodeType ? k : document.createTextNode(k)));
  return el;
}
function toast(msg) { $toast.textContent = msg; $toast.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => $toast.hidden = true, 3500); }
const fmtDate = iso => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
const sign = n => (n > 0 ? "+" : n < 0 ? "−" : "") + Math.abs(Math.round(n));
const dir = n => n > 0.5 ? "up" : n < -0.5 ? "down" : "flat";

class ApiError extends Error { constructor(status, msg) { super(msg); this.status = status; } }
async function api(path, { method = "GET", json, form, auth = true } = {}) {
  const headers = {};
  if (auth && token) headers.Authorization = "Bearer " + token;
  let body;
  if (json) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  if (form) body = form;
  let res;
  try { res = await fetch(API + path, { method, headers, body }); }
  catch { throw new ApiError(0, "Can't reach the server. Is the backend running?"); }
  if (res.status === 401 && auth) { logout(true); throw new ApiError(401, "Your session expired. Please sign in again."); }
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) {
    let d = data?.detail;
    if (Array.isArray(d)) d = d.map(e => e.msg).join("; ");   // pydantic validation errors
    throw new ApiError(res.status, d || `Request failed (${res.status})`);
  }
  return data;
}
function logout(expired) { token = null; me = null; store.set(null); renderNav(); if (location.hash !== "#/login") location.hash = "#/login"; else route(); if (expired) toast("Session expired. Please sign in again."); }

/* ---------- nav & router ---------- */
function renderNav() {
  const cur = (location.hash.replace(/^#\/?/, "").split("/")[0]) || "";
  const link = (href, text, key) => h("a", { href, class: cur === key ? "active" : "" }, text);
  $nav.replaceChildren(...(token ? [
    link("#/", "Dashboard", ""), link("#/new", "New score", "new"), link("#/tools", "Calculators", "tools"),
    link("#/offers", "Offers", "offers"), link("#/history", "History", "history"),
    me ? h("span", { class: "user", title: me.email }, me.is_guest ? "Guest (demo)" : me.email) : null,
    h("button", { onclick: () => logout() }, "Sign out"),
  ] : []));
}
async function route() {
  const parts = (location.hash.replace(/^#\/?/, "") || "").split("/");
  renderNav();
  if (!token && parts[0] !== "login") { location.hash = "#/login"; return; }
  if (token && parts[0] === "login") { location.hash = "#/"; return; }
  if (token && !me) api("/auth/me").then(u => { me = u; renderNav(); }).catch(() => {});
  mount(h("div", { class: "card" }, h("div", { class: "skeleton", style: "width:40%" }), h("div", { class: "skeleton" }), h("div", { class: "skeleton", style: "width:75%" })));
  try {
    if (parts[0] === "login") viewAuth();
    else if (parts[0] === "score" && parts[1]) await viewScore(+parts[1]);
    else if (parts[0] === "history") await viewHistory();
    else if (parts[0] === "new") viewNew(parts[1]);
    else if (parts[0] === "tools") viewTools(parts[1]);
    else if (parts[0] === "offers") await viewOffers(parts[1] ? +parts[1] : null);
    else if (parts[0] === "compare" && parts[1] && parts[2]) await viewCompare(+parts[1], +parts[2]);
    else await viewDashboard();
  } catch (e) { if (e.status !== 401) mount(h("div", { class: "card" }, h("h2", {}, "Something went wrong"), h("p", { class: "err" }, e.message), h("a", { class: "btn", href: "#/" }, "Back"))); }
  $app.focus({ preventScroll: true });
}
addEventListener("hashchange", route);

/* ---------- auth ---------- */
const RULES = [
  ["8+ characters", p => p.length >= 8], ["Uppercase letter (A-Z)", p => /[A-Z]/.test(p)],
  ["Lowercase letter (a-z)", p => /[a-z]/.test(p)], ["A number (0-9)", p => /\d/.test(p)],
  ["Special character (!@#$\u2026)", p => /[^A-Za-z0-9]/.test(p)],
];
function passwordField(id, autocomplete) {
  const input = h("input", { type: "password", id, autocomplete, required: true });
  const eye = h("button", { type: "button", class: "eye", "aria-label": "Show password", onclick: () => {
    const show = input.type === "password"; input.type = show ? "text" : "password"; eye.textContent = show ? "Hide" : "Show";
    eye.setAttribute("aria-label", show ? "Hide password" : "Show password"); } }, "Show");
  return { input, wrap: h("div", { class: "field" }, input, eye) };
}
function viewAuth() {
  let mode = "login";
  const err = h("div", { class: "err", role: "alert" });
  const email = h("input", { type: "email", id: "email", autocomplete: "email", required: true, placeholder: "you@example.com" });
  const { input: pw, wrap: pwWrap } = passwordField("pw", "current-password");
  const rules = h("ul", { class: "rules", "aria-label": "Password requirements" }, RULES.map(([t]) => h("li", {}, t)));
  const bar = h("i"), meter = h("div", { class: "meter", "aria-hidden": "true" }, bar);
  const policy = h("div", { hidden: true }, meter, rules);
  const submit = h("button", { class: "primary wide", type: "submit" }, "Sign in");
  const toggle = h("button", { type: "button", class: "link" }, "Create an account");
  const title = h("h2", { style: "font-size:1.6rem" }, "Welcome back");
  const sub = h("p", { class: "muted small" }, "Sign in to see your scores.");
  const check = () => {
    const n = RULES.filter(([, f]) => f(pw.value)).length;
    [...rules.children].forEach((li, i) => li.classList.toggle("ok", RULES[i][1](pw.value)));
    bar.style.width = n / RULES.length * 100 + "%";
    bar.style.background = n < 3 ? "var(--poor)" : n < 5 ? "var(--fair)" : "var(--good)";
    return n === RULES.length;
  };
  pw.addEventListener("input", () => mode === "register" && check());
  const form = h("form", { novalidate: true,
    onsubmit: async ev => {
      ev.preventDefault(); err.textContent = "";
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.value)) { err.textContent = "Please enter a valid email address."; email.focus(); return; }
      if (mode === "register" && !check()) { err.textContent = "Your password doesn't meet all the requirements yet."; pw.focus(); return; }
      if (!pw.value) { err.textContent = "Please enter your password."; pw.focus(); return; }
      submit.disabled = true;
      try {
        const r = await api(`/auth/${mode}`, { method: "POST", json: { email: email.value, password: pw.value }, auth: false });
        token = r.access_token; store.set(token); me = null; location.hash = "#/";
      } catch (e) { err.textContent = e.message; } finally { submit.disabled = false; }
    }
  }, h("label", { for: "email" }, "Email"), email, h("label", { for: "pw" }, "Password"), pwWrap, policy, err, submit);
  toggle.onclick = () => {
    mode = mode === "login" ? "register" : "login"; err.textContent = "";
    const reg = mode === "register";
    title.textContent = reg ? "Create your account" : "Welcome back";
    sub.textContent = reg ? "Takes 10 seconds. No bank login needed." : "Sign in to see your scores.";
    submit.textContent = reg ? "Create account" : "Sign in";
    toggle.textContent = reg ? "I already have an account" : "Create an account";
    pw.autocomplete = reg ? "new-password" : "current-password"; policy.hidden = !reg; if (reg) check();
  };
  const pt = (ic, t, d) => h("li", {}, h("span", { class: "ic", "aria-hidden": "true" }, ic), h("div", {}, h("b", {}, t), h("span", { class: "muted small" }, d)));
  mount(h("div", { class: "grid split" },
    h("section", { class: "auth-hero" },
      h("h1", {}, "A credit score that ", h("em", {}, "explains itself"), "."),
      h("p", { class: "muted" }, "Built for students and gig workers with no credit history. Upload a statement, see exactly what helps and what hurts, and test changes before you make them."),
      h("ul", { class: "points" },
        pt("\u{1F50D}", "Every point explained", "Plain-language reasons, adding up exactly to your score."),
        pt("\u{1F39A}\uFE0F", "What-if simulator", "Slide a habit up or down and watch the score move."),
        pt("\u{1F512}", "Private by design", "Your raw statement is never stored. Erase everything anytime.")),
      h("div", { class: "mini-gauge", "aria-hidden": "true" }, "300",
        ...["var(--poor)", "var(--fair)", "var(--goodband)", "var(--excellent)"].map(c => h("span", { style: `background:${c}` })), "900")),
    h("div", { class: "card" }, title, sub, form, h("p", { class: "small", style: "text-align:center;margin-top:1rem" }, toggle),
      h("div", { class: "or" }, h("span", {}, "or")),
      h("button", { class: "wide", type: "button", id: "demo-btn", onclick: async ev => {
        const b = ev.currentTarget; b.disabled = true; err.textContent = "";
        try { const r = await api("/auth/demo", { method: "POST", auth: false }); token = r.access_token; store.set(token); me = null; location.hash = "#/"; }
        catch (e) { err.textContent = e.message; b.disabled = false; }
      } }, "\u26A1 Try the demo (no sign-up)"),
      h("p", { class: "small muted", style: "text-align:center" }, "Creates a temporary guest account, deleted after 24 hours."))));
}

/* ---------- home: upload ---------- */
const PERSONAS = [
  ["steady_intern", "\u{1F393} Steady intern", "Our simple format, pays on time"],
  ["gig_driver", "\u{1F6F5} Gig driver", "Irregular income, mixed habits"],
  ["stretched_student", "\u{1F4DA} Stretched student", "Tight budget, late payments"],
  ["bank_export_hdfc_style", "\u{1F3E6} Bank-style export", "Narration + debit/credit columns, no categories"],
  ["upi_gig_style", "\u{1F4F1} UPI-style export", "Dr/Cr column, 'dd-Mon-yyyy' dates"],
];
const money = n => (n < 0 ? "\u2212" : "") + Math.abs(n).toLocaleString("en-IN", { maximumFractionDigits: 0 });
function previewCard(p) {
  const colName = { date: "Date", amount: "Amount", debit: "Money out", credit: "Money in", description: "Description", category: "Category", due_date: "Due date", drcr: "Dr/Cr marker" };
  const chips = Object.entries(p.mapping).map(([k, v]) => h("span", { class: "tag" }, h("b", {}, colName[k] || k), " \u2190 ", v));
  const cats = Object.entries(p.category_counts).sort((a, b) => b[1] - a[1]).map(([k, v]) => h("span", { class: "tag cat" }, `${k} \u00b7 ${v}`));
  return h("div", { class: "card preview" },
    h("h2", {}, p.ready ? "\u2705 We understood your file" : "\u26A0\uFE0F We read your file, but can't score it yet"),
    p.ready ? h("p", { class: "muted small" }, `${p.rows} transactions over ${p.months} months (${p.date_from} to ${p.date_to}).`)
            : h("p", { class: "err", role: "alert" }, p.problem),
    h("h3", {}, "Columns we found"), h("div", { class: "chips tight" }, chips),
    p.auto_categorised ? h("p", { class: "small muted", style: "margin-top:.8rem" }, `${p.auto_categorised} row(s) were categorised automatically from the description. Scan the breakdown to make sure it looks right:`) : null,
    h("div", { class: "chips tight" }, cats),
    [...p.notes, ...p.warnings].length ? h("ul", { class: "notes small" }, [...p.notes, ...p.warnings].map(n => h("li", {}, n))) : null,
    h("details", {}, h("summary", { class: "small" }, "Show first rows as we read them"),
      h("div", { class: "scroll" }, h("table", { class: "small" },
        h("thead", {}, h("tr", {}, ["Date", "Description", "Amount", "Category"].map(t => h("th", {}, t)))),
        h("tbody", {}, p.sample.map(r => h("tr", {}, h("td", {}, r.date), h("td", {}, r.description), h("td", { class: r.amount < 0 ? "neg" : "pos" }, money(r.amount)), h("td", {}, r.category))))))));
}
function csvPanel() {
  let file = null, previewOK = false, seq = 0;
  const err = h("div", { class: "err", role: "alert" });
  const fileName = h("p", { class: "muted small" }, "CSV up to 2 MB");
  const consent = h("input", { type: "checkbox", id: "consent" });
  const go = h("button", { class: "primary wide", disabled: true }, "Get my score");
  const input = h("input", { type: "file", accept: ".csv,text/csv", hidden: true });
  const previewBox = h("div", { "aria-live": "polite" });
  const refresh = () => go.disabled = !(file && previewOK && consent.checked);
  async function pick(f) {
    if (!f) return;
    file = f; previewOK = false; fileName.textContent = "\u2713 " + f.name; drop.classList.add("has"); err.textContent = ""; refresh();
    const mine = ++seq;
    previewBox.replaceChildren(h("div", { class: "card" }, h("div", { class: "skeleton", style: "width:50%" }), h("div", { class: "skeleton" })));
    try {
      const form = new FormData(); form.append("file", f);
      const p = await api("/preview", { method: "POST", form });
      if (mine !== seq) return;
      previewOK = p.ready; previewBox.replaceChildren(previewCard(p));
    } catch (e) {
      if (mine !== seq) return;
      previewBox.replaceChildren(h("div", { class: "card" }, h("h2", {}, "\u26A0\uFE0F Couldn't read this file"), h("p", { class: "err", role: "alert" }, e.message),
        h("p", { class: "small muted" }, "Need a starting point? ", h("a", { href: "samples/template.csv", download: "creditlens_template.csv" }, "Download the template CSV"), ".")));
    }
    refresh();
  }
  const drop = h("div", { class: "drop",
    ondragover: e => { e.preventDefault(); drop.classList.add("over"); },
    ondragleave: () => drop.classList.remove("over"),
    ondrop: e => { e.preventDefault(); drop.classList.remove("over"); pick(e.dataTransfer.files[0]); } },
    h("div", { class: "big", "aria-hidden": "true" }, "\u{1F4C4}"),
    h("p", {}, h("strong", {}, "Drop your bank or UPI statement here"), " or"),
    h("button", { type: "button", onclick: () => input.click() }, "Choose CSV file"), input, fileName,
    h("p", { class: "small muted" }, "Most bank exports work as they are. ", h("a", { href: "samples/template.csv", download: "creditlens_template.csv" }, "Template CSV")));
  input.onchange = () => { pick(input.files[0]); input.value = ""; };
  consent.onchange = refresh;
  go.onclick = async () => {
    err.textContent = ""; go.disabled = true; const old = go.textContent; go.replaceChildren(h("span", { class: "spinner" }), " Analysing\u2026");
    try {
      const form = new FormData(); form.append("file", file); form.append("consent", "true");
      const r = await api("/score", { method: "POST", form });
      location.hash = "#/score/" + r.id;
    } catch (e) { err.textContent = e.message; } finally { go.textContent = old; refresh(); }
  };
  const sampleBtns = PERSONAS.map(([id, label, d]) => h("button", { class: "persona", type: "button", onclick: async () => {
    const blob = await (await fetch(`samples/${id}.csv`)).blob();
    pick(new File([blob], id + ".csv", { type: "text/csv" }));
    previewBox.scrollIntoView({ behavior: "smooth", block: "center" });
  } }, h("b", {}, label), h("span", {}, d)));
  return [
    h("div", { class: "card" }, h("h2", {}, h("span", { class: "step-n" }, "1"), "Add your statement"), drop,
      h("h3", { style: "margin-top:1.2rem" }, "No statement handy? Try a demo file"), h("div", { class: "chips" }, sampleBtns)),
    previewBox,
    h("div", { class: "card" }, h("h2", {}, h("span", { class: "step-n" }, "2"), "Give consent and score"),
      h("label", { class: "check", for: "consent" }, consent, h("span", {}, "I agree to CreditLens analysing this statement. Only 7 derived ratios and the result are stored; the raw statement is discarded. I can erase everything any time.")),
      err, go),
    h("details", { class: "card" }, h("summary", {}, "CSV format help"), h("p", { class: "small" }, "We accept typical bank and UPI exports: a date column plus either one amount column, separate debit/credit columns, or amounts with a Dr/Cr marker. A description (narration) column lets us categorise automatically. For full control, add ", h("code", {}, "category"), " (income, rent, utilities, mobile, emi, food, shopping, transport, subscription, savings, transfer, other) and ", h("code", {}, "due_date"), " for bills. Dates as YYYY-MM-DD or DD/MM/YYYY. At least 3 months of history are needed."),
      h("p", { class: "small" }, h("a", { href: "samples/template.csv", download: "creditlens_template.csv" }, "Download template CSV"))),
  ];
}
function privacyCard() {
  const btn = h("button", { class: "danger", onclick: async () => {
    if (!confirm("Erase all your stored scores?")) return;
    const r = await api("/data", { method: "DELETE" }); toast(`Erased ${r.deleted_scores} stored result(s).`);
  } }, "Erase my stored results");
  const btn2 = h("button", { class: "danger", onclick: async () => {
    if (!confirm("Permanently delete your account and all data?")) return;
    await api("/data?delete_account=true", { method: "DELETE" }); logout(); toast("Account deleted.");
  } }, "Delete my account");
  return h("div", { class: "card" }, h("h2", {}, "Your data"), h("p", { class: "small muted" }, "No sensitive attributes are collected and absolute income is never used, only ratios."), h("div", { class: "chips" }, btn, btn2));
}

/* ---------- score view ---------- */
function gauge(score, min, max, band) {
  const W = 260, cx = 130, cy = 130, r = 105, a0 = Math.PI, pct = Math.max(0, Math.min(1, (score - min) / (max - min)));
  const pt = p => [cx + r * Math.cos(a0 + Math.PI * p), cy + r * Math.sin(a0 + Math.PI * p)];
  const arc = (p1, p2, color) => { const [x1, y1] = pt(p1), [x2, y2] = pt(p2); return s("path", { d: `M${x1} ${y1} A${r} ${r} 0 0 1 ${x2} ${y2}`, stroke: color, "stroke-width": 16, fill: "none", "stroke-linecap": "butt" }); };
  const bands = [[0, (500 - min) / (max - min), "var(--poor)"], [(500 - min) / (max - min), (650 - min) / (max - min), "var(--fair)"], [(650 - min) / (max - min), (750 - min) / (max - min), "var(--goodband)"], [(750 - min) / (max - min), 1, "var(--excellent)"]];
  const [nx, ny] = pt(pct);
  const svg = s("svg", { viewBox: `0 0 ${W} 150`, role: "img", "aria-label": `Score ${score} of ${max}, ${band}` },
    ...bands.map(b => arc(...b)), s("circle", { cx: nx, cy: ny, r: 10, fill: "var(--surface)", stroke: "var(--ink)", "stroke-width": 4 }),
    s("text", { x: 14, y: 148, "font-size": 11, fill: "var(--muted)" }, min), s("text", { x: W - 14, y: 148, "font-size": 11, fill: "var(--muted)", "text-anchor": "end" }, max));
  const num = h("div", { class: "score-num" }, String(score));
  if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {      // count up + sweep the marker
    const t0 = performance.now(), dur = 900, dot = svg.querySelector("circle");
    const step = now => { const k = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      num.textContent = Math.round(min + (score - min) * e); const [x, y] = pt(pct * e); dot.setAttribute("cx", x); dot.setAttribute("cy", y);
      if (k < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }
  return h("div", { class: "gauge" }, svg, num, h("span", { class: `band ${band}` }, band));
}
function factorList(factors) {
  const maxPts = Math.max(20, ...factors.map(f => Math.abs(f.points)));
  return factors.map(f => h("div", { class: "factor" },
    h("div", { class: "frow" }, h("span", {}, f.label), h("span", { class: "pts " + dir(f.points) }, sign(f.points) + " pts")),
    h("div", { class: "bar", "aria-hidden": "true" }, h("i", { class: dir(f.points), style: `width:${Math.min(50, Math.abs(f.points) / maxPts * 50)}%` })),
    h("div", { class: "small muted" }, f.reason)));
}
function tipList(tips) {
  if (!tips.length) return h("p", { class: "muted" }, "Nothing major to fix. Keep it up!");
  return tips.map(t => h("div", { class: "tip" }, h("div", { class: "gain" }, "+" + t.estimated_gain),
    h("div", {}, h("strong", {}, t.label), h("div", { class: "small muted" }, `${t.current_display} → ${t.target_display}`), h("div", {}, t.advice))));
}
const BAND_NOTE = {
  Poor: "Several habits are pulling your score down. The tips below show the quickest wins.",
  Fair: "A workable base with clear room to grow. A few habit changes can move you up a band.",
  Good: "Solid habits. Small improvements could take you to Excellent.",
  Excellent: "Excellent habits across the board. Keep doing what you're doing.",
};
async function viewScore(id) {
  const [r, meta] = await Promise.all([api(`/scores/${id}`), featureMeta ? featureMeta : api("/features", { auth: false })]);
  featureMeta = meta;
  const factorsBox = h("div", {}, factorList(r.factors)), tipsBox = h("div", {}, tipList(r.tips));
  const simOut = h("div", { "aria-live": "polite" }, h("p", { class: "muted small" }, "Move a slider to see the effect."));
  mount(
    h("div", { class: "page-actions no-print" },
      h("a", { class: "btn", href: "#/history" }, "\u2190 History"),
      h("button", { onclick: () => window.print() }, "\u{1F5A8}\uFE0F Print / save as PDF")),
    h("div", { class: "print-only report-head" }, h("h1", {}, "CreditLens score report"), h("p", {}, `Generated ${fmtDate(r.created_at)}`)),
    h("div", { class: "grid hero" },
      h("div", { class: "card" }, gauge(r.score, r.score_min, r.score_max, r.band),
        h("p", { class: "band-note muted" }, BAND_NOTE[r.band]),
        h("div", { class: "stats" }, h("div", { class: "stat" }, h("b", {}, String(r.baseline_score)), h("span", {}, "Average applicant")),
          h("div", { class: "stat" }, h("b", {}, (r.probability_of_default * 100).toFixed(1) + "%"), h("span", {}, "Estimated default risk")))),
      h("div", { class: "card" }, h("h2", {}, "What shaped your score"), h("p", { class: "small muted" }, "Points vs. the average applicant. They add up exactly to your score."), factorsBox)),
    h("div", { class: "card" }, h("h2", {}, "How to improve"), h("p", { class: "small muted" }, "Gains are computed by re-scoring with the real model."), tipsBox),
    simulator(r, simOut, factorsBox, tipsBox),
    ingestCard(r.ingest));
}

/* ---------- what-if simulator ---------- */
function ingestCard(ing) {
  if (!ing) return null;
  const cats = Object.entries(ing.category_counts || {}).sort((a, b) => b[1] - a[1]);
  return h("details", { class: "card" }, h("summary", {}, ing.source === "form" ? "How this was calculated" : "How we read your statement"),
    ing.source === "form"
      ? h("p", { class: "small muted" }, `Calculated from ${ing.rows} months of figures you typed in. The figures themselves were not stored, only the ratios and the result.`)
      : h("p", { class: "small muted" }, `${ing.rows} transactions used` + (ing.rows_ignored ? `, ${ing.rows_ignored} ignored` : "") + ". The statement itself was not stored."),
    h("div", { class: "chips tight" }, cats.map(([k, v]) => h("span", { class: "tag cat" }, `${k} \u00b7 ${v}`))),
    ing.notes?.length ? h("ul", { class: "notes small" }, ing.notes.map(n => h("li", {}, n))) : null);
}
function simulator(r, out, factorsBox, tipsBox) {
  const vals = { ...r.features }; let timer, seq = 0;
  const fmt = (m, v) => m.kind === "months" ? `${Math.round(v)} mo` : `${Math.round(v * 100)}%`;
  const rows = featureMeta.map(m => {
    const lab = h("output", {}), inp = h("input", { type: "range", id: "sl-" + m.name, min: m.min, max: m.max, step: m.step, value: vals[m.name] });
    const upd = () => lab.textContent = fmt(m, +inp.value); upd();
    inp.oninput = () => { upd(); vals[m.name] = +inp.value; clearTimeout(timer); timer = setTimeout(run, 250); };
    return h("div", { class: "slider" }, h("div", { class: "top-row" }, h("label", { for: "sl-" + m.name, style: "margin:0" }, m.label), lab), inp,
      h("div", { class: "small muted" }, m.higher_is_better ? "Higher is better" : "Lower is better"));
  });
  async function run() {
    const mine = ++seq;
    const overrides = Object.fromEntries(Object.entries(vals).filter(([k, v]) => Math.abs(v - r.features[k]) > 1e-9));
    if (!Object.keys(overrides).length) { out.replaceChildren(h("p", { class: "muted small" }, "Move a slider to see the effect.")); factorsBox.replaceChildren(...factorList(r.factors)); tipsBox.replaceChildren(...tipList(r.tips)); return; }
    try {
      const x = await api("/simulate", { method: "POST", json: { score_id: r.id, overrides } });
      if (mine !== seq) return;                       // ignore out-of-order responses
      out.replaceChildren(h("div", { class: "sim-score" }, String(x.new_score)), h("div", { class: "delta " + dir(x.delta) }, `${sign(x.delta)} points`),
        h("div", { class: "small muted" }, `${x.original_band} → `, h("span", { class: `band ${x.new_band}` }, x.new_band)));
      factorsBox.replaceChildren(...factorList(x.factors)); tipsBox.replaceChildren(...tipList(x.tips));
    } catch (e) { out.replaceChildren(h("div", { class: "err" }, e.message)); }
  }
  const reset = h("button", { onclick: () => { featureMeta.forEach(m => { vals[m.name] = r.features[m.name]; const el = document.getElementById("sl-" + m.name); el.value = vals[m.name]; el.dispatchEvent(new Event("input")); }); } }, "Reset");
  return h("div", { class: "card no-print" }, h("h2", {}, "What if…?"), h("p", { class: "small muted" }, "Move a slider to see how your score would change. The factors and tips above update too."),
    h("div", { class: "grid two" }, h("div", {}, rows), h("div", { class: "sim-box" }, h("h3", {}, "Simulated score"), out, reset)));
}

/* ---------- history + compare ---------- */
async function viewHistory() {
  const rows = await api("/scores");
  const picked = new Set();
  const cmp = h("button", { class: "primary", disabled: true }, "Compare selected (pick 2)");
  cmp.onclick = () => { const [a, b] = [...picked].sort((x, y) => x - y); location.hash = `#/compare/${a}/${b}`; };
  const boxes = rows.map(x => h("input", { type: "checkbox", "aria-label": `Select score from ${fmtDate(x.created_at)}`, onchange: ev => {
    ev.target.checked ? picked.add(x.id) : picked.delete(x.id);
    if (picked.size > 2) { const first = [...picked][0]; picked.delete(first); boxes[rows.findIndex(r => r.id === first)].checked = false; }
    cmp.disabled = picked.size !== 2; cmp.textContent = picked.size === 2 ? "Compare selected" : "Compare selected (pick 2)";
  } }));
  mount(h("h1", {}, "History"), h("div", { class: "card" }, rows.length ? [
    h("div", { class: "table-actions" }, h("p", { class: "muted small", style: "margin:0" }, "Tick two scores to see what changed between them."), cmp),
    h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}), h("th", {}, "Date"), h("th", {}, "Score"), h("th", {}, "Band"), h("th", {}))),
      h("tbody", {}, rows.map((x, i) => h("tr", {}, h("td", {}, boxes[i]), h("td", {}, fmtDate(x.created_at)), h("td", {}, h("strong", {}, String(x.score))),
        h("td", {}, h("span", { class: `band ${x.band}` }, x.band)), h("td", {}, h("a", { href: "#/score/" + x.id }, "View"))))))] :
    h("div", { class: "empty" }, h("p", { class: "muted" }, "No scores yet."), h("a", { class: "btn primary", href: "#/new" }, "Get your first score"))));
}
async function viewCompare(idA, idB) {
  const [A, B] = await Promise.all([api(`/scores/${idA}`), api(`/scores/${idB}`)]);   // A = older, B = newer
  const delta = B.score - A.score;
  const byName = r => Object.fromEntries(r.factors.map(f => [f.feature, f]));
  const fa = byName(A), fb = byName(B);
  const rows = Object.keys(fb).map(k => ({ label: fb[k].label, a: fa[k], b: fb[k], d: fb[k].points - fa[k].points }))
    .sort((x, y) => Math.abs(y.d) - Math.abs(x.d));
  const side = (r, tag) => h("div", { class: "card" }, h("p", { class: "small muted", style: "margin:0" }, `${tag} · ${fmtDate(r.created_at)}`), gauge(r.score, r.score_min, r.score_max, r.band),
    h("p", { class: "no-print", style: "text-align:center" }, h("a", { href: "#/score/" + r.id }, "Open full result")));
  mount(
    h("div", { class: "page-actions no-print" }, h("a", { class: "btn", href: "#/history" }, "← History"), h("button", { onclick: () => window.print() }, "\u{1F5A8}️ Print / save as PDF")),
    h("h1", {}, "What changed"),
    h("p", { class: "muted" }, delta === 0 ? "Your score is unchanged." : h("span", {}, "Your score ", h("b", { class: "delta " + dir(delta) }, delta > 0 ? "rose" : "fell"), ` by ${Math.abs(delta)} points (${A.score} → ${B.score}).`)),
    h("div", { class: "grid two" }, side(A, "Earlier"), side(B, "Later")),
    h("div", { class: "card" }, h("h2", {}, "Factor by factor"), h("p", { class: "small muted" }, "Biggest movers first. Points are relative to the average applicant."),
      h("table", {}, h("thead", {}, h("tr", {}, ["Factor", "Earlier", "Later", "Change"].map(t => h("th", {}, t)))),
        h("tbody", {}, rows.map(x => h("tr", {}, h("td", {}, x.label),
          h("td", {}, `${x.a.display_value} (${sign(x.a.points)})`), h("td", {}, `${x.b.display_value} (${sign(x.b.points)})`),
          h("td", {}, h("b", { class: "pts " + dir(x.d) }, sign(x.d) + " pts"))))))));
}

route();
