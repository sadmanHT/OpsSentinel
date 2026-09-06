from collections.abc import Iterator

from chaoslab.models import FaultSpec, FaultType, Severity
from chaoslab.state import FaultStore


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self.values:
                del self.values[key]
                removed += 1
            if key in self.hashes:
                del self.hashes[key]
                removed += 1
        return removed

    def scan_iter(self, match: str) -> Iterator[str]:
        prefix = match.removesuffix("*")
        for key in sorted({*self.values, *self.hashes}):
            if key.startswith(prefix):
                yield key

    def hset(self, key: str, field: str, value: str) -> None:
        self.hashes.setdefault(key, {})[field] = value

    def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))


def make_store() -> FaultStore:
    store = FaultStore("redis://unused")
    store.redis = FakeRedis()  # type: ignore[assignment]
    return store


def test_inject_twice_increments_generation_and_replaces_state() -> None:
    store = make_store()
    spec = FaultSpec(
        fault=FaultType.N_PLUS_ONE,
        service="checkout",
        severity=Severity.P1,
        seed=17,
        configuration={"delay_per_query_ms": 3},
    )

    first = store.inject(spec)
    second = store.inject(spec)

    assert first.generation == 1
    assert second.generation == 2
    assert store.get("checkout", FaultType.N_PLUS_ONE) == second
    assert store.list_all() == [second]


def test_restore_non_active_fault_is_safe_and_idempotent() -> None:
    store = make_store()

    assert store.restore("checkout", FaultType.N_PLUS_ONE) == 0

    store.inject(FaultSpec(fault=FaultType.N_PLUS_ONE, service="checkout"))
    assert store.restore("checkout", FaultType.N_PLUS_ONE) == 1
    assert store.restore("checkout", FaultType.N_PLUS_ONE) == 0


def test_restore_all_and_observable_cleanup() -> None:
    store = make_store()
    store.inject(FaultSpec(fault=FaultType.N_PLUS_ONE, service="checkout"))
    store.inject(FaultSpec(fault=FaultType.MEMORY_LEAK, service="worker"))
    store.set_observable("checkout", "latency_ms", 125.5)

    assert store.observables("checkout") == {"latency_ms": 125.5}
    assert store.restore_all() == 2
    assert store.list_all() == []

    store.clear_observables("checkout")
    assert store.observables("checkout") == {}
