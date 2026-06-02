import asyncio
import logging
import requests
import db
import bybit
from telegram import Bot

logger = logging.getLogger(__name__)

# Кеш для запобігання дублюванню сповіщень (chat_id, symbol, alert_type) -> last_notified_candle_start_time
last_alerts_sent = {}

async def check_alerts(bot: Bot):
    """
    Фонова функція перевірки активностей монет.
    Отримує всі відстежувані монети з бази даних, робить запити до Bybit,
    та надсилає повідомлення користувачам у разі аномалій.
    """
    # Отримуємо унікальний список монет
    tracked_list = db.get_all_tracked_coins()
    if not tracked_list:
        return
        
    from collections import defaultdict
    by_symbol = defaultdict(list)
    for chat_id, symbol, vol_mult, twap_pct in tracked_list:
        by_symbol[symbol].append((chat_id, vol_mult, twap_pct))
        
    for symbol, subscribers in by_symbol.items():
        # Запитуємо свічки 1м
        # limit=1000 для детального хвилинного аналізу (максимальний ліміт Bybit)
        url = f"{bybit.BASE_URL}/v5/market/kline"
        params = {
            "category": "linear",
            "symbol": symbol,
            "interval": "1",
            "limit": 1000
        }
        
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            response = requests.get(url, params=params, headers=headers, proxies=bybit.get_proxies(), timeout=10)
            if response.status_code != 200:
                logger.warning(f"Не вдалося отримати дані з Bybit для {symbol}: HTTP {response.status_code}")
                continue
            try:
                data = response.json()
            except ValueError:
                logger.warning(f"Отримано некоректний JSON-відповідь від Bybit для {symbol} (можливо, блокування IP або Cloudflare)")
                continue
                
            if data.get("retCode") != 0 or not data["result"]["list"]:
                logger.error(f"Не вдалося отримати свічки для {symbol} у фоновому режимі: {data.get('retMsg')}")
                continue
                
            klines = data["result"]["list"]
            if len(klines) < 250:  # хоча б 240 свічок для TWAP (4 години) + 1 поточна
                continue
                
            # klines[0] - поточна (незавершена) свічка, пропускаємо її
            completed = klines[1:]
            
            # Останній завершений об'єм та його час початку
            last_completed_kline = completed[0]
            candle_start_time = last_completed_kline[0] # startTime
            last_volume = float(last_completed_kline[5])
            current_price = float(last_completed_kline[4])
            
            # 1. Рахуємо TWAP за 4 години (останні 240 завершених 1-хвилинних свічок)
            twap_count = min(240, len(completed))
            total_typical = 0.0
            for i in range(twap_count):
                k = completed[i]
                high = float(k[2])
                low = float(k[3])
                close = float(k[4])
                typical = (high + low + close) / 3.0
                total_typical += typical
            twap_4h = total_typical / twap_count
            
            # 2. Рахуємо середній об'єм за доступну історію (пропускаючи останню завершену свічку, тобто від індексу 1 до 999)
            historical_volume_klines = completed[1:1000]
            if historical_volume_klines:
                total_hist_vol = sum(float(k[5]) for k in historical_volume_klines)
                avg_vol_1m = total_hist_vol / len(historical_volume_klines)
            else:
                avg_vol_1m = last_volume
                
            volume_ratio = last_volume / avg_vol_1m if avg_vol_1m > 0 else 1.0
            price_dev_pct = (abs(current_price - twap_4h) / twap_4h) * 100
            
            # Перевіряємо сповіщення для кожного підписника
            for chat_id, vol_mult, twap_pct in subscribers:
                # А. Перевірка об'єму (похвилинний сплеск)
                if volume_ratio >= vol_mult:
                    alert_key = (chat_id, symbol, "volume")
                    if last_alerts_sent.get(alert_key) != candle_start_time:
                        msg = (
                            f"🚨 **[СПЛЕСК ОБ'ЄМУ 1м] {symbol}**\n\n"
                            f"• **Поточний об'єм за 1хв:** `{last_volume:.2f}`\n"
                            f"• **Середній об'єм за 1хв:** `{avg_vol_1m:.2f}`\n"
                            f"• **Перевищення:** `*{volume_ratio:.2f}x*` (поріг: {vol_mult}x)\n"
                            f"• **Поточна ціна ф'ючерсу:** `{current_price}` USDT"
                        )
                        try:
                            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                            last_alerts_sent[alert_key] = candle_start_time
                            logger.info(f"Надіслано повідомлення про об'єм для {symbol} користувачу {chat_id}")
                        except Exception as e:
                            logger.error(f"Помилка надсилання повідомлення користувачу {chat_id}: {e}")
                            if "bot was blocked" in str(e).lower():
                                db.set_user_inactive(chat_id)
                                
                # Б. Перевірка відхилення від TWAP
                if price_dev_pct >= twap_pct:
                    alert_key = (chat_id, symbol, "twap")
                    if last_alerts_sent.get(alert_key) != candle_start_time:
                        direction = "вище" if current_price > twap_4h else "нижче"
                        msg = (
                            f"⚠️ **[ВІДХИЛЕННЯ TWAP] {symbol}**\n\n"
                            f"• **Поточна ціна:** `{current_price}` USDT\n"
                            f"• **TWAP (4г):** `{twap_4h:.4f}` USDT\n"
                            f"• **Відхилення:** `*{price_dev_pct:.2f}%*` {direction} TWAP (поріг: {twap_pct}%)\n"
                        )
                        try:
                            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                            last_alerts_sent[alert_key] = candle_start_time
                            logger.info(f"Надіслано повідомлення про відхилення TWAP для {symbol} користувачу {chat_id}")
                        except Exception as e:
                            logger.error(f"Помилка надсилання повідомлення користувачу {chat_id}: {e}")
                            if "bot was blocked" in str(e).lower():
                                db.set_user_inactive(chat_id)
                                
        except Exception as e:
            logger.error(f"Помилка перевірки аномалій для {symbol}: {e}")

