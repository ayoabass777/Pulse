{{
  config(
    materialized='table',
    schema='mart'
  )
}}

/*
  Daily/Weekly/Monthly Active Users (DAU/WAU/MAU).

  Mental model: Like counting unique visitors to a store.
  - DAU = how many people walked in today
  - WAU = how many different people visited this week
  - MAU = how many different people visited this month

  WAU/MAU use rolling windows (last 7/30 days), not calendar boundaries.
  This gives smoother trends and avoids "new week" discontinuities.

  Stickiness = DAU/MAU ratio:
  - High stickiness (>25%) = users come back frequently
  - Low stickiness (<10%) = users visit once and ghost
*/

with events as (
    select * from {{ ref('stg_events') }}
),

-- Get distinct users per day
daily_users as (
    select
        date_trunc('day', event_timestamp)::date as activity_date,
        user_id
    from events
    group by date_trunc('day', event_timestamp)::date, user_id
),

-- DAU: count per day
dau as (
    select
        activity_date,
        count(distinct user_id) as dau
    from daily_users
    group by activity_date
),

-- WAU: rolling 7-day window (users active in last 7 days including today)
wau as (
    select
        d.activity_date,
        count(distinct du.user_id) as wau
    from (select distinct activity_date from daily_users) d
    cross join lateral (
        select user_id
        from daily_users
        where activity_date between d.activity_date - interval '6 days' and d.activity_date
    ) du
    group by d.activity_date
),

-- MAU: rolling 30-day window
mau as (
    select
        d.activity_date,
        count(distinct du.user_id) as mau
    from (select distinct activity_date from daily_users) d
    cross join lateral (
        select user_id
        from daily_users
        where activity_date between d.activity_date - interval '29 days' and d.activity_date
    ) du
    group by d.activity_date
)

select
    dau.activity_date,
    dau.dau,
    wau.wau,
    mau.mau,

    -- Stickiness: how often do monthly users come back daily?
    round(100.0 * dau.dau / nullif(mau.mau, 0), 2) as stickiness_pct,

    -- Growth indicators (vs previous day)
    dau.dau - lag(dau.dau) over (order by dau.activity_date) as dau_change,
    wau.wau - lag(wau.wau) over (order by dau.activity_date) as wau_change

from dau
join wau on dau.activity_date = wau.activity_date
join mau on dau.activity_date = mau.activity_date
order by dau.activity_date
