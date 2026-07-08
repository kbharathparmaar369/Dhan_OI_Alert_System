# =============================================================
#  OI Alert System — core/oi_engine.py
#  The brain of the system
#  Calculates OI change %, applies filters, decides alerts
# =============================================================

import os
import sys
import json
from datetime import datetime, timedelta
import pytz

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import config
from oi_alert_system.core.snapshot import get_day_open_oi

# ─── Settings file path ──────────────────────────────────────
SETTINGS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "settings.json"
)

# ─── Default settings if settings.json not found ─────────────
DEFAULT_SETTINGS = {
    "underlyings": [
        {"scrip": 13, "seg": "IDX_I", "name": "NIFTY"}
    ],
    "expiries": {
        "NIFTY": ["2026-07-10"]
    },
    "strike_filter": {
        "mode"      : "ITM",
        "itm_depth" : 3,
        "include_atm": True
    },
    "thresholds": {
        "oi_3sec_pct"     : 500,
        "oi_day_pct"      : 500,
        "cooldown_minutes": 5
    }
}

# ─── In memory state ─────────────────────────────────────────
# Stores OI from previous fetch cycle (3 seconds ago)
prev_oi = {}

# Stores last alert time per strike to enforce cooldown
# Format: {"NIFTY_24500_CE": datetime_object}
cooldown_map = {}


def load_settings():
    """Loads user settings from settings.json."""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
    except:
        pass
    return DEFAULT_SETTINGS


def calculate_atm_strike(spot_price, underlying_name):
    """
    Rounds spot price to nearest strike step to get ATM.

    Example:
        NIFTY spot = 24,480, step = 50
        ATM = round(24480 / 50) * 50 = 24500
    """
    step = config.STRIKE_STEP.get(underlying_name, 50)
    return round(spot_price / step) * step


def get_watch_strikes(atm, underlying_name, itm_depth=3):
    """
    Returns the list of strikes to watch.
    CE ITM strikes + ATM + PE ITM strikes.

    For NIFTY with ATM=24500, itm_depth=3, step=50:

    CE ITM (below ATM):
        24350, 24400, 24450

    ATM:
        24500

    PE ITM (above ATM):
        24550, 24600, 24650

    Returns list of dicts:
    [
        {"strike": 24350, "option_type": "CE", "label": "CE ITM 3"},
        {"strike": 24400, "option_type": "CE", "label": "CE ITM 2"},
        {"strike": 24450, "option_type": "CE", "label": "CE ITM 1"},
        {"strike": 24500, "option_type": "CE", "label": "ATM"},
        {"strike": 24500, "option_type": "PE", "label": "ATM"},
        {"strike": 24550, "option_type": "PE", "label": "PE ITM 1"},
        {"strike": 24600, "option_type": "PE", "label": "PE ITM 2"},
        {"strike": 24650, "option_type": "PE", "label": "PE ITM 3"},
    ]
    """
    step   = config.STRIKE_STEP.get(underlying_name, 50)
    watch  = []

    # CE ITM — strikes below ATM (deepest first)
    for i in range(itm_depth, 0, -1):
        watch.append({
            "strike"     : atm - (i * step),
            "option_type": "CE",
            "label"      : f"CE ITM {i}"
        })

    # ATM — both CE and PE
    watch.append({"strike": atm, "option_type": "CE", "label": "ATM"})
    watch.append({"strike": atm, "option_type": "PE", "label": "ATM"})

    # PE ITM — strikes above ATM
    for i in range(1, itm_depth + 1):
        watch.append({
            "strike"     : atm + (i * step),
            "option_type": "PE",
            "label"      : f"PE ITM {i}"
        })

    return watch


def calculate_oi_change_pct(current_oi, previous_oi):
    """
    Calculates percentage change in OI.
    Returns 0 if previous OI is 0 to avoid division by zero.
    """
    if previous_oi == 0:
        return 0.0
    return ((current_oi - previous_oi) / previous_oi) * 100


