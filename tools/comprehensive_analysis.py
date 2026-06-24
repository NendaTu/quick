import sqlite3
import re
import statistics
from collections import defaultdict

def parse_signal(msg):
    try:
        # Extract metadata using regex
        data = {}
        data['symbol'] = msg.split('SIGNAL: ')[1].split(' ')[0]
        data['side'] = msg.split('SIGNAL: ')[1].split(' ')[1]

        # Numeric values
        for key in ['drt', 'rsi', 'macd', 'ema', 'vol', 'equity', 'confidence']:
            match = re.search(f'{key}=([\d.-]+)', msg)
            if match:
                data[key] = float(match.group(1))

        # BTC Confluence
        btc_match = re.search(r'\[1D:([\d.-]+) 4H:([\d.-]+) 1H:([\d.-]+) 15m:([\d.-]+)\]', msg)
        if btc_match:
            data['btc_1d'] = float(btc_match.group(1))
            data['btc_4h'] = float(btc_match.group(2))
            data['btc_1h'] = float(btc_match.group(3))
            data['btc_15m'] = float(btc_match.group(4))

        return data
    except Exception:
        return None

def analyze():
    conn = sqlite3.connect('market_data.db')
    cursor = conn.cursor()

    # Get all completed trades (exits)
    cursor.execute("SELECT session_id, timestamp, message FROM logs WHERE message LIKE '%EXIT%' AND message NOT LIKE '%Background%'")
    exit_logs = cursor.fetchall()

    trades = []
    print(f"Total exit logs found: {len(exit_logs)}")

    for sid, ts, msg in exit_logs:
        net_match = re.search(r'net=([\d.-]+)', msg)
        if not net_match: continue
        net = float(net_match.group(1))

        # Extract symbol and side
        parts = msg.split('EXIT ')
        if len(parts) < 2: continue
        info = parts[1].split(' ')
        sym = info[0]
        side = info[1]

        # Find the signal that opened this position
        cursor.execute("""
            SELECT message FROM logs
            WHERE session_id = ? AND timestamp < ? AND message LIKE ? AND message LIKE ?
            AND (message LIKE '%SIGNAL:%' OR message LIKE '%Entry Triggered%')
            ORDER BY timestamp DESC LIMIT 1
        """, (sid, ts, f"%{sym}%", f"% {side} %"))

        sig_row = cursor.fetchone()
        if sig_row:
            sig_data = parse_signal(sig_row[0])
            if sig_data:
                sig_data['net'] = net
                sig_data['session_id'] = sid
                trades.append(sig_data)

    print(f"Paired trades for analysis: {len(trades)}")
    if not trades: return

    # Group by Side
    for side in ['BUY', 'SELL']:
        side_trades = [t for t in trades if t['side'] == side]
        wins = [t for t in side_trades if t['net'] > 0]
        losses = [t for t in side_trades if t['net'] <= 0]

        if not side_trades: continue

        print(f"\n========================================")
        print(f"  SIDE: {side} (Total: {len(side_trades)})")
        print(f"  Win Rate: {len(wins)/len(side_trades)*100:.1f}%")
        print(f"========================================")

        metrics = ['rsi', 'drt', 'macd', 'vol', 'btc_1h', 'btc_15m', 'confidence']
        for m in metrics:
            w_vals = [t[m] for t in wins if m in t]
            l_vals = [t[m] for t in losses if m in t]

            if w_vals and l_vals:
                w_avg = statistics.mean(w_vals)
                l_avg = statistics.mean(l_vals)
                diff = w_avg - l_avg

                # Check for statistical significance (basic)
                print(f"{m.upper():<12} | Win: {w_avg:>8.4f} | Loss: {l_avg:>8.4f} | Delta: {diff:>+8.4f}")

    conn.close()

analyze()
