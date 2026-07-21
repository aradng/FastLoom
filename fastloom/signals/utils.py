import random


def backoff_delay(attempt: int, base_delay: int, max_delay: int) -> int:
    return min(base_delay * 2 ** (attempt - 1), max_delay)


def with_jitter(delay: float, spread: float = 0.1) -> float:
    return delay + random.uniform(-spread * delay, spread * delay)
