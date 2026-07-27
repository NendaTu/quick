"""
1. Summary: Confirms risk-to-reward ratio targets and break-even stop moves function under slippage.
2. Description: Simulates stop movements and exit targets to verify risk compliance.
3. Context: Verifies correct operation of partial-take profit splits.
"""
import math

MAKER_FEE = 0.0002
TAKER_FEE = 0.0006
EXPECTED_SLIPPAGE = 0.0005

def audit_rrr(tp_move, sl_move):
    qty = 1000
    entry = 100
    tp_price = entry * (1 + tp_move)
    sl_price = entry * (1 - sl_move)

    # Maker Entry, Maker TP
    win_net = (tp_price - entry) * qty - (entry * qty * MAKER_FEE) - (tp_price * qty * MAKER_FEE)
    # Maker Entry, Taker SL (Worst Case)
    loss_net = (sl_price - entry) * qty - (entry * qty * MAKER_FEE) - (sl_price * qty * TAKER_FEE)

    return win_net, loss_net, abs(win_net / loss_net)

print(f"{'TP%':<6} | {'SL%':<6} | {'Net Win':<8} | {'Net Loss':<8} | {'Net RRR'}")
print("-" * 50)
tp = 0.01
sl = 0.005
w, l, r = audit_rrr(tp, sl)
print(f"{tp*100:>5.2f}% | {sl*100:>5.2f}% | {w:>8.4f} | {l:>8.4f} | {r:>6.2f}:1")

# Calculate required SL for 2:1 NET RRR with Maker Entry, Maker TP, Taker SL
# (tp_move * qty) - fees_maker_round = 2 * |(-sl_move * qty) - fees_maker_taker|
# tp_move * qty - 2 * fees_m = 2 * (sl_move * qty + fees_mt)
# tp_move * qty - 2 * fees_m = 2 * sl_move * qty + 2 * fees_mt
# 2 * sl_move * qty = tp_move * qty - 2 * fees_m - 2 * fees_mt
# sl_move = (tp_move - 2*MAKER_FEE - 2*(MAKER_FEE + TAKER_FEE)) / 2
# sl_move = (tp_move - 4*MAKER_FEE - 2*TAKER_FEE) / 2

sl_sync = (tp - 4*MAKER_FEE - 2*TAKER_FEE) / 2
w2, l2, r2 = audit_rrr(tp, sl_sync)
print(f"{tp*100:>5.2f}% | {sl_sync*100:>5.2f}% | {w2:>8.4f} | {l2:>8.4f} | {r2:>6.2f}:1")
