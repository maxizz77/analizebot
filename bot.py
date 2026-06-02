import logging
import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters
)
import db
import bybit
import alerts
from dotenv import load_dotenv

# Завантажуємо конфігурацію з .env
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))

# Налаштування логування
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник команди /start"""
    chat_id = update.effective_chat.id
    db.add_user(chat_id)
    
    welcome_text = (
        "👋 **Привіт! Я ваш персональний Bybit Futures Activity Bot.**\n\n"
        "Я вмію відстежувати активність обраних вами ф'ючерсів (USDT Perpetual) на біржі Bybit та сповіщати про аномалії.\n\n"
        "📈 **Що саме я роблю:**\n"
        "1. **Моніторинг об'ємів (1м)**: Повідомляю кожної хвилини, якщо об'єм торгів різко зріс порівняно із середнім значенням.\n"
        "2. **Контроль TWAP (4г)**: Розраховую середньозважену за часом ціну (240 хвилинних свічок) та повідомляю про сильні відхилення.\n"
        "3. **Індивідуальні звіти**: Можу регулярно надсилати вам звіт про зміну ціни за обраний проміжок часу (наприклад, кожні 20хв).\n"
        "4. **Індивідуальний список**: Ви самі обираєте ф'ючерси для відстеження.\n\n"
        "📋 **Команди бота:**\n"
        "/coins — Показати відстежувані ф'ючерси та керувати ними\n"
        "/add [монета] — Додати ф'ючерс (наприклад, `/add BTCUSDT`)\n"
        "/remove [монета] — Видалити ф'ючерс (наприклад, `/remove BTCUSDT`)\n"
        "/twap [монета] — Отримати поточну TWAP за 4 години\n"
        "/volume [монета] — Отримати статистику 1м об'єму\n"
        "/settings [монета] [об'єм] [twap_%] — Налаштувати індивідуальні пороги сповіщень\n"
        "/report [монета] [хвилини] — Налаштувати регулярні звіти ціни (наприклад, `/report LAB 20`)\n\n"
        "Натисніть кнопку нижче або напишіть `/coins`, щоб розпочати!"
    )
    
    keyboard = [[InlineKeyboardButton("📋 Мої монети", callback_data="list_coins")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

async def coins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник команди /coins"""
    chat_id = update.effective_chat.id
    db.add_user(chat_id)
    
    coins = db.get_tracked_coins(chat_id)
    
    if not coins:
        message = (
            "📉 **Ваш список відстежуваних ф'ючерсів порожній.**\n\n"
            "Ви можете додати монети за допомогою кнопки нижче або командою:\n"
            "`/add назва_монети` (наприклад, `/add BTCUSDT`)."
        )
        keyboard = [[InlineKeyboardButton("➕ Додати BTCUSDT", callback_data="add_default_btc")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="Markdown")
        return
        
    message = "📋 **Ваші відстежувані ф'ючерси:**\n\n"
    keyboard = []
    
    for row in coins:
        sym = row[0]
        vol_mult = row[1]
        twap_pct = row[2]
        message += f"• **{sym}** (1м Об'єм: `>{vol_mult}x`, TWAP: `>{twap_pct}%`)\n"
        
        # Створюємо кнопки для швидких дій
        keyboard.append([
            InlineKeyboardButton(f"📊 TWAP {sym}", callback_data=f"twap_{sym}"),
            InlineKeyboardButton(f"📈 Vol {sym}", callback_data=f"vol_{sym}"),
            InlineKeyboardButton(f"🗑️ Видалити", callback_data=f"remove_{sym}")
        ])
        
    message += "\n*Додати нову монету можна за допомогою:* `/add [СИМВОЛ]` (наприклад: `/add ETHUSDT`)"
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="Markdown")

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник команди /add <SYMBOL>"""
    chat_id = update.effective_chat.id
    db.add_user(chat_id)
    
    if not context.args:
        await update.message.reply_text("❌ Будь ласка, вкажіть назву пари. Наприклад: `/add BTCUSDT`", parse_mode="Markdown")
        return
        
    symbol = context.args[0].upper().strip()
    
    # Тимчасове повідомлення про перевірку
    status_msg = await update.message.reply_text(f"⏳ Перевіряю ф'ючерс {symbol} на Bybit...")
    
    # Валідація через API Bybit
    active_symbols = bybit.get_active_symbols("linear")
    
    # Якщо список порожній через помилку мережі, спробуємо перевірити через пряму ціну
    if not active_symbols:
        price = bybit.get_current_price(symbol, "linear")
        is_valid = price is not None
    else:
        is_valid = symbol in active_symbols
        
    if not is_valid:
        await status_msg.edit_text(
            f"❌ Ф'ючерс **{symbol}** не знайдено на ринку USDT Perpetual Bybit.\n"
            f"Переконайтеся, що назва правильна (наприклад, `BTCUSDT`, `ETHUSDT`, `SOLUSDT`).",
            parse_mode="Markdown"
        )
        return
        
    db.add_coin(chat_id, symbol)
    await status_msg.edit_text(f"✅ Ф'ючерс **{symbol}** успішно додано до вашого списку відстеження!", parse_mode="Markdown")

async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник команди /remove <SYMBOL>"""
    chat_id = update.effective_chat.id
    
    if not context.args:
        coins = db.get_tracked_coins(chat_id)
        if not coins:
            await update.message.reply_text("Ваш список відстеження порожній.")
            return
            
        keyboard = []
        for row in coins:
            sym = row[0]
            keyboard.append([InlineKeyboardButton(f"🗑️ Видалити {sym}", callback_data=f"remove_{sym}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Оберіть монету для видалення:", reply_markup=reply_markup)
        return
        
    symbol = context.args[0].upper().strip()
    db.remove_coin(chat_id, symbol)
    await update.message.reply_text(f"✅ Монету **{symbol}** видалено зі списку відстеження.", parse_mode="Markdown")

async def twap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник команди /twap <SYMBOL>"""
    chat_id = update.effective_chat.id
    
    if not context.args:
        coins = db.get_tracked_coins(chat_id)
        if coins:
            symbol = coins[0][0]
        else:
            await update.message.reply_text("Будь ласка, вкажіть монету. Наприклад: `/twap BTCUSDT`", parse_mode="Markdown")
            return
    else:
        symbol = context.args[0].upper().strip()
        
    status_msg = await update.message.reply_text(f"⏳ Отримую дані TWAP для {symbol}...")
    
    # 240 свічок по 1м = 4 години
    stats = bybit.calculate_twap_and_volume(symbol, limit=240)
    if not stats:
        await status_msg.edit_text(f"❌ Не вдалося отримати дані TWAP для {symbol}. Перевірте назву ф'ючерсу.")
        return
        
    price_dev_pct = ((stats['current_price'] - stats['twap']) / stats['twap']) * 100
    direction = "вище" if price_dev_pct >= 0 else "нижче"
    
    msg = (
        f"📊 **TWAP аналіз для {symbol}** (за останні 4 години)\n\n"
        f"• **Поточна ціна ф'ючерсу:** `{stats['current_price']}` USDT\n"
        f"• **TWAP (1м, 4г):** `{stats['twap']:.4f}` USDT\n"
        f"• **Відхилення:** `{abs(price_dev_pct):.2f}%` ({direction} середнього TWAP)"
    )
    await status_msg.edit_text(msg, parse_mode="Markdown")

async def volume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник команди /volume <SYMBOL>"""
    chat_id = update.effective_chat.id
    
    if not context.args:
        coins = db.get_tracked_coins(chat_id)
        if coins:
            symbol = coins[0][0]
        else:
            await update.message.reply_text("Будь ласка, вкажіть монету. Наприклад: `/volume BTCUSDT`", parse_mode="Markdown")
            return
    else:
        symbol = context.args[0].upper().strip()
        
    status_msg = await update.message.reply_text(f"⏳ Отримую статистику об'єму для {symbol}...")
    
    # limit=1000 для детального 1м аналізу об'єму
    stats = bybit.calculate_twap_and_volume(symbol, limit=240) # Використаємо розрахунок з лімітом 240
    if not stats:
        await status_msg.edit_text(f"❌ Не вдалося отримати дані об'єму для {symbol}. Перевірте назву ф'ючерсу.")
        return
        
    msg = (
        f"📈 **Аналіз об'єму для {symbol}** (1-хвилинні свічки)\n\n"
        f"• **Остання закрита свічка (1хв):** `{stats['last_volume']:.2f}`\n"
        f"• **Середній об'єм за 1хв:** `{stats['avg_volume']:.2f}`\n"
        f"• **Співвідношення:** `*{stats['volume_ratio']:.2f}x*` від середнього\n\n"
    )
    
    if stats['volume_ratio'] >= 10.0:
        msg += "🚨 *Увага! Критичний сплеск об'єму (понад 10x)!*"
    elif stats['volume_ratio'] >= 5.0:
        msg += "⚠️ *Високий сплеск об'єму (понад 5x).*"
    elif stats['volume_ratio'] >= 2.0:
        msg += "📈 *Підвищена активність.*"
    else:
        msg += "✅ Об'єм торгів у межах норми."
        
    await status_msg.edit_text(msg, parse_mode="Markdown")

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник команди /settings <SYMBOL> <VOL_MULT> <TWAP_PCT>"""
    chat_id = update.effective_chat.id
    
    if len(context.args) < 3:
        await update.message.reply_text(
            "🔧 **Налаштування сповіщень**\n\n"
            "Ви можете задати індивідуальні ліміти для кожної монети.\n"
            "Формат:\n`/settings <СИМВОЛ> <множник_об'єму> <відхилення_twap_%>`\n\n"
            "Приклад:\n`/settings BTCUSDT 2.5 4.0`\n"
            "*(Бот надсилатиме сповіщення, якщо об'єм зросте у >2.5 рази або ціна відхилиться від TWAP на >4%)*",
            parse_mode="Markdown"
        )
        return
        
    symbol = context.args[0].upper().strip()
    try:
        vol_mult = float(context.args[1])
        twap_pct = float(context.args[2])
    except ValueError:
        await update.message.reply_text("❌ Помилка! Множник об'єму та % відхилення мають бути числами. Наприклад: `2.5` `4.0`.")
        return
        
    coins = db.get_tracked_coins(chat_id)
    tracked_symbols = [c[0] for c in coins]
    
    if symbol not in tracked_symbols:
        await update.message.reply_text(f"❌ Ви не відстежуєте **{symbol}**. Спочатку додайте її через `/add {symbol}`.", parse_mode="Markdown")
        return
        
    db.add_coin(chat_id, symbol, vol_mult, twap_pct)
    await update.message.reply_text(
        f"✅ **Налаштування для {symbol} успішно оновлено:**\n"
        f"• Поріг сповіщення об'єму: `>{vol_mult}x` від середнього\n"
        f"• Поріг відхилення ціни від TWAP: `>{twap_pct}%`",
        parse_mode="Markdown"
    )

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник команди /report <SYMBOL> <INTERVAL_MINUTES>"""
    chat_id = update.effective_chat.id
    db.add_user(chat_id)
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "📋 **Налаштування регулярних звітів про ціну**\n\n"
            "Ви можете отримувати звіт про ціну та її зміну кожні N хвилин.\n"
            "Формат:\n`/report <СИМВОЛ> <інтервал_хвилин>`\n\n"
            "Приклад:\n`/report LAB 20` або `/report LABUSDT 20`\n"
            "*(Бот надсилатиме звіт про ціну LABUSDT кожні 20 хвилин)*\n\n"
            "Щоб вимкнути звіт для монети, вкажіть інтервал `0` (наприклад, `/report LAB 0`).",
            parse_mode="Markdown"
        )
        return
        
    symbol_input = context.args[0].upper().strip()
    try:
        interval_minutes = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Помилка! Інтервал має бути цілим числом хвилин. Наприклад: `20`.")
        return
        
    if interval_minutes < 0:
        await update.message.reply_text("❌ Помилка! Інтервал не може бути меншим за 0.")
        return

    # Розумне автодоповнення: якщо введено LAB, спробуємо знайти LAB або LABUSDT
    symbol = symbol_input
    active_symbols = bybit.get_active_symbols("linear")
    
    if active_symbols:
        if symbol not in active_symbols:
            if f"{symbol}USDT" in active_symbols:
                symbol = f"{symbol}USDT"
            else:
                await update.message.reply_text(
                    f"❌ Ф'ючерс **{symbol_input}** (або **{symbol_input}USDT**) не знайдено на ринку USDT Perpetual Bybit.",
                    parse_mode="Markdown"
                )
                return
    else:
        # Без активних символів просто додаємо USDT
        if not symbol.endswith("USDT"):
            symbol = f"{symbol}USDT"
            
    # Перевіримо, чи монета вже відстежується користувачем. Якщо ні - додаємо її з дефолтними значеннями
    coins = db.get_tracked_coins(chat_id)
    tracked_symbols = [c[0] for c in coins]
    if symbol not in tracked_symbols and interval_minutes > 0:
        db.add_coin(chat_id, symbol)
        
    db.update_report_interval(chat_id, symbol, interval_minutes)
    
    if interval_minutes > 0:
        await update.message.reply_text(
            f"✅ **Регулярний звіт для {symbol} увімкнено!**\n"
            f"Звіт надходитиме кожні `{interval_minutes}` хвилин із розрахунком зміни ціни за цей час.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"✅ **Регулярні звіти для {symbol} вимкнено.**",
            parse_mode="Markdown"
        )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник натискання інлайн кнопок"""
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat_id
    data = query.data
    
    if data == "list_coins":
        # Перевикористовуємо coins_command
        # Але оскільки coins_command надсилає нове повідомлення, ми перепишемо текст поточного
        coins = db.get_tracked_coins(chat_id)
        if not coins:
            message = (
                "📉 **Ваш список відстежуваних ф'ючерсів порожній.**\n\n"
                "Ви можете додати монети командою:\n"
                "`/add назва_монети` (наприклад, `/add BTCUSDT`)."
            )
            keyboard = [[InlineKeyboardButton("➕ Додати BTCUSDT", callback_data="add_default_btc")]]
        else:
            message = "📋 **Ваші відстежувані ф'ючерси:**\n\n"
            keyboard = []
            for row in coins:
                sym = row[0]
                vol_mult = row[1]
                twap_pct = row[2]
                message += f"• **{sym}** (1м Об'єм: `>{vol_mult}x`, TWAP: `>{twap_pct}%`)\n"
                keyboard.append([
                    InlineKeyboardButton(f"📊 TWAP {sym}", callback_data=f"twap_{sym}"),
                    InlineKeyboardButton(f"📈 Vol {sym}", callback_data=f"vol_{sym}"),
                    InlineKeyboardButton(f"🗑️ Видалити", callback_data=f"remove_{sym}")
                ])
            message += "\n*Додати нову монету можна за допомогою:* `/add [СИМВОЛ]`"
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode="Markdown")
        
    elif data == "add_default_btc":
        db.add_coin(chat_id, "BTCUSDT")
        await query.edit_message_text("✅ **BTCUSDT успішно додано!** Напишіть `/coins` для перегляду.", parse_mode="Markdown")
        
    elif data.startswith("remove_"):
        symbol = data.split("_")[1]
        db.remove_coin(chat_id, symbol)
        
        # Оновлюємо список
        coins = db.get_tracked_coins(chat_id)
        message = f"🗑️ Монету **{symbol}** видалено зі списку.\n\n"
        keyboard = []
        if coins:
            message += "📋 **Ваші відстежувані ф'ючерси:**\n\n"
            for row in coins:
                sym = row[0]
                vol_mult = row[1]
                twap_pct = row[2]
                message += f"• **{sym}** (1м Об'єм: `>{vol_mult}x`, TWAP: `>{twap_pct}%`)\n"
                keyboard.append([
                    InlineKeyboardButton(f"📊 TWAP {sym}", callback_data=f"twap_{sym}"),
                    InlineKeyboardButton(f"📈 Vol {sym}", callback_data=f"vol_{sym}"),
                    InlineKeyboardButton(f"🗑️ Видалити", callback_data=f"remove_{sym}")
                ])
            message += "\n*Додати нову монету можна за допомогою:* `/add [СИМВОЛ]`"
        else:
            message += "📉 **Ваш список відстеження тепер порожній.**"
            keyboard = [[InlineKeyboardButton("➕ Додати BTCUSDT", callback_data="add_default_btc")]]
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode="Markdown")
        
    elif data.startswith("twap_"):
        symbol = data.split("_")[1]
        stats = bybit.calculate_twap_and_volume(symbol, limit=240)
        if not stats:
            await query.message.reply_text(f"❌ Не вдалося отримати дані TWAP для {symbol}.")
            return
        price_dev_pct = ((stats['current_price'] - stats['twap']) / stats['twap']) * 100
        direction = "вище" if price_dev_pct >= 0 else "нижче"
        msg = (
            f"📊 **TWAP для {symbol}** (за останні 4 години):\n"
            f"• Ціна ф'ючерсу: `{stats['current_price']}` USDT\n"
            f"• TWAP (1м, 4г): `{stats['twap']:.4f}` USDT\n"
            f"• Відхилення: `{abs(price_dev_pct):.2f}%` ({direction} TWAP)"
        )
        await query.message.reply_text(msg, parse_mode="Markdown")
        
    elif data.startswith("vol_"):
        symbol = data.split("_")[1]
        stats = bybit.calculate_twap_and_volume(symbol, limit=240)
        if not stats:
            await query.message.reply_text(f"❌ Не вдалося отримати дані об'єму для {symbol}.")
            return
        msg = (
            f"📈 **Об'єм для {symbol}** (1-хвилинний інтервал):\n"
            f"• Поточна 1хв свічка: `{stats['last_volume']:.2f}`\n"
            f"• Середній об'єм за 1хв: `{stats['avg_volume']:.2f}`\n"
            f"• Перевищення: `*{stats['volume_ratio']:.2f}x*` від середнього"
        )
        await query.message.reply_text(msg, parse_mode="Markdown")

async def post_init(application):
    """
    Ця функція запускається після ініціалізації бота
    та запускає фоновий планувальник сповіщень.
    """
    # Запускаємо фонову перевірку в окремому асинхронному завданні (task)
    asyncio.create_task(alerts.start_alert_scheduler(application.bot, CHECK_INTERVAL))

def main():
    """Точка входу"""
    if not TOKEN or TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error("Критична помилка! Вкажіть дійсний TELEGRAM_BOT_TOKEN у файлі .env!")
        print("ПОМИЛКА: Будь ласка, вкажіть ваш TELEGRAM_BOT_TOKEN у файлі .env")
        return
        
    logger.info("Запуск Telegram-бота...")
    
    # Будуємо додаток та підключаємо фонову задачу через post_init
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    
    # Додаємо обробники команд
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("coins", coins_command))
    app.add_handler(CommandHandler("add", add_command))
    app.add_handler(CommandHandler("remove", remove_command))
    app.add_handler(CommandHandler("twap", twap_command))
    app.add_handler(CommandHandler("volume", volume_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("report", report_command))
    
    # Обробник callback-запитів від інлайн кнопок
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    # Запуск бота на прослуховування (polling)
    app.run_polling()

if __name__ == "__main__":
    main()
