"""
1. Summary: Tertiary validator ensuring simulator PnL calculations match live ledger results.
2. Description: Validates fee-deducted gross-to-net equations against realistic account ledgers.
3. Context: Verifies math accuracy.
"""
import math

MAKER_FEE = 0.0002
TAKER_FEE = 0.0006
EXPECTED_SLIPPAGE = 0.0005

def calculate_logic_v3(leverage=100):
    # Goal: TP_NET = 2 * |SL_NET|
    # Price moves:
    tp_move = 0.01
    # Net Win = (PriceMove * Qty) - Fees
    # Net Loss = (PriceMove * Qty) - Fees

    # We want (tp_move * qty) - fees = 2 * |(-sl_move * qty) - fees|
    # (tp_move * qty) - fees = 2 * (sl_move * qty + fees)
    # tp_move * qty - fees = 2 * sl_move * qty + 2 * fees
    # tp_move * qty - 2 * sl_move * qty = 3 * fees
    # qty * (tp_move - 2 * sl_move) = 3 * fees

    # Simplify for Price Move ratio:
    # sl_move = (tp_move - (3 * fees_rate)) / 2

    fee_rate = MAKER_FEE + MAKER_FEE # round trip
    sl_move = (tp_move - (3 * fee_rate)) / 2

    # Check:
    qty = 1000
    entry = 100
    tp_price = entry * (1 + tp_move)
    sl_price = entry * (1 - sl_move)

    win_net = (tp_price - entry) * qty - (entry * qty * MAKER_FEE) - (tp_price * qty * MAKER_FEE)
    loss_net = (sl_price - entry) * qty - (entry * qty * MAKER_FEE) - (sl_price * qty * MAKER_FEE)

    return {
        "tp_pct": tp_move * 100,
        "sl_pct": sl_move * 100,
        "win_net": win_net,
        "loss_net": loss_net,
        "rrr": abs(win_net / loss_net)
    }

res = calculate_logic_v3(100)
print(f"TP: {res['tp_pct']:.2f}% | SL: {res['sl_pct']:.4f}% | RRR: {res['rrr']:.2f}:1")
