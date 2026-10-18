"""FinPlan - personal finance planner engine (educational, India-first).
Run: pip install -r requirements.txt && uvicorn app:app --reload  -> http://127.0.0.1:8000
"""
import json, math, sqlite3, time
from pathlib import Path
import numpy as np
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="FinPlan")
HERE = Path(__file__).parent

# Cost-of-living multipliers by state (edit / extend; keep as data, not logic)
COST = {"Delhi": 1.2, "Maharashtra": 1.15, "Karnataka": 1.15, "Telangana": 1.1, "Tamil Nadu": 1.05,
        "Kerala": 1.05, "Gujarat": 1.0, "West Bengal": 1.0, "Rajasthan": 0.95,
        "Uttar Pradesh": 0.92, "Madhya Pradesh": 0.9, "Bihar": 0.85, "Other": 1.0}

# Assumption ranges per scenario (labelled assumptions, NOT forecasts)
SC = {"pessimistic": dict(infl=.07, eq=.09, debt=.06, gold=.06, life=1.10),
      "moderate":    dict(infl=.055, eq=.115, debt=.07, gold=.08, life=1.00),
      "optimistic":  dict(infl=.045, eq=.13, debt=.075, gold=.09, life=.90)}
VOL = dict(eq=.17, debt=.03, gold=.13, fd=.0)

class Inp(BaseModel):
    salary: float
    dependents: int = 0
    homemaker: bool = False
    needs: dict[str, float] = {}      # extra monthly needs, e.g. {"Rent": 15000, "Medical": 3000}
    goal_type: str = "wealth"         # wealth | study | business | purchase
    goal_amount: float = 0            # today's money
    goal_years: int = 5
    emi: float = 0                    # existing monthly EMIs
    state: str = "Other"
    country: str = "India"
    risk: int = 3                     # 1 (very low) .. 5 (very high)
    lifestyle_cut: float = 0          # what-if: monthly cut in lifestyle spend
    d80c: float = 0                   # annual 80C investments (old regime)
    nps: float = 0                    # annual NPS 80CCD(1B)
    d80d: float = 0                   # annual health insurance 80D
    other_ded: float = 0              # annual HRA / home-loan interest / other old-regime deductions

# ---- Tax (FY 2026-27, salaried, resident individual). Surcharge ignored; salary assumed fully taxable.
NEW = [(4e5, 0), (8e5, .05), (12e5, .10), (16e5, .15), (20e5, .20), (24e5, .25), (float("inf"), .30)]
OLD = [(2.5e5, 0), (5e5, .05), (10e5, .20), (float("inf"), .30)]

def _slab(x, slabs):
    t, lo = 0, 0
    for hi, r in slabs:
        if x > lo: t += (min(x, hi) - lo) * r
        lo = hi
    return t

def tax_summary(i: Inp):
    g = i.salary * 12
    ti_n = max(0, g - 75000)
    t_n = 0 if ti_n <= 12e5 else min(_slab(ti_n, NEW), ti_n - 12e5)       # 87A rebate + marginal relief
    ded = min(i.d80c, 150000) + min(i.nps, 50000) + min(i.d80d, 25000) + i.other_ded
    ti_o = max(0, g - 50000 - ded)
    t_o = 0 if ti_o <= 5e5 else _slab(ti_o, OLD)                           # 87A rebate (old)
    t_n, t_o = round(t_n * 1.04), round(t_o * 1.04)                        # 4% cess
    rate = .30 if ti_o > 10e5 else .20 if ti_o > 5e5 else .05 if ti_o > 2.5e5 else 0
    room = max(0, 150000 - i.d80c) + max(0, 50000 - i.nps)
    return dict(gross_annual=round(g), new=t_n, old=t_o, best="new" if t_n <= t_o else "old",
                saving=abs(t_n - t_o), net_monthly=(g - min(t_n, t_o)) / 12, old_deductions=round(ded),
                tip=round(room * rate * 1.04))

def budget(i: Inp, sc: dict):
    m = COST.get(i.state, 1.0) * sc["life"]
    share = {"Food": .14 + .03 * i.dependents + (.02 if i.homemaker else 0),
             "Transport / Petrol": .05, "Utilities & Internet": .05,
             "Health & Fitness": .04 + .01 * i.dependents, "Lifestyle & Eating out": .08}
    rows = {k: round(i.salary * v * m) for k, v in share.items()}
    rows["Lifestyle & Eating out"] = max(0, rows["Lifestyle & Eating out"] - round(i.lifestyle_cut))
    for k, v in i.needs.items():
        rows[k] = rows.get(k, 0) + round(v)
    return rows

