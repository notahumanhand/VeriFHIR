import hashlib
import json
import os
import time
from io import BytesIO
from pathlib import Path

import requests
import pandas as pd
import streamlit as st
from PIL import Image
from validation import (
    draw_evidence_overlay, evaluate_observation, observation_name, observation_value,
    parse_fhir_observations,
)

st.set_page_config(page_title="SourceCheck | FHIR Validation", page_icon=None, layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 2rem; max-width: 1440px; }
    .eyebrow { color: #5D6B78; text-transform: uppercase; letter-spacing: .12em; font-size: .72rem; font-weight: 700; }
    .hero { padding: 1.5rem 0 1.2rem 0; border-bottom: 1px solid #DCE2E7; margin-bottom: 1.4rem; }
    .hero h1 { margin: .25rem 0 .45rem 0; font-size: 2.25rem; letter-spacing: -.04em; }
    .hero p { color: #53616D; max-width: 760px; font-size: 1.02rem; }
    .metric { background: #F5F7F8; border: 1px solid #E1E6EA; border-radius: 10px; padding: 1rem; }
    .metric-label { color: #596773; font-size: .82rem; }
    .metric-value { font-size: 1.8rem; font-weight: 650; margin-top: .2rem; }
    div[data-testid="stDataFrame"] { border: 1px solid #E1E6EA; border-radius: 8px; overflow: hidden; }
    .panel-title { font-weight: 700; font-size: 1.05rem; margin-bottom: .2rem; }
    .muted { color: #65727D; font-size: .87rem; }
    .stButton button { border-radius: 7px; }
</style>
""", unsafe_allow_html=True)

ROOT = Path(__file__).parent
SAMPLE_DIR = ROOT / "sample_data"
IMAGE_PATH = SAMPLE_DIR / "ehr_screenshot.png"
BUNDLE_PATH = SAMPLE_DIR / "synthetic_ehr_bundle.json"
AZURE_READ_API_VERSION = "3.2"


def azure_read(image_bytes, endpoint, key, crop_percent=68):
    """Submit the EHR-side crop to Azure AI Vision Read API and return OCR lines."""
    endpoint = endpoint.strip().rstrip("/")
    if not endpoint.startswith(("https://", "http://")):
        raise ValueError("VISION_ENDPOINT must be a full URL beginning with https://.")
    if not key.strip():
        raise ValueError("VISION_KEY is empty.")

    with Image.open(BytesIO(image_bytes)) as source:
        image = source.convert("RGB")
        crop_width = max(1, min(image.width, round(image.width * crop_percent / 100)))
        # The demo screenshot places the EHR results on the left; this crop avoids
        # treating a possible right-side illustrative JSON pane as source evidence.
        source_crop = image.crop((0, 0, crop_width, image.height))
        buffer = BytesIO()
        source_crop.save(buffer, format="PNG")
        crop_bytes = buffer.getvalue()

    analyze_url = f"{endpoint}/vision/v{AZURE_READ_API_VERSION}/read/analyze"
    headers = {
        "Ocp-Apim-Subscription-Key": key.strip(),
        "Content-Type": "application/octet-stream",
    }
    try:
        response = requests.post(
            analyze_url,
            params={"language": "en"},
            headers=headers,
            data=crop_bytes,
            timeout=(10, 45),
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach Azure AI Vision: {exc}") from exc

    if response.status_code not in (200, 202):
        detail = response.text[:500]
        if response.status_code in (401, 403):
            raise RuntimeError("Azure rejected the key or endpoint (HTTP "
                               f"{response.status_code}). Check VISION_KEY and VISION_ENDPOINT.")
        raise RuntimeError(f"Azure AI Vision returned HTTP {response.status_code}: {detail}")

    operation_url = response.headers.get("Operation-Location")
    if response.status_code == 200:
        result = response.json()
    elif operation_url:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            time.sleep(1)
            try:
                poll = requests.get(
                    operation_url,
                    headers={"Ocp-Apim-Subscription-Key": key.strip()},
                    timeout=(10, 30),
                )
            except requests.RequestException as exc:
                raise RuntimeError(f"Could not retrieve Azure OCR results: {exc}") from exc
            if poll.status_code != 200:
                raise RuntimeError(f"Azure OCR polling failed with HTTP {poll.status_code}: {poll.text[:300]}")
            result = poll.json()
            status = result.get("status", "").lower()
            if status == "succeeded":
                break
            if status == "failed":
                raise RuntimeError("Azure AI Vision could not read this image. Try a clearer synthetic screenshot.")
        else:
            raise RuntimeError("Azure OCR timed out while waiting for the Read operation.")
    else:
        raise RuntimeError("Azure accepted the OCR request but did not return an Operation-Location header.")

    status = result.get("status", "").lower()
    if status == "failed":
        raise RuntimeError("Azure AI Vision reported that OCR processing failed.")
    lines = []
    for page in result.get("analyzeResult", {}).get("readResults", []):
        for line in page.get("lines", []):
            # Word-level boxes let the comparison separate adjacent table cells
            # (label, result, and unit) even when Azure groups them into one line.
            fragments = line.get("words") or [line]
            for fragment in fragments:
                box = fragment.get("boundingBox", [])
                if len(box) >= 8:
                    xs, ys = box[0::2], box[1::2]
                    lines.append({
                        "text": fragment.get("text", "").strip(),
                        "x1": min(xs), "y1": min(ys),
                        "x2": max(xs), "y2": max(ys),
                        "cx": (min(xs) + max(xs)) / 2,
                        "cy": (min(ys) + max(ys)) / 2,
                    })
    return lines


def style_observation_row(row):
    """Apply a high-contrast background to rows that need attention."""
    status = str(row.get("Status", "")).strip().lower()
    styles = {
        "unit mismatch": ("#4A3A1C", "#FFE7A3"),
        "value mismatch": ("#4A2528", "#FFE5E5"),
        "value and unit mismatch": ("#5A2026", "#FFFFFF"),
        "not found": ("#303944", "#E2E8F0"),
        "needs review": ("#303944", "#E2E8F0"),
    }
    if status in styles:
        background, foreground = styles[status]
        return [
            f"background-color: {background}; color: {foreground};"
            for _ in row.index
        ]
    return ["" for _ in row.index]


def display_observation_table(rows, height=500):
    """Render results and highlight mismatch/review rows across all columns."""
    dataframe = pd.DataFrame(rows)
    if "Status" in dataframe.columns:
        styled_dataframe = dataframe.style.apply(style_observation_row, axis=1)
        st.dataframe(
            styled_dataframe,
            use_container_width=True,
            hide_index=True,
            height=height,
        )
    else:
        st.dataframe(
            dataframe,
            use_container_width=True,
            hide_index=True,
            height=height,
        )


st.markdown("""
<div class="hero">
  <div class="eyebrow">Interoperability quality assurance · Proof of concept</div>
  <h1>SourceCheck</h1>
  <p>Compare clinical observations in a FHIR R4 bundle against their supporting evidence in a source EHR screenshot. Review values, units, and evidence locations in one workspace.</p>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### Validation inputs")
    st.caption("Synthetic demonstration data only. Do not upload real patient data.")
    use_sample = st.button("Load sample", type="primary", use_container_width=True)
    screenshot_upload = st.file_uploader("EHR screenshot", type=["png", "jpg", "jpeg"])
    bundle_upload = st.file_uploader("FHIR R4 bundle (JSON)", type=["json"])
    crop_percent = st.slider(
        "OCR region width (%)",
        min_value=45, max_value=100, value=68,
        help="The OCR request uses the left side of the screenshot to avoid reading an illustrative JSON pane on the right. Increase this only if the EHR values or units are cut off.",
    )
    st.divider()
    st.markdown("**Pipeline status**")
    st.markdown("`1`  Input selection")
    st.markdown("`2`  Azure AI Vision OCR")
    st.markdown("`3`  Deterministic comparison")
    st.caption("Azure credentials are read from Render environment variables.")

if use_sample:
    st.session_state["load_sample"] = True

image_bytes = None
bundle = None
try:
    if screenshot_upload is not None:
        image_bytes = screenshot_upload.getvalue()
    elif st.session_state.get("load_sample") and IMAGE_PATH.exists():
        image_bytes = IMAGE_PATH.read_bytes()
except Exception as exc:
    st.error(f"Could not read screenshot: {exc}")

try:
    if bundle_upload is not None:
        bundle = json.load(bundle_upload)
    elif st.session_state.get("load_sample") and BUNDLE_PATH.exists():
        with open(BUNDLE_PATH, encoding="utf-8") as f:
            bundle = json.load(f)
except (json.JSONDecodeError, OSError) as exc:
    st.error(f"Could not read FHIR JSON: {exc}")

if image_bytes is None or bundle is None:
    st.info("Load the synthetic sample or provide both input files to begin.")
    left, right = st.columns([1.15, 1])
    with left:
        st.markdown("#### Review workflow")
        st.markdown("1. Load an EHR screenshot and FHIR bundle.\n2. Run Azure OCR.\n3. Review each result and its highlighted source evidence.")
    with right:
        st.markdown("#### Validation states")
        st.markdown("- **Match** — values and units agree.\n- **Value mismatch** — numerical values differ.\n- **Unit mismatch** — units differ.\n- **Not found** — source evidence is absent.\n- **Needs review** — evidence is ambiguous.")
    st.stop()

try:
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    entries, observations = parse_fhir_observations(bundle)
except (OSError, ValueError) as exc:
    st.error(f"Invalid input: {exc}")
    st.stop()

if not observations:
    st.warning("No Observation resources were found in this FHIR bundle.")

input_fingerprint = hashlib.sha256(
    image_bytes + json.dumps(bundle, sort_keys=True).encode("utf-8") + str(crop_percent).encode("ascii")
).hexdigest()
if st.session_state.get("result_fingerprint") != input_fingerprint:
    st.session_state.pop("validation_results", None)
    st.session_state.pop("ocr_lines", None)
    st.session_state["result_fingerprint"] = input_fingerprint

st.markdown("### Validation overview")
st.caption(f"FHIR bundle parsed: {len(observations)} Observation resources. Azure OCR and comparison run when you click Validate.")
if st.button("Validate", type="primary"):
    endpoint = os.getenv("VISION_ENDPOINT", "").strip()
    key = os.getenv("VISION_KEY", "").strip()
    if not endpoint or not key:
        st.error("Azure credentials are missing. Set VISION_ENDPOINT and VISION_KEY in Render Environment, then redeploy the service.")
    else:
        try:
            with st.spinner("Sending the EHR screenshot region to Azure AI Vision…"):
                lines = azure_read(image_bytes, endpoint, key, crop_percent)
            if not lines:
                st.error("Azure OCR returned no readable text. Try a clearer screenshot or adjust OCR region width.")
            else:
                results = [evaluate_observation(resource, lines, image.width) for resource in observations]
                st.session_state["ocr_lines"] = lines
                st.session_state["validation_results"] = results
                st.success("OCR and deterministic comparison completed.")
        except (RuntimeError, ValueError, requests.RequestException) as exc:
            st.error(str(exc))

results = st.session_state.get("validation_results", [])
if results:
    counts = {
        "Matches": sum(r["Status"] == "Match" for r in results),
        "Mismatches": sum("mismatch" in r["Status"].lower() for r in results),
        "Not found": sum(r["Status"] == "Not found" for r in results),
        "Needs review": sum(r["Status"] == "Needs review" for r in results),
    }
    columns = st.columns(5)
    metrics = [
        ("Observations", len(observations)),
        ("Matches", counts["Matches"]),
        ("Mismatches", counts["Mismatches"]),
        ("Not found", counts["Not found"]),
        ("Needs review", counts["Needs review"]),
    ]
    for column, (label, value) in zip(columns, metrics):
        with column:
            st.markdown(
                f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value">{value}</div></div>',
                unsafe_allow_html=True,
            )
    left, right = st.columns([1.1, 1], gap="large")
    with left:
        st.markdown('<div class="panel-title">Source EHR evidence</div>', unsafe_allow_html=True)
        st.markdown('<div class="muted">Original screenshot with OCR evidence highlighted</div>', unsafe_allow_html=True)
        st.image(draw_evidence_overlay(image, results), use_container_width=True)
        st.caption("Highlights indicate OCR evidence used for the comparison. The original uploaded image is not modified.")
    with right:
        st.markdown('<div class="panel-title">Observation results</div>', unsafe_allow_html=True)
        st.markdown('<div class="muted">FHIR values compared with OCR evidence from the EHR-side crop</div>', unsafe_allow_html=True)
        display_rows = [{key: value for key, value in result.items() if key != "evidence_box"} for result in results]
        display_observation_table(display_rows, height=500)
    with st.expander("OCR text returned by Azure"):
        st.dataframe(
            [{"Text": line["text"], "X": round(line["x1"]), "Y": round(line["y1"])} for line in st.session_state.get("ocr_lines", [])],
            use_container_width=True,
            hide_index=True,
        )
else:
    m1, m2, m3, m4, m5 = st.columns(5)
    metrics = [(m1, "Observations", len(observations)), (m2, "Matches", "—"),
               (m3, "Mismatches", "—"), (m4, "Not found", "—"), (m5, "Needs review", "—")]
    for col, label, value in metrics:
        with col:
            st.markdown(f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value">{value}</div></div>', unsafe_allow_html=True)
    left, right = st.columns([1.1, 1], gap="large")
    with left:
        st.markdown('<div class="panel-title">Source EHR evidence</div>', unsafe_allow_html=True)
        st.image(image, use_container_width=True)
        st.caption("No evidence is highlighted until OCR and comparison have run.")
    with right:
        st.markdown('<div class="panel-title">Observation results</div>', unsafe_allow_html=True)
        rows = []
        for resource in observations:
            value, unit = observation_value(resource)
            rows.append({
                "Observation": observation_name(resource),
                "FHIR value": value,
                "FHIR unit": unit or "—",
                "Source value": "Pending OCR",
                "Source unit": "Pending OCR",
                "Status": "Not evaluated",
                "Observation ID": resource.get("id", "—"),
            })
        display_observation_table(rows, height=500)

with st.expander("FHIR bundle details"):
    st.write(f"Bundle type: `{bundle.get('type', 'unspecified')}`")
    st.write(f"Resources: {len(entries)}")
    st.json({"resourceType": bundle.get("resourceType"), "type": bundle.get("type"), "observation_count": len(observations)})

st.divider()
st.markdown("**Scope note**  This proof of concept uses synthetic data only. OCR locates visible text; deterministic application code compares values and units. It is not a clinical validation tool and does not confirm FHIR conformance.")
