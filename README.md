# SourceCheck — FHIR Source Validation POC

A minimal Streamlit wireframe for a portfolio proof of concept that compares observations in a FHIR R4 bundle against evidence in a synthetic EHR screenshot.

## Current scope

This is a **wireframe**, not a working OCR or clinical validation system. It can:
- Load the included synthetic screenshot and FHIR JSON bundle.
- Accept alternate PNG/JPEG screenshots and JSON bundles.
- Parse and list FHIR `Observation` resources dynamically.
- Present the intended review layout and validation statuses.

It does **not** yet perform OCR, locate source evidence, draw evidence overlays, or compare source values against FHIR. The UI deliberately does not claim that placeholder rows are matches.

## Run locally

Requires Python 3.11+ (Render is configured for Python 3.12).

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

Open the local URL printed by Streamlit. Use **Load sample** to load the included synthetic inputs.

## Deploy to Render

1. Push this repository to GitHub.
2. In Render, create a new Blueprint or Web Service connected to the repository.
3. If using the Blueprint, Render reads `render.yaml`. Confirm the selected plan is available to your account and adjust it in the dashboard if needed.
4. Deploy and open the service URL.

For manual Web Service configuration:
- Build command: `pip install -r requirements.txt`
- Start command: `streamlit run app.py --server.address 0.0.0.0 --server.port $PORT`

No database or persistent disk is required for this wireframe.

## Included sample data

The `sample_data/` directory contains the manufactured EHR screenshot and FHIR R4 bundle from the supplied sample archive. They are synthetic demonstration data. Do not upload real patient information.

## Planned next steps

1. Implement and test FHIR R4 parsing.
2. Add an OCR adapter that returns text and bounding boxes.
3. Exclude the illustrative JSON panel from screenshot OCR.
4. Implement deterministic value/unit comparison.
5. Draw evidence overlays and link table rows to screenshot locations.
6. Add regression tests for the 11-match, one-unit-mismatch, one-value-mismatch baseline.

## Limitations

- No authentication, user accounts, database, or audit infrastructure.
- Not intended for PHI, clinical decisions, or production use.
- No OCR, deterministic comparison, or source-coordinate localization has been implemented yet.
