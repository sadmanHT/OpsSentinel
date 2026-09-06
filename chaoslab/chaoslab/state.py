import json
from collections.abc import Iterable

from redis import Redis

from chaoslab.models import FaultSpec, FaultState, FaultType


class FaultStore:
    """Redis-backed fault state shared by the controller and simulator services."""

    def __init__(self, redis_url: str) -> None:
        self.redis = Redis.from_url(redis_url, decode_responses=True)

    @staticmethod
    def _key(service: str, fault: FaultType) -> str:
        return f"chaoslab:fault:{service}:{fault.value}"

    def inject(self, spec: FaultSpec) -> FaultState:
        existing = self.get(spec.service, spec.fault)
        generation = existing.generation + 1 if existing else 1
        state = FaultState(**spec.model_dump(), active=True, generation=generation)
        self.redis.set(self._key(spec.service, spec.fault), state.model_dump_json())
        return state

    def get(self, service: str, fault: FaultType) -> FaultState | None:
        raw = self.redis.get(self._key(service, fault))
        return FaultState.model_validate_json(raw) if raw else None

    def active_for(self, service: str) -> list[FaultState]:
        result: list[FaultState] = []
        for fault in FaultType:
            state = self.get(service, fault)
            if state and state.active:
                result.append(state)
        return result

    def restore(self, service: str, fault: FaultType | None = None) -> int:
        faults: Iterable[FaultType] = [fault] if fault is not None else list(FaultType)
        keys = [self._key(service, item) for item in faults]
        return int(self.redis.delete(*keys)) if keys else 0

    def restore_all(self) -> int:
        keys = list(self.redis.scan_iter(match="chaoslab:fault:*"))
        return int(self.redis.delete(*keys)) if keys else 0

    def list_all(self) -> list[FaultState]:
        states: list[FaultState] = []
        for key in self.redis.scan_iter(match="chaoslab:fault:*"):
            raw = self.redis.get(key)
            if raw:
                states.append(FaultState.model_validate_json(raw))
        return sorted(states, key=lambda item: (item.service, item.fault.value))

    def set_observable(self, service: str, key: str, value: int | float) -> None:
        self.redis.hset(f"chaoslab:observable:{service}", key, json.dumps(value))

    def observables(self, service: str) -> dict[str, int | float]:
        raw = self.redis.hgetall(f"chaoslab:observable:{service}")
        return {key: json.loads(value) for key, value in raw.items()}

    def clear_observables(self, service: str | None = None) -> None:
        if service:
            self.redis.delete(f"chaoslab:observable:{service}")
            return
        keys = list(self.redis.scan_iter(match="chaoslab:observable:*"))
        if keys:
            self.redis.delete(*keys)
