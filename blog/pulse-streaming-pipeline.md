# Building a Streaming Session Analytics Pipeline with Kafka, Postgres, and dbt

*How I built an end-to-end clickstream pipeline with exactly-once delivery guarantees*

---

When I set out to build Pulse, I had a specific goal: demonstrate that I could work with streaming data, not just batch. My first portfolio project (Ballistics) was a batch pipeline — API calls on a schedule, Airflow orchestration, daily refreshes. That's the bread and butter of most data engineering work, but it's only half the picture.

Pulse is the other half. Real-time events flowing through Kafka, landing in Postgres, transformed by dbt into session analytics. Same dbt layer, completely different ingestion paradigm.

## What I Built

Pulse is a session analytics pipeline that processes clickstream events in real-time:

```
Event Simulator → Kafka → Python Consumer → Postgres → dbt → Metabase
```

The simulator generates realistic user behavior — page views, product views, add-to-cart events, checkouts, and payments. These flow through Kafka, get written to Postgres with exactly-once semantics, and dbt transforms them into:

- **Session metrics** — duration, bounce rate, landing pages
- **Funnel analysis** — step-by-step conversion from awareness to purchase
- **User engagement** — DAU/WAU/MAU with stickiness ratios

![Sessions Dashboard](../docs/images/01_sessions.png)

## Architecture

```
┌─────────────┐     ┌──────────┐     ┌──────────────┐     ┌──────────┐     ┌───────────┐
│   Event     │     │  Kafka   │     │   Python     │     │ Postgres │     │ Metabase  │
│  Simulator  │────▶│ (KRaft)  │────▶│  Consumer    │────▶│   raw    │────▶│ Dashboard │
│  (producer) │     │          │     │              │     │  events  │     │           │
└─────────────┘     └──────────┘     └──────────────┘     └────┬─────┘     └───────────┘
                         │                                     │
                    ┌────▼─────┐                          ┌────▼─────┐
                    │   DLQ    │                          │   dbt    │
                    │  topic   │                          │ models   │
                    └──────────┘                          └──────────┘
```

Everything runs locally in Docker — Kafka in KRaft mode (no Zookeeper), Postgres, and Metabase. The producer and consumer are Python scripts.

## The Hard Part: Exactly-Once Delivery

The most interesting engineering challenge was achieving exactly-once semantics end-to-end. This required two separate mechanisms working together:

### Layer 1: Idempotent Producer (`enable.idempotence=True`)

When the producer sends a message and the network times out, it doesn't know if Kafka received it. So it retries. Without idempotence, you'd get duplicate messages in the topic.

The idempotent producer solves this by tagging each message with a sequence number. If Kafka already has that sequence, it silently drops the retry. Duplicates never enter the topic.

### Layer 2: Idempotent Consumer Key (`ON CONFLICT DO NOTHING`)

Even with an idempotent producer, the consumer can still create duplicates. Here's how:

1. Consumer reads message from Kafka
2. Consumer writes row to Postgres ✓
3. Consumer crashes before committing offset to Kafka
4. Consumer restarts, replays from last committed offset
5. Consumer writes the same row again ← duplicate

The fix is an idempotent key. Every event gets a unique `event_id` derived from `user_id` + `kafka_timestamp_ms`. The Postgres table has a primary key constraint on this field, and every insert uses `ON CONFLICT (event_id) DO NOTHING`.

When the replay happens, Postgres silently rejects the duplicate. No error, no data corruption.

```sql
INSERT INTO raw.events (...) VALUES (...)
ON CONFLICT (event_id) DO NOTHING;
```

**These two mechanisms are not the same thing.** The producer idempotence prevents duplicates *in Kafka*. The consumer idempotent key prevents duplicates *in Postgres*. You need both for end-to-end exactly-once.

I verified this works by stopping the consumer mid-stream, resetting the Kafka offset to the beginning, and replaying all messages. Zero duplicates in Postgres.

## Two Timestamps, Two Purposes

Every event carries two timestamps:

| Timestamp | Source | Purpose |
|-----------|--------|---------|
| `event_timestamp` | Producer (business time) | When did the user act? Used for session ordering. |
| `kafka_timestamp` | Kafka broker (ingestion time) | When did we receive it? Used for freshness checks. |

Session reconstruction uses `event_timestamp` because that's the truth of user behavior. `kafka_timestamp` is for operational concerns — "is data flowing?" and "how stale is the latest batch?"

This distinction matters because events can arrive out of order. A user might click at 10:00:01, but network latency means Kafka receives it at 10:00:03. If you sessionize on ingestion time, you get wrong session boundaries.

## Session Reconstruction in SQL

The sessionization logic uses a 30-minute inactivity gap — industry standard for web analytics. If a user is idle for more than 30 minutes, the next event starts a new session.

```sql
-- Flag new sessions based on time gap
CASE
  WHEN prev_event_timestamp IS NULL THEN 1  -- first event
  WHEN event_timestamp - prev_event_timestamp > INTERVAL '30 minutes' THEN 1
  ELSE 0
END AS is_new_session
```

Then a running sum of those flags gives each event its session number:

