"""
1. Summary: Secondary data visualizer for technical indicator telemetry.
2. Description: Constructs plots of EMA, MACD, and volume deltas over historical candles.
3. Context: Diagnostic script for optimizing technical criteria.
"""
import sqlite3
import re
import statistics

def parse_signal(msg):
    try:
        parts = msg.split('SIGNAL: ')[1].split(' ')
        symbol = parts[0]
        side = parts[1]

        drt = float(re.search(r'drt=([\d.-]+)', msg).group(1))
        rsi = float(re.search(r'rsi=([\d.-]+)', msg).group(1))
        macd = float(re.search(r'macd=([\d.-]+)', msg).group(1))
        vol = float(re.search(r'vol=([\d.-]+)', msg).group(1))

        btc_match = re.search(r'\[1D:([\d.-]+) 4H:([\d.-]+) 1H:([\d.-]+) 15m:([\d.-]+)\]', msg)
        btc = {
            '1d': float(btc_match.group(1)),
            '4h': float(btc_match.group(2)),
            '1h': float(btc_match.group(3)),
            '15m': float(btc_match.group(4))
        }
        return {'symbol': symbol, 'side': side, 'drt': drt, 'rsi': rsi, 'macd': macd, 'vol': vol, 'btc': btc}
    except Exception: return None

def parse_exit(msg):
    try:
        parts = msg.split('EXIT ')[1].split(' ')
        symbol = parts[0]
        side = parts[1]
        net = float(re.search(r'net=([\d.-]+)', msg).group(1))
        return {'symbol': symbol, 'side': side, 'net': net}
    except Exception: return None

def analyze():
    conn = sqlite3.connect('market_data.db')
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, message FROM logs WHERE message LIKE '%EXIT%' AND message NOT LIKE '%Background%' ORDER BY timestamp ASC")
    exit_logs = cursor.fetchall()

    trades = []
    for ts, msg in exit_logs:
        exit_data = parse_exit(msg)
        if not exit_data: continue
        cursor.execute("""
            SELECT message FROM logs
            WHERE timestamp < ? AND message LIKE ? AND message LIKE ?
            AND (message LIKE '%SIGNAL:%' OR message LIKE '%Entry Triggered%')
            ORDER BY timestamp DESC LIMIT 1
        """, (ts, f"%{exit_data['symbol']}%", f"% {exit_data['side']} %"))
        sig_row = cursor.fetchone()
        if not sig_row: continue
        sig_data = parse_signal(sig_row[0])
        if sig_data: trades.append({**sig_data, **exit_data})

    for side in ['BUY', 'SELL']:
        side_trades = [t for t in trades if t['side'] == side]
        wins = [t for t in side_trades if t['net'] > 0]
        losses = [t for t in side_trades if t['net'] <= 0]

        print(f"\n=== SIDE: {side} ===")
        print(f"Wins: {len(wins)}, Losses: {len(losses)}")

        for m in ['drt', 'rsi', 'macd', 'vol']:
            w_val = [t[m] for t in wins]; l_val = [t[m] for t in losses]
            if w_val and l_val:
                print(f"Metric {m.upper()}: WinAvg={statistics.mean(w_val):.4f}, LossAvg={statistics.mean(l_val):.4f}")

        for tf in ['1d', '4h', '1h', '15m']:
            w_val = [t['btc'][tf] for t in wins]; l_val = [t['btc'][tf] for t in losses]
            if w_val and l_val:
                print(f"BTC {tf.upper()}: WinAvg={statistics.mean(w_val):.4f}, LossAvg={statistics.mean(l_val):.4f}")

    conn.close()

if __name__ == "__main__":
    analyze()
