import os
import sys
import json
import re
import csv
import subprocess
from datetime import datetime
import pytz

# Add grandparent root workspace folder to path lookup
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, request, jsonify
import requests

import config 
from core.market_hours import get_market_status, is_market_open
from core.dhan_client  import validate_token, renew_token, get_expiry_list

app=Flask(__name__)

# File path

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(BASE_DIR, "data", "settings.json")
ALERTS_CSV    = os.path.join(BASE_DIR, "data", "alerts_log.csv")
TOKEN_LOG     = os.path.join(BASE_DIR, "logs", "token_update.log")
CONFIG_FILE   = os.path.join(BASE_DIR, "config.py")

# Helper functions

def get_ist_now():
    ist = pytz.timezone(config.TIMEZONE)
    return datetime.now(ist)

def load_settings():
    default={
        "underlyings": [
            {"scrip": 13, "seg": "IDX_I", "name": "NIFTY"}
        ],
        "expiries": {"NIFTY": []},
        "strike_filter": {
            "mode"       : "ITM",
            "itm_depth"  : 3,
            "include_atm": True
        },
        "thresholds": {
            "oi_3sec_pct"     : 500,
            "oi_day_pct"      : 500,
            "cooldown_minutes": 5
        }

    }

    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
    except:
        pass

    return default

def save_settings(data):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    
def save_token_to_config(new_token):
    try:
        with open(CONFIG_FILE, "r") as f:
            content = f.read()

        updated = re.sub(
            r'DHAN_ACCESS_TOKEN\s*=\s*".*?"',
            f'DHAN_ACCESS_TOKEN = "{new_token}"',
            content
        )

        with open(CONFIG_FILE, "w") as f:
            f.write(updated)

        return True
    except Exception as e:
        print(f"Error saving token: {e}")
        return False


def log_token_update():
    os.makedirs(os.path.dirname(TOKEN_LOG), exist_ok=True)
    now = get_ist_now().strftime("%Y-%m-%d %H:%M:%S")
    with open(TOKEN_LOG, "a") as f:
        f.write(f"{now}\n")

def get_last_token_update():
    """Returns last token update time as string."""
    try:
        if os.path.exists(TOKEN_LOG):
            with open(TOKEN_LOG, "r") as f:
                lines = f.readlines()
            if lines:
                return lines[-1].strip()
    except:
        pass
    return "Never"

def get_masked_token():
    """Returns masked version of current token for display."""
    import importlib
    importlib.reload(config)
    token = config.DHAN_ACCESS_TOKEN
    if not token:
        return "Not set"
    if len(token) < 10:
        return "***"
    return token[:6] + "••••••••••••••••" + token[-4:]


def is_monitor_running():
    """Checks if main.py is currently running."""
    try:
        if os.name == "nt":
            result = subprocess.run(
                'wmic process where "CommandLine like \'%main.py%\'" get ProcessId',
                shell=True, capture_output=True, text=True
            )
            pids = [line.strip() for line in result.stdout.splitlines() if line.strip().isdigit()]
            return len(pids) > 0
        else:
            result = subprocess.run(
                ["pgrep", "-f", "main.py"],
                capture_output=True, text=True
            )
            return result.returncode == 0
    except:
        return False


