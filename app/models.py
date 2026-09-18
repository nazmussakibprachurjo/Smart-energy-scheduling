from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DirectiveType = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HourInput(StrictModel):
    hour: int = Field(ge=0, le=23)
    demand_kwh: float = Field(ge=0)
    solar_kwh: float = Field(ge=0)
    tariff_bdt_per_kwh: float = Field(ge=0)

    @field_validator("demand_kwh", "solar_kwh", "tariff_bdt_per_kwh")
    @classmethod
    def finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("must be finite")
        return value


class BatteryInput(StrictModel):
    capacity_kwh: float = Field(gt=0)
    initial_energy_kwh: float = Field(ge=0)
    minimum_energy_kwh: float = Field(ge=0)
    max_charge_kwh_per_hour: float = Field(ge=0)
    max_discharge_kwh_per_hour: float = Field(ge=0)

    @model_validator(mode="after")
    def valid_bounds(self) -> "BatteryInput":
        values = [
            self.capacity_kwh,
            self.initial_energy_kwh,
            self.minimum_energy_kwh,
            self.max_charge_kwh_per_hour,
            self.max_discharge_kwh_per_hour,
        ]
        if not all(math.isfinite(v) for v in values):
            raise ValueError("battery values must be finite")
        if self.minimum_energy_kwh > self.initial_energy_kwh:
            raise ValueError("minimum_energy_kwh exceeds initial_energy_kwh")
        if self.initial_energy_kwh > self.capacity_kwh:
            raise ValueError("initial_energy_kwh exceeds capacity_kwh")
        return self


class OptimizeRequest(StrictModel):
    scenario_id: str = Field(min_length=1, max_length=200)
    operator_notes: list[str] = Field(min_length=1, max_length=3)
    hours: list[HourInput] = Field(min_length=24, max_length=24)
    battery: BatteryInput

    @field_validator("operator_notes")
    @classmethod
    def nonempty_notes(cls, notes: list[str]) -> list[str]:
        if any(not note.strip() for note in notes):
            raise ValueError("operator notes must be non-empty")
        return notes

    @field_validator("hours")
    @classmethod
    def all_hours_once(cls, hours: list[HourInput]) -> list[HourInput]:
        if sorted(h.hour for h in hours) != list(range(24)):
            raise ValueError("hours must contain each integer 0 through 23 exactly once")
        return sorted(hours, key=lambda h: h.hour)


class LLMDirective(StrictModel):
    note_index: int
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: dict[str, Any] | None
    explanation: str = Field(min_length=1, max_length=400)


class LLMResult(StrictModel):
    directives: list[LLMDirective]


class HourPlan(StrictModel):
    hour: int
    grid_kwh: float
    solar_used_kwh: float
    battery_action: Literal["charge", "discharge", "idle"]
    battery_kwh: float
    battery_energy_after_kwh: float


class OptimizeResponse(StrictModel):
    scenario_id: str
    directive_interpretation: list[LLMDirective]
    hourly_plan: list[HourPlan]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str

