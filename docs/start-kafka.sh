#!/usr/bin/env bash
# start-kafka.sh

# generate a fresh ID
export CLUSTER_ID=$(docker run --rm confluentinc/cp-kafka:latest kafka-storage random-uuid)

# launch compose
docker-compose down -v
docker-compose up -d