```sql
SUM(is_new_session) OVER (
  PARTITION BY user_id
  ORDER BY event_timestamp
  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
) AS session_number
```

I chose to do this in dbt (batch) rather than a stream processor (Flink/Spark Streaming) deliberately. The session definition is still evolving — maybe 30 minutes becomes 20, maybe we add page-specific rules. SQL is testable, rerunnable, and version-controlled. Once the rules stabilize, I can move to stream processing if latency requires it.

## Error Handling: DLQ for Non-Transient Errors Only

Not all errors are equal:

| Error Type | Example | Action |
|------------|---------|--------|
| Transient | Connection timeout, deadlock | Don't commit offset → Kafka replays automatically |
| Non-transient | Missing required field, bad data type | Route to DLQ topic → commit offset to unblock |

Transient errors fix themselves. Just let Kafka replay. Non-transient errors need human attention, so they go to a dead letter queue where someone can inspect and decide what to do.

The key insight: **DLQ is for errors you can't retry your way out of.** If you DLQ transient errors, you're throwing away free retries.

## Funnel Analysis

The funnel tracks users through a five-step purchase journey:

```
Page View (0) → Product View (1) → Add to Cart (2) → Checkout (3) → Payment (4)
```

Each event carries a `funnel_step_index` from the producer. dbt aggregates this into daily conversion rates:

```sql
-- What % of users who viewed a product added it to cart?
ROUND(100.0 * users_step_2 / NULLIF(users_step_1, 0), 2) AS cvr_product_to_cart
```

![Funnel Dashboard](../docs/images/02_funnel.png)

## DAU/WAU/MAU with Stickiness

User engagement uses rolling windows:

- **DAU**: Distinct users today
- **WAU**: Distinct users in the last 7 days
- **MAU**: Distinct users in the last 30 days
- **Stickiness**: DAU / MAU — how often do monthly users come back daily?

A stickiness of 25% means a quarter of your monthly users are daily actives. Consumer apps aim for 20%+. Below 10% suggests users try the product once and ghost.

![Engagement Dashboard](../docs/images/03_engagement.png)

## Late Data Detection

In streaming, events can arrive out of order. A user clicks at 10:00:00, but network lag means Kafka receives it at 10:06:00. That's "late" data.

Pulse flags these in the staging layer:

```sql
CASE
  WHEN kafka_timestamp - event_timestamp > INTERVAL '5 minutes' 
  THEN TRUE
  ELSE FALSE
END AS is_late
```

I chose **flagging over exclusion**. Late events still contribute to session reconstruction — they're just marked for observability. If late data becomes a problem (>5% of events), that's a signal to investigate upstream latency, not throw data away.

## What's Not Here (And Why)

**No Airflow.** Pulse is event-driven. The consumer runs continuously, reacting to Kafka messages. There's nothing to schedule for ingestion. dbt runs on a simple cron or EventBridge trigger — Airflow would be overkill for a single transform job.

**No S3 landing zone.** For a production deployment, I'd add S3 between Kafka and Postgres as a raw archive layer. Enables replay from cold storage if the database needs to be rebuilt. I documented this in the production architecture doc but didn't implement it locally — diminishing returns for a portfolio project.

**Simulated data, not real traffic.** The event simulator generates fake clickstream. Real production would swap in a JavaScript SDK tracking actual user behavior. The pipeline architecture doesn't change — only the producer does.

## Production Path

If this were going to production on AWS:

| Local | Production |
|-------|------------|
| Kafka (Docker) | Amazon MSK |
| Postgres (Docker) | Amazon RDS |
| Manual dbt runs | EventBridge + Lambda |
| localhost:3000 | QuickSight or Power BI Service |

The patterns stay identical. Idempotent producer, idempotent consumer key, DLQ for non-transient errors, dbt for transforms. Just swap local containers for managed services.

## What I Learned

1. **Exactly-once is a chain, not a single mechanism.** Producer idempotence and consumer idempotent keys solve different failure modes. You need both.

2. **Timestamps are a design decision.** Business time vs ingestion time isn't academic — it affects session reconstruction correctness.

3. **DLQ is for non-retryable errors.** Transient failures should replay from Kafka, not clutter your dead letter queue.

4. **dbt works for streaming too.** The transform layer doesn't care if events arrived via batch API or real-time Kafka. Same staging → intermediate → marts pattern.

## What's Next

This completes my second portfolio project. Ballistics showed batch patterns (API → Airflow → S3 → Postgres → dbt). Pulse shows streaming patterns (Kafka → Postgres → dbt). Together they tell the story: I can work across both paradigms.

Next up: an AI-flavoured pipeline. RAG ingestion, embeddings, vector store. The "DE + AI" trend isn't about building ML models — it's about building pipelines that feed them.

---

**Code:** [github.com/ayoabass777/Pulse](https://github.com/ayoabass777/Pulse)

**Author:** Ayomide Abass — Data Engineer, Vancouver  
[LinkedIn](https://www.linkedin.com/in/ayomide-abass-36b40025a/) · [GitHub](https://github.com/ayoabass777)
