import json
import time

def calculate_price_points(current_price, deep_fall=False):
    if deep_fall:
        buy = [current_price - (current_price * i / 100) for i in range(1, 11)]
        return buy, None
    buy = [current_price - (current_price * i / 100) for i in range(1, 11)]
    sell = current_price + (current_price * 5 / 100)
    return buy, sell

def calculate_purchase_amount(price, goal=100):
    amount = goal / price
    return amount

def sf(value, digits=3):
    """Significant figures to n digits."""
    return float(f"{value:.{digits}g}")

def log(type, symbol, price):
    with open("log.json", "r") as f:
        data = json.load(f)
    
    data.append({"type": type, "symbol": symbol, "price": price, "timestamp": time.time()})

    with open("log.json", "w") as f:
        json.dump(data, f, indent=4)
if __name__ == "__main__":
    print(log("ENTRY", "ZAMAUSDT", 0.001102))