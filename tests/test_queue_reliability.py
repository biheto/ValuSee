import json
import sys
from types import SimpleNamespace

from app.core.infrastructure import (
    MONITOR_DEAD_QUEUE,
    MONITOR_QUEUE,
    MONITOR_RETRY_QUEUE,
    declare_monitor_queues,
)
from app.shopping.worker import consume_events, write_heartbeat


class FakeChannel:
    def __init__(self):
        self.declarations = []

    def queue_declare(self, **kwargs):
        self.declarations.append(kwargs)
        return SimpleNamespace(method=SimpleNamespace(message_count=0))


def test_monitor_queue_topology_has_retry_and_dead_letter_routes(monkeypatch):
    monkeypatch.setenv("VALUSee_QUEUE_RETRY_DELAY_MS", "45000")
    channel = FakeChannel()
    declare_monitor_queues(channel)

    by_name = {item["queue"]: item for item in channel.declarations}
    assert set(by_name) == {MONITOR_QUEUE, MONITOR_RETRY_QUEUE, MONITOR_DEAD_QUEUE}
    assert by_name[MONITOR_QUEUE]["arguments"]["x-dead-letter-routing-key"] == MONITOR_DEAD_QUEUE
    assert by_name[MONITOR_RETRY_QUEUE]["arguments"] == {
        "x-message-ttl": 45000,
        "x-dead-letter-exchange": "",
        "x-dead-letter-routing-key": MONITOR_QUEUE,
    }


def test_price_event_contract_is_json_serializable():
    payload = {"type": "price_snapshot", "snapshot_id": "price_123"}
    assert json.loads(json.dumps(payload))["snapshot_id"] == "price_123"


class ConsumerChannel(FakeChannel):
    def __init__(self, messages):
        super().__init__()
        self.messages = list(messages)
        self.acked = []
        self.nacked = []
        self.published = []

    def basic_qos(self, **_kwargs):
        return None

    def basic_get(self, **_kwargs):
        if not self.messages:
            return None, None, None
        return self.messages.pop(0)

    def basic_ack(self, delivery_tag):
        self.acked.append(delivery_tag)

    def basic_nack(self, delivery_tag, requeue):
        self.nacked.append((delivery_tag, requeue))

    def basic_publish(self, **kwargs):
        self.published.append(kwargs)


def queue_message(tag: int, payload: object, retries: int = 0):
    method = SimpleNamespace(delivery_tag=tag)
    properties = SimpleNamespace(headers={"x-valuesee-retries": retries}, message_id=f"message-{tag}")
    return method, properties, json.dumps(payload).encode("utf-8")


def install_fake_pika(monkeypatch, channel: ConsumerChannel):
    connection = SimpleNamespace(channel=lambda: channel, close=lambda: None)
    module = SimpleNamespace(
        URLParameters=lambda value: value,
        BlockingConnection=lambda _parameters: connection,
        BasicProperties=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setitem(sys.modules, "pika", module)
    monkeypatch.setenv("RABBITMQ_URL", "amqp://test")


def test_consumer_acknowledges_success_and_dead_letters_invalid_payload(monkeypatch):
    channel = ConsumerChannel([
        queue_message(1, {"type": "price_snapshot", "snapshot_id": "snap-ok"}),
        queue_message(2, {"type": "unknown"}),
    ])
    install_fake_pika(monkeypatch, channel)

    handled = []
    result = consume_events(handled.append, limit=10)

    assert handled == [{"type": "price_snapshot", "snapshot_id": "snap-ok"}]
    assert channel.acked == [1]
    assert channel.nacked == [(2, False)]
    assert result == {"consumed": 1, "retried": 0, "dead_lettered": 1}


def test_consumer_retries_transient_failure_then_dead_letters_after_limit(monkeypatch):
    channel = ConsumerChannel([
        queue_message(3, {"type": "price_snapshot", "snapshot_id": "snap-retry"}, retries=1),
        queue_message(4, {"type": "price_snapshot", "snapshot_id": "snap-dead"}, retries=5),
    ])
    install_fake_pika(monkeypatch, channel)
    monkeypatch.setenv("VALUSee_QUEUE_MAX_RETRIES", "5")

    def fail(_payload):
        raise RuntimeError("temporary dependency failure")

    result = consume_events(fail, limit=10)

    assert channel.acked == [3, 4]
    assert [item["routing_key"] for item in channel.published] == [MONITOR_RETRY_QUEUE, MONITOR_DEAD_QUEUE]
    assert channel.published[0]["properties"].headers["x-valuesee-retries"] == 2
    assert result == {"consumed": 0, "retried": 1, "dead_lettered": 1}


def test_worker_heartbeat_is_written_to_configured_path(monkeypatch, tmp_path):
    heartbeat = tmp_path / "worker" / "heartbeat"
    monkeypatch.setenv("VALUSee_WORKER_HEARTBEAT_PATH", str(heartbeat))
    write_heartbeat()
    assert heartbeat.is_file()
