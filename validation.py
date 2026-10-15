import re
from decimal import Decimal, InvalidOperation

from PIL import Image, ImageDraw


def observation_name(resource):
    code = resource.get("code", {})
    if code.get("text"):
        return str(code["text"])
    for coding in code.get("coding", []):
        if coding.get("display"):
            return str(coding["display"])
    return str(resource.get("id", "Unnamed observation"))


def observation_value(resource):
    quantity = resource.get("valueQuantity", {})
    if "value" not in quantity:
        return "—", str(quantity.get("unit", quantity.get("code", "")))
    return str(quantity["value"]), str(quantity.get("unit", quantity.get("code", "")))


def normalize_text(value):
    value = str(value).lower().replace("₂", "2").replace("³", "3")
    value = value.replace("ckd epi", "ckd-epi")
    return re.sub(r"[^a-z0-9]+", "", value)


def normalize_unit(value):
    unit = normalize_text(value)
    aliases = {
        "10*3ul": "10^3ul",
        "103ul": "10^3ul",
        "10^3ul": "10^3ul",
        "mlmin173m2": "mlmin173m2",
        "mlmin173m": "mlmin173m2",
        "umol/l": "umoll",
    }
    return aliases.get(unit, unit)


def parse_fhir_observations(bundle):
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise ValueError("The JSON input must be a FHIR Bundle.")
    entries = bundle.get("entry", [])
    if not isinstance(entries, list):
        raise ValueError("FHIR Bundle.entry must be a JSON array.")
    observations = [
        entry["resource"]
        for entry in entries
        if isinstance(entry, dict)
        and isinstance(entry.get("resource"), dict)
        and entry["resource"].get("resourceType") == "Observation"
    ]
    return entries, observations


def label_aliases(name):
    normalized = normalize_text(name)
    aliases = {
        "wbc count": ["wbccount", "whitebloodcellcount", "wbc"],
        "platelet count": ["plateletcount", "platelets"],
        "co2 bicarbonate": ["co2bicarbonate", "co2", "bicarbonate"],
        "egfr ckd-epi": ["egfrckdepi", "egfr"],
        "glucose fasting": ["glucosefasting", "fastingglucose", "glucose"],
    }
    return aliases.get(name.lower(), [normalized])


def find_label_line(name, lines):
    aliases = label_aliases(name)
    # Azure Read provides word boxes as well as line text. Group words by row and
    # reconstruct multi-word labels while retaining a tight box around the label.
    rows = []
    for line in sorted(lines, key=lambda item: item["cy"]):
        row = next((group for group in rows if abs(group[0]["cy"] - line["cy"]) <= 10), None)
        if row is None:
            rows.append([line])
        else:
            row.append(line)

    candidates = []
    for row in rows:
        row.sort(key=lambda item: item["x1"])
        for start in range(len(row)):
            combined = ""
            for end in range(start, min(len(row), start + 6)):
                combined += normalize_text(row[end]["text"])
                if not combined:
                    continue
                for alias in aliases:
                    if combined == alias:
                        selected = row[start:end + 1]
                        box = {
                            "text": " ".join(item["text"] for item in selected),
                            "x1": min(item["x1"] for item in selected),
                            "y1": min(item["y1"] for item in selected),
                            "x2": max(item["x2"] for item in selected),
                            "y2": max(item["y2"] for item in selected),
                            "cx": (min(item["x1"] for item in selected) + max(item["x2"] for item in selected)) / 2,
                            "cy": sum(item["cy"] for item in selected) / len(selected),
                        }
                        candidates.append((0, len(combined) - len(alias), box))
                    elif len(alias) >= 5 and alias in combined:
                        candidates.append((1, len(combined) - len(alias), row[start]))
    return min(candidates, key=lambda item: (item[0], item[1]))[2] if candidates else None


def parse_numeric(text):
    cleaned = text.strip().replace(",", "")
    match = re.search(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", cleaned)
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def evaluate_observation(resource, lines, image_width):
    name = observation_name(resource)
    fhir_value, fhir_unit = observation_value(resource)
    label = find_label_line(name, lines)
    result = {
        "Observation": name,
        "FHIR value": fhir_value,
        "FHIR unit": fhir_unit or "—",
        "Source value": "—",
        "Source unit": "—",
        "Status": "Not found",
        "Observation ID": resource.get("id", "—"),
        "evidence_box": None,
    }
    if label is None:
        return result

    # Group OCR fragments by the label's table row. Keep the left-side value and
    # unit columns, not reference ranges or collection dates farther to the right.
    row = [line for line in lines if abs(line["cy"] - label["cy"]) <= max(12, (label["y2"] - label["y1"]) * 1.5)]
    row = sorted(row, key=lambda line: line["x1"])
    value_candidates = [
        line for line in row
        if line["x1"] > label["x1"] and line["cx"] < image_width * 0.52
        and re.fullmatch(r"\s*[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?\s*", line["text"]) is not None
    ]
    if not value_candidates:
        result["Status"] = "Needs review"
        result["evidence_box"] = [label["x1"], label["y1"], label["x2"], label["y2"]]
        return result

    value_line = min(value_candidates, key=lambda line: line["x1"])
    source_numeric = parse_numeric(value_line["text"])
    result["Source value"] = str(source_numeric)
    expected_numeric = parse_numeric(fhir_value)
    unit_candidates = [
        line for line in row
        if line["x1"] >= value_line["x2"] - 2
        and line["cx"] < image_width * 0.68
        and (re.search(r"[A-Za-zµμ]", line["text"]) is not None or "%" in line["text"])
        and (normalize_unit(line["text"]) not in {"", "referencerange", "collectiondate"} or "%" in line["text"])
    ]
    unit_line = min(unit_candidates, key=lambda line: line["x1"]) if unit_candidates else None
    if unit_line:
        result["Source unit"] = unit_line["text"]

    boxes = [label, value_line] + ([unit_line] if unit_line else [])
    result["evidence_box"] = [
        min(line["x1"] for line in boxes),
        min(line["y1"] for line in boxes),
        max(line["x2"] for line in boxes),
        max(line["y2"] for line in boxes),
    ]

    if expected_numeric is None or source_numeric is None or not unit_line:
        result["Status"] = "Needs review"
        return result

    units_match = normalize_unit(result["Source unit"]) == normalize_unit(fhir_unit)
    values_match = source_numeric == expected_numeric
    if units_match and values_match:
        result["Status"] = "Match"
    elif not units_match and values_match:
        result["Status"] = "Unit mismatch"
    elif units_match and not values_match:
        result["Status"] = "Value mismatch"
    else:
        result["Status"] = "Value and unit mismatch"
    return result


def draw_evidence_overlay(image, results):
    annotated = image.convert("RGB").copy()
    draw = ImageDraw.Draw(annotated)
    colors = {
        "Match": "#1D8A52",
        "Unit mismatch": "#C28A00",
        "Value mismatch": "#C0392B",
        "Value and unit mismatch": "#8E3030",
        "Not found": "#64748B",
        "Needs review": "#64748B",
    }
    for result in results:
        box = result.get("evidence_box")
        if not box:
            continue
        x1, y1, x2, y2 = [int(round(value)) for value in box]
        color = colors.get(result["Status"], "#64748B")
        draw.rectangle((x1 - 3, y1 - 3, x2 + 3, y2 + 3), outline=color, width=3)
    return annotated


