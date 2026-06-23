"""
update_indicators.py
====================
Switch & Vault — I1-I6 Indicator Board Updater
Runs weekly via GitHub Actions (see .github/workflows/update.yml).

WHAT THIS SCRIPT DOES
---------------------
1. Fetches automatable data series (IMF COFER, FRED gold price, FRED dollar index)
2. Loads manual_overrides.json for indicators that require human judgment
3. Merges everything into data.json (preserving existing text/detail fields)
4. Prints a change summary for the GitHub Actions log

AUTOMATABLE vs MANUAL
---------------------
  I1 (Coercion-Failure)     → MANUAL  — requires event coding, not a data pull
  I2 (Reserve Diversification) → AUTO  — IMF COFER API + FRED gold price
  I3 (Mineral Chokepoint)   → MANUAL  — USGS has no real-time API
  I4 (Indigenization)       → MANUAL  — TrendForce is commercial/paywalled
  I5 (Entanglement-Seam)    → MANUAL  — requires SEC filing review
  I6 (Regionalization)      → MANUAL  — mBridge/e-CNY figures are self-reported

HOW TO UPDATE MANUAL INDICATORS
--------------------------------
Edit manual_overrides.json in the repo root. The format is:
  {
    "I1": { "status": "TRIGGERED", "summary": "...", "detail": "...", "last_reviewed": "2026-06-22" },
    ...
  }
Commit the updated file. GitHub Actions will pick it up on next run (or trigger manually).

DEPENDENCIES
------------
  pip install requests python-dateutil
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: 'requests' not installed. Run: pip install requests")
    sys.exit(1)

# ── Config ─────────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent
DATA_FILE    = SCRIPT_DIR / "data.json"
OVERRIDES_FILE = SCRIPT_DIR / "manual_overrides.json"

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")  # Set in GitHub Actions secrets
FRED_BASE    = "https://api.stlouisfed.org/fred/series/observations"

IMF_BASE     = "https://dataservices.imf.org/REST/SDMX_JSON.svc"

HEADERS = {"User-Agent": "switch-vault-dashboard/1.0 (research; jeremycody@arizona.edu)"}


# ── FRED data fetch ─────────────────────────────────────────────────────────

def fetch_fred(series_id: str, limit: int = 5) -> list[dict]:
    """
    Fetch most recent N observations for a FRED series.
    Returns list of {"date": "YYYY-MM-DD", "value": float} dicts.
    Falls back gracefully if API key absent or request fails.
    """
    if not FRED_API_KEY:
        print(f"  [FRED/{series_id}] No API key — skipping auto-fetch.")
        print(f"    → Get a free key at https://fred.stlouisfed.org/docs/api/fred/")
        print(f"    → Add it as a GitHub Actions secret named FRED_API_KEY")
        return []

    params = {
        "series_id":        series_id,
        "api_key":          FRED_API_KEY,
        "file_type":        "json",
        "sort_order":       "desc",
        "limit":            limit,
        "observation_start": "2024-01-01",
    }
    try:
        r = requests.get(FRED_BASE, params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        obs = r.json().get("observations", [])
        results = []
        for o in obs:
            try:
                results.append({"date": o["date"], "value": float(o["value"])})
            except (ValueError, KeyError):
                continue
        return results
    except Exception as e:
        print(f"  [FRED/{series_id}] Request failed: {e}")
        return []


# ── IMF COFER fetch ────────────────────────────────────────────────────────

def fetch_imf_cofer() -> dict | None:
    """
    Fetch USD share of allocated reserves from IMF COFER dataset.
    Returns {"date": "YYYY-QN", "usd_pct": float} or None on failure.

    IMF COFER series structure:
      COFER / Q / W00 / 1_USD / 1_ALLOC_RES
      = World, USD claims, as share of allocated reserves
    """
    # IMF Data Services — CompactData endpoint
    # Series: COFER.Q.W00.1_USD.1_ALLOC_RES (World, USD, % of allocated)
    url = f"{IMF_BASE}/CompactData/COFER/Q.W00.1_USD.1_ALLOC_RES"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()

        # Navigate IMF's nested SDMX-JSON structure
        series = (
            data
            .get("CompactData", {})
            .get("DataSet", {})
            .get("Series", {})
        )
        observations = series.get("Obs", [])
        if not observations:
            print("  [IMF COFER] No observations returned — series path may have changed.")
            return None

        # Most recent observation
        obs = observations[-1] if isinstance(observations, list) else observations
        period = obs.get("@TIME_PERIOD", "")
        value  = obs.get("@OBS_VALUE", "")

        if period and value:
            return {"date": period, "usd_pct": round(float(value), 2)}
        return None

    except Exception as e:
        print(f"  [IMF COFER] Request failed: {e}")
        return None


# ── Gold price (FRED) ──────────────────────────────────────────────────────

def fetch_gold_price() -> dict | None:
    """
    GOLDAMGBD228NLBM = Gold Fixing Price 10:30 A.M. (London time) in London Bullion Market.
    USD per Troy Ounce. Daily series.
    """
    obs = fetch_fred("GOLDAMGBD228NLBM", limit=3)
    if obs:
        latest = obs[0]  # sorted desc
        return {"date": latest["date"], "price_usd_oz": latest["value"]}
    return None


# ── Dollar index (FRED) ────────────────────────────────────────────────────

def fetch_dollar_index() -> dict | None:
    """
    DTWEXBGS = Nominal Broad U.S. Dollar Index. Weekly. Jan 2006=100.
    Useful as a second data point alongside COFER for I2.
    """
    obs = fetch_fred("DTWEXBGS", limit=3)
    if obs:
        latest = obs[0]
        return {"date": latest["date"], "index_value": latest["value"]}
    return None


# ── Load existing data.json ────────────────────────────────────────────────

def load_data() -> dict:
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    print(f"WARNING: {DATA_FILE} not found — starting from empty template.")
    return {"indicators": {}, "ach": {}, "key_datapoints": []}


# ── Load manual overrides ──────────────────────────────────────────────────

def load_overrides() -> dict:
    if OVERRIDES_FILE.exists():
        with open(OVERRIDES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    print(f"INFO: No manual_overrides.json found at {OVERRIDES_FILE}.")
    print("  → Manual indicators (I1, I3, I4, I5, I6) will not be updated.")
    print("  → Create manual_overrides.json to update these fields.")
    return {}


# ── Apply auto-fetched data to I2 ─────────────────────────────────────────

def update_i2(data: dict, cofer: dict | None, gold: dict | None, dollar: dict | None) -> list[str]:
    """
    Update I2 (Reserve Diversification) with auto-fetched data.
    Returns a list of change-log strings.
    """
    changes = []
    i2 = data["indicators"].get("I2", {})
    notes = []

    if cofer:
        old_pct = i2.get("current_usd_pct")
        new_pct = cofer["usd_pct"]
        i2["current_usd_pct"] = new_pct
        i2["cofer_date"] = cofer["date"]

        # Auto-update the key_datapoints entry
        for dp in data.get("key_datapoints", []):
            if "USD share of allocated reserves" in dp.get("label", ""):
                dp["value"] = f"{new_pct}%"
                dp["note"]  = f"IMF COFER {cofer['date']} (auto-fetched)"

        notes.append(f"IMF COFER {cofer['date']}: USD {new_pct}%")
        if old_pct and abs(new_pct - old_pct) > 0.5:
            changes.append(f"I2: USD reserve share moved {old_pct}% → {new_pct}%")

        # Auto-assess threshold: trigger if < 60%
        if new_pct < 57:
            new_status = "TRIGGERED"
        elif new_pct < 60:
            new_status = "PARTIAL"
        else:
            new_status = "WATCH"

        if i2.get("status") != new_status:
            changes.append(f"I2 status: {i2.get('status')} → {new_status}")
            i2["status"] = new_status

    if gold:
        i2["gold_price_usd"] = gold["price_usd_oz"]
        i2["gold_price_date"] = gold["date"]
        notes.append(f"Gold ${gold['price_usd_oz']}/oz on {gold['date']}")

    if dollar:
        i2["dollar_index"] = dollar["index_value"]
        i2["dollar_index_date"] = dollar["date"]
        notes.append(f"Dollar index {dollar['index_value']} on {dollar['date']}")

    if notes:
        i2["auto_fetch_note"] = " | ".join(notes)

    data["indicators"]["I2"] = i2
    return changes


# ── Apply manual overrides ─────────────────────────────────────────────────

def apply_overrides(data: dict, overrides: dict) -> list[str]:
    """
    Apply human-reviewed updates to manual indicators.
    Only updates fields explicitly present in the override — preserves everything else.
    """
    changes = []
    for ind_id, override in overrides.items():
        if ind_id not in data["indicators"]:
            print(f"  WARNING: Override for unknown indicator '{ind_id}' — skipping.")
            continue
        ind = data["indicators"][ind_id]
        for field, value in override.items():
            if field == "last_reviewed":
                ind["last_reviewed"] = value
                continue
            old = ind.get(field)
            if old != value:
                changes.append(f"{ind_id}.{field}: updated (reviewed {override.get('last_reviewed', '?')})")
                ind[field] = value
        data["indicators"][ind_id] = ind
    return changes


# ── Write updated data.json ────────────────────────────────────────────────

def save_data(data: dict) -> None:
    now = datetime.now(timezone.utc)
    data["last_updated"] = now.strftime("%Y-%m-%d")
    data["update_note"]  = f"Auto-updated {now.strftime('%Y-%m-%d %H:%M UTC')} via GitHub Actions"
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\n✓ Wrote {DATA_FILE}")


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Switch & Vault — Indicator Board Updater")
    print(f"Run time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # 1. Load current data
    data = load_data()

    # 2. Fetch auto-updatable series
    print("\n[1/3] Fetching auto-updatable data series...")
    print("  Fetching IMF COFER (USD reserve share)...")
    cofer = fetch_imf_cofer()
    print(f"    → {cofer}")

    print("  Fetching FRED: Gold price (GOLDAMGBD228NLBM)...")
    gold = fetch_gold_price()
    print(f"    → {gold}")

    print("  Fetching FRED: Dollar index (DTWEXBGS)...")
    dollar = fetch_dollar_index()
    print(f"    → {dollar}")

    # 3. Apply auto-updates to I2
    print("\n[2/3] Applying auto-fetched data...")
    all_changes = []
    all_changes += update_i2(data, cofer, gold, dollar)

    # 4. Apply manual overrides
    print("\n[3/3] Applying manual overrides...")
    overrides = load_overrides()
    if overrides:
        all_changes += apply_overrides(data, overrides)
    else:
        print("  No overrides to apply.")

    # 5. Save
    save_data(data)

    # 6. Change summary
    print("\n── Change summary ──────────────────────────────────")
    if all_changes:
        for c in all_changes:
            print(f"  • {c}")
    else:
        print("  No changes detected.")
    print("────────────────────────────────────────────────────")

    # 7. Reminder for manual indicators
    print("""
── Manual indicators (require human review) ────────────
  I1  Coercion-Failure     → edit manual_overrides.json
  I3  Mineral-Chokepoint   → edit manual_overrides.json
  I4  Indigenization        → edit manual_overrides.json
  I5  Entanglement-Seam    → edit manual_overrides.json
  I6  Regionalization       → edit manual_overrides.json
────────────────────────────────────────────────────────

To update a manual indicator:
  1. Edit manual_overrides.json in repo root
  2. Commit and push (or edit directly on GitHub)
  3. Run this script manually via Actions → "Run workflow"
""")


if __name__ == "__main__":
    main()
