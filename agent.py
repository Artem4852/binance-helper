import json
import time
import os
from datetime import datetime

from requests.exceptions import Timeout

from helper import calculate_price_points, calculate_purchase_amount, sf, log
from api import BinanceAPI
from api_bybit import BybitAPI
from api_okx import OKXAPI
from api_kucoin import KuCoinAPI

with open("parameters.json", "r") as f:
    parameters = json.load(f)
    max_symbols = parameters.get("max_symbols", 20)
    max_budget = parameters.get("max_budget", 100)
    always_block = parameters.get("always_block", [])
    exchange = parameters.get("exchange", "binance")

def load_json_file(filename):
    for _ in range(10):
        try:
            with open(filename, "r") as f:
                return json.load(f)
        except Exception as e:
            time.sleep(0.5)

def get_sell_quantity(symbol_name: str):
    if exchange == "okx": symbol_name = symbol_name.replace("-USDT-SWAP", "USDT")
    elif exchange == "kucoin": symbol_name = symbol_name.replace("USDTM", "USDT")
    balance = load_json_file("balance.json")
    position = [p for p in balance['positions'] if p['symbol'] == symbol_name]
    if not position:
        return 0
    position = position[0]
    return float(position['positionAmt'])

def get_unrealized_profit(symbol_name: str):
    if exchange == "okx": symbol_name = symbol_name.replace("-USDT-SWAP", "USDT")
    elif exchange == "kucoin": symbol_name = symbol_name.replace("USDTM", "USDT")
    balance = load_json_file("balance.json")
    position = [p for p in balance['positions'] if p['symbol'] == symbol_name]
    if not position:
        return 0
    position = position[0]
    return float(position['unrealizedProfit'])

class Symbol:
    def __init__(self, name: str, price_at_entry=None, deep_fall=False, price_points=None):
        self.name = name
        self.price_at_entry = price_at_entry
        self.deep_fall = deep_fall
        self.current_price = None
        self.price_points = price_points if price_points is not None else []
        if exchange == "binance":
            self.api = BinanceAPI()
        elif exchange == "bybit":
            self.api = BybitAPI()
        elif exchange == "kucoin":
            self.api = KuCoinAPI()
        else:
            self.api = OKXAPI()

    def update(self, price: float):
        self.current_price = price
        if self.price_at_entry is None:
            self.price_at_entry = price
            buy, sell = calculate_price_points(price)
            for point in buy:
                point = {"side": "BUY", "price": point, "executed": False}
                self.price_points.append(point)
            sell_point = {"side": "SELL", "price": sell, "executed": False}
            self.price_points.append(sell_point)
        
        for point in self.price_points:
            if point['side'] == "SELL" and price > point['price'] and not point['executed']:
                quantity = get_sell_quantity(self.name)
                if quantity == 0:
                    continue
                print(f"Selling {quantity} {self.name} at {price}")
                if not self.api.trade_symbol(self.name, "SELL", quantity):
                    return None
                log("SELL", self.name, point['price'])
                point['executed'] = True
                return "SOLD"

            elif point['side'] == "BUY" and not point['executed'] and price < point['price']:
                print(f"Buying {sf(calculate_purchase_amount(price, max_budget/10), 1)} {self.name} at {price}")
                if not self.api.trade_symbol(self.name, "BUY", sf(calculate_purchase_amount(price, max_budget/10), 1)):
                    return None
                log("BUY", self.name, point['price'])
                point['executed'] = True
                return "BOUGHT"
        
        if not self.deep_fall and price < self.price_at_entry * 0.8:
            self.deep_fall = True
            buy, _ = calculate_price_points(self.price_at_entry * 0.8, True)
            for point in buy:
                point = {"side": "BUY", "price": point, "executed": False}
                self.price_points.append(point)
                log("DEEPFALL", self.name, point['price'])
        
        elif self.deep_fall:
            if get_unrealized_profit(self.name) > 1:
                quantity = get_sell_quantity(self.name)
                print(f"Selling all of {self.name} at {self.current_price} due to deep fall exit")
                log("SELLALL", self.name, self.current_price)
                if not self.api.trade_symbol(self.name, "SELL", quantity):
                    return None
                return "SOLD"

    def sell_everything(self):
        purchased = sum(1 for p in self.price_points if p['side'] == "BUY" and p['executed'])
        if purchased == 0:
            return "NOTHING_TO_SELL"
    
        print(f"Selling all of {self.name} at {self.current_price}")
        # self.api.trade_symbol(self.name, "SELL", sf(calculate_purchase_amount(self.current_price, 5*purchased), 2))
        return "SOLD"

