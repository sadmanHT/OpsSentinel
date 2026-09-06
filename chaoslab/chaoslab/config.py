import os
from dataclasses import dataclass


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
