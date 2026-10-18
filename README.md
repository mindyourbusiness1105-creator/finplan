# FinPlan

A personal finance planner built for Indian salaried users.

## What it does
- Compares old vs new income tax regime (FY 2026-27)
- Builds a monthly budget adjusted for state, dependents and needs
- Plans goals (study, business, purchase, wealth) with inflation-adjusted targets
- Runs Monte Carlo simulations to show the chance of reaching your goal
- Calculates a safe EMI limit
- Suggests an asset-class mix (equity / debt / gold / FD) by risk appetite
- Pessimistic, Moderate and Optimistic scenarios, plus what-if sliders

## Run locally
pip install -r requirements.txt
python -m uvicorn app:app --reload
Then open http://127.0.0.1:8000

## Disclaimer
Educational tool only. Not tax, legal or investment advice. All returns,
inflation and cost-of-living figures are labelled assumptions, not forecasts.
Consult a CA or SEBI-registered adviser before making financial decisions.

## Tech
FastAPI, NumPy, vanilla JavaScript, Chart.js
