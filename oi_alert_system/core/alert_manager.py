from csv import writer
import requests
import os
import sys
import csv
import time
import platform
from datetime import datetime
import pytz
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import config



# CSV LOG FILE PATH
ALERTS_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "alerts_log.csv"
)

#CSV COLUMNS

CSV_COLUMNS = [
    "Date", "Time", "Underlying", "Expiry",
    "Strike", "Type", "Label", "Spot", "ATM",
    "Current OI", "Prev OI", "Day Open OI",
    "OI Chg 3sec %", "OI Chg Day %",
    "LTP", "IV", "Trigger"
]


# SOUND SYSTEM

def play_beep():
    try:
        os_name=platform.system()

        if os_name == "Linux":
            #Linux
            print('\a', end='', flush=True)
        elif os_name=="Windows":
            import winsound

            winsound.Beep(1000, 300)
            time.sleep(0.1)
            winsound.Beep(1000, 300)
            time.sleep(0.1)
            winsound.Beep(1500, 500)
        
        elif os_name=="Darwin":
            #Mac
            os.system("afplay /System/Library/Sounds/Glass.aiff")
        
        else:
            os.system("echo -e '\a'")
            time.sleep(0.2)
            os.system("echo -e '\a'")
            time.sleep(0.2)
            os.system("echo -e '\a'")

    except:
        print("Error playing sound. Skipping.")


# TELEGRAM ALERT

def format_telegram_message(alert, top_gamma=None, top_volume=None):
    ist=pytz.timezone(config.TIMEZONE)
    now=datetime.now(ist).strftime("%d %b %Y %H:%M:%S")

    # format OI numbers
    current_oi=f"{alert['current_oi']:,}"
    prev_oi=f"{alert['prev_oi']:,}"
    day_open_oi=f"{alert['day_open_oi']:,}" if alert['day_open_oi'] and alert['day_open_oi'] > 0 else "N/A"

    # Format OI change percentage
    chg_3sec = f"+{alert['chg_3sec_pct']:.1f}%" if alert['chg_3sec_pct'] >= 0 else f"{alert['chg_3sec_pct']:.1f}%"
    chg_day  = f"+{alert['chg_day_pct']:.1f}%"  if alert['chg_day_pct'] >= 0  else f"{alert['chg_day_pct']:.1f}%"

    message = (
        f"⚠️ *OI SPIKE ALERT*\n"
        f"{'─' * 28}\n"
        f"*{alert['underlying']}* | {alert['strike']} {alert['option_type']} | _{alert['label']}_\n"
        f"Expiry : {alert['expiry']}\n"
        f"Trigger: {alert['trigger']}\n"
        f"{'─' * 28}\n"
        f"OI Change  : *{chg_3sec}* (last 3 sec)\n"
        f"OI Change  : *{chg_day}* (from day open)\n"
        f"{'─' * 28}\n"
        f"Current OI : {current_oi}\n"
        f"Prev OI    : {prev_oi}\n"
        f"Day Open OI: {day_open_oi}\n"
        f"{'─' * 28}\n"
        f"LTP        : ₹{alert['ltp']}\n"
        f"IV         : {alert['iv']}%\n"
        f"Spot       : {alert['spot_price']}\n"
        f"ATM        : {alert['atm']}\n"
    )

    # ── Add gamma and volume context if available ─────────────
    if top_gamma or top_volume:
        message += f"{'─' * 28}\n"
        message += f"📊 *Market Context*\n"

        if top_gamma:
            message += (
                f"Highest Gamma  : {top_gamma['strike']} {top_gamma['option_type']} "
                f"| γ {top_gamma.get('gamma', 0):.4f}\n"
            )

        if top_volume:
            message += (
                f"Highest Volume : {top_volume['strike']} {top_volume['option_type']} "
                f"| {top_volume.get('volume', 0):,} lots\n"
            )

    message += f"{'─' * 28}\n"
    message += f"🕐 {now}"

    return message

def send_telegram(alert, top_gamma=None, top_volume=None):
    import importlib
    importlib.reload(config)

    bot_token=config.TELEGRAM_BOT_TOKEN
    chat_id=config.TELEGRAM_CHAT_ID

    if not bot_token:
        print("[Telegram] Bot token not configured — skipping")
        return False
    
    if not chat_id:
        print("[Telegram] Chat ID not configured — skipping")
        return False
    
    message=format_telegram_message(alert, top_gamma, top_volume)

    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload={
            "chat_id":chat_id,
            "text":message,
            "parse_mode":"Markdown"
        }

        response=requests.post(url, json=payload, timeout=10)

        if response.status_code==200:
            return True
        
        else:
            print(f"Telegram] Failed — status {response.status_code}: {response.text}")
            return False
    except requests.exceptions.Timeout:
        print(f"[Telegram] Timeout error")
        return False
    except requests.exceptions.RequestException as e:
        print(f"[Telegram] Error: {e}")
        return False

    
