import logging, json, os, dotenv, re
import datetime
from telegram import KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import CommandHandler, MessageHandler, ConversationHandler, ApplicationBuilder
from telegram.ext import filters
from datetime import datetime

from helper import sf

dotenv.load_dotenv()
token = os.getenv("TELEGRAM_API_TOKEN")

with open("parameters.json", "r") as f:
    parameters = json.load(f)
    exchange = parameters.get("exchange", "binance")

# Configure logging settings
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

def load_balance():
    with open('balance.json', 'r') as f:
        data = json.load(f)

    with open('agent.json', 'r') as f:
        agent_data = json.load(f)

    balance_data = {
        "totalWalletBalance": float(data.get("totalWalletBalance", 0)),
        "totalUnrealizedProfit": float(data.get("totalUnrealizedProfit", 0)),
        "totalMarginBalance": float(data.get("totalMarginBalance", 0)),
        "positions": [],
        "lastUpdated": agent_data.get("last_updated", "")
    }
    for position in data.get("positions", []):
        balance_data["positions"].append({
            "symbol": position.get("symbol", ""),
            "positionAmt": float(position.get("positionAmt", 0)),
            "unrealizedProfit": float(position.get("unrealizedProfit", 0))
        })
    return balance_data

def load_delisting_positions():
    with open('delisting_positions.json', 'r') as f:
        data = json.load(f)
    return data

