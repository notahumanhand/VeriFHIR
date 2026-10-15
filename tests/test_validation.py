import json
from pathlib import Path

import pytest

from validation import evaluate_observation, normalize_unit, parse_fhir_observations

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_BUNDLE = ROOT / "sample_data" / "synthetic_ehr_bundle.json"


def word(text, x, y, width=35, height=12):
    return {
        "text": text,
        "x1": x, "y1": y,
        "x2": x + width, "y2": y + height,
        "cx": x + width / 2, "cy": y + height / 2,
    }


def baseline_ocr_lines(observations):
    lines = []
    source_values = {
        "obs-hemoglobin": ("13.5", "g/dL"),
        "obs-hematocrit": ("41.2", "%"),
        "obs-wbc": ("7.8", "10^3/uL"),
        "obs-platelets": ("250", "10^3/uL"),
        "obs-sodium": ("140", "mmol/L"),
        "obs-potassium": ("4.2", "mmol/L"),
        "obs-chloride": ("102", "mmol/L"),
        "obs-bicarbonate": ("24", "mmol/L"),
        "obs-bun": ("14", "mg/dL"),
        "obs-creatinine": ("0.9", "mg/dL"),
        "obs-egfr": ("95", "mL/min/1.73m²"),
        "obs-glucose": ("88", "mg/dL"),
        "obs-calcium": ("9.4", "mg/dL"),
    }
    for index, observation in enumerate(observations):
        y = 100 + index * 30
        name = observation["code"].get("text", "")
        x = 100
        for token in name.split():
            lines.append(word(token, x, y))
            x += len(token) * 7 + 8
        value, unit = source_values[observation["id"]]
        lines.append(word(value, 350, y, width=max(20, len(value) * 8)))
        lines.append(word(unit, 455, y, width=max(20, len(unit) * 7)))
    return lines


def test_sample_bundle_contains_thirteen_observations():
    bundle = json.loads(SAMPLE_BUNDLE.read_text(encoding="utf-8"))
    _, observations = parse_fhir_observations(bundle)
    assert len(observations) == 13


def test_baseline_has_eleven_matches_and_two_expected_discrepancies():
    bundle = json.loads(SAMPLE_BUNDLE.read_text(encoding="utf-8"))
    _, observations = parse_fhir_observations(bundle)
    lines = baseline_ocr_lines(observations)
    results = [evaluate_observation(item, lines, image_width=955) for item in observations]
    statuses = {result["Observation ID"]: result["Status"] for result in results}
    assert sum(status == "Match" for status in statuses.values()) == 11
    assert statuses["obs-hemoglobin"] == "Unit mismatch"
    assert statuses["obs-potassium"] == "Value mismatch"


def test_wrong_input_is_rejected():
    with pytest.raises(ValueError, match="FHIR Bundle"):
        parse_fhir_observations({"resourceType": "Patient"})


def test_equivalent_display_units_are_normalized():
    assert normalize_unit("10^3/uL") == normalize_unit("10*3/uL")
