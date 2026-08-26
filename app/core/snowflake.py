import threading
import time


CUSTOM_EPOCH_MS = 1_704_067_200_000  # 2024-01-01 00:00:00 UTC
WORKER_ID_BITS = 10
SEQUENCE_BITS = 12
MAX_WORKER_ID = (1 << WORKER_ID_BITS) - 1
MAX_SEQUENCE = (1 << SEQUENCE_BITS) - 1
WORKER_ID_SHIFT = SEQUENCE_BITS
TIMESTAMP_SHIFT = WORKER_ID_BITS + SEQUENCE_BITS


class SnowflakeGenerator:
    """Thread-safe backend Snowflake ID generator."""

    def __init__(self, worker_id: int = 1):
        if not 0 <= worker_id <= MAX_WORKER_ID:
            raise ValueError(f"worker_id 必须在 0 到 {MAX_WORKER_ID} 之间")
        self.worker_id = worker_id
        self.sequence = 0
        self.last_timestamp = -1
        self.lock = threading.Lock()

    @staticmethod
    def current_timestamp_ms() -> int:
        return time.time_ns() // 1_000_000

    def wait_next_millisecond(self, last_timestamp: int) -> int:
        timestamp = self.current_timestamp_ms()
        while timestamp <= last_timestamp:
            timestamp = self.current_timestamp_ms()
        return timestamp

    def next_id(self) -> int:
        with self.lock:
            timestamp = self.current_timestamp_ms()
            if timestamp < self.last_timestamp:
                raise RuntimeError("系统时钟发生回拨，拒绝生成雪花 ID")

            if timestamp == self.last_timestamp:
                self.sequence = (self.sequence + 1) & MAX_SEQUENCE
                if self.sequence == 0:
                    timestamp = self.wait_next_millisecond(self.last_timestamp)
            else:
                self.sequence = 0

            self.last_timestamp = timestamp
            return (
                ((timestamp - CUSTOM_EPOCH_MS) << TIMESTAMP_SHIFT)
                | (self.worker_id << WORKER_ID_SHIFT)
                | self.sequence
            )


snowflake = SnowflakeGenerator(worker_id=1)


def generate_id() -> int:
    return snowflake.next_id()
