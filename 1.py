import requests
import json
import threading

with open("prices.json", "r") as f:
    price_dict = json.load(f)
    symbols = list(price_dict.keys())

# we need price that was today at 00:00 UTC
def get_price_at_midnight(symbol):
    print(symbol)
    endpoint = "/fapi/v1/klines"
    url = "https://fapi.binance.com" + endpoint
    params = {
        "symbol": symbol,
        "interval": "1d",
        "limit": 1
    }
    response = requests.get(url, params=params)
    data = response.json()
    if isinstance(data, list) and len(data) > 0:
        return float(data[0][1])  # Open price of the day
    return None

symbol_groups = [symbols[i:i + 10] for i in range(0, len(symbols), 10)]

prices_at_midnight = {}

for symbol_group in symbol_groups:
    threads = []
    for symbol in symbol_group:
        thread = threading.Thread(target=lambda s: prices_at_midnight.update({s: get_price_at_midnight(s)}), args=(symbol,))
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()
# for symbol in symbols:
#     print(f"Getting price at midnight for {symbol}...")
#     price = get_price_at_midnight(symbol)
#     if price is not None:
#         prices_at_midnight[symbol] = price

with open("prices_daily.json", "w") as f:
    json.dump(prices_at_midnight, f, indent=4)