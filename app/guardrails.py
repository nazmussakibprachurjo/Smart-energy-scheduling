from __future__ import annotations

import math

from .models import LLMDirective, OptimizeRequest


class DirectiveValidationError(ValueError):
    pass


def _hours(value: object) -> list[int]:
    if not isinstance(value, list) or not value:
        raise DirectiveValidationError("hours must be a non-empty array")
    if any(type(h) is not int or not 0 <= h <= 23 for h in value):
        raise DirectiveValidationError("hours must be integers from 0 through 23")
    if value != sorted(set(value)):
        raise DirectiveValidationError("hours must be unique and ascending")
    return value


def _finite_number(value: object, name: str, minimum: float, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DirectiveValidationError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum or (maximum is not None and result > maximum):
        raise DirectiveValidationError(f"{name} is outside the allowed range")
    return result


def validate_directives(raw: list[LLMDirective], request: OptimizeRequest) -> list[LLMDirective]:
    if len(raw) != len(request.operator_notes):
        raise DirectiveValidationError("one interpretation is required per note")
    if [d.note_index for d in raw] != list(range(len(raw))):
        raise DirectiveValidationError("note_index must be complete and ordered")

    allowed_shapes = {
        "solar_reduction": {"hours", "factor"},
        "minimum_battery_reserve": {"hours", "minimum_energy_kwh"},
        "no_charge_window": {"hours"},
        "no_discharge_window": {"hours"},
        "max_grid_window": {"hours", "max_grid_kwh"},
    }
    clean: list[LLMDirective] = []
    for item in raw:
        if item.directive_type == "no_op":
            if item.applies or item.structured_adjustment is not None:
                raise DirectiveValidationError("no_op requires applies=false and null adjustment")
            clean.append(item)
            continue
        if not item.applies or not isinstance(item.structured_adjustment, dict):
            raise DirectiveValidationError("non-no_op directives require applies=true and an adjustment")
        adjustment = item.structured_adjustment
        if set(adjustment) != allowed_shapes[item.directive_type]:
            raise DirectiveValidationError(f"invalid adjustment shape for {item.directive_type}")
        _hours(adjustment["hours"])
        if item.directive_type == "solar_reduction":
            _finite_number(adjustment["factor"], "factor", 0, 1)
        elif item.directive_type == "minimum_battery_reserve":
            _finite_number(
                adjustment["minimum_energy_kwh"],
                "minimum_energy_kwh",
                0,
                request.battery.capacity_kwh,
            )
        elif item.directive_type == "max_grid_window":
            _finite_number(adjustment["max_grid_kwh"], "max_grid_kwh", 0)
        clean.append(item)
    return clean

