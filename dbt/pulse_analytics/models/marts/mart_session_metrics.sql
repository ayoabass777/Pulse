{{
  config(
    materialized='table',
    schema='mart'
  )
}}

/*
  Session-level metrics — one row per session.

  Key metrics:
  - Duration: time from first to last event
  - Event count: how engaged was this session?
  - Bounce: single-event sessions (user landed and left immediately)
  - Conversion: did this session end in a payment?

  Use cases:
  - "What's our average session duration?"
  - "What's our bounce rate?"
  - "What % of sessions convert?"
  - Segment by landing page, category, etc.
*/

with sessionized_events as (
    select * from {{ ref('int_sessions') }}
),

session_aggregates as (
    select
        session_id,
        user_id,

        -- Timing
        min(event_timestamp) as session_start,
        max(event_timestamp) as session_end,
        extract(epoch from (max(event_timestamp) - min(event_timestamp))) as duration_seconds,

        -- Engagement
        count(*) as event_count,
        count(distinct event_type) as distinct_event_types,

        -- Content
        min(page) as landing_page,  -- first page (assuming ordered insert)
        array_agg(distinct category) filter (where category is not null) as categories_viewed,

        -- Conversion
        bool_or(funnel_complete) as converted,
        max(funnel_step_index) as max_funnel_step

    from sessionized_events
    group by session_id, user_id
)

select
    session_id,
    user_id,

    -- Timing
    session_start,
    session_end,
    duration_seconds,
    round(duration_seconds / 60.0, 2) as duration_minutes,

    -- Engagement
    event_count,
    distinct_event_types,
    case when event_count = 1 then true else false end as is_bounce,

    -- Content
    landing_page,
    categories_viewed,

    -- Conversion
    converted,
    max_funnel_step,
    case max_funnel_step
        when 0 then 'page_view'
        when 1 then 'product_view'
        when 2 then 'add_to_cart'
        when 3 then 'checkout'
        when 4 then 'payment'
    end as exit_funnel_step

from session_aggregates
