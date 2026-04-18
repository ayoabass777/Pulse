{{
  config(
    materialized='view',
    schema='int'
  )
}}

/*
  Funnel step tracking — event-level view with funnel position.

  Funnel sequence:
    0 = page_view (awareness)
    1 = product_view (interest)
    2 = add_to_cart (intent)
    3 = checkout (commitment)
    4 = payment (conversion)

  Mental model: This is like tracking where each runner is in a race.
  The mart layer (funnel_conversion) will aggregate to show "how many
  runners finished each leg?" and "what % dropped out at each stage?"

  Session context is included so you can answer:
  - "Did this user complete the funnel in one session or across multiple?"
  - "Which sessions had add-to-cart but no checkout?"
*/

with sessionized_events as (
    select * from {{ ref('int_sessions') }}
),

funnel_events as (
    select
        session_id,
        user_id,
        event_id,
        event_type,
        event_timestamp,
        funnel_step_index,
        funnel_complete,
        product_id,
        category,
        price
    from sessionized_events
    where funnel_step_index is not null  -- only funnel-relevant events
)

select
    -- Keys
    event_id,
    session_id,
    user_id,

    -- Funnel position
    funnel_step_index,
    case funnel_step_index
        when 0 then 'page_view'
        when 1 then 'product_view'
        when 2 then 'add_to_cart'
        when 3 then 'checkout'
        when 4 then 'payment'
    end as funnel_step_name,
    funnel_complete,

    -- Event context
    event_type,
    event_timestamp,
    product_id,
    category,
    price

from funnel_events
