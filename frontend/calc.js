/* CreditLens calculators: pure maths, no DOM. Loaded in the browser as window.CL_CALC and in Node for tests.
   Formulas mirror app/services/offers.py (emi, affordable_principal, FOIR cap) so the UI and API agree. */
(function (root) {
  "use strict";
  const FOIR_CAP = 0.50;            // lenders usually allow total EMIs up to ~50% of income (same as backend)
  const num = x => (Number.isFinite(+x) ? +x : 0);

  /** Equated monthly instalment. Zero rate -> principal / months. */
  function emi(principal, annualRatePct, months) {
    principal = num(principal); months = Math.round(num(months));
    if (months <= 0 || principal <= 0) return 0;
    const r = num(annualRatePct) / 1200;
    if (r === 0) return principal / months;
    const f = Math.pow(1 + r, months);
    return principal * r * f / (f - 1);
  }

  /** Largest loan whose EMI equals monthlyEmi (inverse of emi()). */
  function affordablePrincipal(monthlyEmi, annualRatePct, months) {
    monthlyEmi = num(monthlyEmi); months = Math.round(num(months));
    if (monthlyEmi <= 0 || months <= 0) return 0;
    const r = num(annualRatePct) / 1200;
    if (r === 0) return monthlyEmi * months;
    return monthlyEmi * (1 - Math.pow(1 + r, -months)) / r;
  }

  /** Full repayment schedule, optionally with an extra monthly prepayment.
      Returns totals plus a per-year summary {year, principal, interest, balance}. */
  function amortise(principal, annualRatePct, months, extra) {
    principal = num(principal); months = Math.round(num(months)); extra = Math.max(0, num(extra));
    const base = emi(principal, annualRatePct, months);
    const r = num(annualRatePct) / 1200;
    let bal = principal, totalInterest = 0, m = 0;
    const yearly = []; let yP = 0, yI = 0;
    while (bal > 0.005 && m < months + 1 && base > 0) {
      m++;
      const interest = bal * r;
      let princ = Math.min(bal, base - interest + extra);
      if (princ < 0) princ = 0;
      bal -= princ; totalInterest += interest; yP += princ; yI += interest;
      if (m % 12 === 0 || bal <= 0.005) { yearly.push({ year: Math.ceil(m / 12), principal: yP, interest: yI, balance: Math.max(0, bal) }); yP = 0; yI = 0; }
    }
    return { emi: base, months: m, totalInterest, totalPaid: principal + totalInterest, yearly };
  }

  /** Loan sizing: how much can you borrow while keeping total EMIs under a share of income. */
  function affordability(monthlyIncome, existingEmi, annualRatePct, months, cap) {
    cap = cap == null ? FOIR_CAP : cap;
    const room = Math.max(0, num(monthlyIncome) * cap - num(existingEmi));
    return { room, maxLoan: affordablePrincipal(room, annualRatePct, months), usedPct: monthlyIncome > 0 ? num(existingEmi) / monthlyIncome : 0 };
  }

  /** Monthly saving needed to reach a target (end-of-month deposits, monthly compounding). */
  function savingsGoal(target, years, annualReturnPct, alreadySaved) {
    target = num(target); const n = Math.round(num(years) * 12); const r = num(annualReturnPct) / 1200;
    if (n <= 0) return { monthly: 0, months: 0, grownLumpSum: num(alreadySaved), invested: 0, growth: 0 };
    const lump = num(alreadySaved) * Math.pow(1 + r, n);
    const need = Math.max(0, target - lump);
    const factor = r === 0 ? n : (Math.pow(1 + r, n) - 1) / r;
    const monthly = need / factor;
    const invested = monthly * n + num(alreadySaved);
    return { monthly, months: n, grownLumpSum: lump, invested, growth: Math.max(0, target - invested) };
  }

  /** Same three ratios the scoring model sees, from typed-in months (income, rent, emi, ... savings). */
  function budgetRatios(months) {
    const sum = k => months.reduce((a, m) => a + num(m[k]), 0);
    const income = sum("income"), n = months.length || 1;
    const spendKeys = ["rent", "emi", "bills", "food", "shopping", "transport", "subscription", "other"];
    const spend = spendKeys.reduce((a, k) => a + sum(k), 0), saved = sum("savings");
    const incomes = months.map(m => num(m.income));
    const mean = income / n;
    const sd = Math.sqrt(incomes.reduce((a, v) => a + (v - mean) * (v - mean), 0) / n);
    return {
      avgIncome: income / n, avgOutgo: (spend + saved) / n, avgSpend: spend / n, avgSaved: saved / n,
      leftover: (income - spend - saved) / n,
      savingsRatio: income > 0 ? saved / income : 0,
      rentRatio: income > 0 ? sum("rent") / income : 0,
      emiRatio: income > 0 ? sum("emi") / income : 0,
      incomeCV: mean > 0 ? sd / mean : 0,
      overspent: income > 0 && spend + saved > income * 1.0001,
    };
  }

  /** Traffic-light verdicts for the ratios (same thresholds the dashboard alerts use). */
  function ratioHealth(b) {
    const lvl = (v, good, ok) => v <= good ? "good" : v <= ok ? "ok" : "bad";
    return {
      savings: b.savingsRatio >= 0.15 ? "good" : b.savingsRatio >= 0.05 ? "ok" : "bad",
      rent: lvl(b.rentRatio, 0.30, 0.40),
      emi: lvl(b.emiRatio, 0.25, 0.40),
      income: lvl(b.incomeCV, 0.20, 0.40),
    };
  }

  const api = { FOIR_CAP, emi, affordablePrincipal, amortise, affordability, savingsGoal, budgetRatios, ratioHealth };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.CL_CALC = api;
})(typeof window !== "undefined" ? window : globalThis);
