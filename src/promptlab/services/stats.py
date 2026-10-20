"""Pure-Python statistics for experiment analysis (no SciPy).

Every function returns ``None`` instead of NaN/inf when a statistic is undefined (no samples,
zero variance, ...), so callers can pass the values straight to JSON.

Implementations:

* normal CDF through :func:`math.erfc`; inverse normal CDF with Acklam's rational approximation
  refined by one Halley step (accurate to ~1e-15);
* Student's t CDF through the regularized incomplete beta function, evaluated with the modified
  Lentz continued fraction (Numerical Recipes ``betacf``); its inverse by bisection;
* chi-square survival function through the regularized upper incomplete gamma function
  (series expansion below ``a + 1``, continued fraction above).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

_EPS = 1e-15
_TINY = 1e-300
_MAX_ITERATIONS = 500
_SQRT2 = math.sqrt(2.0)


# --------------------------------------------------------------------------------------------
# Normal distribution
# --------------------------------------------------------------------------------------------


def normal_cdf(x: float) -> float:
    """Standard normal cumulative distribution function Φ(x)."""
    return 0.5 * math.erfc(-x / _SQRT2)


def two_sided_p_from_z(z: float) -> float:
    """Two-sided p-value ``P(|Z| >= |z|)`` of a standard normal statistic."""
    return math.erfc(abs(z) / _SQRT2)


# Coefficients of Acklam's rational approximation of the inverse normal CDF.
_A = (
    -3.969683028665376e01,
    2.209460984245205e02,
    -2.759285104469687e02,
    1.383577518672690e02,
    -3.066479806614716e01,
    2.506628277459239e00,
)
_B = (
    -5.447609879822406e01,
    1.615858368580409e02,
    -1.556989798598866e02,
    6.680131188771972e01,
    -1.328068155288572e01,
)
_C = (
    -7.784894002430293e-03,
    -3.223964580411365e-01,
    -2.400758277161838e00,
    -2.549732539343734e00,
    4.374664141464968e00,
    2.938163982698783e00,
)
_D = (
    7.784695709041462e-03,
    3.224671290700398e-01,
    2.445134137142996e00,
    3.754408661907416e00,
)
_P_LOW = 0.02425


def normal_ppf(p: float) -> float:
    """Inverse of :func:`normal_cdf` for ``0 < p < 1``."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    if p < _P_LOW:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / (
            (((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0
        )
    elif p <= 1.0 - _P_LOW:
        q = p - 0.5
        r = q * q
        x = (
            (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5])
            * q
            / (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1.0)
        )
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / (
            (((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0
        )
    # One step of Halley's method brings the relative error to machine precision.
    e = normal_cdf(x) - p
    u = e * math.sqrt(2.0 * math.pi) * math.exp(x * x / 2.0)
    return x - u / (1.0 + x * u / 2.0)


# --------------------------------------------------------------------------------------------
# Special functions
# --------------------------------------------------------------------------------------------


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (modified Lentz's method)."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _TINY:
        d = _TINY
    d = 1.0 / d
    h = d
    for m in range(1, _MAX_ITERATIONS + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < _TINY:
            d = _TINY
        c = 1.0 + aa / c
        if abs(c) < _TINY:
            c = _TINY
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < _TINY:
            d = _TINY
        c = 1.0 + aa / c
        if abs(c) < _TINY:
            c = _TINY
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function ``I_x(a, b)`` for ``a, b > 0`` and ``0 <= x <= 1``."""
    if a <= 0 or b <= 0:
        raise ValueError("a and b must be positive")
    if not 0.0 <= x <= 1.0:
        raise ValueError("x must be in [0, 1]")
    if x in (0.0, 1.0):
        return x
    log_front = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    )
    front = math.exp(log_front)
    # The continued fraction converges rapidly for x < (a + 1) / (a + b + 2); use the symmetry
    # I_x(a, b) = 1 - I_{1-x}(b, a) otherwise.
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def gammaincc(a: float, x: float) -> float:
    """Regularized upper incomplete gamma function ``Q(a, x)`` for ``a > 0`` and ``x >= 0``."""
    if a <= 0:
        raise ValueError("a must be positive")
    if x < 0:
        raise ValueError("x must be non-negative")
    if x == 0:
        return 1.0
    log_front = -x + a * math.log(x) - math.lgamma(a)
    if x < a + 1.0:
        # Series for the lower function P(a, x); Q = 1 - P.
        term = 1.0 / a
        total = term
        ap = a
        for _ in range(_MAX_ITERATIONS):
            ap += 1.0
            term *= x / ap
            total += term
            if abs(term) < abs(total) * _EPS:
                break
        return max(0.0, 1.0 - total * math.exp(log_front))
    # Continued fraction for Q(a, x) (modified Lentz's method).
    b = x + 1.0 - a
    c = 1.0 / _TINY
    d = 1.0 / b
    h = d
    for i in range(1, _MAX_ITERATIONS + 1):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < _TINY:
            d = _TINY
        c = b + an / c
        if abs(c) < _TINY:
            c = _TINY
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return math.exp(log_front) * h


# --------------------------------------------------------------------------------------------
# Student's t and chi-square distributions
# --------------------------------------------------------------------------------------------


def student_t_cdf(t: float, df: float) -> float:
    """Cumulative distribution function of Student's t with ``df`` degrees of freedom."""
    if df <= 0:
        raise ValueError("df must be positive")
    tail = 0.5 * betainc(df / 2.0, 0.5, df / (df + t * t))
    return 1.0 - tail if t > 0 else tail


def student_t_two_sided_p(t: float, df: float) -> float:
    """Two-sided p-value ``P(|T| >= |t|)`` (computed directly to keep tail precision)."""
    if df <= 0:
        raise ValueError("df must be positive")
    return betainc(df / 2.0, 0.5, df / (df + t * t))


def student_t_ppf(p: float, df: float) -> float:
    """Inverse of :func:`student_t_cdf` for ``0 < p < 1``, by bisection."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    if df <= 0:
        raise ValueError("df must be positive")
    if p == 0.5:
        return 0.0
    if p < 0.5:
        return -student_t_ppf(1.0 - p, df)
    lo, hi = 0.0, 1.0
    while student_t_cdf(hi, df) < p:
        lo, hi = hi, hi * 2.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if student_t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo <= 1e-12 * max(1.0, hi):
            break
    return (lo + hi) / 2.0


def chi_square_sf(x: float, df: float) -> float:
    """Survival function ``P(X >= x)`` of the chi-square distribution."""
    if df <= 0:
        raise ValueError("df must be positive")
    if x <= 0:
        return 1.0
    return gammaincc(df / 2.0, x / 2.0)


# --------------------------------------------------------------------------------------------
# Tests and intervals used by experiment results
# --------------------------------------------------------------------------------------------


def wilson_interval(successes: int, n: int, alpha: float = 0.05) -> tuple[float, float] | None:
    """Wilson score interval for a binomial proportion at confidence ``1 - alpha``."""
    if n <= 0:
        return None
    z = normal_ppf(1.0 - alpha / 2.0)
    p = successes / n
    z2 = z * z
    denominator = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denominator
    half_width = z * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n)) / denominator
    # The exact bounds at 0 and n are 0 and 1; avoid rounding residue such as 2.8e-17.
    low = 0.0 if successes <= 0 else max(0.0, center - half_width)
    high = 1.0 if successes >= n else min(1.0, center + half_width)
    return low, high


def two_proportion_z_test(successes_a: int, n_a: int, successes_b: int, n_b: int) -> float | None:
    """Two-sided p-value of the pooled two-proportion z-test (``None`` when undefined)."""
    if n_a <= 0 or n_b <= 0:
        return None
    pooled = (successes_a + successes_b) / (n_a + n_b)
    variance = pooled * (1.0 - pooled) * (1.0 / n_a + 1.0 / n_b)
    if variance <= 0:
        return None
    z = (successes_b / n_b - successes_a / n_a) / math.sqrt(variance)
    return two_sided_p_from_z(z)


@dataclass(frozen=True, slots=True)
class WelchResult:
    t: float
    df: float
    p_value: float


def welch_t_test(
    mean_a: float, var_a: float, n_a: int, mean_b: float, var_b: float, n_b: int
) -> WelchResult | None:
    """Welch's unequal-variances t-test of ``b`` vs ``a`` with Welch-Satterthwaite df."""
    if n_a < 2 or n_b < 2:
        return None
    se_a = var_a / n_a
    se_b = var_b / n_b
    se2 = se_a + se_b
    if se2 <= 0:
        return None
    t = (mean_b - mean_a) / math.sqrt(se2)
    df = se2 * se2 / (se_a * se_a / (n_a - 1) + se_b * se_b / (n_b - 1))
    return WelchResult(t=t, df=df, p_value=student_t_two_sided_p(t, df))


def t_interval(mean: float, std: float, n: int, alpha: float = 0.05) -> tuple[float, float] | None:
    """Confidence interval ``mean ± t_{1-alpha/2, n-1} · std / sqrt(n)`` for a sample mean."""
    if n < 2:
        return None
    half_width = student_t_ppf(1.0 - alpha / 2.0, n - 1) * std / math.sqrt(n)
    return mean - half_width, mean + half_width


@dataclass(frozen=True, slots=True)
class ChiSquareResult:
    chi_square: float
    p_value: float


def sample_ratio_test(observed: Sequence[int], weights: Sequence[int]) -> ChiSquareResult | None:
    """Pearson chi-square goodness of fit of ``observed`` counts against ``weights``."""
    if len(observed) != len(weights):
        raise ValueError("observed and weights must have the same length")
    total = sum(observed)
    total_weight = sum(weights)
    if total <= 0 or total_weight <= 0 or len(observed) < 2:
        return None
    chi_square = 0.0
    for count, weight in zip(observed, weights, strict=True):
        expected = total * weight / total_weight
        chi_square += (count - expected) ** 2 / expected
    return ChiSquareResult(
        chi_square=chi_square, p_value=chi_square_sf(chi_square, len(observed) - 1)
    )
