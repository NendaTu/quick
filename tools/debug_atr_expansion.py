import sqlite3
from ta.indicators.atr import is_expansion_candle
import sys
import os
from datetime import datetime
import pytz

sys.path.append(os.getcwd())

db = sqlite3.connect("market_data.db")

def check_for_expansions(symbol, tf, multiplier):
    cursor = db.cursor()
    query = f"SELECT timestamp, open, high, low, close, volume FROM candles WHERE symbol='{symbol}' AND timeframe='{tf}' ORDER BY timestamp ASC"
    cursor.execute(query)
    rows = cursor.fetchall()
    ohlcv = []
    for r in rows:
        ohlcv.append({'ts': r[0], 'o': r[1], 'h': r[2], 'l': r[3], 'c': r[4], 'v': r[5]})

    print(f"Scanning {len(ohlcv)} candles for {symbol} {tf} with multiplier {multiplier}...")

    found = 0
    for i in range(20, len(ohlcv)):
        res = is_expansion_candle(ohlcv[:i+1], multiplier=multiplier, period=14)
        if res['is_expansion']:
            dt = datetime.fromtimestamp(res['candle']['ts'], tz=pytz.UTC)
            print(f"Expansion found at {dt}: Ratio {res['ratio']:.2f}x")
            found += 1

    print(f"Total expansions found: {found}")

# Try 1H since we know we have lots of 1H data
check_for_expansions("ETHUSDT", "1H", 2.0)
db.close()
