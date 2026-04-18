{{
  config(
    materialized='table',
    schema='mart'
  )
}}

/*
  Funnel conversion analysis — step-by-step drop-off.

  Mental model: Like a leaky pipe. Water (users) enters at the top,
  and we measure how much leaks out at each joint (funnel step).

  Output is daily grain with:
  - How many users reached each step
  - What % converted to the next step
  - What % converted from step 0 (overall funnel efficiency)

  Note: This counts users who reached each step, not events.
  A user adding 5 items to cart counts once at step 2.
*/

with funnel_events as (
    select * from {{ ref('int_funnels') }}
),

-- Get the max funnel step each user reached per day
user_daily_max_step as (
    select
        user_id,
        date_trunc('day', event_timestamp)::date as event_date,
        max(funnel_step_index) as max_step_reached
    from funnel_events
    group by user_id, date_trunc('day', event_timestamp)::date
),

-- Count users at each step per day
-- A user at step 3 also counts for steps 0, 1, 2
step_counts as (
    select
        event_date,
        sum(case when max_step_reached >= 0 then 1 else 0 end) as users_step_0,
        sum(case when max_step_reached >= 1 then 1 else 0 end) as users_step_1,
        sum(case when max_step_reached >= 2 then 1 else 0 end) as users_step_2,
        sum(case when max_step_reached >= 3 then 1 else 0 end) as users_step_3,
        sum(case when max_step_reached >= 4 then 1 else 0 end) as users_step_4
    from user_daily_max_step
    group by event_date
)

select
    event_date,

    -- Absolute counts
    users_step_0 as users_page_view,
    users_step_1 as users_product_view,
    users_step_2 as users_add_to_cart,
    users_step_3 as users_checkout,
    users_step_4 as users_payment,

    -- Step-over-step conversion (what % moved to next step?)
    round(100.0 * users_step_1 / nullif(users_step_0, 0), 2) as cvr_view_to_product,
    round(100.0 * users_step_2 / nullif(users_step_1, 0), 2) as cvr_product_to_cart,
    round(100.0 * users_step_3 / nullif(users_step_2, 0), 2) as cvr_cart_to_checkout,
    round(100.0 * users_step_4 / nullif(users_step_3, 0), 2) as cvr_checkout_to_payment,

    -- Overall funnel conversion (what % made it all the way?)
    round(100.0 * users_step_4 / nullif(users_step_0, 0), 2) as overall_conversion_rate

from step_counts
order by event_date
