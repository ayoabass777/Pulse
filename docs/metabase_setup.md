# Pulse — Metabase Dashboard Setup

## Quick Start

```bash
# If Postgres volume already exists, recreate to pick up metabase DB
docker-compose down -v
docker-compose up -d

# Wait for Metabase to initialize (~1-2 min on first run)
open http://localhost:3000
```

## Initial Setup

1. **Create admin account** — email + password (local only, doesn't matter)
2. **Add database connection:**
   - Database type: **PostgreSQL**
   - Host: `postgres` (Docker network name)
   - Port: `5432`
   - Database: `pulse`
   - Username: (from `.env` → `DB_USER`)
   - Password: (from `.env` → `DB_PASSWORD`)
   - Schema: Leave blank (Metabase will discover all schemas)

3. **Let Metabase sync** — takes ~30 seconds to scan tables

---

## Dashboards to Build

### 1. Session Overview

**Source:** `raw_mart.mart_session_metrics`

| Chart | Type | Fields |
|-------|------|--------|
| Sessions Over Time | Line | `session_start` (day), count(*) |
| Avg Session Duration | Number | avg(`duration_seconds`) |
| Bounce Rate | Number | sum(`is_bounce`::int) / count(*) |
| Sessions by Landing Page | Bar | `landing_page`, count(*) |

**Filters:** Date range on `session_start`

---

### 2. Funnel Analysis

**Source:** `raw_mart.mart_funnel_conversion`

| Chart | Type | Fields |
|-------|------|--------|
| Funnel Waterfall | Funnel/Bar | Step names vs user counts |
| Conversion by Step | Line | `event_date`, step conversion rates |
| Overall Conversion Trend | Line | `event_date`, `overall_conversion_rate` |

**SQL for funnel visualization:**
```sql
SELECT 
    'Page View' as step, users_page_view as users, 1 as step_order FROM raw_mart.mart_funnel_conversion WHERE event_date = CURRENT_DATE - 1
UNION ALL
SELECT 'Product View', users_product_view, 2 FROM raw_mart.mart_funnel_conversion WHERE event_date = CURRENT_DATE - 1
UNION ALL
SELECT 'Add to Cart', users_add_to_cart, 3 FROM raw_mart.mart_funnel_conversion WHERE event_date = CURRENT_DATE - 1
UNION ALL
SELECT 'Checkout', users_checkout, 4 FROM raw_mart.mart_funnel_conversion WHERE event_date = CURRENT_DATE - 1
UNION ALL
SELECT 'Payment', users_payment, 5 FROM raw_mart.mart_funnel_conversion WHERE event_date = CURRENT_DATE - 1
ORDER BY step_order;
```

---

### 3. User Engagement (DAU/WAU/MAU)

**Source:** `raw_mart.mart_daily_active_users`

| Chart | Type | Fields |
|-------|------|--------|
| Active Users Trend | Line (multi-series) | `activity_date`, `dau`, `wau`, `mau` |
| Stickiness | Line | `activity_date`, `stickiness_pct` |
| DAU Change | Bar | `activity_date`, `dau_change` |

**Filters:** Date range on `activity_date`

---

## Screenshot Checklist (for blog)

- [ ] Session Overview dashboard (full view)
- [ ] Funnel waterfall chart (zoomed)
- [ ] DAU/WAU/MAU trend lines (zoomed)
- [ ] Stickiness metric over time

---

## Troubleshooting

**Metabase can't connect to Postgres:**
- Use `postgres` as host (not `localhost`) — Docker internal network
- Check `.env` credentials match

**Tables not showing:**
- Run `dbt run` first to create mart tables
- Click "Sync database now" in Admin → Databases

**Metabase data lost on restart:**
- Ensure `metabase_data` volume exists in docker-compose
- Don't use `-v` flag when restarting unless you want to reset