# CSV LOGGING

def ensure_csv_exists():
    os.makedirs(os.path.dirname(ALERTS_CSV), exist_ok=True)

    if not os.path.exists(ALERTS_CSV):
        with open(ALERTS_CSV, "w", newline="", encoding="utf-8") as f:
            writer=csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()


def log_to_csv(alert):

    ensure_csv_exists()

    ist=pytz.timezone(config.TIMEZONE)
    now=datetime.now(ist)

    row={
        "Date"          : now.strftime("%Y-%m-%d"),
        "Time"          : alert["time"],
        "Underlying"    : alert["underlying"],
        "Expiry"        : alert["expiry"],
        "Strike"        : alert["strike"],
        "Type"          : alert["option_type"],
        "Label"         : alert["label"],
        "Spot"          : alert["spot_price"],
        "ATM"           : alert["atm"],
        "Current OI"    : alert["current_oi"],
        "Prev OI"       : alert["prev_oi"],
        "Day Open OI"   : alert["day_open_oi"],
        "OI Chg 3sec %" : alert["chg_3sec_pct"],
        "OI Chg Day %"  : alert["chg_day_pct"],
        "LTP"           : alert["ltp"],
        "IV"            : alert["iv"],
        "Trigger"       : alert["trigger"],

    }

    try:
        with open(ALERTS_CSV, "a", newline="") as f:
            writer=csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writerow(row)
        return True

    except Exception as e:
        print(f"[CSV] Error writing log : {e}")
        return False


# MAIN will be called for every alert

def fire_alert(alert, top_gamma=None, top_volume=None):

    ist = pytz.timezone(config.TIMEZONE)
    now = datetime.now(ist).strftime("%H:%M:%S")

    # print to terminal
    print(f"\n[{now}]  ALERT - "
        f"{alert['underlying']} {alert['strike']} {alert['option_type']} "
        f"({alert['label']}) | "
        f"{'+' if alert['chg_3sec_pct'] >= 0 else ''}{alert['chg_3sec_pct']:.1f}% OI spike | "
        f"OI: {alert['current_oi']:,} | "
        f"LTP: Rs. {alert['ltp']}")

    play_beep()

    tg_success=send_telegram(alert, top_gamma, top_volume)

    if tg_success:
        print(f"[Telegram] Alert sent successfully")
    
    else:
        print(f"[Telegram] Failed to send alert")

    csv_success=log_to_csv(alert)

    if csv_success:
        print(f"[CSV] Alert logged successfully")


def send_telegram_text(message):
    import importlib
    importlib.reload(config)

    bot_token=config.TELEGRAM_BOT_TOKEN
    chat_id=config.TELEGRAM_CHAT_ID

    if not bot_token or bot_token == "your_telegram_bot_token_here":
        return False

    if not chat_id or chat_id == "your_telegram_chat_id_here":
        return False
    
    try:
        url     = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id"   : chat_id,
            "text"      : message,
            "parse_mode": "Markdown"
        }
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except:
        return False
    

if __name__ == "__main__":
    print("Testing Alert Manager...")
    print("=" * 50)

    # Fake alert to test with
    fake_alert = {
        "underlying"  : "NIFTY",
        "expiry"      : "2026-07-10",
        "strike"      : 24500,
        "option_type" : "PE",
        "label"       : "ATM",
        "spot_price"  : 24480.0,
        "atm"         : 24500,
        "current_oi"  : 280000,
        "prev_oi"     : 40000,
        "day_open_oi" : 30000,
        "chg_3sec_pct": 600.0,
        "chg_day_pct" : 833.3,
        "ltp"         : 85.5,
        "iv"          : 22.3,
        "trigger"     : "3 Second Spike + Day Open Spike",
        "time"        : "11:42:07",
    }

    print("\n[1] Testing sound beep...")
    play_beep()
    print("    Beep done")

    print("\n[2] Testing Telegram message...")
    print("    Message preview:")
    preview = format_telegram_message(fake_alert)
    print(preview.encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8'))
    # Removed direct send to prevent duplicate Telegram alerts during testing
    # result = send_telegram(fake_alert)
    # print(f"    Sent: {result}")

    print("\n[3] Testing CSV log...")
    log_to_csv(fake_alert)
    print(f"    CSV saved to: {ALERTS_CSV}")

    print("\n[4] Full fire_alert test...")
    fire_alert(fake_alert)

    print("\n" + "=" * 50)
    print("Test complete")