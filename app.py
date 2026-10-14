import json
from pathlib import Path

import streamlit as st
from PIL import Image, ImageDraw

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
    .status { display: inline-block; padding: .22rem .5rem; border-radius: 5px; font-size: .78rem; font-weight: 650; }
    .status-match { color: #17603B; background: #E5F4EB; }
    .status-unit { color: #805800; background: #FFF0C2; }
    .status-value { color: #8E3030; background: #FCE8E6; }
    .status-review { color: #4F5D6A; background: #E9EDF0; }
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

st.markdown("""
<div class="hero">
  <div class="eyebrow">Interoperability quality assurance · Proof of concept</div>
  <h1>SourceCheck</h1>
  <p>Compare clinical observations in a FHIR R4 bundle against their supporting evidence in a source EHR screenshot. Review values, units, and evidence locations in one workspace.</p>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### Validation inputs")
    st.caption("This wireframe uses synthetic demonstration data only.")
    use_sample = st.button("Load sample", type="primary", use_container_width=True)
    screenshot_upload = st.file_uploader("EHR screenshot", type=["png", "jpg", "jpeg"])
    bundle_upload = st.file_uploader("FHIR R4 bundle (JSON)", type=["json"])
    st.divider()
    st.markdown("**Pipeline status**")
    st.markdown("`1`  Input selection")
    st.markdown("`2`  OCR evidence extraction")
    st.markdown("`3`  Deterministic comparison")
    st.caption("OCR and validation are placeholders in this wireframe.")

if use_sample:
    st.session_state["load_sample"] = True

image = None
bundle = None
try:
    if screenshot_upload is not None:
        image = Image.open(screenshot_upload).convert("RGB")
    elif st.session_state.get("load_sample") and IMAGE_PATH.exists():
        image = Image.open(IMAGE_PATH).convert("RGB")
except Exception as exc:
    st.error(f"Could not read screenshot: {exc}")

try:
    if bundle_upload is not None:
        bundle = json.load(bundle_upload)
    elif st.session_state.get("load_sample") and BUNDLE_PATH.exists():
        with open(BUNDLE_PATH, encoding="utf-8") as f:
            bundle = json.load(f)
except Exception as exc:
    st.error(f"Could not read FHIR JSON: {exc}")

if image is None or bundle is None:
    st.info("Load the synthetic sample or provide both input files to begin.")
    left, right = st.columns([1.15, 1])
    with left:
        st.markdown("#### Review workflow")
        st.markdown("1. Load an EHR screenshot and FHIR R4 bundle.\n2. Run validation.\n3. Review per-observation status and supporting source evidence.")
    with right:
        st.markdown("#### Planned validation states")
        st.markdown("- **Match** — values and units agree.\n- **Value mismatch** — numerical values differ.\n- **Unit mismatch** — units differ.\n- **Not found** — source evidence is absent.\n- **Needs review** — evidence is ambiguous.")
    st.stop()

entries = bundle.get("entry", []) if isinstance(bundle, dict) else []
observations = [
    entry.get("resource", {})
    for entry in entries
    if isinstance(entry, dict)
    and isinstance(entry.get("resource"), dict)
    and entry["resource"].get("resourceType") == "Observation"
]

def observation_name(resource):
    code = resource.get("code", {})
    if code.get("text"):
        return code["text"]
    for coding in code.get("coding", []):
        if coding.get("display"):
            return coding["display"]
    return resource.get("id", "Unnamed observation")

def observation_value(resource):
    quantity = resource.get("valueQuantity", {})
    if "value" not in quantity:
        return "—", quantity.get("unit", "")
    return str(quantity["value"]), quantity.get("unit", quantity.get("code", ""))

st.markdown("### Validation overview")
st.caption("Input bundle parsed for display. Comparison results below are illustrative wireframe data, not OCR findings.")
m1, m2, m3, m4, m5 = st.columns(5)
metrics = [
    (m1, "Observations", len(observations)),
    (m2, "Matches", "—"),
    (m3, "Mismatches", "—"),
    (m4, "Not found", "—"),
    (m5, "Needs review", "—"),
]
for col, label, value in metrics:
    with col:
        st.markdown(f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value">{value}</div></div>', unsafe_allow_html=True)

st.write("")
validate = st.button("Validate sample", type="primary")
if validate:
    st.warning("Wireframe only: OCR extraction and deterministic comparison have not been implemented. No match or mismatch is being asserted.")

left, right = st.columns([1.1, 1], gap="large")
with left:
    st.markdown('<div class="panel-title">Source EHR evidence</div>', unsafe_allow_html=True)
    st.markdown('<div class="muted">Original screenshot preview · evidence overlays will appear here</div>', unsafe_allow_html=True)
    st.image(image, use_container_width=True)
    st.caption("The final implementation should OCR only the EHR panel, exclude any illustrative JSON panel, and preserve source-image coordinates.")
with right:
    st.markdown('<div class="panel-title">Observation results</div>', unsafe_allow_html=True)
    st.markdown('<div class="muted">FHIR observations discovered from the uploaded bundle</div>', unsafe_allow_html=True)
    rows = []
    for resource in observations:
        value, unit = observation_value(resource)
        rows.append({
            "Observation": observation_name(resource),
            "FHIR value": value,
            "FHIR unit": unit or "—",
            "Source value": "Pending OCR",
            "Status": "Not evaluated",
            "Observation ID": resource.get("id", "—"),
        })
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True, height=430)
    else:
        st.warning("No Observation resources were found in this bundle.")
    with st.expander("FHIR bundle details"):
        st.write(f"Bundle type: `{bundle.get('type', 'unspecified')}`")
        st.write(f"Resources: {len(entries)}")
        st.json({"resourceType": bundle.get("resourceType"), "type": bundle.get("type"), "observation_count": len(observations)})

st.divider()
st.markdown("**Scope note**  This is a UI wireframe, not a clinical validation tool. Use synthetic data only. It does not perform OCR, validate clinical accuracy, or confirm FHIR conformance.")
