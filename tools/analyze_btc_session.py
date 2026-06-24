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
    print(f"Analyzing Session ID: {sid}")

    cursor.execute("SELECT message FROM logs WHERE session_id=? AND message LIKE '%EXIT%' AND message NOT LIKE '%Background%'", (sid,))
    exits = cursor.fetchall()

    wins = []
    losses = []
    for msg_row in exits:
        msg = msg_row[0]
        net_match = re.search(r'net=([\d.-]+)', msg)
        if not net_match: continue
        net = float(net_match.group(1))

        # Find signal
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
                if net > 0: wins.append(btc)
                else: losses.append(btc)

    print(f"Wins: {len(wins)}, Losses: {len(losses)}")
    if wins and losses:
        for tf in ['1d', '4h', '1h', '15m']:
            w_val = [x[tf] for x in wins]; l_val = [x[tf] for x in losses]
            print(f"BTC {tf.upper()}: WinAvg={statistics.mean(w_val):.5f}, LossAvg={statistics.mean(l_val):.5f}")

analyze()
