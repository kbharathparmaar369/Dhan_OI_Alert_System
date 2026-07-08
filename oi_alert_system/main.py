from http.client import REQUEST_TIMEOUT
from typing import ChainMap
from requests.utils import default_user_agent
import time
import sys
import os
import json
from datetime import datetime
import pytz

# Add the grandparent project root directory to search paths
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# importing all modules
import config
from core.market_hours  import is_market_open, is_market_day, seconds_to_market_open, get_market_status
from core.dhan_client   import get_option_chain, get_expiry_list, validate_token
from core.snapshot      import take_day_snapshot, load_day_snapshot, snapshot_exists_today
from core.oi_engine     import process_option_chain
from core.alert_manager import fire_alert, send_telegram_text
from core.market_snapshot import scan_full_chain, save_snapshot, format_snapshot_telegram

# setting file
SETTINGS_FILE=os.path.join(os.path.dirname(__file__),"data","settings.json")

# log files
LOG_FILE=os.path.join(os.path.dirname(__file__),"logs","app.log")

#Logging
def log(message):
    ist=pytz.timezone(config.TIMEZONE)
    timestamp=datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S")
    line=f"[{timestamp}] {message}"
    print(line)

    os.makedirs(os.path.dirname(LOG_FILE),exist_ok=True)
    try:
        with open(LOG_FILE,"a") as f:
            f.write(line + "\n")
    except:
        pass

