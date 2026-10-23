import math

import pytest

from privfuse.dp.cost import CostVector, sum_costs
from privfuse.dp.mechanisms import gaussian_cost, gaussian_sigma, zcdp_rho


def test_zcdp_rho_inverts_conversion():
    eps, delta = 0.4, 1e-5
    rho = zcdp_rho(eps, delta)
    recovered = rho + 2.0 * math.sqrt(rho * math.log(1.0 / delta))
    assert recovered == pytest.approx(eps, rel=1e-9)


def test_gaussian_cost_reports_requested_epsilon():
    for eps in (0.01, 0.05, 0.2, 1.0):
        cost = gaussian_cost(eps, 1e-5, 1.0)
        assert cost.eps(1e-5) == pytest.approx(eps, rel=1e-6)


def test_sigma_shrinks_as_epsilon_grows():
    assert gaussian_sigma(0.01, 1e-5, 1.0) > gaussian_sigma(0.1, 1e-5, 1.0)


def test_composition_is_sublinear_for_gaussians():
    single = gaussian_cost(0.02, 1e-5, 1.0)
    hundred = single.scale(100)
    assert hundred.eps(1e-5) < 100 * single.eps(1e-5)
    assert hundred.eps(1e-5) > single.eps(1e-5)


def test_mixing_pure_and_concentrated_keeps_the_pure_part():
    gauss = gaussian_cost(0.1, 1e-5, 1.0)
    laplace = CostVector.from_laplace(scale=10.0, sensitivity=1.0)
    mixed = gauss + laplace
    assert mixed.eps_pure == pytest.approx(0.1)
    assert mixed.eps(1e-5) >= 0.1


def test_zero_and_scale():
    zero = CostVector.zero()
    assert zero.is_zero()
    assert sum_costs([]).is_zero()
    assert CostVector(eps_pure=1.0, rho=1.0).scale(0.5).eps_pure == 0.5


def test_negative_cost_rejected():
    with pytest.raises(ValueError):
        CostVector(eps_pure=-1.0)
    with pytest.raises(ValueError):
        CostVector(eps_pure=1.0, rho=-1.0)


def test_dominates():
    small = gaussian_cost(0.1, 1e-5, 1.0)
    large = gaussian_cost(0.2, 1e-5, 1.0)
    assert large.dominates(small)
    assert not small.dominates(large)
