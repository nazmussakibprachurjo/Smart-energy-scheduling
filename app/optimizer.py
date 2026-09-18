from __future__ import annotations

import numpy as np
from scipy.optimize import linprog

from .models import HourPlan, LLMDirective, OptimizeRequest

N = 24
G, S, C, D, E = 0, 24, 48, 72, 96


class OptimizationError(RuntimeError):
    pass


def _constraints(request: OptimizeRequest, directives: list[LLMDirective]):
    solar = np.array([h.solar_kwh for h in request.hours], dtype=float)
    reserve = np.full(N, request.battery.minimum_energy_kwh, dtype=float)
    charge_cap = np.full(N, request.battery.max_charge_kwh_per_hour, dtype=float)
    discharge_cap = np.full(N, request.battery.max_discharge_kwh_per_hour, dtype=float)
    grid_cap = np.full(N, np.inf, dtype=float)
    for directive in directives:
        if not directive.applies:
            continue
        a = directive.structured_adjustment
        assert a is not None
        hours = a["hours"]
        if directive.directive_type == "solar_reduction":
            solar[hours] *= float(a["factor"])
        elif directive.directive_type == "minimum_battery_reserve":
            reserve[hours] = np.maximum(reserve[hours], float(a["minimum_energy_kwh"]))
        elif directive.directive_type == "no_charge_window":
            charge_cap[hours] = 0
        elif directive.directive_type == "no_discharge_window":
            discharge_cap[hours] = 0
        elif directive.directive_type == "max_grid_window":
            grid_cap[hours] = np.minimum(grid_cap[hours], float(a["max_grid_kwh"]))
    return solar, reserve, charge_cap, discharge_cap, grid_cap


def optimize(request: OptimizeRequest, directives: list[LLMDirective]) -> list[HourPlan]:
    solar, reserve, charge_cap, discharge_cap, grid_cap = _constraints(request, directives)
    objective = np.zeros(120)
    objective[G:G + N] = [h.tariff_bdt_per_kwh for h in request.hours]
    # A tiny deterministic preference discourages needless simultaneous charge/discharge and solar curtailment.
    objective[C:C + N] = 1e-7
    objective[D:D + N] = 1e-7
    objective[S:S + N] = -1e-8

    a_eq: list[np.ndarray] = []
    b_eq: list[float] = []
    for h, hour in enumerate(request.hours):
        row = np.zeros(120)
        row[G + h], row[S + h], row[C + h], row[D + h] = 1, 1, -1, 1
        a_eq.append(row)
        b_eq.append(hour.demand_kwh)

        row = np.zeros(120)
        row[E + h], row[C + h], row[D + h] = 1, -1, 1
        if h == 0:
            b = request.battery.initial_energy_kwh
        else:
            row[E + h - 1] = -1
            b = 0
        a_eq.append(row)
        b_eq.append(b)
    row = np.zeros(120)
    row[E + 23] = 1
    a_eq.append(row)
    b_eq.append(request.battery.initial_energy_kwh)

    bounds = []
    bounds.extend((0, None if np.isinf(grid_cap[h]) else grid_cap[h]) for h in range(N))
    bounds.extend((0, solar[h]) for h in range(N))
    bounds.extend((0, charge_cap[h]) for h in range(N))
    bounds.extend((0, discharge_cap[h]) for h in range(N))
    bounds.extend((reserve[h], request.battery.capacity_kwh) for h in range(N))
    result = linprog(objective, A_eq=np.array(a_eq), b_eq=np.array(b_eq), bounds=bounds, method="highs")
    if not result.success:
        raise OptimizationError(f"scenario is infeasible: {result.message}")

    x = result.x
    plan: list[HourPlan] = []
    for h in range(N):
        net = x[C + h] - x[D + h]
        if net > 1e-7:
            action, amount = "charge", net
        elif net < -1e-7:
            action, amount = "discharge", -net
        else:
            action, amount = "idle", 0.0
        # Recompute grid after cancelling any simultaneous charge/discharge.
        grid = request.hours[h].demand_kwh - x[S + h] + net
        plan.append(HourPlan(
            hour=h,
            grid_kwh=_clean(grid),
            solar_used_kwh=_clean(x[S + h]),
            battery_action=action,
            battery_kwh=_clean(amount),
            battery_energy_after_kwh=_clean(x[E + h]),
        ))
    return plan


def _clean(value: float) -> float:
    value = 0.0 if abs(value) < 5e-8 else float(value)
    return round(value, 6)

