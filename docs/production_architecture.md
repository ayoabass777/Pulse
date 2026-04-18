# Pulse — Production Architecture

> This document maps the local development stack to a production-ready AWS deployment. The patterns and guarantees remain identical; only the infrastructure changes.

---

## Architecture Comparison

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            LOCAL (Development)                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Producer ──► Kafka (Docker) ──► Consumer ──► Postgres (Docker) ──► dbt    │
│                    │                              │                          │
│                   DLQ                         localhost:5433                 │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                           PRODUCTION (AWS)                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   SDK ──► API Gateway ──► Lambda ──► MSK ──► ECS/Lambda ──► RDS ──► dbt     │
│    │           │                      │           │          │              │
│   Web       WAF/Auth               S3 Archive   DLQ Topic   Private VPC     │
│                                                                              │
│                              ┌──────────────┐                                │
│                              │   Airflow    │ (MWAA)                         │
│                              │  Scheduler   │                                │
│                              └──────────────┘                                │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Component Mapping

| Layer | Local | AWS Production | Why the change |
|-------|-------|----------------|----------------|
| **Event Ingestion** | Python producer (simulated) | API Gateway + Lambda | Real SDK hits an HTTP endpoint; Lambda handles auth, validation, and Kafka produce |
| **Message Broker** | Kafka (Docker, KRaft) | Amazon MSK | Managed Kafka — no broker ops, automatic patching, multi-AZ replication |
| **Raw Storage** | Postgres `raw.events` | S3 (raw/) + RDS | S3 for cheap, durable raw archive; RDS for queryable events |
| **Stream Consumer** | Python script | ECS Fargate or Lambda | Containerized consumer with auto-scaling; Lambda for lower volume |
| **Dead Letter Queue** | Kafka topic (`user_activity_dlq`) | MSK DLQ topic + S3 DLQ prefix | Same pattern, just managed |
| **Transform** | dbt (local CLI) | dbt Cloud or EventBridge + Lambda | Scheduled runs, CI/CD integration, environment separation |
| **Orchestration** | Manual / cron | EventBridge + Lambda (simple) or MWAA (complex) | Trigger dbt on schedule; Airflow only if multi-source dependencies |
| **BI Layer** | Metabase / Power BI Desktop | QuickSight or Power BI Service | Embedded dashboards, row-level security, SSO |
| **Secrets** | `.env` file | AWS Secrets Manager | Rotation, audit trail, IAM-based access |
| **Networking** | localhost | VPC + Private Subnets | MSK and RDS in private subnets; no public exposure |

---

## AWS Services Deep Dive

### Amazon MSK (Managed Streaming for Kafka)

**What it replaces:** Local Kafka container

**Why MSK over Kinesis:**
- Kafka API compatibility — no code changes to producer/consumer
- Higher throughput per shard (Kinesis limited to 1MB/s per shard)
- Multi-consumer support without shard splitting
- Industry-standard skill (more transferable)

**Configuration:**
```
Cluster type:         Provisioned (or Serverless for variable load)
Broker instance:      kafka.m5.large (start small)
Number of brokers:    3 (one per AZ)
Storage:              100 GB per broker (auto-scaling enabled)
Replication factor:   3 (for durability)
Min in-sync replicas: 2
```

**Cost estimate:** ~$200-400/month for a small 3-broker cluster

---

### Amazon RDS (PostgreSQL)

**What it replaces:** Local Postgres container

**Why RDS over Aurora:**
- Simpler pricing model
- Familiar Postgres semantics
- Aurora overkill for this data volume

**Configuration:**
```
Engine:               PostgreSQL 15
Instance:             db.t3.medium (start small)
Storage:              100 GB gp3 (auto-scaling)
Multi-AZ:             Yes (for production)
Backup retention:     7 days
VPC:                  Private subnet only
```

**Cost estimate:** ~$50-100/month for a small instance

---

### S3 (Raw Data Lake)

**What it replaces:** N/A (new layer for production)

**Purpose:**
1. **Durability** — 11 nines, cheaper than RDS for cold storage
2. **Replayability** — re-ingest from S3 if consumer logic changes
3. **Audit trail** — immutable record of every event received

**Bucket structure:**
```
s3://pulse-data-prod/
├── raw/
│   └── events/
│       └── year=2026/month=04/day=17/
│           └── hour=14/
│               └── events-1713365400.jsonl.gz
├── dlq/
│   └── events/
│       └── 2026-04-17/
│           └── batch-abc123.jsonl
└── dbt/
    └── artifacts/
        └── manifest.json
```

**Cost estimate:** ~$5-20/month for modest volume

---

### Amazon MWAA (Managed Airflow) — When You Need It

**What it replaces:** Manual dbt runs / local Airflow

**When to use MWAA:**
- Multiple data sources with dependencies (e.g., wait for source A and B before running transform)
- Complex backfill orchestration
- Team needs DAG visibility and alerting
- More than 3-5 scheduled jobs

**When to skip MWAA (use EventBridge + Lambda instead):**
- Single data source (like Pulse)
- One transform job (dbt run)
- No cross-job dependencies
- Cost-sensitive ($300+/month for MWAA vs ~$5/month for Lambda)

