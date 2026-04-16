import requests
import json
import os, dotenv
import time
from datetime import datetime

import hmac
import hashlib

from helper import calculate_price_points, calculate_purchase_amount, sf

dotenv.load_dotenv()

proxy_user = os.getenv("PROXY_USER")
proxy_pass = os.getenv("PROXY_PASS")
proxy_ip = os.getenv("PROXY_IP")

def has_no_ascii(s: str):
    return all(ord(c) < 128 for c in s)

def url_encode_tickers(tickers):
    tickets_new = []
    for t in tickers:
        if has_no_ascii(t): tickets_new.append(t)
    if len(tickets_new) > 100:
        tickets_new = tickets_new[len(tickets_new)-100:]
    output = json.dumps(tickets_new).replace(" ", "")
    return output

def sign_payload(payload: dict, secret: str):
    query_string = '&'.join([f"{key}={value}" for key, value in payload.items()])
    signature = hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    return signature

def today():
    return datetime.now().strftime("%d")

class BinanceAPI:
    def __init__(self):
        self.base_url = "https://api.binance.com"
        self.futures_url = "https://fapi.binance.com"
        # self.futures_url = "https://demo-fapi.binance.com"
        self.api_key = os.getenv("BINANCE_KEY")
        self.api_secret = os.getenv("BINANCE_SECRET")
        self.session = requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": self.api_key})
        self.session.proxies.update({
            "http": f"http://{proxy_user}:{proxy_pass}@{proxy_ip}:59100",
            "https": f"http://{proxy_user}:{proxy_pass}@{proxy_ip}:59100"
        })

        self.last_day_updated = today()

    def get_tickers_24hr(self):
        endpoint = "/api/v3/ticker/24hr"
        url = self.base_url + endpoint

        response = self.session.get(url)
        response.raise_for_status()

        tickers = response.json()

        filtered_tickers = [t for t in tickers if t['symbol'].endswith('USDT')]
        filtered_tickers.sort(key=lambda x: float(x['quoteVolume']), reverse=True)
        filtered_tickers = [t for t in filtered_tickers if float(t['quoteVolume']) > 5_000_000]

        return filtered_tickers
    
    def get_tickers_trading_day(self, tickers: list):
        endpoint = "/api/v3/ticker/tradingDay"
        url = self.base_url + endpoint

        params = {
            "symbols": url_encode_tickers(tickers),
            "timeZone": "1"
        }

        for key, value in params.items():
            url += f"{'&' if '?' in url else '?'}{key}={value}"

        response = self.session.get(url)
        if 399 < response.status_code < 500:
            print(f"Error fetching trading day tickers: {response.status_code} - {response.text}")
            return []
        response.raise_for_status()

        tickers = response.json()
        filtered_tickers = [t for t in tickers if 15 > abs(float(t['priceChangePercent'])) > 10]
        return filtered_tickers
    
    def choose_tickers(self):
        filtered_tickers = self.get_tickers_24hr()
        print(f"Tickers with volume > 5M: {len(filtered_tickers)}")
        symbols = [t['symbol'] for t in filtered_tickers]
        symbols = self.get_tickers_trading_day(symbols)
        print(symbols)
        final_tickers = []
        for t in symbols:
            if self.is_symbol_on_futures(t['symbol']):
                final_tickers.append(t)
        symbols = [t['symbol'] for t in final_tickers]
        with open("delisting_positions.json", "r") as f:
            delisting_positions = json.load(f)
        symbols = [s for s in symbols if s not in delisting_positions]

        with open("additional_tickers.json", "w") as f:
            json.dump({"tickers": symbols}, f, indent=4)
        return symbols
    
    def seven_day_volume_average(self, symbol: str):
        endpoint = "/fapi/v1/klines"
        url = self.futures_url + endpoint

        params = {
            "symbol": symbol,
            "interval": "1d",
            "limit": 7
        }

        response = self.session.get(url, params=params)
        response.raise_for_status()

        klines = response.json()
        volumes = [float(kline[7]) for kline in klines]
        average_volume = sum(volumes) / len(volumes)
        return average_volume, volumes[-1]
    
    def ticker_age(self, symbol: str):
        with open("exchange_info.json", "r") as f:
            exchange_info = json.load(f)
        for item in exchange_info['symbols']:
            if item['symbol'] == symbol:
                launch_time = item['onboardDate']
                age_days = (int(time.time() * 1000) - launch_time) / (1000 * 60 * 60 * 24)
                return age_days
        return 0
    
    def additional_validation(self, symbol: str):
        seven_day_avg, last_day_volume = self.seven_day_volume_average(symbol)
        if last_day_volume / seven_day_avg > 2.5:  
            return False
        if self.ticker_age(symbol) < 120:
            return False
        return True
    
    def is_symbol_on_futures(self, symbol: str):
        # endpoint = "/fapi/v2/ticker/price"
        # url = self.futures_url + endpoint

        # response = self.session.get(url)

        # prices = response.json()
        # price_dict = {item['symbol']: item['price'] for item in prices}

        with open("prices.json", "r") as f:
            price_dict = json.load(f)

        return symbol in price_dict
    
    def update_prices(self, filename="prices.json"):
        endpoint = "/fapi/v2/ticker/price"
        url = self.futures_url + endpoint

        response = self.session.get(url)
        response.raise_for_status()

        prices = response.json()
        price_dict = {item['symbol']: item['price'] for item in prices}

        with open(filename, "w") as f:
            json.dump(price_dict, f, indent=4)

        return price_dict
    
    def get_max_leverage(self, symbol: str):
        endpoint = "/fapi/v1/leverageBracket"
        url = self.futures_url + endpoint

        params = {
            "timestamp": int(time.time() * 1000)
        }

        signature = sign_payload(params, self.api_secret)
        params['signature'] = signature

        response = self.session.get(url, params=params)
        response.raise_for_status()

        leverage_info = response.json()
        for item in leverage_info:
            if item['symbol'] == symbol:
                return item['brackets'][0]["initialLeverage"]
            
    def set_max_leverage(self, symbol: str):
        max_leverage = self.get_max_leverage(symbol)
        endpoint = "/fapi/v1/leverage"
        url = self.futures_url + endpoint

        params = {
            "symbol": symbol,
            "leverage": max_leverage,
            "timestamp": int(time.time() * 1000)
        }

        signature = sign_payload(params, self.api_secret)
        params['signature'] = signature

        response = self.session.post(url, params=params)
        response.raise_for_status()
    
    def trade_symbol(self, symbol: str, side: str, quantity: float, price: float = None):
        self.set_max_leverage(symbol)

        endpoint = "/fapi/v1/order"
        url = self.futures_url + endpoint

        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET", 
            "quantity": quantity,
            "timestamp": int(time.time() * 1000)
        }

        if price:
            params["type"] = "LIMIT"
            params["price"] = price
            params["timeInForce"] = "GTD"
            params["goodTillDate"] =  int(time.time() + 610) * 1000

        signature = sign_payload(params, self.api_secret)
        params['signature'] = signature

        response = self.session.post(url, params=params)
        if 399 < response.status_code < 500:
            print(f"Error placing order: {response.status_code} - {response.text}")
            return None
        response.raise_for_status()
        return response.json()
    
    def get_account_balance(self):
        endpoint = "/fapi/v3/account"
        url = self.futures_url + endpoint

        params = {
            "timestamp": int(time.time() * 1000)
        }

        signature = sign_payload(params, self.api_secret)
        params['signature'] = signature

        response = self.session.get(url, params=params)
        response.raise_for_status()

        balance_info = response.json()
        with open("balance.json", "w") as f:
            json.dump(balance_info, f, indent=4)
        return balance_info
    
    def get_delisting_positions(self):
        endpoint = "/fapi/v1/exchangeInfo"
        url = self.futures_url + endpoint

        response = self.session.get(url)
        response.raise_for_status()

        exchange_info = response.json()
        with open("exchange_info.json", "w") as f:
            json.dump(exchange_info, f, indent=4)
        delisting_positions = [symbol['symbol'] for symbol in exchange_info['symbols'] if symbol['deliveryDate'] < 3000000000000]
        with open("delisting_positions.json", "w") as f:
            json.dump(delisting_positions, f, indent=4)
        return delisting_positions
    
    def update_data(self):
        self.update_prices()
        new_day = False
        if self.last_day_updated != today():
            self.update_prices("daily_prices.json")
            self.last_day_updated = today()
            new_day = True

        if not os.path.exists("prices_10s.json"):
            with open("prices.json", "r") as f:
                current_prices = json.load(f)
            with open("prices_10s.json", "w") as f:
                json.dump(current_prices, f, indent=4)
            return
        
        with open("prices_10s.json", "r") as f:
            prices_10s = json.load(f)
        with open("daily_prices.json", "r") as f:
            daily_prices = json.load(f)
        with open("prices.json", "r") as f:            
            current_prices = json.load(f)
        daily_change = {}
        change_10s = {}
        for symbol in current_prices:
            if symbol in daily_prices:
                change = (float(current_prices[symbol]) - float(daily_prices[symbol])) / float(daily_prices[symbol]) * 100
                daily_change[symbol] = change
            if symbol in prices_10s:
                change = (float(current_prices[symbol]) - float(prices_10s[symbol])) / float(prices_10s[symbol]) * 100
                change_10s[symbol] = change
        with open("daily_change.json", "w") as f:
            json.dump(daily_change, f, indent=4)
        with open("change_10s.json", "w") as f:
            json.dump(change_10s, f, indent=4)
        with open("prices_10s.json", "w") as f:
            json.dump(current_prices, f, indent=4)
        with open("volume5m.json", "w") as f:
            volume_5m = self.get_tickers_24hr()
            json.dump(volume_5m, f, indent=4)

        return new_day

    def select_symbols(self, new_day=False):
        with open("daily_change.json", "r") as f:
            daily_change = json.load(f)
        with open("change_10s.json", "r") as f:
            change_10s = json.load(f)
        with open("volume5m.json", "r") as f:
            volume_5m = json.load(f)
        with open("additional_data.json", "r") as f:
            additional_data = json.load(f)
            symbols_already = [item['symbol'] for item in additional_data]
        with open("prices.json", "r") as f:
            current_prices = json.load(f)
        
        if new_day:
            additional_data = []
            selected_symbols_old = []
        
        selected_symbols = []
        for item in volume_5m:
            symbol = item['symbol']
            if symbol in daily_change and symbol in change_10s:
                if 15 > daily_change[symbol] and change_10s[symbol] >= 1:
                    selected_symbols.append(symbol)
                
        selected_symbols = [s for s in selected_symbols]
        selected_symbols_2 = []
        for symbol in selected_symbols:
            if symbol not in symbols_already:
                additional_data.append({
                    "symbol": symbol,
                    "selected_at": time.time(),
                    "selected_price": float(current_prices[symbol])
                })
            else:
                if current_prices[symbol] < additional_data[[item['symbol'] for item in additional_data].index(symbol)]['selected_price'] * 0.95:
                    selected_symbols_2.append(symbol)

        with open("selected_symbols.json", "w") as f:
            json.dump(selected_symbols, f, indent=4)
        with open("selected_symbols_2.json", "w") as f:
            json.dump(selected_symbols_2, f, indent=4)
        with open("additional_data.json", "w") as f:
            json.dump(additional_data, f, indent=4)

        return selected_symbols

if __name__ == "__main__":
    api = BinanceAPI()
    print(api.get_delisting_positions())