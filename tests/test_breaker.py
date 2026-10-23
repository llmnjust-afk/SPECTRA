from privfuse.control.breaker import BreakerConfig, BreakerController, BreakerLevel


def test_escalation_is_immediate():
    breaker = BreakerController(BreakerConfig())
    assert breaker.update("s", 0.0) is BreakerLevel.NORMAL
    assert breaker.update("s", 0.9) is BreakerLevel.REJECT
    assert breaker.update("s", 1.2) is BreakerLevel.FREEZE


def test_deescalation_requires_dwell():
    config = BreakerConfig(hysteresis=0.05, dwell=3)
    breaker = BreakerController(config)
    breaker.update("s", 0.95)
    assert breaker.state("s").level is BreakerLevel.REJECT
    assert breaker.update("s", 0.1) is BreakerLevel.REJECT
    assert breaker.update("s", 0.1) is BreakerLevel.REJECT
    assert breaker.update("s", 0.1) is BreakerLevel.THROTTLE


def test_hysteresis_prevents_flapping_near_threshold():
    config = BreakerConfig(throttle_ratio=0.6, hysteresis=0.1, dwell=2)
    breaker = BreakerController(config)
    levels = []
    for _ in range(20):
        levels.append(breaker.update("s", 0.61))
        levels.append(breaker.update("s", 0.58))
    assert levels.count(BreakerLevel.NORMAL) <= 2


def test_no_hysteresis_flaps():
    config = BreakerConfig(throttle_ratio=0.6, hysteresis=0.0, dwell=1)
    breaker = BreakerController(config)
    for _ in range(10):
        breaker.update("s", 0.61)
        breaker.update("s", 0.59)
    assert breaker.total_flaps() >= 5
