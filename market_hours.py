from datetime import datetime, time
import pytz
import sys
import os


sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import config 

def get_ist_now():
    ist=pytz.timezone(config.TIMEZONE)
    return datetime.now(ist)

def is_market_open():
    now=get_ist_now()

    if now.weekday() > 4:
        return False

    today_str=now.strftime("%Y-%m-%d")
    if today_str in config.NSE_HOLIDAYS_2026:
        return False
    
    #check time
    market_start=time(9, 15, 0)
    market_end=time(15, 30, 0)
    current_time=now.time()
    return market_start <= current_time <=market_end

def is_market_day():
    now=get_ist_now()

    if now.weekday() > 4:
        return False
    
    today_str=now.strftime("%Y-%m-%d")
    if today_str in config.NSE_HOLIDAYS_2026:
        return False

    return True


def seconds_to_market_open():
    if not is_market_day():
        return -1

    now = get_ist_now()
    ist = pytz.timezone(config.TIMEZONE)
    today = now.date()

    market_open = ist.localize(datetime(today.year, today.month, today.day, 9, 15, 0))
    market_close = ist.localize(datetime(today.year, today.month, today.day, 15, 30, 0))

    if now < market_open:
        return int((market_open - now).total_seconds())
    elif now <= market_close:
        return 0
    else:
        return -1


def get_market_status():
    now=get_ist_now()
    today=now.strftime("%Y-%m-%d")
    ist=pytz.timezone(config.TIMEZONE)

    if now.weekday() > 4:
        return "closed", "Weekend"
    
    if today in config.NSE_HOLIDAYS_2026:
        return "closed", "NSE Holiday"
    
    market_open  = ist.localize(datetime(now.year, now.month, now.day, 9, 15, 0))
    market_close = ist.localize(datetime(now.year, now.month, now.day, 15, 30, 0))

    if now < market_open:
        mins=int((market_open - now).total_seconds() // 60)
        return "Pre-Open" , f"Opens in {mins} minutes"
    
    if now > market_close:
        return "closed" , "market Closed"

    return "open", "Market Open"

# CORE

if __name__=="__main__":
    now=get_ist_now()
    status, message=get_market_status()
    secs=seconds_to_market_open()

    print(f"Current IST Time :{now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}")
    print(f"Market Status : {status.upper()} - {message}")
    print(f"Is Market Open : {is_market_open()}")
    print(f"Is Market Day : {is_market_day()}")
    
    if secs > 0:
        print(f"Opens in   : {secs //60} mins {secs % 60} sec")
    
    elif secs ==0:
        print(f"Market is open right now")
    else:
        print(f"Market closed for today")