# Pulse — Power BI Dashboard Setup

## Prerequisites

- **Power BI Desktop** (Windows, free) — [Download](https://powerbi.microsoft.com/desktop/)
- Or **Power BI Service** (web, free tier) — [app.powerbi.com](https://app.powerbi.com)
- Postgres running on `localhost:5433`
- dbt marts built (`dbt run` completed)

---

## Connect to Postgres

### Power BI Desktop

1. **Get Data** → **Database** → **PostgreSQL database**
2. Enter connection details:
   - Server: `localhost:5433`
   - Database: `pulse`
3. **Database** credentials (from `.env`):
   - User: your `DB_USER`
   - Password: your `DB_PASSWORD`
4. Select tables:
   - `raw_mart.mart_session_metrics`
   - `raw_mart.mart_funnel_conversion`
   - `raw_mart.mart_daily_active_users`
5. Click **Load**

### Power BI Service (Web)

1. Install **On-premises data gateway** (required for localhost connections)
2. Or deploy Postgres to a cloud endpoint (e.g., Render, Railway, RDS)
3. **Get Data** → **Databases** → **PostgreSQL**
4. Same credentials as above

---

## Dashboard 1: Session Overview

**Source:** `mart_session_metrics`

| Visual | Type | Fields |
|--------|------|--------|
| Sessions Over Time | Line Chart | X: `session_start` (Date), Y: Count of `session_id` |
| Avg Duration | Card | Average of `duration_seconds` |
| Bounce Rate | Card | `is_bounce` = TRUE count / total count |
| Sessions by Landing Page | Bar Chart | X: `landing_page`, Y: Count |
| Conversion Rate | Card | `converted` = TRUE count / total count |

**Filters:**
- Date slicer on `session_start`
- Dropdown for `landing_page`

### DAX Measures

```dax
Bounce Rate = 
DIVIDE(
    COUNTROWS(FILTER(mart_session_metrics, mart_session_metrics[is_bounce] = TRUE)),
    COUNTROWS(mart_session_metrics)
)

Conversion Rate = 
DIVIDE(
    COUNTROWS(FILTER(mart_session_metrics, mart_session_metrics[converted] = TRUE)),
    COUNTROWS(mart_session_metrics)
)

Avg Session Duration (min) = 
AVERAGE(mart_session_metrics[duration_minutes])
```

---

## Dashboard 2: Funnel Analysis

**Source:** `mart_funnel_conversion`

| Visual | Type | Fields |
|--------|------|--------|
| Funnel Chart | Funnel | Values: `users_page_view`, `users_product_view`, `users_add_to_cart`, `users_checkout`, `users_payment` |
| Conversion by Step | Clustered Bar | X: Step names, Y: Conversion % |
| Overall Conversion Trend | Line Chart | X: `event_date`, Y: `overall_conversion_rate` |
| Step Drop-off | Table | All step counts + conversion rates |

### Unpivot for Funnel Visual

Power BI's built-in Funnel visual needs data in rows, not columns. Transform in Power Query:

1. Select columns: `users_page_view` through `users_payment`
2. **Transform** → **Unpivot Columns**
3. Rename: `Attribute` → `Step`, `Value` → `Users`
4. Add custom column for step order:
   ```
   Step Order = 
   SWITCH([Step],
       "users_page_view", 1,
       "users_product_view", 2,
       "users_add_to_cart", 3,
       "users_checkout", 4,
       "users_payment", 5
   )
   ```

---

## Dashboard 3: User Engagement

**Source:** `mart_daily_active_users`

| Visual | Type | Fields |
|--------|------|--------|
| DAU/WAU/MAU Trend | Line Chart (multi-series) | X: `activity_date`, Y: `dau`, `wau`, `mau` |
| Stickiness | Line Chart | X: `activity_date`, Y: `stickiness_pct` |
| DAU Change | Bar Chart | X: `activity_date`, Y: `dau_change` (conditional formatting: green +, red -) |
| Current Metrics | Cards | Latest `dau`, `wau`, `mau`, `stickiness_pct` |

### DAX for Latest Metrics

```dax
Latest DAU = 
CALCULATE(
    MAX(mart_daily_active_users[dau]),
    FILTER(mart_daily_active_users, 
        mart_daily_active_users[activity_date] = MAX(mart_daily_active_users[activity_date]))
)

Latest Stickiness = 
CALCULATE(
    MAX(mart_daily_active_users[stickiness_pct]),
    FILTER(mart_daily_active_users, 
        mart_daily_active_users[activity_date] = MAX(mart_daily_active_users[activity_date]))
)
```

---

## Design Tips

1. **Color palette**: Use 2-3 colors max. Blue for primary metrics, gray for secondary.
2. **Cards at top**: Key metrics (DAU, bounce rate, conversion) should be immediately visible.
3. **Date filter**: Always include a date slicer — reviewers will interact with it.
4. **Mobile layout**: Power BI has a phone view — configure it for bonus points.

---

## Export for Portfolio

1. **Publish to Power BI Service** → Get shareable link (if using web)
2. **Export to PDF**: File → Export → PDF
3. **Screenshots**: Use Windows Snipping Tool or `Win+Shift+S`
   - Full dashboard view
   - Zoomed funnel chart
   - DAU/WAU/MAU trend

---

## Troubleshooting

**Can't connect to localhost:**
- Ensure Postgres container is running: `docker ps`
- Check port: should be `5433` (mapped from container's 5432)
- Firewall may block connections — try disabling temporarily

**Tables not showing:**
- Run `dbt run` first to create mart tables
- Check schema: tables are in `raw_mart`, not `public`

**Data gateway issues (Power BI Service):**
- For local dev, use Power BI Desktop instead
- Gateway only needed for scheduled refresh from localhost

---

## Comparison: Power BI vs Metabase

| Aspect | Power BI | Metabase |
|--------|----------|----------|
| Resume signal | ✅ Enterprise standard | ⚠️ Startup-tier |
| Setup | Needs Windows or gateway | Docker, 2 min |
| DAX learning curve | Medium | N/A (SQL only) |
| Visual polish | Higher | Good enough |
| Cost | Free Desktop, paid Service | Free OSS |

**Recommendation:** Use Power BI for portfolio screenshots. Keep Metabase for quick iteration during development.