**Simple alternative — EventBridge + Lambda:**
```python
# lambda_function.py
import subprocess

def handler(event, context):
    result = subprocess.run(
        ["dbt", "run", "--profiles-dir", "/opt/dbt", "--target", "prod"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise Exception(f"dbt failed: {result.stderr}")
    return {"status": "success", "output": result.stdout}
```

**EventBridge rule:**
```json
{
  "ScheduleExpression": "rate(15 minutes)",
  "Targets": [{"Arn": "arn:aws:lambda:...:dbt-runner"}]
}
```

---

### Alternatives Considered

| Local Tool | AWS Option A | AWS Option B | Decision |
|------------|--------------|--------------|----------|
| Kafka | MSK | Kinesis | MSK — Kafka compatibility, no code changes |
| Postgres | RDS | Aurora Serverless | RDS — simpler, cheaper for known workload |
| Airflow | MWAA | Step Functions | MWAA — dbt native, DAG visibility |
| BI | QuickSight | Power BI Embedded | Either — QuickSight cheaper, Power BI more familiar |

---

## Delivery Guarantees (Unchanged)

The production stack maintains the same guarantees as local:

| Guarantee | Local Implementation | Production Implementation |
|-----------|---------------------|---------------------------|
| **Producer → Kafka: Exactly-once** | `enable.idempotence=True` | Same config on MSK |
| **Kafka → Consumer: At-least-once** | Manual offset commit | Same pattern on ECS/Lambda |
| **Consumer → Postgres: Idempotent** | `ON CONFLICT DO NOTHING` | Same DDL on RDS |
| **End-to-end: Effectively exactly-once** | Idempotent key (`event_id`) | Same key derivation |

---

## Security Layers (Production Only)

| Layer | Service | Purpose |
|-------|---------|---------|
| **Edge** | API Gateway + WAF | Rate limiting, IP filtering, bot protection |
| **Auth** | Cognito or API keys | SDK authentication |
| **Network** | VPC + Security Groups | MSK and RDS in private subnets |
| **Encryption** | KMS | At-rest encryption for S3, RDS, MSK |
| **Secrets** | Secrets Manager | DB credentials, API keys |
| **IAM** | Least-privilege roles | ECS task roles, Lambda execution roles |

---

## Cost Summary (Estimated)

| Component | Monthly Cost |
|-----------|--------------|
| MSK (3-broker) | $200-400 |
| RDS (t3.medium, Multi-AZ) | $100-150 |
| S3 (100 GB) | $5-20 |
| EventBridge + Lambda (dbt) | $5-10 |
| ECS Fargate (consumer) | $30-50 |
| API Gateway | $5-20 |
| **Total** | **$345-650/month** |

*Note: MWAA ($300-400/month) only if you have multi-source dependencies.*

For a portfolio project, you'd use:
- MSK Serverless (pay-per-use)
- RDS Single-AZ (no Multi-AZ)
- Skip MWAA, use Lambda + EventBridge for scheduling

**Reduced portfolio cost:** ~$100-200/month

---

## Migration Path

### Phase 1: Add S3 Landing Zone (Local)
```
Producer → Kafka → Consumer → S3 (local MinIO) → Postgres → dbt
```
- Add MinIO container to docker-compose
- Consumer writes to S3 before Postgres
- Validates the pattern without AWS cost

### Phase 2: Deploy to AWS Free Tier
- RDS Free Tier (750 hours/month for 12 months)
- S3 Free Tier (5 GB)
- Lambda Free Tier (1M requests/month)
- Skip MSK initially — use Lambda direct-to-RDS

### Phase 3: Add MSK (When Ready)
- Provision MSK Serverless
- Point producer and consumer to MSK endpoint
- Full production architecture achieved

---

## Interview Talking Points

1. **"Why Kafka over Kinesis?"**
   - Kafka: multi-consumer, higher throughput, industry standard, portable skills
   - Kinesis: tighter AWS integration, simpler if already all-in on AWS
   - Choice depends on team expertise and existing infrastructure

2. **"How would you handle 10x traffic?"**
   - MSK: add brokers, increase partitions
   - Consumer: ECS auto-scaling on queue depth
   - RDS: read replicas or Aurora Serverless
   - dbt: incremental models already in place

3. **"What about real-time dashboards?"**
   - Phase 2 adds Druid for sub-second queries
   - Alternative: Materialize or ksqlDB for streaming SQL
   - Or: Lambda → DynamoDB → AppSync for WebSocket push

4. **"How do you ensure exactly-once?"**
   - Walk through the delivery guarantee chain
   - Idempotent producer (broker dedup)
   - At-least-once consumer (commit after write)
   - Idempotent sink (ON CONFLICT)
   - End-to-end: effectively exactly-once

5. **"What would you monitor?"**
   - Consumer lag (MSK metrics)
   - DLQ depth (CloudWatch alarm)
   - dbt test failures (Airflow alerts)
   - RDS connections and CPU
   - S3 object count (data freshness proxy)

---

## References

- [MSK Best Practices](https://docs.aws.amazon.com/msk/latest/developerguide/bestpractices.html)
- [RDS for PostgreSQL](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_PostgreSQL.html)
- [MWAA User Guide](https://docs.aws.amazon.com/mwaa/latest/userguide/what-is-mwaa.html)
- [dbt Cloud Deployment](https://docs.getdbt.com/docs/deploy/deployments)
