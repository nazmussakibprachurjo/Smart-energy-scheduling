from __future__ import annotations

from .models import HourPlan, LLMDirective, OptimizeRequest
from .optimizer import _constraints

TOL = 1e-4


def verify(request: OptimizeRequest, directives: list[LLMDirective], plan: list[HourPlan]) -> None:
    if [p.hour for p in plan] != list(range(24)):
        raise ValueError("plan hours are incomplete or unordered")
    solar, reserve, charge_cap, discharge_cap, grid_cap = _constraints(request, directives)
    energy = request.battery.initial_energy_kwh
    for h, item in enumerate(plan):
        if min(item.grid_kwh, item.solar_used_kwh, item.battery_kwh) < -TOL:
            raise ValueError(f"negative energy at hour {h}")
        if item.solar_used_kwh > solar[h] + TOL:
            raise ValueError(f"solar limit exceeded at hour {h}")
        charge = item.battery_kwh if item.battery_action == "charge" else 0.0
        discharge = item.battery_kwh if item.battery_action == "discharge" else 0.0
        if item.battery_action == "idle" and abs(item.battery_kwh) > TOL:
            raise ValueError(f"idle battery has nonzero action at hour {h}")
        if charge > charge_cap[h] + TOL or discharge > discharge_cap[h] + TOL:
            raise ValueError(f"battery rate/directive violated at hour {h}")
        energy += charge - discharge
        if not reserve[h] - TOL <= energy <= request.battery.capacity_kwh + TOL:
            raise ValueError(f"battery bound violated at hour {h}")
        if abs(energy - item.battery_energy_after_kwh) > TOL:
            raise ValueError(f"battery transition mismatch at hour {h}")
        balance = item.grid_kwh + item.solar_used_kwh + discharge - request.hours[h].demand_kwh - charge
        if abs(balance) > TOL:
            raise ValueError(f"energy balance failed at hour {h}")
        if item.grid_kwh > grid_cap[h] + TOL:
            raise ValueError(f"grid cap exceeded at hour {h}")
    if abs(energy - request.battery.initial_energy_kwh) > TOL:
        raise ValueError("end-of-day battery neutrality failed")

