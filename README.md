# SourceCheck — FHIR Source Validation POC

A Streamlit proof of concept that compares observations in a FHIR R4 bundle against evidence in a synthetic EHR screenshot. Azure AI Vision performs OCR; application code deterministically compares the extracted value and unit against the FHIR observation.

## Current capabilities

- Load the included synthetic EHR screenshot and FHIR R4 bundle, or upload PNG/JPEG and JSON inputs.
- Discover `Observation` resources dynamically from `Bundle.entry[].resource`.
- Send a configurable left-side crop of the screenshot to Azure AI Vision Read OCR. The default crop is intended to exclude an illustrative JSON pane on the right.
- Match OCR text to observation labels, compare values and units separately, and classify results as Match, Value mismatch, Unit mismatch, Value and unit mismatch, Not found, or Needs review.
- Draw evidence boxes on a copy of the screenshot and show the OCR text returned by Azure.
- Handle missing credentials, malformed FHIR bundles, OCR failures, and timeouts with visible error messages.

The application uses only synthetic demonstration data. Do not upload real patient information. This is not a clinical validation tool and is not intended for PHI or clinical decision-making.

## Azure configuration

Create an Azure AI Vision / Computer Vision resource and configure these environment variables on the Render web service:

- `VISION_ENDPOINT` — the endpoint URL shown on the Azure resource's **Keys and Endpoint** page. Use the full URL, for example `https://YOUR-RESOURCE-NAME.cognitiveservices.azure.com/`.
- `VISION_KEY` — either key shown on that same page.

Keep the key in Render's environment settings. Do not commit a real key to GitHub or put it in `.env.example`. The application uses the Azure AI Vision Read API (`/vision/v3.2/read/analyze`) and polls Azure until OCR completes. The endpoint must correspond to the resource that issued the key.

After changing environment variables in Render, trigger a redeploy/restart so the running process receives them.

## Run locally

Requires Python 3.11+ (Render is configured for Python 3.12).

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

Set `VISION_ENDPOINT` and `VISION_KEY` in your local shell, then run:

```bash
streamlit run app.py
```

Use **Load sample**, then click **Validate**. The sidebar's OCR region width setting controls how much of the screenshot is sent to OCR. Increase it only if the EHR result values or units are being cut off; a wider crop can include the illustrative JSON panel.

## Deploy to Render

The repository's `render.yaml` defines the web service and declares `VISION_ENDPOINT` and `VISION_KEY` as environment variables that are configured outside source control.

1. Push the reviewed code to GitHub.
2. Wait for Render to finish the deployment.
3. In the Render service, open **Environment** and verify that `VISION_ENDPOINT` and `VISION_KEY` exist and have the correct values.
4. Redeploy/restart if you changed the environment values.
5. Open the service URL, click **Load sample**, and click **Validate**.
6. Confirm the baseline result: 13 observations, 11 matches, a Hemoglobin unit mismatch (`13.5 g/dL` in the screenshot versus `13.5 mg/dL` in FHIR), and a Potassium value mismatch (`4.2 mmol/L` in the screenshot versus `4.8 mmol/L` in FHIR).

If OCR returns incomplete or unexpected results, expand **OCR text returned by Azure** and adjust the crop width before interpreting any finding.

## Tests

Run the deterministic comparison tests with:

```bash
pytest -q
```

The tests cover dynamic Observation parsing, the expected synthetic baseline, malformed bundle rejection, and common unit notation normalization. They use mocked OCR fragments and do not make a live Azure API request. A live Render test is still required to verify credentials, endpoint connectivity, and Azure's actual OCR response.

## Limitations

- OCR localization depends on screenshot layout and recognition quality; ambiguous results should be reviewed rather than treated as matches.
- The default crop assumes the relevant EHR results are on the left side of the screenshot. Adjust the crop width for the supplied synthetic layout.
- No authentication, user accounts, database, or audit infrastructure.
- Not intended for PHI, clinical decisions, production use, or full FHIR conformance.
