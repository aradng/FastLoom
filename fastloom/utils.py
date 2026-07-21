import random


def exponential_backoff(
    attempt: int,
    base_delay: int,
    max_delay: int,
    jitter: bool = True,
) -> float:
    delay = min(base_delay * 2 ** (attempt - 1), max_delay)
    if jitter:
        delay += random.uniform(-0.1 * delay, 0.1 * delay)
    return delay
