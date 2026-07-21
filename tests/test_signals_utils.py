from fastloom.signals.utils import exponential_backoff


def test_exponential_backoff_doubles_across_several_attempts():
    delays = [
        exponential_backoff(attempt, base_delay=1, max_delay=100, jitter=False)
        for attempt in range(1, 6)
    ]

    assert delays == [1, 2, 4, 8, 16]


def test_exponential_backoff_caps_at_max_delay():
    delays = [
        exponential_backoff(attempt, base_delay=1, max_delay=8, jitter=False)
        for attempt in range(1, 8)
    ]

    assert delays == [1, 2, 4, 8, 8, 8, 8]
