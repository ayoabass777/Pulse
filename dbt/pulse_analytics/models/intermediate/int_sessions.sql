{{
  config(
    materialized='view',
    schema='int'
  )
}}

/*
  Session reconstruction using 30-minute inactivity gap.

  Mental model: Think of sessions like TV episodes. If a viewer stops watching
  for 30+ minutes, that's a new viewing session — even if they come back to
  the same show.

  Timestamp choice:
  - We use `event_timestamp` (business time) for ordering, not `kafka_timestamp`
  - Business time = "when did the user act?" — correct for session logic
  - Ingestion time = "when did Kafka receive it?" — used for freshness, not ordering
  - Out-of-order ingestion is possible; business time is the source of truth

  How it works:
  1. Order events by user + event_timestamp
  2. Flag a "new session" whenever the gap from the previous event > 30 min
  3. Running sum of those flags = session_number per user
  4. Generate session_id from user_id + session_number

  Note: This is batch session reconstruction. Works great for analytics.
  If you need real-time sessions (e.g., "how many active sessions right now?"),
  you'd move this logic to Flink/Spark Streaming with event-time windowing.
*/

with events as (
    select * from {{ ref('stg_events') }}
),

events_with_lag as (
    select
        *,
        lag(event_timestamp) over (
            partition by user_id
            order by event_timestamp
        ) as prev_event_timestamp
    from events
),

events_with_session_flag as (
    select
        *,
        case
            -- First event for this user = new session
            when prev_event_timestamp is null then 1
            -- Gap > 30 minutes = new session
            when event_timestamp - prev_event_timestamp > interval '30 minutes' then 1
            else 0
        end as is_new_session
    from events_with_lag
),

events_with_session_number as (
    select
        *,
        sum(is_new_session) over (
            partition by user_id
            order by event_timestamp
            rows between unbounded preceding and current row
        ) as session_number
    from events_with_session_flag
)

select
    -- Session key
    user_id || ':' || session_number::text as session_id,
    user_id,
    session_number,

    -- Event details
    event_id,
    event_type,
    page,
    product_id,
    category,
    price,
    search_query,
    funnel_step_index,
    funnel_complete,

    -- Timestamps
    event_timestamp,
    kafka_timestamp,

    -- Session flags (useful for debugging)
    is_new_session,
    prev_event_timestamp

from events_with_session_number