def reply_keyboard(buttons):
    if isinstance(buttons[0], list):
        keyboard = [[KeyboardButton(button) for button in row] for row in buttons]
    else:
        keyboard = [[KeyboardButton(button) for button in buttons]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def set_boundary(kind, value, notified):
    with open('boundaries.json', 'r') as f:
        boundaries = json.load(f)
    boundaries[kind] = [value, notified]
    with open('boundaries.json', 'w') as f:
        json.dump(boundaries, f)

def get_boundary(kind):
    with open('boundaries.json', 'r') as f:
        boundaries = json.load(f)
    return boundaries.get(kind, [0, False])

if exchange == "binance" and token.startswith("837"):
    default_keyboard = reply_keyboard([['/balance', '/price_points'], ['/set_upper_boundary', '/set_lower_boundary']])
else:
    default_keyboard = reply_keyboard([['/balance', '/price_points']])

async def start(update, context):
    user_id = update.message.from_user.id
    if not user_id in [879805663, 452856763]: return
    await update.message.reply_text(
        "Welcome to the Bot! Use the commands below to interact.",
        reply_markup=default_keyboard
    )

async def balance(update, context):
    user_id = update.message.from_user.id
    if not user_id in [879805663, 452856763]: return
    balance_data = load_balance()
    delisting_positions = load_delisting_positions()
    response = (
        f"Total Wallet Balance: ${balance_data['totalWalletBalance']:.2f}\n"
        f"Total Unrealized Profit: ${balance_data['totalUnrealizedProfit']:.2f}\n"
        f"Total Margin Balance: ${balance_data['totalMarginBalance']:.2f}\n"
        f"Total Positions: {len(balance_data['positions'])}\n\n"
        "Positions:\n"
    )
    balance_data['positions'].sort(key=lambda x: x['unrealizedProfit'], reverse=True)
    for position in balance_data['positions']:
        link = f"<a href='https://www.binance.com/en/futures/{position['symbol']}'>{position['symbol']}</a> | " if exchange == "binance" else f"{position['symbol']} | "
        delisting = "⚠️ DELISTING\n" if position['symbol'] in delisting_positions else "\n"
        response += (
            link +
            f"Amt: {position['positionAmt']} | " +
            f"PNL: ${sf(position['unrealizedProfit'])}" +
            delisting
        )

    updated_str = balance_data.get("lastUpdated", "")
    updated_str = datetime.fromtimestamp(float(updated_str)).strftime('%Y-%m-%d %H:%M:%S') if updated_str else "N/A"
    response += f"\nLast Updated: {updated_str}"

    await update.message.reply_text(response, reply_markup=default_keyboard, parse_mode='html', disable_web_page_preview=True)


async def pnl_update(context):
    balance_data = load_balance()
    marginBalance = balance_data.get("totalMarginBalance", 0)
    upperBoundary, upperBoundaryNotified = get_boundary("upperBoundary")
    lowerBoundary, lowerBoundaryNotified = get_boundary("lowerBoundary")

    if marginBalance >= upperBoundary and not upperBoundaryNotified:
        message = f"Margin Balance has reached the upper boundary: ${marginBalance:.2f} (Threshold: ${upperBoundary:.2f})"
        await context.bot.send_message(chat_id=452856763, text=message)
        set_boundary("upperBoundary", upperBoundary, True)
    elif marginBalance < upperBoundary and upperBoundaryNotified:
        set_boundary("upperBoundary", upperBoundary, False)
    
    if marginBalance <= lowerBoundary and not lowerBoundaryNotified:
        message = f"Margin Balance has reached the lower boundary: ${marginBalance:.2f} (Threshold: ${lowerBoundary:.2f})"
        await context.bot.send_message(chat_id=452856763, text=message)
        set_boundary("lowerBoundary", lowerBoundary, True)
    elif marginBalance > lowerBoundary and lowerBoundaryNotified:
        set_boundary("lowerBoundary", lowerBoundary, False)

async def set_upper_boundary(update, context):
    user_id = update.message.from_user.id
    if not user_id in [879805663, 452856763]: return
    await update.message.reply_text("Send me the upper boundary amount (e.g. 100):")
    return 0

async def receive_upper_boundary(update, context):
    user_id = update.message.from_user.id
    if not user_id in [879805663, 452856763]: return
    try:
        upper_boundary = float(update.message.text)
        set_boundary("upperBoundary", upper_boundary, False)
        await update.message.reply_text(f"Upper boundary set to ${upper_boundary:.2f}.")
    except ValueError:
        await update.message.reply_text("Invalid input. Please send a valid number for the upper boundary.")
    return ConversationHandler.END

async def set_lower_boundary(update, context):
    user_id = update.message.from_user.id
    if not user_id in [879805663, 452856763]: return
    await update.message.reply_text("Send me the lower boundary amount (e.g. 100):")
    return 0

async def receive_lower_boundary(update, context):
    user_id = update.message.from_user.id
    if not user_id in [879805663, 452856763]: return
    try:
        lower_boundary = float(update.message.text)
        set_boundary("lowerBoundary", lower_boundary, False)
        await update.message.reply_text(f"Lower boundary set to ${lower_boundary:.2f}.")
    except ValueError:
        await update.message.reply_text("Invalid input. Please send a valid number for the lower boundary.")
    return ConversationHandler.END

async def symbols_update(context):
    with open("selected_symbols.json", "r") as f:
        selected_symbols = json.load(f)
    with open("selected_symbols_2.json", "r") as f:
        selected_symbols_2 = json.load(f)
    
    message = "Selected Symbols:\n\n" + "\n".join(selected_symbols) + "\n\n" + "Selected Symbols 2nd level:\n\n" + "\n".join(selected_symbols_2)
    await context.bot.send_message(chat_id=452856763, text=message)

def main():
    application = ApplicationBuilder().token(token).build()

    upper_boundary_conv = ConversationHandler(
        entry_points=[CommandHandler('set_upper_boundary', set_upper_boundary)],
        states={
            0: [MessageHandler(filters.TEXT, receive_upper_boundary)]
        },
        fallbacks=[]
    )
    lower_boundary_conv = ConversationHandler(
        entry_points=[CommandHandler('set_lower_boundary', set_lower_boundary)],
        states={
            0: [MessageHandler(filters.TEXT, receive_lower_boundary)]
        },
        fallbacks=[]
    )

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('balance', balance))
    application.add_handler(upper_boundary_conv)
    application.add_handler(lower_boundary_conv)

    application.job_queue.run_repeating(pnl_update, interval=5, first=5)
    application.job_queue.run_repeating(symbols_update, interval=10, first=10)

    application.run_polling(poll_interval=1)

if __name__ == '__main__':
    main()