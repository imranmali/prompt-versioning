"""Statistics module pinned against reference values (SciPy / closed forms)."""

from __future__ import annotations

import math

import pytest

from promptlab.services import stats


def test_normal_cdf_reference_values() -> None:
    assert stats.normal_cdf(1.96) == pytest.approx(0.9750021048517795, abs=1e-12)
    assert stats.normal_cdf(0.0) == 0.5
    assert stats.normal_cdf(-1.0) == pytest.approx(0.15865525393145707, abs=1e-12)
    assert stats.two_sided_p_from_z(1.96) == pytest.approx(0.04999579029644087, abs=1e-12)
    assert stats.two_sided_p_from_z(-1.96) == stats.two_sided_p_from_z(1.96)


@pytest.mark.parametrize(
    ("p", "expected"),
    [
        (0.975, 1.959963984540054),
        (0.995, 2.5758293035489004),
        (0.5, 0.0),
        (0.01, -2.3263478740408408),  # lower tail region of the approximation
        (0.999, 3.090232306167813),  # upper tail region of the approximation
        (1e-10, -6.361340902404056),
    ],
)
def test_normal_ppf(p: float, expected: float) -> None:
    assert stats.normal_ppf(p) == pytest.approx(expected, abs=1e-9)
    assert stats.normal_cdf(stats.normal_ppf(p)) == pytest.approx(p, rel=1e-9)


@pytest.mark.parametrize("p", [0.0, 1.0, -0.1, 1.5])
def test_normal_ppf_domain(p: float) -> None:
    with pytest.raises(ValueError, match="p must be"):
        stats.normal_ppf(p)


@pytest.mark.parametrize(
    ("t", "df", "expected"),
    [
        (2.0, 10, 0.963305982614630),
        (-1.5, 5, 0.0969518401212337),
        (0.0, 3, 0.5),
        (0.7, 2.5, 0.728297528405226),  # non-integer df (Welch)
        (12.706204736174707, 1, 0.975),
        (-2.042272456301238, 30, 0.025),
    ],
)
def test_student_t_cdf(t: float, df: float, expected: float) -> None:
    assert stats.student_t_cdf(t, df) == pytest.approx(expected, abs=1e-9)


def test_student_t_two_sided_p_matches_cdf() -> None:
    assert stats.student_t_two_sided_p(2.0, 10) == pytest.approx(
        2 * (1 - stats.student_t_cdf(2.0, 10)), abs=1e-12
    )
    # Computed directly from the incomplete beta, so deep tails do not underflow to 0 via 1 - cdf.
    assert 0.0 < stats.student_t_two_sided_p(40.0, 100) < 1e-50
    assert stats.student_t_cdf(40.0, 100) == 1.0


@pytest.mark.parametrize(
    ("p", "df", "expected"),
    [
        (0.975, 10, 2.2281388519649385),
        (0.975, 1, 12.706204736174707),
        (0.025, 30, -2.042272456301238),
        (0.5, 7, 0.0),
        (0.995, 4, 4.604094871415897),
    ],
)
def test_student_t_ppf(p: float, df: float, expected: float) -> None:
    assert stats.student_t_ppf(p, df) == pytest.approx(expected, abs=1e-8)


def test_t_domain_errors() -> None:
    with pytest.raises(ValueError, match="df"):
        stats.student_t_cdf(1.0, 0)
    with pytest.raises(ValueError, match="df"):
        stats.student_t_two_sided_p(1.0, -1)
    with pytest.raises(ValueError, match="df"):
        stats.student_t_ppf(0.9, 0)
    with pytest.raises(ValueError, match="p must be"):
        stats.student_t_ppf(1.0, 3)


@pytest.mark.parametrize(
    ("x", "df", "expected"),
    [
        (3.841459, 1, 0.05),
        (5.991465, 2, 0.05),
        (10.0, 3, 0.01856613546304325),
        (1.0, 3, 0.8012519569012008),  # series branch (x/2 < a + 1)
        (30.0, 10, 0.0008566412107753),
        (0.0, 4, 1.0),
    ],
)
def test_chi_square_sf(x: float, df: float, expected: float) -> None:
    assert stats.chi_square_sf(x, df) == pytest.approx(expected, abs=1e-7)


def test_chi_square_closed_forms() -> None:
    # df=2: sf(x) = exp(-x/2); df=3: erfc(sqrt(x/2)) + sqrt(2x/pi) exp(-x/2)
    for x in (0.5, 2.0, 7.5, 25.0):
        assert stats.chi_square_sf(x, 2) == pytest.approx(math.exp(-x / 2), rel=1e-10)
        closed = math.erfc(math.sqrt(x / 2)) + math.sqrt(2 * x / math.pi) * math.exp(-x / 2)
        assert stats.chi_square_sf(x, 3) == pytest.approx(closed, rel=1e-9)


