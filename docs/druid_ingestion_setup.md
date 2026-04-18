# ✅ Druid Ingestion Setup Checklist

Use this checklist to set up a working ingestion pipeline from Kafka to Apache Druid.

---

## 📦 1. Kafka Broker Ready
- [ ] Kafka broker is up and running
- [ ] Kafka topic is created (e.g., `user_activity_logs`)
- [ ] Messages are being published to the topic in expected format (e.g., JSON)

---

## 🌐 Docker Networking
- [ ] Create a Docker network for Druid and Kafka, for example:
  ```bash
  docker network create druid-net
  ```
- [ ] In each `docker-compose.yml` for Kafka and Druid, add under each service:
  ```yaml
  networks:
    - druid-net
  ```
- [ ] Ensure Kafka’s `advertised.listeners` uses the container hostname (e.g., `PLAINTEXT://kafka:9092`) and that Druid points to `kafka:9092`.

---

## 🔧 2. Druid Configurations
- [ ] Druid cluster is running with all necessary services:
  - [ ] Coordinator
  - [ ] Overlord
  - [ ] Historical
  - [ ] MiddleManager or Indexer
  - [ ] Broker
  - [ ] Router
- [ ] Zookeeper is running (unless using metadata-based discovery and PostgreSQL)
- [ ] Kafka indexing extension is enabled:
```properties
  druid.extensions.loadList=["druid-kafka-indexing-service", ...]
```
- [ ] All Druid services are attached to the `druid-net` network and can communicate with the Kafka broker.

---

## 🛠️ 3. Define Supervisor Spec
- [ ] Create a `supervisor-spec.json` with the following structure:
```json
{
  "type": "kafka",
  "spec": {
    "dataSchema": {
      "dataSource": "your-druid-table-name",
      "timestampSpec": {
        "column": "timestamp",
        "format": "iso"
      },
      "dimensionsSpec": {
        "dimensions": ["user_id", "event_type", "page"]
      },
      "metricsSpec": [],
      "granularitySpec": {
        "type": "uniform",
        "segmentGranularity": "hour",
        "queryGranularity": "none",
        "rollup": false
      }
    },
    "ioConfig": {
      "topic": "your-kafka-topic",
      "inputFormat": {
        "type": "json"
      },
      "consumerProperties": {
        "bootstrap.servers": "kafka:9092"
      },
      "taskCount": 1,
      "replicas": 1,
      "taskDuration": "PT10M",
      "useEarliestOffset": true
    },
    "tuningConfig": {
      "type": "kafka"
    }
  }
}
```
- [ ] Save it as `kafka_supervisor.json`

---

## 📤 4. Submit Ingestion Spec
- [ ] Submit via API:
```bash
curl -X POST http://localhost:8081/druid/indexer/v1/supervisor \
     -H 'Content-Type: application/json' \
     -d @kafka_supervisor.json
```
- [ ] Or use the Druid Console → Ingestion → Kafka → Paste the spec and submit

---

## 📊 5. Verify Ingestion
- [ ] Check Ingestion tab for running supervisor
- [ ] Check Datasources tab for new segments appearing
- [ ] Query data from Druid Broker via console or API

---

## 🧪 Optional: Test Data Push
- [ ] Produce test messages to Kafka topic using CLI or script
```bash
echo '{"timestamp":"2025-06-13T10:00:00Z", "user_id":123, "event_type":"click", "page":"/home"}' \
| kafka-console-producer --broker-list localhost:9092 --topic user_activity_logs
```

---

Let me know if you'd like this expanded for multi-topic ingestion or Kafka Connect integration.
