import sqlite3
import re
import statistics

def parse_signal(msg):
    try:
        btc_match = re.search(r'\[1D:([\d.-]+) 4H:([\d.-]+) 1H:([\d.-]+) 15m:([\d.-]+)\]', msg)
        return {
            '1d': float(btc_match.group(1)),
            '4h': float(btc_match.group(2)),
            '1h': float(btc_match.group(3)),
            '15m': float(btc_match.group(4))
        }
    except Exception: return None

def analyze():
    conn = sqlite3.connect('market_data.db')
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(id) FROM sessions")
    sid = cursor.fetchone()[0]

    cursor.execute("SELECT message FROM logs WHERE session_id=? AND message LIKE '%EXIT%' AND message NOT LIKE '%Background%'", (sid,))
    exits = cursor.fetchall()

    trades = []
    for msg_row in exits:
        msg = msg_row[0]
        net_match = re.search(r'net=([\d.-]+)', msg)
        if not net_match: continue
        net = float(net_match.group(1))

        parts = msg.split('EXIT ')
        if len(parts) < 2: continue
        info = parts[1].split(' ')
        sym = info[0]
        side = info[1]

        cursor.execute("SELECT message FROM logs WHERE session_id=? AND message LIKE ? AND message LIKE ? AND (message LIKE '%SIGNAL%' OR message LIKE '%Entry Triggered%') ORDER BY timestamp DESC LIMIT 1", (sid, f"%{sym}%", f"%{side}%"))
        sig = cursor.fetchone()
        if sig:
            btc = parse_signal(sig[0])
            if btc:
                trades.append({'net': net, 'btc': btc, 'side': side})

    if not trades:
        print("No trades to analyze.")
        return

    print(f"Total trades analyzed: {len(trades)}")

    for tf in ['1h', '15m']:
        print(f"\n--- Testing Thresholds for BTC {tf.upper()} ---")
        for threshold in [-0.005, -0.002, -0.001, -0.0005, 0.0, 0.0005, 0.001]:
            # For Longs: BTC > threshold
            # For Shorts: BTC < -threshold
            filtered_wins = 0
            filtered_losses = 0

            for t in trades:
                val = t['btc'][tf]
                if t['side'] == 'BUY':
                    if val >= threshold:
                        if t['net'] > 0: filtered_wins += 1
                        else: filtered_losses += 1
                else: # SELL
                    if val <= -threshold:
                        if t['net'] > 0: filtered_wins += 1
                        else: filtered_losses += 1

            total = filtered_wins + filtered_losses
            wr = (filtered_wins / total * 100) if total > 0 else 0
            print(f"Threshold {threshold:+.5f}: WR={wr:.1f}% (Trades: {total}, Wins: {filtered_wins})")

analyze()