def test_special_function_domains() -> None:
    assert stats.betainc(2, 3, 0.0) == 0.0
    assert stats.betainc(2, 3, 1.0) == 1.0
    assert stats.betainc(1, 1, 0.3) == pytest.approx(0.3)
    # Both branches of the continued-fraction symmetry.
    assert stats.betainc(2, 3, 0.2) + stats.betainc(3, 2, 0.8) == pytest.approx(1.0)
    assert stats.gammaincc(1, 0) == 1.0
    assert stats.gammaincc(1, 2.0) == pytest.approx(math.exp(-2.0))
    with pytest.raises(ValueError, match="positive"):
        stats.betainc(0, 1, 0.5)
    with pytest.raises(ValueError, match="x must be"):
        stats.betainc(1, 1, 1.5)
    with pytest.raises(ValueError, match="positive"):
        stats.gammaincc(0, 1.0)
    with pytest.raises(ValueError, match="non-negative"):
        stats.gammaincc(1, -1.0)
    with pytest.raises(ValueError, match="df"):
        stats.chi_square_sf(1.0, 0)


def test_wilson_interval() -> None:
    low, high = stats.wilson_interval(50, 100) or (0.0, 0.0)
    assert low == pytest.approx(0.4038315, abs=1e-6)
    assert high == pytest.approx(0.5961685, abs=1e-6)
    low, high = stats.wilson_interval(0, 10) or (1.0, 1.0)
    assert low == 0.0
    assert high == pytest.approx(0.2775328, abs=1e-6)
    low99, high99 = stats.wilson_interval(50, 100, alpha=0.01) or (0.0, 0.0)
    assert low99 < 0.4038315
    assert high99 > 0.5961685
    assert stats.wilson_interval(10, 10) == (pytest.approx(0.7224672, abs=1e-6), 1.0)
    assert stats.wilson_interval(0, 0) is None


def test_two_proportion_z_test() -> None:
    # pooled p = 0.125, se = sqrt(0.125 * 0.875 * 2 / 1000), z = 3.3806
    assert stats.two_proportion_z_test(100, 1000, 150, 1000) == pytest.approx(
        0.000723232716, rel=1e-6
    )
    assert stats.two_proportion_z_test(100, 1000, 100, 1000) == pytest.approx(1.0)
    assert stats.two_proportion_z_test(0, 0, 1, 10) is None
    assert stats.two_proportion_z_test(0, 10, 0, 10) is None  # zero variance


def test_welch_t_test() -> None:
    # Two samples: a = [1, 2, 3, 4], b = [2, 4, 6, 8, 10]
    result = stats.welch_t_test(2.5, 5 / 3, 4, 6.0, 10.0, 5)
    assert result is not None
    assert result.t == pytest.approx(2.2514363, abs=1e-6)
    assert result.df == pytest.approx(5.5207877, abs=1e-6)
    assert result.p_value == pytest.approx(0.0691336, abs=1e-6)
    assert stats.welch_t_test(1.0, 1.0, 1, 2.0, 1.0, 10) is None
    assert stats.welch_t_test(1.0, 0.0, 5, 1.0, 0.0, 5) is None


def test_t_interval() -> None:
    low, high = stats.t_interval(10.0, 2.0, 16) or (0.0, 0.0)
    half = 2.131449545559323 * 2.0 / 4.0
    assert low == pytest.approx(10.0 - half, abs=1e-8)
    assert high == pytest.approx(10.0 + half, abs=1e-8)
    assert stats.t_interval(1.0, 0.0, 1) is None


def test_sample_ratio_test() -> None:
    skewed = stats.sample_ratio_test([1000, 700], [1, 1])
    assert skewed is not None
    assert skewed.chi_square == pytest.approx(52.941176, abs=1e-5)
    assert skewed.p_value < 1e-10
    balanced = stats.sample_ratio_test([1000, 1010], [1, 1])
    assert balanced is not None
    assert balanced.p_value == pytest.approx(0.8234967, abs=1e-6)
    weighted = stats.sample_ratio_test([900, 100], [9, 1])
    assert weighted is not None
    assert weighted.chi_square == pytest.approx(0.0)
    assert weighted.p_value == pytest.approx(1.0)
    assert stats.sample_ratio_test([0, 0], [1, 1]) is None
    with pytest.raises(ValueError, match="same length"):
        stats.sample_ratio_test([1], [1, 1])
