# Mineral Prospectivity Mapping (Uranium) - pilot

CPU-only, crash-safe pipeline that ranks map cells by relative uranium favorability using
public geoscience data. A learning/demo project: it ranks areas, it does not find deposits.

See [PLAN.md](PLAN.md) for the phases and [docs/decisions.md](docs/decisions.md) for choices.

## Setup (Windows, PowerShell)
```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/run_pipeline.py      # safe to re-run; finished stages are skipped
pytest -q
```