def is_in_cooldown(strike_key, cooldown_minutes):
    """
    Checks if this strike was recently alerted.
    Returns True if still in cooldown period.
    """
    if strike_key not in cooldown_map:
        return False

    ist      = pytz.timezone(config.TIMEZONE)
    now      = datetime.now(ist)
    last     = cooldown_map[strike_key]
    elapsed  = (now - last).total_seconds() / 60

    return elapsed < cooldown_minutes


def set_cooldown(strike_key):
    """Marks a strike as alerted — starts cooldown timer."""
    ist = pytz.timezone(config.TIMEZONE)
    cooldown_map[strike_key] = datetime.now(ist)


def process_option_chain(chain_data, underlying_name, expiry, day_snapshot):
    """
    Main function — called every 3 seconds.
    Processes one option chain and returns list of alerts to fire.

    Args:
        chain_data      : dict from dhan_client.get_option_chain()
        underlying_name : str — e.g. "NIFTY"
        expiry          : str — e.g. "2026-07-10"
        day_snapshot    : dict from snapshot.load_day_snapshot()

    Returns:
        list of alert dicts — one per spike detected
    """
    settings      = load_settings()
    thresholds    = settings.get("thresholds", DEFAULT_SETTINGS["thresholds"])
    strike_filter = settings.get("strike_filter", DEFAULT_SETTINGS["strike_filter"])

    oi_3sec_threshold = thresholds.get("oi_3sec_pct", 500)
    oi_day_threshold  = thresholds.get("oi_day_pct", 1000)
    cooldown_minutes  = thresholds.get("cooldown_minutes", 5)
    itm_depth         = strike_filter.get("itm_depth", 3)

    alerts    = []
    chain_key = f"{underlying_name}_{expiry}"

    # Get spot price and calculate ATM
    spot_price = chain_data.get("last_price")
    if not spot_price:
        return alerts

    atm           = calculate_atm_strike(spot_price, underlying_name)
    watch_strikes = get_watch_strikes(atm, underlying_name, itm_depth)
    oc_data       = chain_data.get("oc", {})

    for item in watch_strikes:
        strike      = item["strike"]
        option_type = item["option_type"]
        label       = item["label"]
        strike_str  = str(strike)
        strike_key  = f"{underlying_name}_{strike}_{option_type}"

        # Get strike data from chain
        strike_data = oc_data.get(strike_str, {})
        opt_data    = strike_data.get(option_type.lower(), {})

        if not opt_data:
            continue

        current_oi = opt_data.get("oi", 0)
        ltp        = opt_data.get("last_price", 0)
        iv         = opt_data.get("implied_volatility", 0)

        if current_oi == 0:
            continue

        # ── Calculate 3 second OI change ──────────────────────
        prev_key    = f"{chain_key}_{strike_str}_{option_type}"
        previous_oi = prev_oi.get(prev_key, current_oi)
        chg_3sec    = calculate_oi_change_pct(current_oi, previous_oi)

        # ── Calculate day open OI change vs previous day close ──
        previous_day_oi = opt_data.get("previous_oi", 0)
        day_open_oi     = previous_day_oi if previous_day_oi > 0 else get_day_open_oi(day_snapshot, chain_key, strike_str, option_type)
        chg_day         = calculate_oi_change_pct(current_oi, day_open_oi) if day_open_oi > 0 else 0

        # ── Update previous OI for next cycle ─────────────────
        prev_oi[prev_key] = current_oi

        # ── Check thresholds ──────────────────────────────────
        triggered_3sec = abs(chg_3sec) >= oi_3sec_threshold
        triggered_day  = abs(chg_day)  >= oi_day_threshold

        if not triggered_3sec and not triggered_day:
            continue

        # ── Check cooldown ────────────────────────────────────
        if is_in_cooldown(strike_key, cooldown_minutes):
            continue

        # ── Build alert ───────────────────────────────────────
        ist     = pytz.timezone(config.TIMEZONE)
        trigger = []
        if triggered_3sec:
            trigger.append("3 Second Spike")
        if triggered_day:
            trigger.append("Day Open Spike")

        alert = {
            "underlying"  : underlying_name,
            "expiry"      : expiry,
            "strike"      : strike,
            "option_type" : option_type,
            "label"       : label,
            "spot_price"  : spot_price,
            "atm"         : atm,
            "current_oi"  : current_oi,
            "prev_oi"     : previous_oi,
            "day_open_oi" : day_open_oi,
            "chg_3sec_pct": round(chg_3sec, 2),
            "chg_day_pct" : round(chg_day, 2),
            "ltp"         : ltp,
            "iv"          : iv,
            "trigger"     : " + ".join(trigger),
            "time"        : datetime.now(ist).strftime("%H:%M:%S"),
        }

        alerts.append(alert)

        # Start cooldown for this strike
        set_cooldown(strike_key)

    return alerts


