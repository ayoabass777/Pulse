# ✅ Druid Setup Checklist (Zookeeper-Free, Docker-Based)

This checklist covers two approaches:
- **Single-Node Micro-Quickstart** (development/demo).
- **Multi-Node Cluster Mode** (production-like, shared config).

---

## Prerequisites
- [ ] Install Docker and Docker Compose
- [ ] Allocate at least **8–12 GB RAM** to Docker
- [ ] Create your project structure (e.g., `user_activity_streams/`)
- [ ] Clone the Apache Druid repository:
  ```bash
  git clone https://github.com/apache/druid.git
  cd druid
  ```
- [ ] (Optional) Checkout a stable version:
  ```bash
  git checkout 27.0.0
  ```
- [ ] Build the Docker image locally:
  ```bash
  docker build -f distribution/docker/Dockerfile -t apache/druid:local .
  ```

---

## PostgreSQL Metadata Store
- [ ] Add a `postgres` service in `docker-compose.yml`
- [ ] Ensure port `5432` is exposed
- [ ] Set environment variables:
  ```yaml
  POSTGRES_USER=druid
  POSTGRES_PASSWORD=FoolishPassword
  POSTGRES_DB=druid
  ```
- [ ] Allow external connections in `postgresql.conf` and `pg_hba.conf` if deploying across hosts

---

## Deep Storage Setup
- [ ] Choose storage backend:
  - Local: `druid.storage.type=local`
  - S3: `druid.storage.type=s3`, with access credentials
- [ ] Mount a shared volume (`druid_shared:/opt/shared`)
- [ ] Ensure deep storage directory exists or is volume mounted

---

## A. Single-Node Micro-Quickstart Setup

1. [ ] Use the built-in micro-quickstart Docker-Compose in `distribution/docker/docker-compose.yml`.
2. [ ] (Optional) Extract and override `conf/druid/single-server/micro-quickstart` if customization is needed.
3. [ ] In your Compose, pass Druid settings via environment variables:
   ```yaml
   environment:
     DRUID_DISCOVERY_TYPE: curator
     DRUID_ZK_SERVICE_HOST: zookeeper:2181
     DRUID_METADATA_STORAGE_CONNECTURI: jdbc:postgresql://postgres:5432/druid
     DRUID_METADATA_STORAGE_USER: druid
     DRUID_METADATA_STORAGE_PASSWORD: FoolishPassword
   ```
4. [ ] (Optional) Mount overrides:
   ```yaml
   volumes:
     - ./my-overrides/micro-quickstart/broker/runtime.properties:/opt/druid/conf/druid/single-server/micro-quickstart/broker/runtime.properties:ro
   ```
5. [ ] Run:
   ```bash
   docker-compose -f distribution/docker/docker-compose.yml up -d
   ```

---

## B. Multi-Node Cluster Setup

1. [ ] Create a `.env` file alongside your `docker-compose.yml` and define all Druid configuration there using uppercase environment variables, for example:
   ```
   DRUID_DISCOVERY_TYPE=curator
   DRUID_ZK_SERVICE_HOST=zookeeper:2181
   DRUID_METADATA_STORAGE_TYPE=postgresql
   DRUID_METADATA_STORAGE_CONNECTOR_CONNECTURI=jdbc:postgresql://postgres:5432/druid
   DRUID_METADATA_STORAGE_CONNECTOR_USER=druid
   DRUID_METADATA_STORAGE_CONNECTOR_PASSWORD=FoolishPassword
   DRUID_STORAGE_TYPE=local
   DRUID_STORAGE_STORAGEDIRECTORY=/opt/shared/deepstorage
   DRUID_EXTENSIONS_LOADLIST=["druid-discovery-curator","postgresql-metadata-storage","druid-kafka-indexing-service"]
   ```
2. [ ] In your `docker-compose.yml`, add:
   ```yaml
   env_file:
     - .env
   ```
   under each Druid service (coordinator, broker, historical, middleManager, router) so they receive these environment variables.
3. [ ] Override commands to use cluster config:
   ```yaml
   command:
     - broker
     - -c
     - /opt/druid/conf/druid/cluster
   ```
   (Repeat for each Druid service with its name.)
4. [ ] Define services (`coordinator`, `broker`, `historical`, `middleManager`, `router`), each depending on `postgres` and `zookeeper`, with volumes and ports.
5. [ ] Start the cluster:
   ```bash
   docker-compose up -d
   ```