async def check_reports(bot: Bot):
    """
    Фонова функція відправки регулярних звітів про зміну ціни.
    """
    import time
    report_items = db.get_coins_for_reports()
    if not report_items:
        return
        
    current_time = int(time.time())
    
    for chat_id, symbol, interval_minutes, last_sent in report_items:
        # Перевіряємо, чи настав час відправити звіт (з невеликим люфтом у 5 секунд)
        if last_sent == 0 or (current_time - last_sent) >= (interval_minutes * 60 - 5):
            # Запитуємо свічки 1м
            url = f"{bybit.BASE_URL}/v5/market/kline"
            params = {
                "category": "linear",
                "symbol": symbol,
                "interval": "1",
                "limit": interval_minutes + 2
            }
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
                response = requests.get(url, params=params, headers=headers, proxies=bybit.get_proxies(), timeout=10)
                if response.status_code != 200:
                    logger.warning(f"Не вдалося отримати дані з Bybit для звіту {symbol}: HTTP {response.status_code}")
                    continue
                try:
                    data = response.json()
                except ValueError:
                    logger.warning(f"Отримано некоректний JSON-відповідь від Bybit для звіту {symbol} (можливо, блокування IP)")
                    continue
                    
                if data.get("retCode") != 0 or not data["result"]["list"]:
                    logger.error(f"Не вдалося отримати свічки для звіту {symbol}: {data.get('retMsg')}")
                    continue
                    
                klines = data["result"]["list"]
                if len(klines) < interval_minutes + 1:
                    logger.warning(f"Недостатньо свічок для звіту {symbol} (потрібно {interval_minutes}, є {len(klines)})")
                    continue
                    
                # klines[0] - поточна незавершена свічка, completed[0] - остання завершена
                completed = klines[1:]
                current_price = float(completed[0][4])
                
                # Ціна interval_minutes хвилин тому
                old_candle_index = min(interval_minutes, len(completed) - 1)
                old_price = float(completed[old_candle_index][4])
                
                price_change = current_price - old_price
                price_change_pct = (price_change / old_price) * 100 if old_price > 0 else 0.0
                
                direction_emoji = "📈" if price_change_pct >= 0 else "📉"
                direction_text = "зростання" if price_change_pct >= 0 else "падіння"
                
                msg = (
                    f"📋 **[РЕГУЛЯРНИЙ ЗВІТ] {symbol}** (кожні {interval_minutes}хв)\n\n"
                    f"• **Поточна ціна:** `{current_price}` USDT\n"
                    f"• **Ціна {interval_minutes}хв тому:** `{old_price}` USDT\n"
                    f"• **Зміна:** `{direction_emoji} {abs(price_change_pct):.2f}%` ({direction_text})\n"
                )
                
                try:
                    await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                    db.update_last_report_time(chat_id, symbol, current_time)
                    logger.info(f"Надіслано регулярний звіт для {symbol} ({interval_minutes}хв) користувачу {chat_id}")
                except Exception as e:
                    logger.error(f"Помилка відправки звіту користувачу {chat_id}: {e}")
                    if "bot was blocked" in str(e).lower():
                        db.set_user_inactive(chat_id)
            except Exception as e:
                logger.error(f"Помилка при генерації звіту для {symbol}: {e}")

async def start_alert_scheduler(bot: Bot, interval_seconds: int):
    """
    Запускає нескінченний асинхронний цикл перевірки активностей.
    """
    logger.info(f"Фонова перевірка активована. Інтервал: {interval_seconds} секунд.")
    while True:
        try:
            await check_alerts(bot)
        except Exception as e:
            logger.error(f"Критична помилка у фоновому циклі сповіщень: {e}")
            
        try:
            await check_reports(bot)
        except Exception as e:
            logger.error(f"Критична помилка у фоновому циклі звітів: {e}")
            
        await asyncio.sleep(interval_seconds)
