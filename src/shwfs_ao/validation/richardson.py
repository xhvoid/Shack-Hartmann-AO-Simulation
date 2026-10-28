"""Richardson analysis of a refinement scan (T2, section 5 of the design note).

For a declared refinement parameter ``h`` and a scalar metric ``Q`` the model
is ``Q(h) = Q0 + C h**p``.  With three settings ``h1 > h2 > h3`` (coarse to
fine), ratios ``r21 = h1/h2`` and ``r32 = h2/h3`` and differences
``e21 = Q2 - Q1``, ``e32 = Q3 - Q2``, the observed order solves

    e21 / e32 = r32**p (r21**p - 1) / (r32**p - 1),

(``p = ln(e21/e32) / ln r`` for equal ratios) and the extrapolated limit is
``Q0 = Q3 + e32 / (r32**p - 1)``.  The left side is increasing in ``p`` and
tends to ``ln r21 / ln r32`` as ``p -> 0``, so a finite positive order exists
only when the difference ratio exceeds that limit (the differences shrink
with refinement).

An observed order is reported only when every value is finite, both
differences are nonzero and of one sign, each difference is resolved against
its uncertainty (``|e| > z * SE(e)`` with ``SE(e) = sqrt(s_i**2 + s_j**2)``
from the settings' standard errors; without uncertainties the comparison is
against zero and the result is flagged), the ratio exceeds its ``p -> 0``
limit, and the root lies in ``order_bounds``.  Otherwise the status is
``NOT_ESTIMATED`` with a reason.  Two settings give a change table and no
order.  An *assumed* order gives a labelled extrapolation of its own from the
two finest settings; it is never mixed with the observed one.  A Gauss
quadrature node count is not a power-law refinement parameter: callers
declare ``power_law=False`` for such an axis and only the change table is
produced.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math
from numbers import Real
from typing import Any

from scipy import optimize


__all__ = (
    "RichardsonError",
    "RichardsonResult",
    "change_table",
    "richardson_estimate",
)

NOT_ESTIMATED = "NOT_ESTIMATED"
# Refinement ratios closer to one than exp(1e-6) - 1 cannot resolve an order from
# double-precision differences (review 2026-10-21, T2-04); such scans are refused.
MINIMUM_LOG_REFINEMENT_RATIO = 1.0e-6
ESTIMATED = "ESTIMATED"


class RichardsonError(ValueError):
    """Raised for malformed refinement data (not for an unestimable order)."""


@dataclass(frozen=True)
class RichardsonResult:
    """The outcome of :func:`richardson_estimate`; ``to_record`` is JSON-ready."""

    status: str
    reason: str | None
    refinement_parameters: tuple[float, ...]
    values: tuple[float, ...]
    uncertainties: tuple[float | None, ...]
    uncertainty_available: bool
    differences: tuple[float, ...]
    difference_uncertainties: tuple[float | None, ...]
    refinement_ratios: tuple[float, ...]
    observed_order: float | None
    extrapolated_limit: float | None
    extrapolation_error_estimate: float | None
    gci_fine_relative: float | None
    assumed_order: float | None
    assumed_order_limit: float | None
    assumed_order_error_estimate: float | None
    power_law_declared: bool

    def to_record(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "order_source": None if self.observed_order is None else "observed",
            "model": "Q(h) = Q0 + C h**p; order from the three finest settings, Celik et al. 2008 eqs. (3a)-(3c)",
            "refinement_parameters": list(self.refinement_parameters),
            "values": list(self.values),
            "uncertainties": list(self.uncertainties),
            "uncertainty_available": self.uncertainty_available,
            "differences_fine_minus_coarse": list(self.differences),
            "difference_uncertainties": list(self.difference_uncertainties),
            "refinement_ratios": list(self.refinement_ratios),
            "observed_order": self.observed_order,
            "extrapolated_limit": self.extrapolated_limit,
            "extrapolation_error_estimate_finest": self.extrapolation_error_estimate,
            # Celik et al. 2008 eq. (7): the fine-grid convergence index with the
            # safety factor 1.25, relative to the finest value.
            "gci_fine_relative": self.gci_fine_relative,
            "assumed_order": self.assumed_order,
            "assumed_order_limit": self.assumed_order_limit,
            "assumed_order_error_estimate_finest": self.assumed_order_error_estimate,
            "power_law_declared": self.power_law_declared,
        }


def _finite_sequence(values: Sequence[object], *, label: str, allow_none: bool = False) -> list[float | None]:
    out: list[float | None] = []
    for index, value in enumerate(values):
        if value is None and allow_none:
            out.append(None)
            continue
        if isinstance(value, bool) or not isinstance(value, Real):
            raise RichardsonError(f"{label}[{index}] must be a real number.")
        out.append(float(value))
    return out


def _sorted_scan(
    refinement: Sequence[float], values: Sequence[float], uncertainties: Sequence[float | None] | None
) -> tuple[list[float], list[float], list[float | None]]:
    h = [float(v) for v in _finite_sequence(refinement, label="refinement_parameters") if v is not None]
    if len(h) != len(values):
        raise RichardsonError("refinement_parameters and values must have the same length.")
    if any(not math.isfinite(v) or v <= 0.0 for v in h):
        raise RichardsonError("refinement parameters must be positive and finite.")
    if len(set(h)) != len(h):
        raise RichardsonError("refinement parameters must be distinct.")
    q_raw = _finite_sequence(values, label="values")
    q = [float("nan") if v is None else v for v in q_raw]
    if uncertainties is None:
        s: list[float | None] = [None] * len(h)
    else:
        if len(uncertainties) != len(h):
            raise RichardsonError("uncertainties must have the same length as values.")
        s = _finite_sequence(uncertainties, label="uncertainties", allow_none=True)
        for value in s:
            if value is not None and (not math.isfinite(value) or value < 0.0):
                raise RichardsonError("uncertainties must be finite and non-negative.")
    order = sorted(range(len(h)), key=lambda i: -h[i])  # coarse to fine
    return [h[i] for i in order], [q[i] for i in order], [s[i] for i in order]


def change_table(
    refinement_parameters: Sequence[float],
    values: Sequence[float],
    *,
    uncertainties: Sequence[float | None] | None = None,
) -> dict[str, Any]:
    """Adjacent changes of a scan, coarse to fine: difference, relative change, uncertainty."""

    h, q, s = _sorted_scan(refinement_parameters, values, uncertainties)
    rows = []
    for i in range(len(h) - 1):
        difference = q[i + 1] - q[i]
        left, right = s[i], s[i + 1]
        se = None if left is None or right is None else math.hypot(left, right)
        reference = abs(q[i + 1])
        rows.append(
            {
                "from_h": h[i],
                "to_h": h[i + 1],
                "ratio": h[i] / h[i + 1],
                "difference_fine_minus_coarse": difference,
                "relative_change": None if reference == 0.0 or not math.isfinite(reference) else difference / reference,
                "difference_uncertainty": se,
                "resolved_2se": None if se is None else (abs(difference) > 2.0 * se),
            }
        )
    return {"ordering": "coarse_to_fine", "refinement_parameters": h, "values": q, "uncertainties": s, "changes": rows}


def _assumed_extrapolation(h: list[float], q: list[float], order: float) -> tuple[float, float] | None:
    if len(h) < 2 or not all(math.isfinite(v) for v in q[-2:]):
        return None
    ratio = h[-2] / h[-1]
    factor = ratio**order - 1.0
    if factor <= 0.0:
        return None
    limit = q[-1] + (q[-1] - q[-2]) / factor
    return limit, abs(q[-1] - limit)


def richardson_estimate(
    refinement_parameters: Sequence[float],
    values: Sequence[float],
    *,
    uncertainties: Sequence[float | None] | None = None,
    assumed_order: float | None = None,
    power_law: bool = True,
    resolution_z: float = 2.0,
    order_bounds: tuple[float, float] = (0.1, 8.0),
) -> RichardsonResult:
    """Observed order and extrapolated limit of a scan, or ``NOT_ESTIMATED`` with a reason."""

    if isinstance(resolution_z, bool) or not isinstance(resolution_z, Real) or resolution_z <= 0.0:
        raise RichardsonError("resolution_z must be positive.")
    low_bound, high_bound = (float(order_bounds[0]), float(order_bounds[1]))
    if not 0.0 < low_bound < high_bound:
        raise RichardsonError("order_bounds must satisfy 0 < low < high.")
    if assumed_order is not None and (
        isinstance(assumed_order, bool) or not isinstance(assumed_order, Real) or float(assumed_order) <= 0.0
    ):
        raise RichardsonError("assumed_order must be positive or None.")
    h, q, s = _sorted_scan(refinement_parameters, values, uncertainties)
    differences = tuple(q[i + 1] - q[i] for i in range(len(h) - 1))
    difference_se = tuple(
        None if s[i] is None or s[i + 1] is None else math.hypot(s[i], s[i + 1]) for i in range(len(h) - 1)
    )
    ratios = tuple(h[i] / h[i + 1] for i in range(len(h) - 1))
    uncertainty_available = all(value is not None for value in s) and len(s) > 0
    assumed_limit: float | None = None
    assumed_error: float | None = None
    if assumed_order is not None and power_law:
        extrapolated = _assumed_extrapolation(h, q, float(assumed_order))
        if extrapolated is not None:
            assumed_limit, assumed_error = extrapolated

    def result(
        status: str,
        reason: str | None,
        order: float | None = None,
        limit: float | None = None,
        error: float | None = None,
        gci: float | None = None,
    ) -> RichardsonResult:
        return RichardsonResult(
            status=status,
            reason=reason,
            refinement_parameters=tuple(h),
            values=tuple(q),
            uncertainties=tuple(s),
            uncertainty_available=uncertainty_available,
            differences=differences,
            difference_uncertainties=difference_se,
            refinement_ratios=ratios,
            observed_order=order,
            extrapolated_limit=limit,
            extrapolation_error_estimate=error,
            gci_fine_relative=gci,
            assumed_order=None if assumed_order is None else float(assumed_order),
            assumed_order_limit=assumed_limit,
            assumed_order_error_estimate=assumed_error,
            power_law_declared=bool(power_law),
        )

    if not power_law:
        return result(NOT_ESTIMATED, "no power-law refinement declared for this axis (Gauss quadrature nodes converge geometrically); change table only")
    if len(h) < 3:
        return result(NOT_ESTIMATED, "fewer than three settings; change table only")
    if not all(math.isfinite(v) for v in q):
        return result(NOT_ESTIMATED, "nonfinite metric value")
    # The two finest adjacent differences decide the order (three finest settings).
    e21, e32 = differences[-2], differences[-1]
    r21, r32 = ratios[-2], ratios[-1]
    se21, se32 = difference_se[-2], difference_se[-1]
    if e21 == 0.0 or e32 == 0.0:
        return result(NOT_ESTIMATED, "flat: a difference between adjacent settings is exactly zero")
    if (e21 > 0.0) != (e32 > 0.0):
        return result(NOT_ESTIMATED, "oscillatory: adjacent differences have opposite signs")
    for e, se in ((e21, se21), (e32, se32)):
        if se is not None and abs(e) <= resolution_z * se:
            return result(NOT_ESTIMATED, f"uncertainty-dominated: a difference is within {resolution_z:g} standard errors of zero")
    ratio = e21 / e32
    # A finite positive order exists only above the zero-order limit of the ratio
    # equation, ln r21 / ln r32: one for equal ratios, below one when the ratios
    # decrease towards the fine end (a difference ratio below one is then still a
    # positive order), above one when they increase.
    log_r21, log_r32 = math.log(r21), math.log(r32)
    if min(log_r21, log_r32) < MINIMUM_LOG_REFINEMENT_RATIO:
        return result(
            NOT_ESTIMATED,
            "ill-conditioned: a refinement ratio within "
            f"{math.expm1(MINIMUM_LOG_REFINEMENT_RATIO):.1e} of one cannot resolve an order",
        )
    limit_at_zero = log_r21 / log_r32
    if ratio <= limit_at_zero * (1.0 + 1.0e-9):
        return result(
            NOT_ESTIMATED,
            f"non-shrinking differences: the difference ratio {ratio:.6g} does not exceed its "
            f"zero-order limit {limit_at_zero:.6g} for refinement ratios ({r21:.6g}, {r32:.6g}) "
            "(zero or negative order)",
        )

    def residual(p: float) -> float:
        # ``r**p - 1`` as ``expm1(p ln r)``: no cancellation for ratios close to
        # one, so an endpoint residual near zero means a root, not lost digits.
        return math.exp(p * log_r32) * math.expm1(p * log_r21) / math.expm1(p * log_r32) - ratio

    low, high = residual(low_bound), residual(high_bound)
    # An exact root at an admitted bound is a solution, not an excursion beyond
    # the range: accept it (to rounding of the residual) before requiring a
    # strict bracket.
    endpoint_tolerance = 1.0e-12 * max(1.0, abs(ratio))
    if abs(low) <= endpoint_tolerance:
        order = float(low_bound)
    elif abs(high) <= endpoint_tolerance:
        order = float(high_bound)
    elif not (low < 0.0 < high):
        # The residual increases with p: both positive puts the root below
        # the range, both negative above it.
        where = "below" if low > 0.0 else "above"
        return result(NOT_ESTIMATED, f"ill-conditioned: the observed order lies {where} the admitted range {order_bounds}")
    else:
        try:
            order = float(optimize.brentq(residual, low_bound, high_bound, xtol=1.0e-12, maxiter=200))
        except (RuntimeError, ValueError) as exc:  # pragma: no cover - brentq with a valid bracket converges
            return result(NOT_ESTIMATED, f"ill-conditioned: the order solver failed ({exc})")
    limit = q[-1] + e32 / math.expm1(order * log_r32)
    if not math.isfinite(limit):
        return result(NOT_ESTIMATED, "ill-conditioned: the extrapolated limit is not finite")
    gci = None if q[-1] == 0.0 else 1.25 * abs(e32 / q[-1]) / math.expm1(order * log_r32)
    flag = None if uncertainty_available else "uncertainty not available: differences compared with zero only"
    return result(ESTIMATED, flag, order=order, limit=limit, error=abs(q[-1] - limit), gci=gci)