class Agent:
    def __init__(self):
        self.current_symbol_names = []
        self.traded_symbol_names = []
        self.banned_for_today = []
        self.symbols = []
        self.symbols_with_max_leverage = []
        self.load_data()
        self.last_banned_reset = datetime.now()
        if exchange == "binance":
            self.api = BinanceAPI()
        elif exchange == "bybit":
            self.api = BybitAPI()
        elif exchange == "kucoin":
            self.api = KuCoinAPI()
        else:
            self.api = OKXAPI()

    def load_data(self):
        if not os.path.exists('agent.json'):
            data = {
                'current_symbol_names': [],
                'traded_symbol_names': [],
                'banned_for_today': always_block.copy(),
                'symbols': [],
                'symbols_with_max_leverage': [],
                'last_updated': str(time.time())
            }
            with open('agent.json', 'w') as file:
                json.dump(data, file, indent=4)

        with open('agent.json', 'r') as file:
            data = json.load(file)
            self.banned_for_today = data['banned_for_today']
            for symbol in data['symbols']:
                sym = Symbol(symbol['name'], price_at_entry=symbol['price_at_entry'], deep_fall=symbol.get('deep_fall', False), price_points=symbol['price_points'])
                self.symbols.append(sym)
            self.current_symbol_names = [s.name for s in self.symbols]
            self.traded_symbol_names = [s.name for s in self.symbols if any(p['executed'] for p in s.price_points if p['side'] == "BUY")]
            self.symbols_with_max_leverage = data['symbols_with_max_leverage']

    def save_data(self):
        data = {
            'current_symbol_names': self.current_symbol_names,
            'traded_symbol_names': self.traded_symbol_names,
            'banned_for_today': self.banned_for_today,
            'symbols': [],
            'symbols_with_max_leverage': self.symbols_with_max_leverage,
            'last_updated': str(time.time())
        }
        for symbol in self.symbols:
            sym_data = {
                'name': symbol.name,
                'price_at_entry': symbol.price_at_entry,
                'current_price': symbol.current_price,
                'deep_fall': symbol.deep_fall,
                'price_points': symbol.price_points
            }
            data['symbols'].append(sym_data)
        
        with open('agent.json', 'w') as file:
            json.dump(data, file, indent=4)
    
    def is_symbol_with_max_leverage(self, symbol_name: str) -> bool:
        if symbol_name in self.symbols_with_max_leverage:
            return True
        return False

    def add_symbol_with_max_leverage(self, symbol_name: str):
        if symbol_name not in self.symbols_with_max_leverage:
            self.symbols_with_max_leverage.append(symbol_name)

    def load_additional_tickers(self):
        return load_json_file("additional_tickers.json")['tickers']
    
    def get_prices(self):
        return load_json_file("prices.json")

    def update(self):
        if len(self.traded_symbol_names) < max_symbols:
            additional_symbols = self.load_additional_tickers()
            for sym in additional_symbols:
                if sym not in self.current_symbol_names and sym not in self.banned_for_today:
                    if not self.api.additional_validation(sym):
                        self.banned_for_today.append(sym)
                        continue

                    log("START", sym, "")
                    self.symbols.append(Symbol(sym))
                    self.current_symbol_names.append(sym)
                    break
        
        elif len(self.traded_symbol_names) >= max_symbols:
            self.symbols = [s for s in self.symbols if s.name in self.traded_symbol_names or any(p['executed'] for p in s.price_points if p['side'] == "BUY")]
            self.current_symbol_names = [s.name for s in self.symbols]
        
        new_symbols = []
        price_dict = self.get_prices()
        executed = False
        for symbol in self.symbols:
            current_price = price_dict.get(symbol.name)
            if current_price is None:
                continue
            if executed:
                new_symbols.append(symbol)
                continue

            result = symbol.update(float(current_price))
            if result == "SOLD":
                self.banned_for_today.append(symbol.name)
                self.current_symbol_names.remove(symbol.name)
                self.traded_symbol_names.remove(symbol.name)
                log("EXIT", symbol.name, current_price)
            elif result == "BOUGHT":
                executed = True
                if symbol.name not in self.traded_symbol_names:
                    log("ENTRY", symbol.name, current_price)
                    self.traded_symbol_names.append(symbol.name)
            
            if result != "SOLD":
                new_symbols.append(symbol)
        self.symbols = new_symbols

        self.save_data()
        self.reset_daily()

    def sell_symbol(self, symbol_name: str):
        for symbol in self.symbols:
            if symbol.name == symbol_name:
                result = symbol.sell_everything()
                if result == "SOLD":
                    self.banned_for_today.append(symbol.name)
                    self.symbols.remove(symbol)
                    self.current_symbol_names.remove(symbol.name)
                return result
        return "SYMBOL_NOT_FOUND"
    
    def sell_all(self):
        for symbol in self.symbols[:]:
            result = symbol.sell_everything()
            if result == "SOLD":
                self.banned_for_today.append(symbol.name)
                self.symbols.remove(symbol)
                self.current_symbol_names.remove(symbol.name)
        self.save_data()

    def reset_daily(self):
        now = datetime.now()
        if now.date() != self.last_banned_reset.date():
            self.banned_for_today = always_block.copy()
            self.last_banned_reset = now
            self.save_data()

if __name__ == "__main__":
    agent = Agent()
    while True:
        try:
            s = time.time()
            agent.update()
            if time.time() - s < 0.5:
                time.sleep(0.5 - (time.time() - s))
            print (f"Update cycle took {time.time() - s:.2f} seconds")
        except Timeout:
            print("Request timed out. Retrying...")
            time.sleep(5)