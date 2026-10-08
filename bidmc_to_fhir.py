#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bidmc_to_fhir.py - Chuyen doi BIDMC PPG and Respiration Dataset sang FHIR R4.

Moi ban ghi (bidmc_XX) -> 1 Bundle (type=transaction) gom:
  Patient, Location, Encounter, Device, Practitioner (nguoi chu thich nhip tho),
  Observation tuoi, Observation chi so 1 Hz (HR, PULSE, RESP, SpO2),
  Observation tin hieu song 125 Hz (RESP, PLETH, V, AVR, II) dang valueSampledData,
  Observation chu thich nhip tho (moi nguoi chu thich 1 Observation).

Yeu cau: Python >= 3.8, KHONG can thu vien ngoai cho phan chuyen doi.
Tuy chon: `pip install fhir.resources` de dung --validate.

Cach dung:
  python bidmc_to_fhir.py --input-dir ./bidmc_csv --output-dir ./fhir_out
  python bidmc_to_fhir.py --input-dir ./bidmc_csv --output-dir ./fhir_out --records 01 02 --validate
  python bidmc_to_fhir.py --input-dir ./bidmc_csv --output-dir ./fhir_out --split
  python bidmc_to_fhir.py --input-dir ./bidmc_csv --post http://localhost:8080/fhir

Ten file dau vao (cung thu muc): bidmc_XX_Fix.txt, bidmc_XX_Numerics.csv,
bidmc_XX_Signals.csv, bidmc_XX_Breaths.csv
"""
import argparse
import csv
import json
import math
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

# ----------------------------------------------------------------------------
# CAU HINH MA HOA (sua tai day neu muon doi he ma)
# ----------------------------------------------------------------------------
LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
CAT_SYSTEM = "http://terminology.hl7.org/CodeSystem/observation-category"
LOCAL_CS = "https://example.org/fhir/CodeSystem/bidmc"          # ma noi bo (doi thanh domain cua ban)
ID_SYSTEM = "https://physionet.org/content/bidmc/record"        # dinh danh ban ghi BIDMC
MIMIC_SYSTEM = "https://physionet.org/content/mimic2wdb-matched/wdb-id"

# Chi so 1 Hz: ten cot -> (LOINC, display, don vi UCUM, nhan don vi)
# Da doi chieu LOINC: 8867-4 Heart rate; 8889-8 Heart rate by Pulse oximetry;
# 9279-1 Respiratory rate; 59408-5 Oxygen saturation in Arterial blood by Pulse oximetry.
NUMERICS = {
    "HR":    ("8867-4",  "Heart rate",                                          "/min", "/min"),
    "PULSE": ("8889-8",  "Heart rate by Pulse oximetry",                        "/min", "/min"),
    "RESP":  ("9279-1",  "Respiratory rate",                                    "/min", "/min"),
    "SpO2":  ("59408-5", "Oxygen saturation in Arterial blood by Pulse oximetry", "%",  "%"),
}

# Tin hieu song 125 Hz. Chua co ma LOINC chuan da xac minh -> dung ma noi bo.
# Neu ban co ma LOINC/MDC phu hop, thay vao 'system' va 'code' o day.
# (system, code, display, category)
WAVEFORMS = {
    "RESP":  (LOCAL_CS, "resp-impedance-waveform", "Respiration impedance waveform", "vital-signs"),
    "PLETH": (LOCAL_CS, "ppg-waveform",            "Photoplethysmogram (PPG) waveform", "vital-signs"),
    "II":    (LOCAL_CS, "ecg-lead-II-waveform",    "ECG lead II waveform", "procedure"),
    "V":     (LOCAL_CS, "ecg-lead-V-waveform",     "ECG lead V waveform", "procedure"),
    "AVR":   (LOCAL_CS, "ecg-lead-aVR-waveform",   "ECG lead aVR waveform", "procedure"),
}

LOCATIONS = {
    "micu": "Medical Intensive Care Unit",
    "sicu": "Surgical Intensive Care Unit",
    "ccu":  "Coronary Care Unit",
    "csru": "Cardiac Surgery Recovery Unit",
    "nicu": "Neonatal Intensive Care Unit",
}

GENDER = {"M": "male", "F": "female"}


# ----------------------------------------------------------------------------
# DOC DU LIEU
# ----------------------------------------------------------------------------
def read_fix(path):
    """Doc bidmc_XX_Fix.txt -> dict. Dong dau la ten ban ghi."""
    meta = {}
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    meta["record"] = lines[0].strip()
    for ln in lines[1:]:
        if ": " in ln:
            k, v = ln.split(": ", 1)  # tach o dau ': ' dau tien (URL co 'http:')
            meta[k.strip()] = v.strip()
    return meta


def read_csv_cols(path):
    """Doc CSV, tra ve (ten_cot_da_strip, {cot: [chuoi]}). Giu nguyen chuoi so goc."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = [h.strip() for h in next(reader)]
        cols = {h: [] for h in header}
        for row in reader:
            if not row or all(not c.strip() for c in row):
                continue
            for h, v in zip(header, row):
                cols[h].append(v.strip())
    return header, cols