def safe_emi(i: Inp):
    pct = .40 - .03 * i.dependents - (.05 if i.risk <= 2 else 0)
    pct = max(.15, pct)
    cap = pct * i.salary
    return dict(cap_pct=round(pct * 100), cap_total=round(cap), room=round(max(0, cap - i.emi)),
                stressed=i.emi > cap)

def allocation(risk: int, years: int):
    eq = [.15, .30, .45, .60, .75][risk - 1]
    eq *= .2 if years < 3 else .5 if years < 5 else .8 if years < 7 else 1
    gold = .10
    rest = 1 - eq - gold
    fd = rest * (.5 if years < 3 else .3)
    return dict(eq=eq, debt=rest - fd, gold=gold, fd=fd)

def simulate(sip, years, w, sc, paths=3000):
    n = years * 12
    mu = sum(w[k] * (sc[k] if k in sc else .065) for k in w)   # fd ~ 6.5%
    sig = math.sqrt(sum((w[k] * VOL[k]) ** 2 for k in w))     # simplified: independent assets
    mm, ms = mu / 12, sig / math.sqrt(12)
    rets = np.random.default_rng(7).normal(mm, ms, (paths, n))
    fv, bands = np.zeros(paths), {"p10": [], "p50": [], "p90": []}
    for t in range(n):
        fv = fv * (1 + rets[:, t]) + sip
        if (t + 1) % 12 == 0:
            for k, q in (("p10", 10), ("p50", 50), ("p90", 90)):
                bands[k].append(round(float(np.percentile(fv, q))))
    return fv, mu, bands

@app.post("/api/plan")
def plan(raw: Inp):
    tx = tax_summary(raw)
    i = raw.model_copy(update={"salary": round(tx["net_monthly"])})        # everything below uses take-home
    out = {"tax": tx, "net_monthly": i.salary, "emi_limit": safe_emi(i), "scenarios": {}}
    w = allocation(i.risk, i.goal_years)
    out["allocation"] = {k: round(v * 100) for k, v in w.items()}
    for name, sc in SC.items():
        b = budget(i, sc)
        ess = sum(b.values())
        surplus = i.salary - ess - i.emi
        capacity = max(0, surplus) * .8                       # keep 20% buffer
        years, n = i.goal_years, i.goal_years * 12
        fv, mu, bands = simulate(capacity, years, w, sc)
        infl = sc["infl"]
        target = i.goal_amount * (1 + infl) ** years
        r = mu / 12
        need = target * r / ((1 + r) ** n - 1) if target and r else 0
        out["scenarios"][name] = dict(
            budget=b, essentials=ess, surplus=round(surplus), monthly_saving=round(capacity),
            emergency_fund=round(6 * (ess + i.emi)), inflation=infl, expected_return=round(mu * 100, 1),
            target_future=round(target), required_sip=round(need),
            projected_median=round(float(np.median(fv))), projected_p10=round(float(np.percentile(fv, 10))),
            real_median=round(float(np.median(fv)) / (1 + infl) ** years),
            goal_probability=round(float((fv >= target).mean()) * 100) if target else None,
            deficit=surplus < 0, bands=bands,
            goal_curve=[round(i.goal_amount * (1 + infl) ** y) for y in range(1, years + 1)])
    _log(raw)
    return out

# --- Stage-1 "learning": log anonymised inputs so defaults can be learned from real data later
def _log(i: Inp):
    c = sqlite3.connect(HERE / "finplan.db")
    c.execute("create table if not exists log(ts, state, band, deps, risk, goal, emi_pct)")
    band = int(i.salary // 25000) * 25000
    c.execute("insert into log values(?,?,?,?,?,?,?)",
              (time.time(), i.state, band, i.dependents, i.risk, i.goal_type, round(i.emi / max(i.salary, 1), 2)))
    c.commit(); c.close()

@app.get("/api/states")
def states(): return list(COST)

@app.get("/")
def home(): return FileResponse(HERE / "index.html")
