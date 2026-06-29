# Game Perfomix — Analytics Dashboard

**Project root:** `/Users/krishansmacbook/Desktop/sapphyre-dashboard`

---

## Quick Start

```bash
cd /Users/krishansmacbook/Desktop/sapphyre-dashboard
source .venv/bin/activate
python scripts/sync_sapphyre.py   # fetch latest data
python app.py                      # start on http://localhost:5001
```

---

## Architecture

```
Sapphyre API (IST date range, UTC timestamps)
        ↓
scripts/sync_sapphyre.py
        ↓
data/raw/YYYY-MM-DD.parquet
        ↓
backend/aggregator.py
        ↓
data/aggregated/daily_summary.parquet  (date·partner·offerName·goal)
        ↓
app.py  (Flask)
        ↓
frontend/templates/index.html + static/js/dashboard.js
```

**Timezone:** API queried in IST. Returned timestamps are UTC — converted to `Asia/Kolkata` before all display, aggregation, charts, and CSV export.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, Flask, Pandas, PyArrow |
| Storage | Parquet (raw + aggregated) |
| Frontend | HTML/CSS/JS, Plotly.js, Tom Select |
| Sync | `scripts/sync_sapphyre.py` (every 6 h via cron) |

---

## Pages

### Overview
- 9 KPIs: Revenue, Cost, Profit, Margin %, Installs, Events, Active Offers, Publishers, Conv. Rate
- Inline alert banner (critical/warning offers)
- Period comparisons: Today vs Yesterday · Week vs Prev Week · MTD vs Last Month
- Revenue/Cost/Profit trend + Conversion trend charts
- Top 10 leaderboards: Offers and Publishers by revenue

### Operations (sub-tabs)
- **Daily Review** — KPIs + Scale/Monitor/Optimize/Pause table per partner–offer
- **Afternoon Monitoring** — same table for mid-day check
- **Evening Performance** — last-2-days bar chart

Recommendation rules: Margin > 30% = Scale · 15-30% = Monitor · 0-15% = Optimize · Negative = Pause

### Publishers (sub-tabs)
- **Summary** — all publishers: revenue, cost, profit, margin %, conv rate, active offers + charts
- **Deep Dive** — requires Partner filter; shows all offers for that partner
- **Offer Comparison** — requires Offer filter; compares publishers on same offer

### Offers (sub-tabs)
- **Summary** — all offers: revenue, cost, profit, margin %, valid %, publishers, goals, dates + charts
- **Publisher Breakdown** — requires Offer filter; which publishers run it
- **Offer Funnel** — requires Offer filter; goal-count funnel (auto-sorted, steps reorderable)

### Analytics (sub-tabs)
- **Weekly Review** — last 8 ISO weeks with WoW % growth charts and table
- **Monthly Review** — last 6 months with MoM % growth charts and table

### Alerts
- Negative margin (critical), Margin < 5% (critical), Margin < 20% (warning)
- Revenue drop > 20% DoD (warning), Traffic drop > 30% DoD (warning)
- Summary KPI cards + full alert list

---

## Global Filters

```
Date Range → Partner → Offer → Goal
```
Cascading, auto-refresh (280 ms debounce), no Apply button, no duplicate controls inside pages.

---

## API Reference

### Existing (unchanged)
`/api/status` `/api/filters` `/api/kpis` `/api/revenue-trend` `/api/top-offers`
`/api/top-goals` `/api/top-partners` `/api/conversion-trend` `/api/valid-invalid`
`/api/raw-data` `/api/export-csv` `/api/funnel/data` `/api/partner-offers`

### New (added in redesign)
| Endpoint | Purpose |
|---|---|
| `/api/overview/kpis` | Extended KPIs incl. installs, events, active_offers/publishers |
| `/api/overview/comparisons` | Period-over-period (today/week/MTD) |
| `/api/overview/alerts` | Alert detection inline |
| `/api/alerts` | Full alert centre |
| `/api/operations/recommendations` | Scale/Monitor/Optimize/Pause per partner–offer |
| `/api/publishers/summary` | All publishers with margin/conv stats |
| `/api/publishers/comparison` | Same offer across publishers |
| `/api/offers/summary` | All offers with full metrics |
| `/api/offers/publishers` | Publishers for a specific offer |
| `/api/analytics/weekly` | Last 8 weeks + WoW growth |
| `/api/analytics/monthly` | Last 6 months + MoM growth |

---

## Files Changed (redesign)

| File | What changed |
|---|---|
| `app.py` | Added `_offer_metrics()`, `_pct_change()` helpers + 11 new endpoints |
| `frontend/templates/index.html` | Full rewrite — 6-page structure with sub-tabs |
| `frontend/static/js/dashboard.js` | Full rewrite — new routing, tab system, all render functions |
| `frontend/static/css/style.css` | Added tab bar, rec badges, alert cards, comparison grid, leaderboard styles, kpi-grid-5 |
| `README.md` | This file — source of truth |

---

## Data Notes

- **Installs** = conversions where `goal` contains "install" (case-insensitive approximation)
- **Events** = all other conversions
- **Clicks** = not available in postback data
- **CPI / CPE** = not yet implemented (need confirmed goal naming)

---

## Known Issues / Next Steps

- CPI Dashboard and CPE Dashboard sub-tabs (under Analytics) not yet built
- Installs metric depends on goal naming — confirm "install" appears in goal names
- Raw Data table removed from main nav (API still active at `/api/raw-data` and `/api/export-csv`)
- Oracle Cloud cron job not yet configured

---

## Data Paths

```
data/raw/YYYY-MM-DD.parquet
data/aggregated/daily_summary.parquet
```

## Sync

```bash
python scripts/sync_sapphyre.py
# Fetches Sapphyre API, saves raw parquet, rebuilds aggregates
# Run every 6 hours via cron on Oracle Cloud VM
```
