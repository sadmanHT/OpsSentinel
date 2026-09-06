from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RuntimeState:
    request_count: int = 0
    error_count: int = 0
    last_latency_ms: float = 0.0
    db_query_count_last_request: int = 0
    simulated_db_connections: int = 0
    memory_chunks: list[bytes] = field(default_factory=list)
    simulated_restarts: int = 0
    disk_files: list[Path] = field(default_factory=list)

    @property
    def simulated_memory_leak_bytes(self) -> int:
        return sum(len(chunk) for chunk in self.memory_chunks)

    def reset_fault_artifacts(self) -> None:
        self.simulated_db_connections = 0
        self.memory_chunks.clear()
        for path in self.disk_files:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        self.disk_files.clear()