def get_today_alerts():
    """Returns today's alerts from CSV as list of dicts."""
    alerts = []
    if not os.path.exists(ALERTS_CSV):
        return alerts

    today = get_ist_now().strftime("%Y-%m-%d")

    try:
        with open(ALERTS_CSV, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("Date") == today:
                    alerts.append(row)
    except:
        pass

    return list(reversed(alerts))  # newest first


def get_current_token_from_config():
    """Reads current token directly from config.py file."""
    try:
        import importlib
        importlib.reload(config)
        return config.DHAN_ACCESS_TOKEN
    except:
        return ""

@app.route("/")
def home():
    """Main control panel page."""
    settings          = load_settings()
    market_status, market_msg = get_market_status()
    monitor_running   = is_monitor_running()
    token_valid, _    = validate_token()
    today_alerts      = get_today_alerts()
    last_token_update = get_last_token_update()
    masked_token      = get_masked_token()

    return render_template(
        "index.html",
        settings          = settings,
        all_underlyings   = config.ALL_UNDERLYINGS,
        market_status     = market_status,
        market_msg        = market_msg,
        monitor_running   = monitor_running,
        token_valid       = token_valid,
        today_alerts      = today_alerts,
        last_token_update = last_token_update,
        masked_token      = masked_token,
        alert_count       = len(today_alerts),
        now               = get_ist_now().strftime("%H:%M:%S"),
    )


# ─── Token Routes ────────────────────────────────────────────

@app.route("/api/update-token", methods=["POST"])
def update_token():
    """Saves new token pasted by user."""
    data      = request.json
    pin       = data.get("pin", "").strip()
    new_token = data.get("token", "").strip()

    # Check PIN
    if pin != config.TOKEN_PAGE_PIN:
        return jsonify({"success": False, "message": "Wrong PIN"})

    # Validate token not empty
    if not new_token:
        return jsonify({"success": False, "message": "Token cannot be empty"})

    if len(new_token) < 20:
        return jsonify({"success": False, "message": "Token looks too short — check again"})

    # Save to config.py
    saved = save_token_to_config(new_token)
    if not saved:
        return jsonify({"success": False, "message": "Failed to save token"})

    # Validate new token works
    import importlib
    importlib.reload(config)
    valid, msg = validate_token()

    if valid:
        log_token_update()
        return jsonify({
            "success": True,
            "message": "Token saved and validated ✅",
            "masked" : get_masked_token()
        })
    else:
        return jsonify({
            "success": False,
            "message": f"Token saved but validation failed: {msg}"
        })


@app.route("/api/renew-token", methods=["POST"])
def renew_token_route():
    """Renews token for another 24 hours via Dhan API."""
    data = request.json
    pin  = data.get("pin", "").strip()

    if pin != config.TOKEN_PAGE_PIN:
        return jsonify({"success": False, "message": "Wrong PIN"})

    success, result = renew_token()

    if success:
        saved = save_token_to_config(result)
        if saved:
            log_token_update()
            return jsonify({
                "success": True,
                "message": "Token renewed for another 24 hours ✅",
                "masked" : get_masked_token()
            })
        return jsonify({"success": False, "message": "Token renewed but failed to save"})

    return jsonify({"success": False, "message": f"Renewal failed: {result}"})


@app.route("/api/validate-token", methods=["GET"])
def validate_token_route():
    """Checks if current token is valid."""
    valid, msg = validate_token()
    return jsonify({
        "valid"  : valid,
        "message": msg,
        "masked" : get_masked_token()
    })


# ─── Settings Routes ─────────────────────────────────────────

@app.route("/api/save-settings", methods=["POST"])
def save_settings_route():
    """Saves all user settings from control panel."""
    try:
        data     = request.json
        settings = load_settings()

        # Update underlyings
        if "underlyings" in data:
            selected_names = data["underlyings"]
            settings["underlyings"] = [
                u for u in config.ALL_UNDERLYINGS
                if u["name"] in selected_names
            ]

        # Update thresholds
        if "thresholds" in data:
            settings["thresholds"].update(data["thresholds"])

        # Update strike filter
        if "strike_filter" in data:
            settings["strike_filter"].update(data["strike_filter"])

        save_settings(settings)
        return jsonify({"success": True, "message": "Settings saved ✅"})

    except Exception as e:
        return jsonify({"success": False, "message": f"Error: {str(e)}"})


@app.route("/api/save-expiries", methods=["POST"])
def save_expiries_route():
    """Saves selected expiries for each underlying."""
    try:
        data     = request.json
        settings = load_settings()

        # data = {"NIFTY": ["2026-07-10"], "BANKNIFTY": ["2026-07-09"]}
        settings["expiries"] = data
        save_settings(settings)

        return jsonify({"success": True, "message": "Expiries saved ✅"})

    except Exception as e:
        return jsonify({"success": False, "message": f"Error: {str(e)}"})


# ─── Expiry Routes ───────────────────────────────────────────

@app.route("/api/get-expiries/<underlying_name>", methods=["GET"])
def get_expiries(underlying_name):
    """Fetches available expiries from Dhan for an underlying."""
    underlying = next(
        (u for u in config.ALL_UNDERLYINGS if u["name"] == underlying_name),
        None
    )

    if not underlying:
        return jsonify({"success": False, "message": "Unknown underlying"})

    success, expiries = get_expiry_list(underlying["scrip"], underlying["seg"])

    if success:
        return jsonify({"success": True, "expiries": expiries})

    return jsonify({"success": False, "message": str(expiries)})


# ─── Status Routes ───────────────────────────────────────────

@app.route("/api/status", methods=["GET"])
def get_status():
    """Returns current system status — polled by frontend."""
    market_status, market_msg = get_market_status()
    token_valid, _            = validate_token()
    today_alerts              = get_today_alerts()

    return jsonify({
        "monitor_running"  : is_monitor_running(),
        "market_status"    : market_status,
        "market_msg"       : market_msg,
        "token_valid"      : token_valid,
        "alert_count"      : len(today_alerts),
        "last_token_update": get_last_token_update(),
        "time"             : get_ist_now().strftime("%H:%M:%S"),
    })


@app.route("/api/alerts", methods=["GET"])
def get_alerts():
    """Returns today's alerts for the alerts table."""
    return jsonify({
        "success": True,
        "alerts" : get_today_alerts()
    })


@app.route("/api/market-snapshot", methods=["GET"])
def get_market_snapshot():
    """Returns latest market snapshot for control panel."""
    from core.market_snapshot import load_all_snapshots
    snapshots = load_all_snapshots()
    return jsonify({"success": True, "snapshots": snapshots})


# =============================================================
#  RUN
# =============================================================

if __name__ == "__main__":
    print(f"Starting OI Alert Control Panel on port {config.TOKEN_SERVER_PORT}")
    print(f"Access at: http://localhost:{config.TOKEN_SERVER_PORT}")
    print(f"On Oracle VM: http://your_vm_ip:{config.TOKEN_SERVER_PORT}")

    app.run(
        host  = "0.0.0.0",
        port  = config.TOKEN_SERVER_PORT,
        debug = False
    )
 