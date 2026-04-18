import os
import json
import random
import time
import uuid
import logging
from kafka import KafkaProducer
from faker import Faker
from datetime import datetime

#logging.basicConfig(format='%(levelname)s: %')

def on_send_success(record_metadata):
    print(f"Sent to {record_metadata.topic}, partition {record_metadata.partition}, offset {record_metadata.offset}")

def on_send_error(error):
    print(f"Kafka delivery failed: {error}")

def main():
    #Read from env with defaults
    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS","localhost:29092")
    topic = os.getenv("KAFKA_TOPIC", "user_activity")

    if not topic:
        print("Error: KAFKA_TOPIC must be set")
        return

    # Configure producer for at-least-once (acks='all') with retries
    producer = KafkaProducer(
        bootstrap_servers=[bootstrap_servers],
        key_serializer=lambda k: k.encode("utf-8"),
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        acks="all",
        retries=5,
        enable_idempotence=True,
        linger_ms=10,
        client_id="druid"
    )

    fake = Faker()
    Faker.seed(42)
    # Define realistic e-commerce event types and weights for selection
    event_types = [
        "page_view", "product_view", "search", "add_to_cart", "remove_from_cart",
        "checkout", "payment", "button_click", "form_submit", "video_play"
    ]
    event_weights = [5, 4, 3, 2, 1, 1, 1, 2, 1, 1]  # weights for event_types
    # Define product categories for metadata
    categories = ["electronics", "books", "clothing", "home", "sports"]
    no_uris = 30
    unique_uris = [fake.uri_path() for _ in range(no_uris)]

    # Define monthly user base
    monthly_users = [fake.uuid4() for _ in range(600)]

    funnel_sequence = [
        "page_view", "product_view", "add_to_cart", "checkout", "payment"
    ]
    step_prob = {
        "page_view": 0.6,
        "product_view": 0.5,
        "add_to_cart": 0.4,
        "checkout": 0.3
    }
    step_delay = {
        "page_view": (0.1, 1.0),
        "product_view": (0.1, 1.0),
        "add_to_cart": (0.5, 2.0),
        "checkout": (1.0, 3.0),
        "payment": (0.1, 0.5)
    }

    user_funnel_states = {user_id: None for user_id in monthly_users}

    print(f"Producing to topic '{topic}' on {bootstrap_servers} (Ctrl+C to stop)")
    
    try:
        while True:
            # Generate timestamp biased toward realistic e-commerce peak hours
            base_time = fake.date_time_between(start_date='-30d', end_date='now')

            # Define peak hours (9–11 AM and 7–9 PM) and use weighted random choice
            peak_hours = list(range(9, 12)) + list(range(19, 22))
            off_peak_hours = [h for h in range(24) if h not in peak_hours]
            hour = random.choices(
                population=peak_hours + off_peak_hours,
                weights=[3]*len(peak_hours) + [1]*len(off_peak_hours),
                k=1
            )[0]

            # Replace the hour in base_time to simulate realistic access patterns
            timestamp = base_time.replace(hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59))

            # Choose a user for this event
            user_id = random.choice(monthly_users)

            last_step = user_funnel_states[user_id]
            if last_step is None:
                next_event = funnel_sequence[0]
            else:
                last_index = funnel_sequence.index(last_step)
                cont_prob = step_prob.get(last_step, 0.7)
                if last_index + 1 < len(funnel_sequence) and random.random() < cont_prob:
                    next_event = funnel_sequence[last_index + 1]
                else:
                    next_event = last_step

            user_funnel_states[user_id] = next_event

            # Reset funnel for repeat conversions
            if next_event == "payment" and random.random() < 0.8:
                user_funnel_states[user_id] = None

            event = {
                "event_id": str(uuid.uuid4()),
                "event_type": next_event,
                "user_id": user_id,
                "timestamp": timestamp.isoformat(),
                "page": random.choice(unique_uris),
                "metadata": {
                    "product_id": fake.uuid4(),
                    "category": random.choice(categories),
                    "price": round(random.uniform(5.0, 200.0), 2),
                    "search_query": fake.sentence(nb_words=3)
                },
                "funnel_step_index": funnel_sequence.index(next_event),
                "funnel_complete": (next_event == "payment"),
            }
            print(f"Sending event: {event}")
            # Partition by user_id to keep per-user ordering
            future = producer.send(topic, key=event["user_id"], value=event)
            # callbacks instead of blocking `.get()`
            future.add_callback(on_send_success)
            future.add_errback(on_send_error)
            
            # Pause based on funnel step
            delay = random.uniform(*step_delay.get(next_event, (0.2, 1.0)))
            time.sleep(delay)

    except KeyboardInterrupt:
        print("\nInterrupted. Flushing and closing producer")
    finally:
        producer.flush()
        producer.close()

if __name__ == "__main__":
    main()