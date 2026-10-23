"""The cap is scalar, so testing the two components separately is unsound."""

from privfuse.experiments.e24_mixed import CAPS, DELTA, _admit, _reference_eps, _stream


def test_scalar_domain_never_exceeds_the_cap() -> None:
    for mix in ("laplace", "gaussian", "mixed"):
        costs = _stream(mix)
        for cap in CAPS:
            admitted = _admit(costs, cap, "scalar")
            assert _reference_eps(admitted) <= cap + 1e-9


def test_component_domain_overspends_on_a_mix() -> None:
    costs = _stream("mixed")
    admitted = _admit(costs, 1.0, "component")
    assert len(admitted) > len(_admit(costs, 1.0, "scalar"))
    assert _reference_eps(admitted) > 1.3
    assert sum(c.eps_pure for c in admitted) <= 1.0 + 1e-12
    assert sum(c.rho for c in admitted) <= (
        (__import__("math").sqrt(__import__("math").log(1.0 / DELTA) + 1.0)
         - __import__("math").sqrt(__import__("math").log(1.0 / DELTA))) ** 2 + 1e-12
    )


def test_pure_and_zcdp_streams_agree_with_the_component_test() -> None:
    for mix in ("laplace", "gaussian"):
        for cap in CAPS:
            assert len(_admit(_stream(mix), cap, "scalar")) == len(
                _admit(_stream(mix), cap, "component")
            )
