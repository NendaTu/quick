import sqlite3
import re
import statistics

def parse_signal(msg):
    # SIGNAL: ETHUSDT BUY qty=0.590 entry=1669.91000000 exit=1672.41000000 stop=1668.24000000 [1D:-0.0505 4H:0.0236 1H:-0.0088 15m:-0.0189] drt=0.510 rsi=79.1 macd=0.1476 ema=1663.8321 vol=0.03 equity=100.00
    try:
        parts = msg.split('SIGNAL: ')[1].split(' ')
        symbol = parts[0]
        side = parts[1]

        drt = float(re.search(r'drt=([\d.-]+)', msg).group(1))
        rsi = float(re.search(r'rsi=([\d.-]+)', msg).group(1))
        macd = float(re.search(r'macd=([\d.-]+)', msg).group(1))
        ema = float(re.search(r'ema=([\d.-]+)', msg).group(1))
        vol = float(re.search(r'vol=([\d.-]+)', msg).group(1))

        # Parse BTC confluence
        btc_match = re.search(r'\[1D:([\d.-]+) 4H:([\d.-]+) 1H:([\d.-]+) 15m:([\d.-]+)\]', msg)
        btc = {
            '1d': float(btc_match.group(1)),
            '4h': float(btc_match.group(2)),
            '1h': float(btc_match.group(3)),
            '15m': float(btc_match.group(4))
        }

        return {
            'symbol': symbol,
            'side': side,
            'drt': drt,
            'rsi': rsi,
            'macd': macd,
            'ema': ema,
            'vol': vol,
            'btc': btc
        }
    except Exception as e:
        return None

def parse_exit(msg):
    # EXIT ETHUSDT SELL STOP @ 1672.35000000 PnL=-1.0207 net=-2.2053 [1D:-0.0497 4H:0.0245 1H:-0.0100 15m:-0.0096] drt_entry=0.5733 drt_exit=0.5207 | equity=76.56 used_margin=70.97
    try:
        parts = msg.split('EXIT ')[1].split(' ')
        symbol = parts[0]
        side = parts[1]
        exit_type = parts[2]

        net = float(re.search(r'net=([\d.-]+)', msg).group(1))
        drt_entry = float(re.search(r'drt_entry=([\d.-]+)', msg).group(1))
        drt_exit = float(re.search(r'drt_exit=([\d.-]+)', msg).group(1))

        return {
            'symbol': symbol,
            'side': side,
            'exit_type': exit_type,
            'net': net,
            'drt_entry': drt_entry,
            'drt_exit': drt_exit
        }
    except Exception:
        return None

def analyze():
    conn = sqlite3.connect('market_data.db')
    cursor = conn.cursor()

    # Get all exits
    cursor.execute("SELECT timestamp, message FROM logs WHERE message LIKE '%EXIT%' AND message NOT LIKE '%Background%' ORDER BY timestamp ASC")
    exit_logs = cursor.fetchall()

    wins = []
    losses = []

    for ts, msg in exit_logs:
        exit_data = parse_exit(msg)
        if not exit_data: continue

        # Find corresponding signal
        # Use symbol and side. Note: side in EXIT is the position side, same as in SIGNAL.
        cursor.execute("""
            SELECT message FROM logs
            WHERE timestamp < ?
            AND message LIKE ?
            AND message LIKE ?
            AND (message LIKE '%SIGNAL:%' OR message LIKE '%Entry Triggered%')
            ORDER BY timestamp DESC LIMIT 1
        """, (ts, f"%{exit_data['symbol']}%", f"% {exit_data['side']} %"))

        sig_row = cursor.fetchone()
        if not sig_row: continue

        sig_data = parse_signal(sig_row[0])
        if not sig_data: continue

        trade = {**sig_data, **exit_data}
        if exit_data['net'] > 0:
            wins.append(trade)
        else:
            losses.append(trade)

    print(f"Wins: {len(wins)}, Losses: {len(losses)}")

    metrics = ['drt', 'rsi', 'macd', 'vol']
    btc_tfs = ['1d', '4h', '1h', '15m']

    for m in metrics:
        win_m = [t[m] for t in wins]
        loss_m = [t[m] for t in losses]
        if win_m and loss_m:
            print(f"\nMetric: {m.upper()}")
            print(f"  Win Avg:  {statistics.mean(win_m):.4f} (std: {statistics.stdev(win_m):.4f})")
            print(f"  Loss Avg: {statistics.mean(loss_m):.4f} (std: {statistics.stdev(loss_m):.4f})")

    for tf in btc_tfs:
        win_m = [t['btc'][tf] for t in wins]
        loss_m = [t['btc'][tf] for t in losses]
        if win_m and loss_m:
            print(f"\nBTC Confluence {tf.upper()}")
            print(f"  Win Avg:  {statistics.mean(win_m):.4f}")
            print(f"  Loss Avg: {statistics.mean(loss_m):.4f}")

    # Analyze DRT change
    if wins:
        drt_delta_win = [t['drt_exit'] - t['drt_entry'] for t in wins]
        print(f"\nDRT Delta (Exit - Entry)")
        print(f"  Win Avg:  {statistics.mean(drt_delta_win):.4f}")
    if losses:
        drt_delta_loss = [t['drt_exit'] - t['drt_entry'] for t in losses]
        print(f"  Loss Avg: {statistics.mean(drt_delta_loss):.4f}")

    conn.close()

if __name__ == "__main__":
    analyze()
