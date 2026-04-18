# Kafka Setup Notes

These notes document the key steps and commands used to configure and run the Kafka broker for the user_activity_streams project.

---

## 1. Docker Network

- Create a shared network for Kafka and Druid services:
  ```bash
  docker network create druid-net
  ```
- Attach both Kafka and Druid services to `druid-net` in each `docker-compose.yml`:
  ```yaml
  services:
    kafka:
      networks:
        - druid-net
    coordinator:
      networks:
        - druid-net
  networks:
    druid-net:
      external: true
  ```

---

## 2. Docker-Compose Configuration

- **Image**: use `confluentinc/cp-kafka:<version>` (e.g., `7.4.0`)
- **Ports**:
  ```yaml
  ports:
    - "9092:9092"       # PLAINTEXT_DOCKER for other containers
    - "29092:29092"     # PLAINTEXT_HOST for host clients
  ```
- **Listeners** (bind to all interfaces with separate ports for host vs Docker):
  ```yaml
  environment:
    KAFKA_LISTENERS: PLAINTEXT_DOCKER://0.0.0.0:9092,PLAINTEXT_HOST://0.0.0.0:29092,CONTROLLER://0.0.0.0:9093
    KAFKA_ADVERTISED_LISTENERS: PLAINTEXT_DOCKER://kafka:9092,PLAINTEXT_HOST://localhost:29092
    KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT_DOCKER:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT,CONTROLLER:PLAINTEXT
    KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT_DOCKER
  ```
- **Storage**:
  ```yaml
  volumes:
    - kafka_data:/var/lib/kafka/data
  ```
- **Environment Variable for Cluster ID**:
  ```yaml
  environment:
    CLUSTER_ID: "${CLUSTER_ID}"
  ```

## 2.1 Kafka Broker Configuration File (`kafka.properties`)

The `kafka.properties` file contains broker-specific settings and should be mounted into the container at `/etc/kafka/kafka.properties`. Key entries include:

```properties
# Node and controller IDs
process.roles=broker,controller
node.id=1
controller.listener.names=CONTROLLER
controller.quorum.voters=1@kafka:9093

# Listener configuration
listeners=PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
advertised.listeners=PLAINTEXT://kafka:9092

# Storage directories
log.dirs=/var/lib/kafka/data

# Topic auto-creation (dev only)
auto.create.topics.enable=true

# KRaft mode (no ZooKeeper)
zookeeper.connect=
```

**Note:**  
We expose two listener ports so that Docker-based services (e.g., Druid) connect via `kafka:9092` (PLAINTEXT_DOCKER) and host-based clients (e.g., `producer.py`) connect via `localhost:29092` (PLAINTEXT_HOST).  
---

## 3. Generating and Setting CLUSTER_ID

- **Manually generate** a new cluster ID before startup:
  ```bash
  export CLUSTER_ID=$(docker run --rm confluentinc/cp-kafka:latest kafka-storage random-uuid)
  ```
- **Set CLUSTER_ID** in your shell or in a `.env` file (to be read by Docker Compose):
  ```dotenv
  CLUSTER_ID=R6sdZAE8QtOnatxbX791oA
  ```

---

## 4. start-kafka.sh Wrapper Script

A convenience script to generate the cluster ID, wipe old data, and start containers:

```bash
#!/usr/bin/env bash
set -e

# 1) Generate a fresh cluster ID
export CLUSTER_ID=$(docker run --rm confluentinc/cp-kafka:latest kafka-storage random-uuid)
echo "Using Kafka CLUSTER_ID: $CLUSTER_ID"

# 2) Bring down existing containers and volumes
docker-compose down -v

# 3) Start Kafka (and dependent services)
docker-compose up -d kafka

# Optional: verify broker is healthy
docker-compose exec kafka kafka-topics --bootstrap-server kafka:9092 --list
```

Make the script executable:
```bash
chmod +x start-kafka.sh
```

---

## 5. Topic Management

- **List topics**:
  ```bash
  docker-compose exec kafka kafka-topics --bootstrap-server kafka:9092 --list
  ```
- **Create topic**:
  ```bash
  docker-compose exec kafka \
    kafka-topics --bootstrap-server kafka:9092 \
    --create --topic user_activity --partitions 1 --replication-factor 1
  ```
- **Produce test event**:
  ```bash
  echo '{"timestamp":"2025-06-21T16:00:00Z","user_id":123,"event_type":"test","page":"/"}' \
    | docker-compose exec -T kafka kafka-console-producer --broker-list kafka:9092 --topic user_activity
  ```
- **Consume all messages**:
  ```bash
  docker-compose exec -T kafka \
    kafka-console-consumer --bootstrap-server kafka:9092 \
    --topic user_activity --from-beginning --timeout-ms 10000
  ```

---

## 6. Cleanup

- **Remove data volume**:
  ```bash
  docker volume rm kafka_data
  ```
- **Remove network** (if external):
  ```bash
  docker network rm druid-net
  ```