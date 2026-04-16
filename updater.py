from api import BinanceAPI
from datetime import datetime, timedelta
import time
import json

api = BinanceAPI()

def main():
    day = (datetime.now() - timedelta(days=1)).day

    start = time.time()
    api.get_account_balance()

    if datetime.now().day != day:
        api.get_delisting_positions()
        day = datetime.now().day

    new_day = api.update_data()
    api.select_symbols(new_day=new_day)

    dt = time.time() - start
    if dt < 10:
        time.sleep(10 - dt)

if __name__ == "__main__":
    while True:
        try:
            main()
        except:
            time.sleep(5)
            main()