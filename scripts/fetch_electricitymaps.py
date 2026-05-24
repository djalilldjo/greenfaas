"""
Fetch real historical carbon-intensity data from the ElectricityMaps API
into the LWA-compatible CSV format that greenfaas.traces.carbon_csv accepts.

API:    https://api.electricitymap.org/v3/carbon-intensity/past-range
Auth:   header `auth-token: <YOUR_KEY>`
Limit:  free tier has rate limits and date-range restrictions; commercial
        tier has full historical access.

This script writes one CSV per region to real_data/carbon_em/<REGION>.csv
matching the LWA schema:
    Time,Carbon Intensity
    2024-01-01 00:00:00,180.5
    2024-01-01 00:15:00,178.9
    ...

USAGE:

    export ELECTRICITYMAPS_API_KEY=<your-key>
    python scripts/fetch_electricitymaps.py \\
        --zones DE FR GB US-CAL-CISO PL \\
        --start 2024-01-01 --end 2024-01-31 \\
        --out-dir real_data/carbon_em

Then the existing real-data scripts pick this up:

    python scripts/run_real_carbon.py --carbon-dir real_data/carbon_em
    python scripts/run_real_topology.py --carbon-dir real_data/carbon_em

ZONE CODES (ElectricityMaps):
  - DE              Germany
  - FR              France
  - GB              Great Britain
  - PL              Poland (real, replaces our calibrated synthetic)
  - US-CAL-CISO     California (CAISO)
  - SE              Sweden
  - IN-WE / IN-NO   India regions
  - AU-NSW          New South Wales

API DOCS:
    https://static.electricitymaps.com/api/docs/index.html
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

try:
    import urllib.request
    import urllib.error
except ImportError:
    sys.exit("Python 3.x with urllib required.")


API_BASE = "https://api.electricitymap.org/v3/carbon-intensity/past-range"

# ElectricityMaps caps the date range per request; chunk into ~10-day blocks
# to stay under the limit and respect rate limits.
CHUNK_DAYS = 10
SLEEP_BETWEEN_REQUESTS = 1.0  # seconds, to be polite


def fetch_range(zone: str, start: datetime, end: datetime, api_key: str):
    """Fetch a single date range from the API. Returns list of (datetime, gco2eq_kwh)."""
    params = {
        "zone": zone,
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    url = f"{API_BASE}?{urlencode(params)}"
    req = urllib.request.Request(url, headers={"auth-token": api_key})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            import json
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        sys.exit(f"HTTP {e.code} for zone={zone} {params['start']}..{params['end']}\n{body}")
    except urllib.error.URLError as e:
        sys.exit(f"URL error for zone={zone}: {e}")

    out = []
    for entry in data.get("data", []):
        dt_str = entry.get("datetime")
        ci = entry.get("carbonIntensity")
        if dt_str is None or ci is None:
            continue
        # API returns ISO 8601 with Z suffix.
        dt = datetime.strptime(dt_str.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
        out.append((dt, float(ci)))
    return out


def fetch_zone(zone: str, start: datetime, end: datetime, api_key: str):
    """Fetch a full date range by chunking into CHUNK_DAYS blocks."""
    all_rows = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=CHUNK_DAYS), end)
        sys.stderr.write(
            f"  {zone}: {cursor.date()} -> {chunk_end.date()} ... "
        )
        sys.stderr.flush()
        rows = fetch_range(zone, cursor, chunk_end, api_key)
        sys.stderr.write(f"{len(rows)} points\n")
        all_rows.extend(rows)
        cursor = chunk_end
        time.sleep(SLEEP_BETWEEN_REQUESTS)
    # Sort and dedupe (chunk boundaries may produce duplicate endpoints).
    seen = set()
    deduped = []
    for dt, ci in sorted(all_rows):
        if dt in seen:
            continue
        seen.add(dt)
        deduped.append((dt, ci))
    return deduped


def write_lwa_csv(rows, out_path: Path):
    """Write in LWA schema: 'Time,Carbon Intensity' with space-separated timestamps."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        f.write("Time,Carbon Intensity\n")
        for dt, ci in rows:
            f.write(f"{dt.strftime('%Y-%m-%d %H:%M:%S')},{ci}\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--zones", nargs="+", required=True,
                   help="ElectricityMaps zone codes (e.g., DE FR GB US-CAL-CISO PL)")
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--out-dir", type=Path, default=Path("real_data/carbon_em"))
    p.add_argument("--rename", action="store_true",
                   help="Rename US-CAL-CISO -> CAISO, etc., to match existing loader filenames")
    args = p.parse_args()

    api_key = os.environ.get("ELECTRICITYMAPS_API_KEY")
    if not api_key:
        sys.exit(
            "Environment variable ELECTRICITYMAPS_API_KEY is not set.\n"
            "  export ELECTRICITYMAPS_API_KEY=<your-key>\n"
            "and re-run. Do NOT commit your key to source control."
        )

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")
    if end <= start:
        sys.exit("--end must be after --start")

    # Optional rename map so our load_carbon_model_from_dir loader (which
    # expects e.g. "CAISO.csv" or "US-CAISO.csv") finds the files.
    rename_map = {
        "US-CAL-CISO": "US-CAISO",  # canonical name our loader uses
    }

    for zone in args.zones:
        sys.stderr.write(f"\nZone: {zone}\n")
        rows = fetch_zone(zone, start, end, api_key)
        out_name = rename_map.get(zone, zone) if args.rename else zone
        out_path = args.out_dir / f"{out_name}.csv"
        write_lwa_csv(rows, out_path)
        if rows:
            ci_mean = sum(r[1] for r in rows) / len(rows)
            ci_min = min(r[1] for r in rows)
            ci_max = max(r[1] for r in rows)
            sys.stderr.write(
                f"  wrote {len(rows)} rows to {out_path}\n"
                f"    mean={ci_mean:.1f} g, range=[{ci_min:.1f}, {ci_max:.1f}]\n"
            )
        else:
            sys.stderr.write(f"  WARNING: no rows for {zone}\n")


if __name__ == "__main__":
    main()
