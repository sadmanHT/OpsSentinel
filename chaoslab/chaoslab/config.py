import os
from dataclasses import dataclass


def _env_flag(name: str, default: bool = False) -> bool:
    fallback = "true" if default else "false"
    return os.getenv(name, fallback).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ChaosConfig:
    service_name: str = os.getenv("CHAOSLAB_SERVICE_NAME", "checkout")
    redis_url: str = os.getenv("CHAOSLAB_REDIS_URL", "redis://redis:6379/1")
    database_url: str = os.getenv(
        "CHAOSLAB_DATABASE_URL",
        "postgresql://opssentinel:opssentinel@postgres:5432/opssentinel",
    )
    seed: int = int(os.getenv("CHAOSLAB_SEED", "42"))
    disk_dir: str = os.getenv("CHAOSLAB_DISK_DIR", "/tmp/opssentinel-chaos")
    checkout_url: str = os.getenv("CHAOSLAB_CHECKOUT_URL", "http://checkout:8080")
    inventory_url: str = os.getenv("CHAOSLAB_INVENTORY_URL", "http://inventory:8080")
    payment_url: str = os.getenv("CHAOSLAB_PAYMENT_URL", "http://payment:8080")
    otel_enabled: bool = _env_flag("CHAOSLAB_OTEL_ENABLED")
    otel_exporter_otlp_endpoint: str = os.getenv(
        "CHAOSLAB_OTEL_EXPORTER_OTLP_ENDPOINT",
        "http://localhost:4318",
    )

    @property
    def otel_service_name(self) -> str:
        return f"chaoslab-{self.service_name}"
