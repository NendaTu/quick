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
        return {'symbol': symbol, 'side': side, 'drt': drt, 'rsi': rsi}
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

    # Get latest session ID
    cursor.execute("SELECT MAX(id) FROM sessions")
    session_id = cursor.fetchone()[0]
    print(f"Analyzing Session ID: {session_id}")

    # Get all exits for this session
    cursor.execute("SELECT timestamp, message FROM logs WHERE session_id = ? AND message LIKE '%EXIT%' AND message NOT LIKE '%Background%' ORDER BY timestamp ASC", (session_id,))
    exit_logs = cursor.fetchall()

    trades = []
    for ts, msg in exit_logs:
        exit_data = parse_exit(msg)
        if not exit_data: continue

        # Find corresponding signal in the same session
        cursor.execute("""
            SELECT message FROM logs
            WHERE session_id = ? AND timestamp < ? AND message LIKE ? AND message LIKE ?
            AND (message LIKE '%SIGNAL:%' OR message LIKE '%Entry Triggered%')
            ORDER BY timestamp DESC LIMIT 1
        """, (session_id, ts, f"%{exit_data['symbol']}%", f"% {exit_data['side']} %"))

        sig_row = cursor.fetchone()
        if sig_row:
            sig_data = parse_signal(sig_row[0])
            if sig_data: trades.append({**sig_data, **exit_data})

    if not trades:
        print("No trades found in this session.")
        return

    for side in ['BUY', 'SELL']:
        side_trades = [t for t in trades if t['side'] == side]
        wins = [t for t in side_trades if t['net'] > 0]
        losses = [t for t in side_trades if t['net'] <= 0]

        print(f"\n=== SIDE: {side} ===")
        print(f"Wins: {len(wins)}, Losses: {len(losses)}")

        for m in ['rsi', 'drt']:
            w_val = [t[m] for t in wins]; l_val = [t[m] for t in losses]
            if w_val or l_val:
                w_avg = statistics.mean(w_val) if w_val else 0
                l_avg = statistics.mean(l_val) if l_val else 0
                print(f"Metric {m.upper()}: WinAvg={w_avg:.4f}, LossAvg={l_avg:.4f}")

    conn.close()

if __name__ == "__main__":
    analyze()