# loading the settings
def load_settings():
    default={
        "underlyings":[
            {"scrip":13, "seg": "IDX_I", "name":"NIFTY"}
        ],
        "expiries":{
            "NIFTY":[]
        },
        "strike_filter":{
            "mode": "ITM",
            "itm_depth":3,
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

def get_active_expiry(underlying_name, settings):
    """
    Gets the current week expiry for an underlying.
    First tries settings.json, then auto fetches from Dhan.
    """
    expires=settings.get("expiries", {}).get(underlying_name,[])

    if expires:
        return expires[0]

    underlying=next(
        (u for u in config.ALL_UNDERLYINGS if u["name"] == underlying_name),
        None
    )

    if not underlying:
        return None
    
    success, expiry_list=get_expiry_list(underlying["scrip"], underlying["seg"])

    if success and expiry_list:
        log(f"Auto fetched expiry for {underlying_name}: {expiry_list[0]}")
        return expiry_list[0]

    return None

#check 
def run_startup_checks():
    """
    Runs all checks before starting the main loop.
    Returns True if all pass, False if any fail.
    """
    log("Running startup checks...")

    # Check 1 — Token
    log("Checking Dhan token...")
    valid, msg = validate_token()
    if not valid:
        log(f" Token check failed: {msg}")
        send_telegram_text(
            " *OI Alert System*\n"
            "Token is invalid or expired.\n"
            "Please update token on control panel."
        )
        return False
    log(" Token valid")

    # Check 2 — Telegram
    log("Checking Telegram...")
    sent = send_telegram_text(
        " *OI Alert System Started*\n"
        f"Monitoring NIFTY\n"
        f"Strike mode: ITM 3 + ATM + ITM 3\n"
        f"Threshold: 500% (3sec) | 1000% (day)\n"
        f"Market opens at 09:15 IST"
    )
    if sent:
        log(" Telegram working")
    else:
        log(" Telegram not working - check credentials")

    return True

# Main monitoring loop
def run_monitoring_loop():
    log("=" * 50)
    log("Starting monitoring loop")
    log("=" * 50)

    day_snapshot  = {}
    cycle_count   = 0
    alert_count   = 0
    snapshot_taken = False
    last_snapshot_time = None

    while True:
        if not is_market_open():
            log("Market closed - stopping monitor")
            break
        
        settings =load_settings()
        underlyings= settings.get("underlyings",[])

        # Take day open snapshot once at start
        if not snapshot_taken and not snapshot_exists_today():
            log("Taking day open OI snapshot....")
            all_chains={}

            for u in underlyings:
                expiry=get_active_expiry(u["name"],settings)

                if not expiry:
                    continue

                success,chain=get_option_chain(u["scrip"], u["seg"], expiry)
                if success:
                    key = f"{u['name']}_{expiry}"
                    all_chains[key]=chain

            if all_chains:
                take_day_snapshot(all_chains)
                day_snapshot=load_day_snapshot()
                snapshot_taken=True
                log(f"Snapshot saved - {len(all_chains)} chains")

        if not day_snapshot:
            day_snapshot=load_day_snapshot()

        cycle_count +=1
        cycle_alerts=0

        for u in underlyings:
            expiry=get_active_expiry(u["name"], settings) 

            if not expiry:
                log(f"No expiry found for {u['name']} - skipping")
                continue

            success, chain= get_option_chain(u["scrip"], u["seg"], expiry)

            if not success:
                if chain =="TOKEN_EXPIRED":
                    log("Token expired mid session")
                    send_telegram_text(
                        " *OI Alert System*\n"
                        "Token expired during market hours.\n"
                        "Please update token on control panel immediately."
                    )
                    return
                log(f"Failed to fetch {u['name']} chain : {chain}")
                continue
            
            # Scan for gamma and volume context
            snapshot_data = scan_full_chain(chain, u["name"], expiry)
            top_gamma     = snapshot_data.get("top_gamma")
            top_volume    = snapshot_data.get("top_volume")

            alerts=process_option_chain(
                chain_data=chain,
                underlying_name=u["name"],
                expiry=expiry,
                day_snapshot=day_snapshot
            )
            
            for alert in alerts:
                fire_alert(alert, top_gamma, top_volume)
                alert_count +=1
                cycle_alerts +=1

        # ── Send snapshot every 30 minutes ────────────────────
        ist = pytz.timezone(config.TIMEZONE)
        now = datetime.now(ist)

        if last_snapshot_time is None or (now - last_snapshot_time).seconds >= 1800:
            for u in underlyings:
                expiry = get_active_expiry(u["name"], settings)
                if not expiry:
                    continue

                ok, chain = get_option_chain(u["scrip"], u["seg"], expiry)
                if not ok:
                    continue

                result = scan_full_chain(chain, u["name"], expiry)
                if result:
                    save_snapshot(result)
                    msg = format_snapshot_telegram(result)
                    if msg:
                        send_telegram_text(msg)
                        log(f"Snapshot sent for {u['name']}")

            last_snapshot_time = now

        if cycle_count % 100 ==0:
            ist = pytz.timezone(config.TIMEZONE)
            now = datetime.now(ist).strftime("%H:%M:%S")
            log(f"Cycle {cycle_count} | Time: {now} | Total alerts today: {alert_count}")

        time.sleep(config.FETCH_INTERVAL_SECONDS)

    return alert_count

# Daily summary
def send_daily_summary(alert_count, start_time):
    """Sends end of day summary to Telegram."""
    ist      = pytz.timezone(config.TIMEZONE)
    end_time = datetime.now(ist).strftime("%H:%M:%S")

    message = (
        f" *OI Alert System - Daily Summary*\n"
        f"{'─' * 28}\n"
        f"Date         : {datetime.now(ist).strftime('%d %b %Y')}\n"
        f"Market Hours : 09:15 to 15:30\n"
        f"{'─' * 28}\n"
        f"Total Alerts : {alert_count}\n"
        f"Started At   : {start_time}\n"
        f"Stopped At   : {end_time}\n"
        f"{'─' * 28}\n"
        f"Full log saved to alerts\\_log.csv"
    )

    send_telegram_text(message)
    log(f"Daily summary sent - {alert_count} alerts today")

# Entry point
def main():
    ist        = pytz.timezone(config.TIMEZONE)
    start_time = datetime.now(ist).strftime("%H:%M:%S")

    log("=" * 50)
    log("  OI Alert System - Starting Up")
    log("=" * 50)

    if not is_market_day():
        status, msg=get_market_status()
        log(f"Today is not a market day: {msg}")
        log("System will not run today. Exiting.")
        sys.exit(0)

    secs=seconds_to_market_open()

    if secs == -1:
        log("Market already closed for today. Exiting..")
        sys.exit(0)

    if secs > 0:
        mins = secs // 60
        log(f"Market opens in {mins} min {secs % 60} sec - waiting...")

        if mins > 5:
            send_telegram_text(
                f" *OI Alert System*\n"
                f"Waiting for market to open.\n"
                f"Starting in {mins} minutes."
            )
        
        time.sleep(secs)
    
    if not run_startup_checks():
        log("Startup checks failed - exiting")
        sys.exit(1)

    log("Market is open - starting monitoring")

    try:
        alert_count=run_monitoring_loop()
    
    except KeyboardInterrupt:
        log("Stopped manually by user (Ctrl+C)")    
        alert_count = 0
    
    except Exception as e:
        log(f"Unexpected error: {e}")
        send_telegram_text(f"*OI Alert System crashed*\nError: {e}")
        alert_count=0

    send_daily_summary(alert_count, start_time)
    log("System shut down cleanly")

if __name__ == "__main__":
    main()