# =============================================================
#  Test — python core/oi_engine.py
# =============================================================
if __name__ == "__main__":
    print("Testing OI Engine...")

    # Simulate fake chain data
    fake_chain = {
        "last_price": 24480.0,
        "oc": {
            "24350": {
                "ce": {"oi": 50000, "previous_oi": 80000, "last_price": 180.0, "implied_volatility": 18.5},
                "pe": {"oi": 20000,  "previous_oi": 18000, "last_price": 10.0,  "implied_volatility": 15.0},
            },
            "24400": {
                "ce": {"oi": 45000,  "previous_oi": 40000, "last_price": 140.0, "implied_volatility": 17.0},
                "pe": {"oi": 38000,  "previous_oi": 35000, "last_price": 30.0,  "implied_volatility": 16.0},
            },
            "24450": {
                "ce": {"oi": 60000,  "previous_oi": 10000, "last_price": 100.0, "implied_volatility": 16.0},
                "pe": {"oi": 55000,  "previous_oi": 50000, "last_price": 55.0,  "implied_volatility": 17.5},
            },
            "24500": {
                "ce": {"oi": 80000,  "previous_oi": 75000, "last_price": 70.0,  "implied_volatility": 15.5},
                "pe": {"oi": 90000,  "previous_oi": 85000, "last_price": 75.0,  "implied_volatility": 15.5},
            },
            "24550": {
                "ce": {"oi": 30000,  "previous_oi": 28000, "last_price": 45.0,  "implied_volatility": 16.5},
                "pe": {"oi": 250000, "previous_oi": 40000, "last_price": 100.0, "implied_volatility": 19.0},
            },
            "24600": {
                "ce": {"oi": 20000,  "previous_oi": 18000, "last_price": 25.0,  "implied_volatility": 17.0},
                "pe": {"oi": 70000,  "previous_oi": 65000, "last_price": 130.0, "implied_volatility": 18.0},
            },
            "24650": {
                "ce": {"oi": 15000,  "previous_oi": 14000, "last_price": 12.0,  "implied_volatility": 17.5},
                "pe": {"oi": 85000,  "previous_oi": 80000, "last_price": 160.0, "implied_volatility": 18.5},
            },
        }
    }

    # ATM check
    atm = calculate_atm_strike(24480, "NIFTY")
    print(f"Spot: 24480 -> ATM: {atm}")

    # Watch strikes
    watch = get_watch_strikes(atm, "NIFTY", itm_depth=3)
    print(f"\nWatching {len(watch)} strike-option pairs:")
    for w in watch:
        print(f"  {w['label']:10} -> {w['strike']} {w['option_type']}")

    # Process chain — first cycle builds prev_oi baseline
    print("\nCycle 1 — building baseline...")
    alerts = process_option_chain(fake_chain, "NIFTY", "2026-07-10", {})
    print(f"Alerts: {len(alerts)}")

    # Simulate OI spike on 24350 CE in cycle 2
    fake_chain["oc"]["24350"]["ce"]["oi"] = 500000

    print("\nCycle 2 — with OI spike on 24350 CE...")
    alerts = process_option_chain(fake_chain, "NIFTY", "2026-07-10", {})
    print(f"Alerts fired: {len(alerts)}")
    for a in alerts:
        print(f"\n  [ALERT]")
        print(f"  Strike    : {a['strike']} {a['option_type']} ({a['label']})")
        print(f"  OI Change : {a['chg_3sec_pct']}% (3sec)")
        print(f"  OI Change : {a['chg_day_pct']}% (day)")
        print(f"  LTP       : {a['ltp']}")
        print(f"  Trigger   : {a['trigger']}")