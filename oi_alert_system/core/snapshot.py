import config
import json
import os
import sys
from datetime import datetime
import pytz


sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import config

SNAPSHOT_FILE=os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data","day_snapshot.json"
)

def get_today_str():
    ist=pytz.timezone(config.TIMEZONE)
    return datetime.now(ist).strftime("%Y-%m-%d")

def snapshot_exists_today():
    """
    It returns true if already a snapshot exists or saved.

    """
    if not os.path.exists(SNAPSHOT_FILE):
        return False

    try:
        with open(SNAPSHOT_FILE,"r") as f:
            data=json.load(f)
        return data.get("date") == get_today_str()
    
    except:
        return False

def take_day_snapshot(all_chain_data):
    """
    Save full OI snapshot at market start (9:15 AM IST)
    So you can see how OI grew during the day.

    Args:
        all_chain_data : dict containing OI data for all strikes/expiries
    """
    
    snapshot={
        "date":get_today_str(),
        "time":datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%H:%M:%S"),
        "data": {}

    }

    for key, chain in all_chain_data.items():
        snapshot["data"][key]={}
        oc=chain.get("oc",{})

        for strike_str,values in oc.items():
            ce=values.get("ce",{})
            pe=values.get("pe",{})

            snapshot["data"][key][f"{strike_str}_CE"]={ 
                "oi": ce.get("oi",0),
                "previous_oi" : ce.get("previous_oi", 0),
                "ltp" : ce.get("last_price", 0), 
            }

            snapshot["data"][key][f"{strike_str}_PE"]={
                "oi": pe.get("oi",0),
                "previous_oi" : pe.get("previous_oi", 0),
                "ltp" : pe.get("last_price", 0), 

            }
    
    os.makedirs(os.path.dirname(SNAPSHOT_FILE), exist_ok=True)
    with open(SNAPSHOT_FILE,"w") as f:
        json.dump(snapshot,f,indent=4)

    total_strikes=sum(len(v) for v in snapshot["data"].values())
    print(f"[snapshot] Dday open snapshot saved - {total_strikes} strike-option pairs")
    return True

def load_day_snapshot():
    if not os.path.exists(SNAPSHOT_FILE):
        return {}

    try:
        with open(SNAPSHOT_FILE, "r") as f:
            data=json.load(f)

        if data.get("date") !=get_today_str():
            print("[Snapshot] snapshot is from a prevoius day - will retake")
            return {}
        
        return data.get("data",{})

    except Exception as e:
        print(f"[Snapshot] Error loading snapshot : {e}")
        return {}

def get_day_open_oi(snapshot, chain_key, strike_str, option_type):
    """get day Open OI for a specific strike/option"""

    key=f"{strike_str}_{option_type}"
    return snapshot.get(chain_key,{}).get(key,{}).get("oi",0)

# test

if __name__ == "__main__":
    print("Snapshot exists today:", snapshot_exists_today())

    # Simulate a fake chain to test saving
    fake_chain = {
        "NIFTY_2026-07-10": {
            "last_price": 24480.5,
            "oc": {
                "24400": {
                    "ce": {"oi": 50000, "previous_oi": 40000, "last_price": 142.5},
                    "pe": {"oi": 43000, "previous_oi": 38000, "last_price": 98.0},
                },
                "24450": {
                    "ce": {"oi": 35000, "previous_oi": 30000, "last_price": 105.0},
                    "pe": {"oi": 60000, "previous_oi": 55000, "last_price": 115.0},
                },
            }
        }
    }

    take_day_snapshot(fake_chain)
    loaded = load_day_snapshot()
    print("Loaded snapshot keys:", list(loaded.keys()))
    oi = get_day_open_oi(loaded, "NIFTY_2026-07-10", "24400", "CE")
    print(f"Day open OI for 24400 CE: {oi}")
    
   