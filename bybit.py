import requests
import logging

logger = logging.getLogger(__name__)

import os

BASE_URL = os.getenv("BYBIT_BASE_URL", "https://api.bytick.com").strip()
PROXY = os.getenv("BYBIT_PROXY", "").strip()

def get_proxies():
    if PROXY:
        return {"http": PROXY, "https": PROXY}
    return None

def get_active_symbols(category="linear"):
    """
    Отримує список усіх активних торгових пар для вказаної категорії (spot або linear).
    Повертає множину (set) символів у верхньому регістрі.
    """
    url = f"{BASE_URL}/v5/market/instruments-info"
    params = {"category": category}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    try:
        response = requests.get(url, params=params, headers=headers, proxies=get_proxies(), timeout=10)
        if response.status_code != 200:
            logger.warning(f"Не вдалося отримати інструменти Bybit: HTTP {response.status_code}")
            return set()
        try:
            data = response.json()
        except ValueError:
            logger.warning("Отримано некоректний JSON-відповідь від Bybit instruments-info")
            return set()
            
        if data.get("retCode") == 0:
            symbols = {
                item["symbol"].upper() 
                for item in data["result"]["list"] 
                if item.get("status", "").upper() == "TRADING"
            }
            return symbols
        else:
            logger.error(f"Помилка Bybit API при отриманні списку символів: {data.get('retMsg')}")
            return set()
    except Exception as e:
        logger.error(f"Помилка з'єднання при отриманні символів Bybit: {e}")
        return set()

def get_current_price(symbol, category="linear"):
    """
    Отримує поточну ціну (lastPrice) для вказаного символу.
    """
    symbol = symbol.strip().upper()
    url = f"{BASE_URL}/v5/market/tickers"
    params = {"category": category, "symbol": symbol}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    try:
        response = requests.get(url, params=params, headers=headers, proxies=get_proxies(), timeout=10)
        if response.status_code != 200:
            logger.warning(f"Не вдалося отримати ціну {symbol} з Bybit: HTTP {response.status_code}")
            return None
        try:
            data = response.json()
        except ValueError:
            logger.warning(f"Отримано некоректний JSON-відповідь від Bybit для ціни {symbol}")
            return None
            
        if data.get("retCode") == 0 and data["result"]["list"]:
            ticker = data["result"]["list"][0]
            return float(ticker["lastPrice"])
        else:
            logger.error(f"Помилка Bybit API при отриманні ціни {symbol}: {data.get('retMsg')}")
            return None
    except Exception as e:
        logger.error(f"Помилка з'єднання при отриманні ціни {symbol}: {e}")
        return None

def calculate_twap_and_volume(symbol, category="linear", interval="1", limit=240):
    """
    Отримує свічки (klines) та розраховує:
    1. TWAP за останні 'limit' завершених свічок (наприклад, 240 свічок по 1хв = 4 години).
    2. Статистику об'єму за останню завершену 1хв свічку порівняно з попередніми 999 свічками (~16.6 годин).
    
    Повертає словник зі значеннями або None.
    """
    symbol = symbol.strip().upper()
    url = f"{BASE_URL}/v5/market/kline"
    
    # Запитуємо максимум 1000 свічок для точного розрахунку середнього об'єму
    params = {
        "category": category,
        "symbol": symbol,
        "interval": str(interval),
        "limit": 1000
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    
    try:
        response = requests.get(url, params=params, headers=headers, proxies=get_proxies(), timeout=10)
        if response.status_code != 200:
            logger.warning(f"Не вдалося отримати свічки для {symbol} з Bybit: HTTP {response.status_code}")
            return None
        try:
            data = response.json()
        except ValueError:
            logger.warning(f"Отримано некоректний JSON-відповідь від Bybit klines для {symbol}")
            return None
            
        if data.get("retCode") != 0 or not data["result"]["list"]:
            logger.error(f"Помилка Bybit API при отриманні klines {symbol}: {data.get('retMsg')}")
            return None
            
        klines = data["result"]["list"]
        
        if len(klines) < 10:
            logger.warning(f"Недостатньо історичних даних для {symbol}")
            return None
            
        # klines[0] - поточна незавершена свічка. Пропускаємо її.
        completed_klines = klines[1:]
        
        # Обчислення TWAP за вказаний ліміт (за замовчуванням 240 свічок = 4 години)
        total_typical_price = 0.0
        twap_count = min(limit, len(completed_klines))
        
        for i in range(twap_count):
            k = completed_klines[i]
            high = float(k[2])
            low = float(k[3])
            close = float(k[4])
            typical_price = (high + low + close) / 3.0
            total_typical_price += typical_price
            
        twap = total_typical_price / twap_count
        
        # Останній завершений об'єм
        last_completed_kline = completed_klines[0]
        last_volume = float(last_completed_kline[5])
        current_price = float(last_completed_kline[4])
        
        # Історичний середній об'єм (пропускаємо останню завершену свічку, тобто беремо від index 1 і далі)
        # Для 1-хвилинного інтервалу рахуємо середнє за всіма доступними завершеними свічками (до 999 свічок)
        historical_klines = completed_klines[1:]
        if historical_klines:
            total_hist_volume = sum(float(k[5]) for k in historical_klines)
            avg_volume = total_hist_volume / len(historical_klines)
        else:
            avg_volume = last_volume
            
        volume_ratio = last_volume / avg_volume if avg_volume > 0 else 1.0
        
        return {
            "current_price": current_price,
            "twap": twap,
            "last_volume": last_volume,
            "avg_volume": avg_volume,
            "volume_ratio": volume_ratio
        }
        
    except Exception as e:
        logger.error(f"Помилка з'єднання при обчисленні TWAP/Volume {symbol}: {e}")
        return None
