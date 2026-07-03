
#  All Dhan API communication happens here
#  Every other file talks to Dhan through this file only


import requests
import time
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import config


def get_headers():
    """
    Returns auth headers for every Dhan API call.
    Reads token fresh every time so token updates
    from control panel are picked up automatically.
    """
    # Re-import config fresh to get latest token
    import importlib
    importlib.reload(config)

    return {
        "Content-Type" : "application/json",
        "access-token" : config.DHAN_ACCESS_TOKEN,
        "client-id"    : config.DHAN_CLIENT_ID,
    }



#  TOKEN FUNCTIONS

def validate_token():
    """
    Checks if current token is valid.
    Returns True if valid, False if expired or invalid.
    Calls /profile endpoint — lightest possible API call.
    """
    try:
        response = requests.get(
            f"{config.DHAN_BASE_URL}/profile",
            headers=get_headers(),
            timeout=10
        )
        if response.status_code == 200:
            return True, "Token is valid"
        elif response.status_code == 401:
            return False, "Token expired or invalid"
        else:
            return False, f"Unexpected status: {response.status_code}"

    except requests.exceptions.Timeout:
        return False, "Request timed out"
    except requests.exceptions.ConnectionError:
        return False, "No internet connection"
    except Exception as e:
        return False, f"Error: {str(e)}"


def renew_token():
    """
    Renews current token for another 24 hours.
    Called from control panel Renew Token button.
    Returns new token string if successful, None if failed.
    """
    try:
        response = requests.get(
            f"{config.DHAN_BASE_URL}/RenewToken",
            headers=get_headers(),
            timeout=10
        )

        if response.status_code == 200:
            data      = response.json()
            new_token = data.get("accessToken") or data.get("access_token")
            if new_token:
                return True, new_token
            return False, "Token not found in response"

        return False, f"Failed with status: {response.status_code}"

    except Exception as e:
        return False, f"Error: {str(e)}"



#  EXPIRY FUNCTIONS


def get_expiry_list(scrip, seg):
    """
    Fetches all available expiry dates for an underlying.
    Used by control panel to populate expiry dropdown.

    Args:
        scrip : int   — e.g. 13 for NIFTY
        seg   : str   — e.g. "IDX_I"

    Returns:
        list of expiry date strings ["2026-07-10", "2026-07-17", ...]
    """
    try:
        payload = {
            "UnderlyingScrip" : scrip,
            "UnderlyingSeg"   : seg,
        }

        response = requests.post(
            f"{config.DHAN_BASE_URL}/optionchain/expirylist",
            headers=get_headers(),
            json=payload,
            timeout=10
        )

        if response.status_code == 200:
            data    = response.json()
            expiries = data.get("data", [])
            return True, expiries

        return False, f"Failed with status: {response.status_code}"

    except Exception as e:
        return False, f"Error: {str(e)}"



#  OPTION CHAIN — MAIN FUNCTION


def get_option_chain(scrip, seg, expiry, retries=3):
    """
    Fetches full option chain for one underlying + one expiry.
    This is called every 3 seconds by the main monitoring loop.

   
    """
    attempt = 0

    while attempt < retries:
        try:
            payload = {
                "UnderlyingScrip" : scrip,
                "UnderlyingSeg"   : seg,
                "Expiry"          : expiry,
            }

            response = requests.post(
                f"{config.DHAN_BASE_URL}/optionchain",
                headers=get_headers(),
                json=payload,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                return True, data.get("data", {})

            elif response.status_code == 401:
                return False, "TOKEN_EXPIRED"

            elif response.status_code == 429:
                # Rate limited — wait longer
                print(f"[Dhan] Rate limited — waiting 5 seconds")
                time.sleep(5)
                attempt += 1
                continue

            else:
                attempt += 1
                if attempt < retries:
                    print(f"[Dhan] API error {response.status_code} — retry {attempt}/{retries}")
                    time.sleep(3)
                continue

        except requests.exceptions.Timeout:
            attempt += 1
            if attempt < retries:
                print(f"[Dhan] Timeout — retry {attempt}/{retries}")
                time.sleep(3)

        except requests.exceptions.ConnectionError:
            attempt += 1
            if attempt < retries:
                print(f"[Dhan] No connection — retry {attempt}/{retries}")
                time.sleep(5)

        except Exception as e:
            return False, f"Unexpected error: {str(e)}"

    return False, f"Failed after {retries} retries"


def get_spot_price(scrip, seg, expiry):
    """
    Gets current spot price of underlying.
    Extracted from option chain response.
    Used to calculate ATM strike.

    Returns spot price as float, or None on failure.
    """
    success, data = get_option_chain(scrip, seg, expiry)

    if not success:
        return None

    return data.get("last_price")



#  python core/dhan_client.py

if __name__ == "__main__":
    print("=" * 50)
    print("  Dhan API Connection Test")
    print("=" * 50)

    # Step 1 — validate token
    print("\n[1] Validating token...")
    valid, msg = validate_token()
    print(f"    Result: {msg}")

    if not valid:
        print("\n    [ERROR] Token invalid. Update your token in config.py first.")
        sys.exit(1)

    # Step 2 — get expiry list
    print("\n[2] Fetching NIFTY expiry list...")
    success, expiries = get_expiry_list(13, "IDX_I")
    if success:
        print(f"    Available expiries: {expiries[:4]}")
    else:
        print(f"    Failed: {expiries}")

    # Step 3 — fetch option chain
    if success and expiries:
        nearest_expiry = expiries[0]
        print(f"\n[3] Fetching NIFTY option chain for {nearest_expiry}...")
        ok, chain = get_option_chain(13, "IDX_I", nearest_expiry)

        if ok:
            spot    = chain.get("last_price")
            strikes = list(chain.get("oc", {}).keys())
            print(f"    Spot Price   : {spot}")
            print(f"    Total Strikes: {len(strikes)}")
            print(f"    Sample strikes: {strikes[:5]}")

            # Show sample OI data
            if strikes:
                sample_strike = strikes[len(strikes)//2]
                sample_data   = chain["oc"][sample_strike]
                ce_oi = sample_data.get("ce", {}).get("oi", "N/A")
                pe_oi = sample_data.get("pe", {}).get("oi", "N/A")
                print(f"\n    Sample Strike : {sample_strike}")
                print(f"    CE OI         : {ce_oi}")
                print(f"    PE OI         : {pe_oi}")
        else:
            print(f"    Failed: {chain}")

    print("\n" + "=" * 50)
    print("  Test Complete")
    print("=" * 50)