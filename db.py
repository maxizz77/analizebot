import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv("DB_PATH", "bot_database.db")

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    """Ініціалізація бази даних та створення таблиць, якщо вони не існують."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Таблиця користувачів
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                is_active INTEGER DEFAULT 1
            )
        """)
        
        # Таблиця відстежуваних монет
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tracked_coins (
                chat_id INTEGER,
                symbol TEXT,
                volume_threshold_multiplier REAL DEFAULT 10.0,
                twap_alert_pct REAL DEFAULT 5.0,
                price_report_interval INTEGER DEFAULT 0,
                last_report_sent_time INTEGER DEFAULT 0,
                PRIMARY KEY (chat_id, symbol),
                FOREIGN KEY (chat_id) REFERENCES users(chat_id) ON DELETE CASCADE
            )
        """)
        
        # Спробуємо додати нові стовпчики до вже існуючої таблиці (якщо вона була створена раніше)
        try:
            cursor.execute("ALTER TABLE tracked_coins ADD COLUMN price_report_interval INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE tracked_coins ADD COLUMN last_report_sent_time INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
            
        conn.commit()

def add_user(chat_id):
    """Додає нового користувача до бази даних, якщо його немає."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (chat_id) VALUES (?)", (chat_id,))
        cursor.execute("UPDATE users SET is_active = 1 WHERE chat_id = ?", (chat_id,))
        conn.commit()

def set_user_inactive(chat_id):
    """Деактивує користувача (якщо він заблокував бота або зупинив)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_active = 0 WHERE chat_id = ?", (chat_id,))
        conn.commit()

def add_coin(chat_id, symbol, volume_mult=10.0, twap_pct=5.0):
    """Додає монету до списку відстежуваних користувачем."""
    # Переконуємось, що користувач є в базі
    add_user(chat_id)
    
    # Символ завжди зберігаємо у верхньому регістрі
    symbol = symbol.strip().upper()
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO tracked_coins 
            (chat_id, symbol, volume_threshold_multiplier, twap_alert_pct) 
            VALUES (?, ?, ?, ?)
        """, (chat_id, symbol, volume_mult, twap_pct))
        conn.commit()

def remove_coin(chat_id, symbol):
    """Видаляє монету зі списку відстежуваних користувачем."""
    symbol = symbol.strip().upper()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tracked_coins WHERE chat_id = ? AND symbol = ?", (chat_id, symbol))
        conn.commit()

def get_tracked_coins(chat_id):
    """Повертає список відстежуваних монет для конкретного користувача."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT symbol, volume_threshold_multiplier, twap_alert_pct, price_report_interval 
            FROM tracked_coins 
            WHERE chat_id = ?
        """, (chat_id,))
        return cursor.fetchall()

def get_all_active_users():
    """Повертає список chat_id усіх активних користувачів."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id FROM users WHERE is_active = 1")
        return [row[0] for row in cursor.fetchall()]

def get_all_tracked_coins():
    """Повертає список усіх монет, які відстежуються хоча б одним активним користувачем,
    а також деталі підписників."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT tc.chat_id, tc.symbol, tc.volume_threshold_multiplier, tc.twap_alert_pct 
            FROM tracked_coins tc
            JOIN users u ON tc.chat_id = u.chat_id
            WHERE u.is_active = 1
        """)
        return cursor.fetchall()

def update_report_interval(chat_id, symbol, interval_minutes):
    """Оновлює інтервал надсилання регулярних звітів."""
    symbol = symbol.strip().upper()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tracked_coins 
            SET price_report_interval = ?, last_report_sent_time = 0
            WHERE chat_id = ? AND symbol = ?
        """, (interval_minutes, chat_id, symbol))
        conn.commit()

def get_coins_for_reports():
    """Отримує список монет, для яких увімкнені регулярні звіти."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT tc.chat_id, tc.symbol, tc.price_report_interval, tc.last_report_sent_time 
            FROM tracked_coins tc
            JOIN users u ON tc.chat_id = u.chat_id
            WHERE u.is_active = 1 AND tc.price_report_interval > 0
        """)
        return cursor.fetchall()

def update_last_report_time(chat_id, symbol, timestamp):
    """Оновлює час останнього надісланого звіту."""
    symbol = symbol.strip().upper()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tracked_coins 
            SET last_report_sent_time = ? 
            WHERE chat_id = ? AND symbol = ?
        """, (timestamp, chat_id, symbol))
        conn.commit()

def update_coin_settings(chat_id, symbol, volume_mult, twap_pct, price_report_interval):
    """Оновлює всі налаштування відстеження для монети за один запит."""
    symbol = symbol.strip().upper()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tracked_coins 
            SET volume_threshold_multiplier = ?, 
                twap_alert_pct = ?, 
                price_report_interval = ?,
                last_report_sent_time = 0
            WHERE chat_id = ? AND symbol = ?
        """, (volume_mult, twap_pct, price_report_interval, chat_id, symbol))
        conn.commit()

# Ініціалізуємо БД при першому завантаженні модуля
init_db()
