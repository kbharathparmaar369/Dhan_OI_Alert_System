# =============================================================
#  OI Alert System — core/market_snapshot.py
#  Scans full option chain for highest gamma and volume
#  Called every 30 minutes during market hours
# =============================================================

import os
import sys
import json
from datetime import datetime
import pytz

# Add grandparent root workspace folder to path lookup
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import config

SNAPSHOT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "market_snapshot.json"
)


def scan_full_chain(chain_data, underlying_name, expiry):
    """
    Scans the entire option chain and finds:
    - Highest gamma strike
    - Highest volume strike
    - Top 3 strikes by volume
    - Top 3 strikes by Open Interest (OI)

    Args:
        chain_data      : full option chain from dhan_client
        underlying_name : str — e.g. NIFTY
        expiry          : str — e.g. 2026-07-10

    Returns:
        dict with all findings
    """
    oc_data    = chain_data.get("oc", {})
    spot_price = chain_data.get("last_price", 0)

    all_strikes = []

    for strike_str, values in oc_data.items():
        strike = int(strike_str)

        for opt_type in ["ce", "pe"]:
            opt = values.get(opt_type, {})
            if not opt:
                continue

            oi     = opt.get("oi", 0)
            volume = opt.get("volume", 0)
            gamma  = opt.get("greeks", {}).get("gamma", 0) or opt.get("gamma", 0)
            delta  = opt.get("greeks", {}).get("delta", 0) or opt.get("delta", 0)
            ltp    = opt.get("last_price", 0)
            iv     = opt.get("implied_volatility", 0)

            if oi == 0 and volume == 0:
                continue

            all_strikes.append({
                "strike"     : strike,
                "option_type": opt_type.upper(),
                "oi"         : oi,
                "volume"     : volume,
                "gamma"      : gamma,
                "delta"      : delta,
                "ltp"        : ltp,
                "iv"         : iv,
            })

    if not all_strikes:
        return {}

    # ── Find highest gamma ────────────────────────────────────
    by_gamma  = sorted(all_strikes, key=lambda x: x["gamma"], reverse=True)
    top_gamma = by_gamma[0] if by_gamma else {}

    # ── Find highest volume ───────────────────────────────────
    by_volume  = sorted(all_strikes, key=lambda x: x["volume"], reverse=True)
    top_volume = by_volume[0] if by_volume else {}

    # ── Top 3 by volume ───────────────────────────────────────
    top3_volume = by_volume[:3]

    # ── Top 3 by OI ──────────────────────────────────────────
    by_oi    = sorted(all_strikes, key=lambda x: x["oi"], reverse=True)
    top3_oi  = by_oi[:3]

    # ── Build result ──────────────────────────────────────────
    ist = pytz.timezone(config.TIMEZONE)
    now = datetime.now(ist)

    result = {
        "underlying"  : underlying_name,
        "expiry"      : expiry,
        "spot_price"  : spot_price,
        "time"        : now.strftime("%H:%M:%S"),
        "date"        : now.strftime("%Y-%m-%d"),
        "top_gamma"   : top_gamma,
        "top_volume"  : top_volume,
        "top3_volume" : top3_volume,
        "top3_oi"     : top3_oi,
        "total_strikes": len(all_strikes),
    }

    return result


def save_snapshot(result):
    """Saves latest snapshot to data/market_snapshot.json."""
    os.makedirs(os.path.dirname(SNAPSHOT_FILE), exist_ok=True)

    existing = load_all_snapshots()
    key      = f"{result['underlying']}_{result['expiry']}"
    existing[key] = result

    with open(SNAPSHOT_FILE, "w") as f:
        json.dump(existing, f, indent=2)


def load_all_snapshots():
    """Loads all saved snapshots."""
    if not os.path.exists(SNAPSHOT_FILE):
        return {}
    try:
        with open(SNAPSHOT_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def format_snapshot_telegram(result):
    """
    Formats snapshot as a clean Telegram message.
    Sent every 30 minutes during market hours.
    """
    if not result:
        return None

    tg   = result.get("top_gamma", {})
    tv   = result.get("top_volume", {})
    t3v  = result.get("top3_volume", [])
    t3oi = result.get("top3_oi", [])

    # Top 3 volume lines
    vol_lines = "\n".join([
        f"  {i+1}. {s['strike']} {s['option_type']}  →  {s['volume']:,}"
        for i, s in enumerate(t3v)
    ])

    # Top 3 OI lines
    oi_lines = "\n".join([
        f"  {i+1}. {s['strike']} {s['option_type']}  →  {s['oi']:,}"
        for i, s in enumerate(t3oi)
    ])

    # We use safe characters for the Telegram dividers (regular hyphens instead of em-dashes if they might cause visual issues in parsing, though standard hyphens are fine).
    message = (
        f"📊 *{result['underlying']} Market Snapshot*\n"
        f"Time  : {result['time']}\n"
        f"Spot  : {result['spot_price']}\n"
        f"{'—' * 28}\n"
        f"🎯 *Highest Gamma*\n"
        f"  {tg.get('strike')} {tg.get('option_type')}  →  "
        f"Gamma: {tg.get('gamma', 0):.4f} | LTP: ₹{tg.get('ltp')}\n"
        f"{'—' * 28}\n"
        f"📈 *Highest Volume*\n"
        f"  {tv.get('strike')} {tv.get('option_type')}  →  "
        f"Vol: {tv.get('volume', 0):,} | LTP: ₹{tv.get('ltp')}\n"
        f"{'—' * 28}\n"
        f"📈 *Top 3 by Volume*\n{vol_lines}\n"
        f"{'—' * 28}\n"
        f"📊 *Top 3 by OI*\n{oi_lines}\n"
    )

    return message
