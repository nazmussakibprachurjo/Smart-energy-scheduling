# GridWise LLM - BUP CSE Fest 2026 Preliminary

This service implements the required `GET /health` and `POST /optimize-energy` endpoints. It uses an LLM only for semantic interpretation, validates the model output deterministically, builds a linear program for the 24-hour battery/solar/grid schedule, and independently replays the result before returning it.

It also includes a responsive browser dashboard at `/`. The dashboard can load all ten public cases, edit input JSON, call the production endpoint, visualize the resulting energy flow, inspect LLM directives, review the 24-hour schedule, and download the response.

## Architecture

`request -> Pydantic validation -> Gemini/OpenAI structured interpretation -> deterministic guardrails -> SciPy HiGHS linear program -> independent replay verifier -> response`

The optimizer uses five 24-element variable groups: grid import, solar used, battery charge, battery discharge, and battery state. Constraints implement energy balance, battery state transitions and bounds, charge/discharge rates, effective solar, directive windows, grid caps, and end-of-day neutrality. The objective minimizes `sum(grid_kwh[h] * tariff[h])`.

## Configuration

Copy `.env.example` to `.env` or set these environment variables in the deployment platform. Gemini is the default because its Flash-Lite model has a free tier:

- `LLM_PROVIDER` - `gemini` (default) or `openai`.
- `GEMINI_API_KEY` - required when using Gemini; create it in Google AI Studio and never commit it.
- `GEMINI_MODEL` - defaults to `gemini-2.5-flash-lite`, which supports structured outputs and free-tier usage.
- `OPENAI_API_KEY` - required only when `LLM_PROVIDER=openai`.
- `OPENAI_MODEL` - defaults to `gpt-6-astra` for the optional OpenAI provider.
- `LLM_TIMEOUT_SECONDS` - defaults to 15.

The model is mandatory because its structured interpretation is the input to the deterministic guardrails and optimizer. There is deliberately no phrase-matching production fallback.

When no API key is configured, the dashboard enters clearly labeled reference-preview mode. It can display the official expected result for an unchanged bundled public sample, but it will not process arbitrary notes. This preview never replaces the mandatory LLM path and is not used by `/optimize-energy`.

## Windows quickstart (PowerShell)

Create a free Gemini API key in [Google AI Studio](https://aistudio.google.com/app/apikey), then configure it without displaying the key in the terminal:

```powershell
.\configure-gemini.ps1
```

The script saves the secret to the git-ignored `.env` file. Do not paste the key into source code, screenshots, chat messages, or commits.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Alternatively, the included launcher creates the virtual environment, installs dependencies, and starts the application:

```powershell
.\run.ps1
```

Open `http://127.0.0.1:8000` for the dashboard or `http://127.0.0.1:8000/docs` for the generated API documentation.

In a second PowerShell window:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
$body = Get-Content -Raw "C:\path\to\one-request.json"
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/optimize-energy -ContentType "application/json" -Body $body
```

## Test all ten supplied public cases

With the service running and an API key configured:

```powershell
python scripts\test_public_cases.py "samples\public_cases.json"
```

To test the optimizer and replay verifier independently of the model, using the official reference interpretations:

```powershell
$env:GRIDWISE_SAMPLE_JSON = "samples\public_cases.json"
pytest -q
```

## Docker

```powershell
docker build -t gridwise-llm:1.0 .
docker run --rm -p 8000:8000 -e LLM_PROVIDER=gemini -e GEMINI_API_KEY=$env:GEMINI_API_KEY -e GEMINI_MODEL=gemini-2.5-flash-lite gridwise-llm:1.0
Invoke-RestMethod http://127.0.0.1:8000/health
```

Or use Compose after setting `OPENAI_API_KEY`:

```powershell
docker compose up --build
```

Push the tested image to Docker Hub or GHCR and submit the exact tag or digest. Do not place the key in the image.

## Deployment checklist

- Bind to `0.0.0.0`; expose the platform's assigned port or set `PORT=8000`.
- Confirm `/health` externally and keep p95 under five seconds when possible.
- Ensure provider quota and rate limits cover repeated judge calls.
- Keep the repository private during the event and make it public only after the submission deadline, per the supplied guide.
- Record a maximum three-minute video covering the problem, architecture, LLM-to-guardrail-to-optimizer flow, and run/test steps.

### Render

The included `render.yaml` defines a Docker web service, `/health` check, Gemini model, and required secret placeholder. When deploying manually, select the repository root as the service root and add `GEMINI_API_KEY` as a secret environment variable in the Render dashboard.

## Known limitations

- Hosted-model latency and availability depend on the configured provider account.
- A malformed or guardrail-invalid model result returns a controlled generic 500 response; it never silently invents a constraint.
- The supplied public cases can verify known semantics but cannot guarantee hidden paraphrase accuracy. Run additional paraphrase evaluations before submission.

## Dependencies

FastAPI/Uvicorn provide the API, OpenAI's Python SDK provides Structured Outputs through the Responses API, Pydantic validates schemas, and SciPy HiGHS solves the linear program. All are declared in `requirements.txt`.
