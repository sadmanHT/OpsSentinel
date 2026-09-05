import asyncio
import random
from pathlib import Path

from fastapi import HTTPException

from chaoslab.models import FaultState, FaultType, Severity
from chaoslab.runtime import RuntimeState

SEVERITY_SCALE = {Severity.P1: 1.0, Severity.P2: 0.7, Severity.P3: 0.45}


def deterministic_rng(state: FaultState, request_count: int) -> random.Random:
    return random.Random(f"{state.seed}:{state.generation}:{request_count}:{state.service}")


async def apply_pre_request_faults(
    faults: list[FaultState],
    runtime: RuntimeState,
    disk_dir: str,
) -> None:
    for fault in faults:
        scale = SEVERITY_SCALE[fault.severity]
        if fault.fault == FaultType.CONNECTION_LEAK:
            runtime.simulated_db_connections += 1
            capacity = int(fault.configuration.get("capacity", 8))
            if runtime.simulated_db_connections >= capacity:
                await asyncio.sleep(0.05)
                raise HTTPException(status_code=503, detail="database connection pool timeout")
        elif fault.fault == FaultType.DISK_EXHAUSTION:
            root = Path(disk_dir)
            root.mkdir(parents=True, exist_ok=True)
            max_files = int(fault.configuration.get("max_files", 10))
            if len(runtime.disk_files) < max_files:
                path = root / f"debug-{fault.generation}-{len(runtime.disk_files)}.log"
                path.write_bytes(b"x" * 32_768)
                runtime.disk_files.append(path)
            if len(runtime.disk_files) >= max(2, int(max_files * scale)):
                raise HTTPException(status_code=507, detail="simulated no space left on device")
        elif fault.fault == FaultType.MEMORY_LEAK:
            chunk_size = int(fault.configuration.get("chunk_bytes", 262_144))
            max_bytes = int(fault.configuration.get("max_bytes", 4_194_304))
            if runtime.simulated_memory_leak_bytes < max_bytes:
                runtime.memory_chunks.append(b"m" * min(chunk_size, max_bytes))
            threshold = max(1_048_576, int(max_bytes * scale))
            if runtime.simulated_memory_leak_bytes >= threshold:
                runtime.simulated_restarts += 1
                runtime.memory_chunks.clear()
                raise HTTPException(
                    status_code=503,
                    detail="simulated process restart after memory pressure",
                )
        elif fault.fault == FaultType.BROKEN_CONFIG and fault.service == "payment":
            raise HTTPException(status_code=401, detail="downstream authentication rejected")


def disk_usage_ratio(faults: list[FaultState], runtime: RuntimeState) -> float:
    for fault in faults:
        if fault.fault == FaultType.DISK_EXHAUSTION:
            max_files = max(1, int(fault.configuration.get("max_files", 10)))
            return min(1.0, len(runtime.disk_files) / max_files)
    return 0.0
