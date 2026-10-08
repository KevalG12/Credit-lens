// Run: node tests/calc.test.js   (no dependencies). Cross-checks the browser calculators against the backend formulas.
const assert = require("assert"); const c = require("../frontend/calc.js");
const close = (a, b, t = 0.01) => assert.ok(Math.abs(a - b) <= t, `${a} !~ ${b}`);
// Known value: 1,00,000 @ 12% for 12 months -> EMI 8884.88
close(c.emi(100000, 12, 12), 8884.88);
close(c.emi(120000, 0, 12), 10000);
assert.strictEqual(c.emi(0, 12, 12), 0); assert.strictEqual(c.emi(1000, 12, 0), 0);
// affordablePrincipal inverts emi
close(c.affordablePrincipal(c.emi(250000, 14.5, 36), 14.5, 36), 250000, 0.5);
// amortisation: interest total == emi*n - principal, balance ends at 0, extra payments shorten the loan
const a = c.amortise(500000, 11, 60); close(a.totalInterest, a.emi * 60 - 500000, 1); assert.strictEqual(a.months, 60);
close(a.yearly.at(-1).balance, 0, 0.01);
const b = c.amortise(500000, 11, 60, 2000); assert.ok(b.months < 60 && b.totalInterest < a.totalInterest);
close(c.amortise(60000, 0, 12).totalInterest, 0);
// affordability
const f = c.affordability(40000, 5000, 12, 36); close(f.room, 15000); close(f.maxLoan, c.affordablePrincipal(15000, 12, 36), 0.01);
assert.strictEqual(c.affordability(10000, 9000, 12, 36).maxLoan, 0);
// savings goal: depositing the monthly amount really reaches the target
const g = c.savingsGoal(500000, 5, 8, 20000); let bal = 20000; const r = 8 / 1200;
for (let i = 0; i < 60; i++) bal = bal * (1 + r) + g.monthly; close(bal, 500000, 1);
close(c.savingsGoal(120000, 1, 0, 0).monthly, 10000);
assert.strictEqual(c.savingsGoal(1000, 0, 5, 0).monthly, 0);
// budget ratios
const m = [{ income: 20000, rent: 6000, emi: 2000, savings: 3000, food: 4000 }, { income: 20000, rent: 6000, emi: 2000, savings: 3000, food: 4000 }];
const br = c.budgetRatios(m); close(br.savingsRatio, 0.15, 1e-9); close(br.rentRatio, 0.30, 1e-9); close(br.emiRatio, 0.10, 1e-9); close(br.incomeCV, 0, 1e-9);
assert.strictEqual(br.overspent, false); close(br.leftover, 5000);
assert.strictEqual(c.budgetRatios([{ income: 1000, rent: 2000 }]).overspent, true);
assert.deepStrictEqual(c.ratioHealth(br), { savings: "good", rent: "good", emi: "good", income: "good" });
assert.strictEqual(c.budgetRatios([]).avgIncome, 0);
console.log("calc.test.js: all checks passed");
