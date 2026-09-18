from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .guardrails import DirectiveValidationError
from .interpreter import interpret, provider_settings
from .models import OptimizeRequest, OptimizeResponse
from .optimizer import OptimizationError, optimize
from .verifier import verify

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gridwise")
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="GridWise LLM",
    version="1.0.0",
    description="LLM-assisted 24-hour campus energy scheduling API.",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/app-config", include_in_schema=False)
def app_config():
    provider, model, configured = provider_settings()
    return {
        "provider": provider,
        "model": model,
        "api_key_configured": configured,
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/optimize-energy", response_model=OptimizeResponse)
def optimize_energy(request: OptimizeRequest) -> OptimizeResponse:
    try:
        provider, _, configured = provider_settings()
        if not configured:
            raise HTTPException(
                status_code=503,
                detail=f"LLM provider is not configured. Set the {provider.upper()} API key and restart the service.",
            )
        directives = interpret(request)
        plan = optimize(request, directives)
        verify(request, directives, plan)
        total_grid = round(sum(p.grid_kwh for p in plan), 6)
        total_cost = round(sum(p.grid_kwh * request.hours[p.hour].tariff_bdt_per_kwh for p in plan), 6)
        peak = round(max(p.grid_kwh for p in plan), 6)
        applied = [d.directive_type for d in directives if d.applies]
        summary = "Applied " + (", ".join(applied) if applied else "no scheduling directives")
        summary += " and minimized grid cost while restoring the initial battery level."
        return OptimizeResponse(
            scenario_id=request.scenario_id,
            directive_interpretation=directives,
            hourly_plan=plan,
            total_grid_kwh=total_grid,
            total_cost_bdt=total_cost,
            peak_grid_kwh=peak,
            plan_summary=summary,
        )
    except DirectiveValidationError as exc:
        log.warning("Rejected invalid model output: %s", exc)
        raise HTTPException(status_code=500, detail="The language model returned an invalid interpretation") from None
    except OptimizationError as exc:
        log.warning("Optimization failed: %s", exc)
        raise HTTPException(status_code=422, detail="The interpreted scenario is infeasible") from None
    except RuntimeError as exc:
        log.warning("LLM provider failure: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except HTTPException:
        raise
    except Exception as exc:
        log.error("Controlled processing failure: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Unable to process the scenario") from None