def sample_token(v):
    """Chuoi so -> token SampledData. NaN/rong -> 'E' (loi do) theo FHIR R4."""
    if v == "" or v.lower() in ("nan", "inf", "-inf", "null"):
        return "E"
    try:
        if not math.isfinite(float(v)):
            return "E"
    except ValueError:
        return "E"
    return v


def to_sampled_data(values, period_ms, unit_code, unit_label, system=UCUM):
    return {
        "origin": {"value": 0, "unit": unit_label, "system": system, "code": unit_code},
        "period": period_ms,
        "dimensions": 1,
        "data": " ".join(sample_token(v) for v in values),
    }


def parse_segment_time(s, tz):
    """'2688-03-25-23-14' -> '2688-03-25T23:14:00Z' (ngay trong MIMIC da bi doi, la gia)."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})", s or "")
    if not m:
        return None
    y, mo, d, h, mi = m.groups()
    return f"{y}-{mo}-{d}T{h}:{mi}:00{tz}"


def add_seconds(iso, seconds):
    """Cong giay vao chuoi ISO (nam co the > 9999? khong - nam 2688 van hop le voi datetime)."""
    tz = iso[19:]
    dt = datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")
    from datetime import timedelta
    dt = dt + timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + tz


# ----------------------------------------------------------------------------
# DUNG RESOURCE
# ----------------------------------------------------------------------------
def entry(resource):
    rt, rid = resource["resourceType"], resource["id"]
    return {
        "fullUrl": f"{rt}/{rid}",
        "resource": resource,
        "request": {"method": "PUT", "url": f"{rt}/{rid}"},  # PUT voi id co dinh -> chay lai khong tao trung
    }


def ref(rt, rid):
    return {"reference": f"{rt}/{rid}"}


def category(code):
    return [{"coding": [{"system": CAT_SYSTEM, "code": code}]}]


def build_bundle(rec_dir, rec_no, tz="Z"):
    d = Path(rec_dir)
    prefix = f"bidmc_{rec_no}"
    fix = read_fix(d / f"{prefix}_Fix.txt")
    num_header, num = read_csv_cols(d / f"{prefix}_Numerics.csv")
    sig_header, sig = read_csv_cols(d / f"{prefix}_Signals.csv")
    br_header, br = read_csv_cols(d / f"{prefix}_Breaths.csv")

    rid = f"bidmc-{rec_no}"
    fs_sig = float(re.search(r"[\d.]+", fix["Signals sampling frequency"]).group())
    fs_num = float(re.search(r"[\d.]+", fix["Numerics sampling frequency"]).group())
    period_sig = round(1000.0 / fs_sig, 6)   # ms
    period_num = round(1000.0 / fs_num, 6)

    # --- kiem tra nhat quan: tan so trong Fix.txt khop voi cot Time cua CSV ---
    t = sig["Time [s]"]
    if len(t) > 1:
        dt_ms = (float(t[1]) - float(t[0])) * 1000
        if abs(dt_ms - period_sig) > 0.01:
            print(f"[CANH BAO] {prefix}: Signals.csv buoc {dt_ms} ms != {period_sig} ms theo Fix.txt", file=sys.stderr)

    start = parse_segment_time(fix.get("MIMIC II data segment"), tz) or "2000-01-01T00:00:00" + tz
    n_sig = len(t)
    n_num = len(num["Time [s]"])
    end = add_seconds(start, (n_sig - 1) / fs_sig)
    effective = {"start": start, "end": end}

    entries = []

    # --- Patient ---
    patient = {
        "resourceType": "Patient",
        "id": rid,
        "identifier": [
            {"use": "official", "system": ID_SYSTEM, "value": fix["record"]},
            {"use": "secondary", "system": MIMIC_SYSTEM, "value": fix.get("MIMIC II matched wdb ID", "")},
        ],
        "gender": GENDER.get(fix.get("Gender", "").upper(), "unknown"),
    }
    # (tuoi duoc ghi bang Observation 30525-0 vi bo du lieu khong co ngay sinh)
    patient["identifier"] = [i for i in patient["identifier"] if i["value"]]
    entries.append(entry(patient))

    # --- Location + Encounter ---
    loc_key = fix.get("Location", "").lower()
    location = {
        "resourceType": "Location",
        "id": f"{rid}-{loc_key or 'unknown'}",
        "status": "active",
        "name": LOCATIONS.get(loc_key, loc_key.upper() or "Unknown"),
        "alias": [loc_key] if loc_key else [],
        "mode": "instance",
        "type": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-RoleCode", "code": "ICU",
                              "display": "Intensive care unit"}]}],
    }
    if not location["alias"]:
        del location["alias"]
    entries.append(entry(location))

    encounter = {
        "resourceType": "Encounter",
        "id": rid,
        "status": "finished",
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "IMP",
                  "display": "inpatient encounter"},
        "subject": ref("Patient", rid),
        "location": [{"location": ref("Location", location["id"])}],
        "identifier": [{"system": MIMIC_SYSTEM, "value": fix.get("MIMIC II data segment", "")}]
        if fix.get("MIMIC II data segment") else [],
    }
    if not encounter["identifier"]:
        del encounter["identifier"]
    entries.append(entry(encounter))

    # --- Device (may theo doi canh giuong) ---
    device = {
        "resourceType": "Device",
        "id": f"{rid}-monitor",
        "status": "active",
        "deviceName": [{"name": "Bedside patient monitor", "type": "user-friendly-name"}],
        "type": {"text": "Bedside patient monitor (ECG, PPG, impedance respiration, pulse oximetry)"},
        "patient": ref("Patient", rid),
    }
    entries.append(entry(device))

    common = {
        "status": "final",
        "subject": ref("Patient", rid),
        "encounter": ref("Encounter", rid),
        "device": ref("Device", device["id"]),
    }

    # --- Observation: tuoi ---
    if fix.get("Age", "").isdigit():
        entries.append(entry({
            "resourceType": "Observation", "id": f"{rid}-age",
            "status": "final", "category": category("social-history"),
            "code": {"coding": [{"system": LOINC, "code": "30525-0", "display": "Age"}]},
            "subject": ref("Patient", rid), "encounter": ref("Encounter", rid),
            "effectiveDateTime": start,
            "valueQuantity": {"value": int(fix["Age"]), "unit": "year", "system": UCUM, "code": "a"},
        }))

    # --- Observation: chi so 1 Hz ---
    for col, (code, display, ucum, label) in NUMERICS.items():
        if col not in num:
            print(f"[CANH BAO] {prefix}: thieu cot {col} trong Numerics.csv", file=sys.stderr)
            continue
        entries.append(entry({
            "resourceType": "Observation", "id": f"{rid}-num-{col.lower()}",
            **common,
            "category": category("vital-signs"),
            "code": {"coding": [{"system": LOINC, "code": code, "display": display}],
                     "text": f"{col} (1 Hz)"},
            "effectivePeriod": {"start": start, "end": add_seconds(start, (n_num - 1) / fs_num)},
            "valueSampledData": to_sampled_data(num[col], period_num, ucum, label),
            "note": [{"text": "Gia tri 'E' = mat tin hieu / khong do duoc (NaN trong du lieu goc). "
                              "Mau thu i xay ra tai start + i * period."}],
        }))

    # --- Observation: tin hieu song 125 Hz ---
    for col, (system, code, display, cat) in WAVEFORMS.items():
        if col not in sig:
            print(f"[CANH BAO] {prefix}: thieu cot {col} trong Signals.csv", file=sys.stderr)
            continue
        entries.append(entry({
            "resourceType": "Observation", "id": f"{rid}-wave-{col.lower()}",
            **common,
            "category": category(cat),
            "code": {"coding": [{"system": system, "code": code, "display": display}],
                     "text": f"{col} ({fs_sig:g} Hz)"},
            "effectivePeriod": effective,
            "valueSampledData": to_sampled_data(sig[col], period_sig, "1", "normalized"),
            "note": [{"text": "Tin hieu da chuan hoa (khong co don vi vat ly) theo dinh dang BIDMC."}],
        }))

    # --- Practitioner + Observation: chu thich nhip tho ---
    ann_cols = [c for c in br_header if c.startswith("breaths ann")]
    for i, col in enumerate(ann_cols, start=1):
        pid = f"bidmc-annotator-{i}"
        if not any(e["resource"]["id"] == pid for e in entries):
            entries.append(entry({
                "resourceType": "Practitioner", "id": pid,
                "identifier": [{"system": f"{ID_SYSTEM}/annotator", "value": f"annotator-{i}"}],
                "name": [{"text": f"Breath annotator {i}"}],
            }))
        comps = []
        for sample_no in br[col]:
            if not sample_no or sample_no.lower() in ("nan", "inf", "-inf", "null"):
                continue
            comps.append({
                "code": {"coding": [{"system": LOCAL_CS, "code": "breath-onset-time",
                                     "display": "Breath annotation time from record start"}]},
                "valueQuantity": {"value": round(int(sample_no) / fs_sig, 3), "unit": "s",
                                  "system": UCUM, "code": "s"},
            })
        entries.append(entry({
            "resourceType": "Observation", "id": f"{rid}-breaths-ann{i}",
            "status": "final", "category": category("exam"),
            "code": {"coding": [{"system": LOCAL_CS, "code": "breath-annotations",
                                 "display": "Manual breath annotations"}]},
            "subject": ref("Patient", rid), "encounter": ref("Encounter", rid),
            "effectivePeriod": effective,
            "performer": [ref("Practitioner", pid)],
            "valueInteger": len(comps),
            "component": comps,
            "note": [{"text": f"{len(comps)} nhip tho do nguoi chu thich {i} danh dau; "
                              f"moi component la thoi diem (giay) tinh tu dau ban ghi = so mau / {fs_sig:g} Hz."}],
        }))

    return {"resourceType": "Bundle", "id": rid, "type": "transaction", "entry": entries}


# ----------------------------------------------------------------------------
# KIEM TRA
# ----------------------------------------------------------------------------
def check_integrity(bundle):
    """Kiem tra don gian khong can thu vien: id duy nhat, reference tro dung."""
    errs = []
    ids = set()
    for e in bundle["entry"]:
        r = e["resource"]
        key = f'{r["resourceType"]}/{r["id"]}'
        if key in ids:
            errs.append(f"Trung id: {key}")
        ids.add(key)
    def walk(o):
        if isinstance(o, dict):
            if "reference" in o and isinstance(o["reference"], str) and o["reference"] not in ids:
                errs.append(f"Reference khong ton tai: {o['reference']}")
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(bundle)
    for e in bundle["entry"]:
        r = e["resource"]
        sd = r.get("valueSampledData")
        if sd:
            n = len(sd["data"].split())
            if n == 0:
                errs.append(f'{r["id"]}: SampledData rong')
    return errs


def validate_fhir(bundle):
    """Kiem tra cau truc R4 bang fhir.resources (neu da cai)."""
    try:
        from fhir.resources.R4B.bundle import Bundle  # fhir.resources >= 7/8
    except ImportError:
        try:
            from fhir.resources.bundle import Bundle   # fhir.resources 6.x (R4)
        except ImportError:
            print("[BO QUA] Chua cai fhir.resources: pip install fhir.resources", file=sys.stderr)
            return []
    try:
        Bundle.model_validate(bundle) if hasattr(Bundle, "model_validate") else Bundle.parse_obj(bundle)
        return []
    except Exception as ex:  # noqa
        return [str(ex)]


# ----------------------------------------------------------------------------
# GHI / GUI
# ----------------------------------------------------------------------------
def write_json(path, obj, indent=2):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)


def post_bundle(base_url, bundle):
    req = urllib.request.Request(
        base_url.rstrip("/"), data=json.dumps(bundle).encode("utf-8"),
        headers={"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.status


FIX_RE = re.compile(r"bidmc_(\d+)_Fix\.txt", re.IGNORECASE)


def locate_input_dir(input_dir):
    """Tim thu muc thuc su chua bidmc_XX_Fix.txt (ke ca khi nam trong thu muc con).
    Tra ve (thu_muc, danh_sach_so_ban_ghi). Neu khong thay -> (None, [])."""
    base = Path(input_dir).resolve()
    candidates = [base] + sorted(p for p in base.rglob("*") if p.is_dir()) if base.is_dir() else []
    for d in candidates:
        nums = sorted(m.group(1) for p in d.iterdir()
                      if p.is_file() and (m := FIX_RE.fullmatch(p.name)))
        if nums:
            return d, nums
    return None, []


def describe_dir(input_dir):
    """Liet ke toi da 15 muc trong thu muc de nguoi dung thay script dang nhin vao dau."""
    base = Path(input_dir).resolve()
    if not base.exists():
        return f"Thu muc khong ton tai: {base}"
    names = sorted(p.name + ("/" if p.is_dir() else "") for p in base.iterdir())
    shown = ", ".join(names[:15]) + (" ..." if len(names) > 15 else "")
    return f"Dang tim trong: {base}\nTrong do co: {shown or '(trong)'}"


def main():
    ap = argparse.ArgumentParser(description="BIDMC -> FHIR R4 (Bundle transaction)")
    ap.add_argument("--input-dir", required=True, help="Thu muc chua bidmc_XX_*.csv / *_Fix.txt")
    ap.add_argument("--output-dir", default="fhir_out")
    ap.add_argument("--records", nargs="*", help="Chi chuyen cac ban ghi nay, vd: 01 02. Mac dinh: tat ca")
    ap.add_argument("--tz", default="Z", help="Mui gio gan cho thoi gian (mac dinh Z). Vd +00:00")
    ap.add_argument("--split", action="store_true", help="Ghi them tung resource ra file JSON rieng")
    ap.add_argument("--pretty", action="store_true", help="JSON thut le (file se lon hon)")
    ap.add_argument("--validate", action="store_true", help="Kiem tra bang fhir.resources (R4B)")
    ap.add_argument("--post", metavar="FHIR_BASE_URL", help="Gui Bundle len FHIR server")
    args = ap.parse_args()

    in_dir, found = locate_input_dir(args.input_dir)
    if in_dir is None:
        sys.exit("Khong tim thay file bidmc_XX_Fix.txt (ke ca trong thu muc con).\n"
                 + describe_dir(args.input_dir) + "\n"
                 "Goi y: kiem tra ten file (Windows co the an duoi .txt, vd 'bidmc_01_Fix.txt.txt') "
                 "va dung duong dan --input-dir.")
    if in_dir != Path(args.input_dir).resolve():
        print(f"[INFO] Dung du lieu trong: {in_dir}")
    args.input_dir = str(in_dir)
    records = args.records or found

    ok = True
    for rec in records:
        rec = rec.zfill(2)
        try:
            bundle = build_bundle(args.input_dir, rec, tz=args.tz)
        except FileNotFoundError as ex:
            print(f"[LOI] bidmc_{rec}: thieu file {ex.filename}", file=sys.stderr)
            ok = False
            continue

        errs = check_integrity(bundle)
        if args.validate:
            errs += validate_fhir(bundle)
        if errs:
            ok = False
            print(f"[LOI] bidmc_{rec}:", *errs[:10], sep="\n  ", file=sys.stderr)
            continue

        out = Path(args.output_dir)
        write_json(out / f"bidmc_{rec}_bundle.json", bundle, indent=2 if args.pretty else None)
        if args.split:
            for e in bundle["entry"]:
                r = e["resource"]
                write_json(out / f"bidmc_{rec}" / f'{r["resourceType"]}_{r["id"]}.json', r,
                           indent=2 if args.pretty else None)
        print(f"[OK] bidmc_{rec}: {len(bundle['entry'])} resource -> {out / f'bidmc_{rec}_bundle.json'}")

        if args.post:
            status = post_bundle(args.post, bundle)
            print(f"     POST {args.post} -> HTTP {status}")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()