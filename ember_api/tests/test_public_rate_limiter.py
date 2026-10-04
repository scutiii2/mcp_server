from __future__ import annotations

from src.services.public_rate_limiter import PublicReadLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def limiter(max_requests: int = 3, window: float = 10.0, **kwargs) -> tuple[PublicReadLimiter, Clock]:
    clock = Clock()
    return PublicReadLimiter(max_requests, window, clock=clock, **kwargs), clock


def test_allows_up_to_the_limit_then_says_how_long_to_wait() -> None:
    limit, clock = limiter()

    assert [limit.retry_after("1.1.1.1") for _ in range(3)] == [None, None, None]
    assert limit.retry_after("1.1.1.1") == 10

    clock.now += 4
    assert limit.retry_after("1.1.1.1") == 6


def test_the_window_slides() -> None:
    limit, clock = limiter()
    limit.retry_after("a")
    clock.now += 6
    limit.retry_after("a")
    limit.retry_after("a")
    assert limit.retry_after("a") == 4  # the first hit leaves the window in 4 s

    clock.now += 4
    assert limit.retry_after("a") is None


def test_each_address_has_its_own_budget() -> None:
    limit, _ = limiter(max_requests=1)

    assert limit.retry_after("a") is None
    assert limit.retry_after("b") is None
    assert limit.retry_after("a") is not None


def test_refused_requests_do_not_extend_the_wait() -> None:
    limit, clock = limiter(max_requests=1, window=10)
    limit.retry_after("a")

    for _ in range(50):
        clock.now += 0.1
        assert limit.retry_after("a") is not None
    clock.now += 5.1  # 10 s after the one accepted request

    assert limit.retry_after("a") is None


def test_the_wait_is_never_below_a_second() -> None:
    limit, clock = limiter(max_requests=1, window=10)
    limit.retry_after("a")
    clock.now += 9.999

    assert limit.retry_after("a") == 1


def test_the_table_stays_bounded_and_forgets_idle_addresses_first() -> None:
    limit, clock = limiter(max_requests=5, window=10, max_tracked_ips=3)
    for ip in ("a", "b", "c"):
        limit.retry_after(ip)
    clock.now += 11  # all three are idle now
    limit.retry_after("d")
    assert set(limit._hits) == {"d"}

    limit.retry_after("e")
    limit.retry_after("f")
    limit.retry_after("g")  # over the cap with nobody idle: the oldest goes
    assert len(limit._hits) == 3
    assert "d" not in limit._hits
    assert {"e", "f", "g"} == set(limit._hits)
