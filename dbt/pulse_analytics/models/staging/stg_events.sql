{{
  config(
    materialized='view',
    schema='stg'
  )
}}

/*
  Staged events — cleaned and typed from raw.events.

  Consumer already guarantees event_id uniqueness (ON CONFLICT DO NOTHING),
  so no dedup needed here. This layer is for:
  - Explicit typing / casting if needed
  - Column selection (drop kafka provenance from analytics path)
  - Renaming if conventions change
  - A stable contract for downstream models

  Dedup note: If you ever suspect upstream issues, add ROW_NUMBER() over
  (PARTITION BY event_id ORDER BY kafka_timestamp) to surface violations.
*/

with source as (
    select * from {{ source('raw', 'events') }}
)

select
    -- Keys
    event_id,
    user_id,

    -- Event attributes
    event_type,
    page,
    product_id,
    category,
    price,
    search_query,

    -- Funnel tracking
    funnel_step_index,
    funnel_complete,

    -- Timestamps (keep both for different use cases)
    event_timestamp,        -- business time: "when did this happen?"
    kafka_timestamp,        -- ingestion time: watermark / freshness checks

    -- Late data detection
    -- Event is "late" if it arrived >5 min after it occurred
    -- Useful for monitoring data quality in streaming pipelines
    case
        when kafka_timestamp - event_timestamp > interval '5 minutes' then true
        else false
    end as is_late,

    -- Audit (optional — drop if not needed downstream)
    created_at

from source
