"""Reproducible queue availability/load gate for SCALE-401."""

from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.task_queue import DurableTaskQueue


def run_load_test(tasks: int, p99_target_ms: float) -> tuple[float, int]:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "queue.db"
        queue = DurableTaskQueue(path)
        latencies = []
        for index in range(tasks):
            started = time.perf_counter()
            queue.enqueue("scan", f"tenant-{index}", dedupe_key=f"load-{index}")
            latencies.append((time.perf_counter() - started) * 1_000)
        queue.close()  # simulate the web/scheduler process stopping

        reopened = DurableTaskQueue(path)
        recovered = reopened.counts().get("pending", 0)
        reopened.close()
    p99 = statistics.quantiles(latencies, n=100, method="inclusive")[98]
    if recovered != tasks:
        raise RuntimeError(f"durability objective failed: recovered {recovered}/{tasks}")
    if p99 > p99_target_ms:
        raise RuntimeError(f"dispatch objective failed: p99={p99:.2f}ms")
    return p99, recovered


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=int, default=1_000)
    parser.add_argument("--p99-ms", type=float, default=20)
    args = parser.parse_args()
    p99, recovered = run_load_test(args.tasks, args.p99_ms)
    print(f"PASS tasks={args.tasks} recovered={recovered} enqueue_p99_ms={p99:.2f}")


if __name__ == "__main__":
    main()
