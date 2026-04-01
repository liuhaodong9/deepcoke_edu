"""配煤优化 - 差分进化 (scipy) + LP fallback"""

import warnings
import numpy as np
from scipy.optimize import differential_evolution, NonlinearConstraint, linprog

warnings.filterwarnings("ignore", module="scipy.optimize")


def optimize_blend(coal_props: dict, coal_names: list[str],
                   constraints: dict, total_weight_g: float = 1000) -> dict | None:
    """
    Args:
        coal_props: {name: {price, coke_CRI, coke_CSR, coke_M10, coke_M25, Vdaf, G, Ad, ...}}
        coal_names: 参与配煤的煤样名称列表
        constraints: {CRI_min, CRI_max, CSR_min, CSR_max, M10_min, M10_max, M25_min, M25_max, ...}
        total_weight_g: 总量(克)
    """
    n = len(coal_names)
    if n == 0:
        return None

    props = coal_props
    has_quality = any(k in constraints for k in
                      ["CRI_min", "CRI_max", "CSR_min", "CSR_max",
                       "M10_min", "M10_max", "M25_min", "M25_max"])

    if has_quality:
        plan = _de_optimize(props, coal_names, constraints, total_weight_g)
        if plan:
            return plan

    return _lp_optimize(props, coal_names, constraints, total_weight_g)


def _de_optimize(props, names, constraints, total_weight_g):
    n = len(names)
    prices = np.array([props[c]["price"] for c in names], dtype=float)
    cri = np.array([props[c]["coke_CRI"] for c in names], dtype=float)
    csr = np.array([props[c]["coke_CSR"] for c in names], dtype=float)
    m10 = np.array([props[c]["coke_M10"] for c in names], dtype=float)
    m25 = np.array([props[c]["coke_M25"] for c in names], dtype=float)

    nl = [NonlinearConstraint(lambda x: np.sum(x), 1.0, 1.0)]
    for vals, lo_key, hi_key in [
        (cri, "CRI_min", "CRI_max"), (csr, "CSR_min", "CSR_max"),
        (m10, "M10_min", "M10_max"), (m25, "M25_min", "M25_max"),
    ]:
        lo = constraints.get(lo_key, 0)
        hi = constraints.get(hi_key, 100)
        if lo_key in constraints or hi_key in constraints:
            nl.append(NonlinearConstraint(lambda x, v=vals: np.dot(v, x), lo, hi))

    try:
        result = differential_evolution(
            lambda x: np.dot(prices, x), bounds=[(0, 0.6)] * n,
            constraints=nl, maxiter=2000, popsize=100, tol=1e-8, seed=42,
        )
    except Exception:
        return None

    if not result.success:
        return None

    return _build(names, result.x, total_weight_g, float(result.fun), "scipy_DE")


def _lp_optimize(props, names, constraints, total_weight_g):
    n = len(names)
    prices = np.array([props[c]["price"] for c in names], dtype=float)
    A_ub, b_ub = [], []

    vdaf = np.array([props[c]["Vdaf"] for c in names])
    if "Vdaf_max" in constraints: A_ub.append(vdaf); b_ub.append(constraints["Vdaf_max"])
    if "Vdaf_min" in constraints: A_ub.append(-vdaf); b_ub.append(-constraints["Vdaf_min"])
    g = np.array([props[c]["G"] for c in names])
    if "G_min" in constraints: A_ub.append(-g); b_ub.append(-constraints["G_min"])
    ad = np.array([props[c]["Ad"] for c in names])
    if "Ad_max" in constraints: A_ub.append(ad); b_ub.append(constraints["Ad_max"])

    result = linprog(prices,
                     A_ub=np.array(A_ub) if A_ub else None,
                     b_ub=np.array(b_ub) if b_ub else None,
                     A_eq=np.ones((1, n)), b_eq=np.array([1.0]),
                     bounds=[(0.05, 0.60)] * n, method="highs")

    if not result.success:
        return None
    return _build(names, result.x, total_weight_g, float(result.fun), "LP")


def _build(names, ratios, total_weight_g, cost, optimizer):
    return {
        "hoppers": [
            {"coal": names[i], "ratio": round(ratios[i] * 100, 1),
             "weight_g": round(ratios[i] * total_weight_g, 1)}
            for i in range(len(names))
        ],
        "total_weight_g": total_weight_g,
        "cost_per_ton": cost,
        "optimizer": optimizer,
    }
