import logging
from bybit import get_active_symbols, get_current_price, calculate_twap_and_volume

# Налаштування логування для відладки
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def test_bybit_api():
    print("=== Тестування Bybit V5 API ===")
    
    # 1. Тест активних пар
    print("\n1. Запит активних Futures символів...")
    symbols = get_active_symbols("linear")
    print(f"Знайдено активних монет: {len(symbols)}")
    if symbols:
        test_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "INVALIDCOIN"]
        for sym in test_symbols:
            exists = sym in symbols
            print(f" - Перевірка '{sym}': {'Є в списку' if exists else 'Немає в списку'}")
            
    # 2. Тест поточної ціни
    print("\n2. Запит поточної ціни ф'ючерсу BTCUSDT...")
    price = get_current_price(symbol="BTCUSDT", category="linear")
    print(f"Поточна ціна BTCUSDT: {price}")
    
    # 3. Тест TWAP та об'ємів
    print("\n3. Розрахунок TWAP та аналіз об'ємів для BTCUSDT (інтервал 1м, за останні 4 години = 240 свічок)...")
    stats = calculate_twap_and_volume("BTCUSDT", category="linear", interval="1", limit=240)
    if stats:
        print(f"Успішно розраховано:")
        print(f" - Поточна ціна: {stats['current_price']} USDT")
        print(f" - TWAP (середньозважена ціна 4г): {stats['twap']:.4f} USDT")
        print(f" - Ціна відхилилась від TWAP на: {abs(stats['current_price'] - stats['twap']) / stats['twap'] * 100:.2f}%")
        print(f" - Об'єм останньої свічки (1м): {stats['last_volume']:.4f}")
        print(f" - Середній іст. об'єм (1м): {stats['avg_volume']:.4f}")
        print(f" - Співвідношення об'ємів (поточний / середній): {stats['volume_ratio']:.2f}x")
    else:
        print("Помилка при отриманні статистики свічок.")

if __name__ == "__main__":
    test_bybit_api()
