import math

MAKER_FEE = 0.0002
TAKER_FEE = 0.0006
EXPECTED_SLIPPAGE = 0.0005

def calculate_new_logic(
    equity=1000.0,
    risk_per_trade=0.002,
    leverage=100,
    target_roe=0.05
):
    risk_amount = equity * risk_per_trade
    entry_price = 100.0

    # NEW LOGIC in models.py
    # 1. Calculate TP Move
    tp_move = (target_roe / leverage) + (MAKER_FEE * 2) + EXPECTED_SLIPPAGE
    tp_move = max(tp_move, 0.01) # Baseline floor from config

    # 2. Calculate Synchronized SL Move (1:2 RRR)
    sl_move = (tp_move / 2) - (MAKER_FEE * 2)
    sl_move = max(sl_move, 0.001) # Safety floor

    # 3. Calculate Quantity (Risk-based)
    risk_per_unit = entry_price * sl_move
    qty = risk_amount / risk_per_unit
    notional = qty * entry_price
    margin = notional / leverage

    # 4. Scenario Outcomes
    entry_fee = notional * MAKER_FEE

    tp_price = entry_price * (1 + tp_move)
    tp_net = ((tp_price - entry_price) * qty) - (qty * tp_price * MAKER_FEE) - entry_fee

    sl_price = entry_price * (1 - sl_move)
    sl_net = ((sl_price - entry_price) * qty) - (qty * sl_price * MAKER_FEE) - entry_fee

    return {
        "tp_pct": tp_move * 100,
        "sl_pct": sl_move * 100,
        "tp_net": tp_net,
        "sl_net": sl_net,
        "rrr": abs(tp_net / sl_net) if sl_net != 0 else 0,
        "margin": margin
    }

print(f"{'Lev':<5} | {'TP%':<6} | {'SL%':<6} | {'Net Win':<8} | {'Net Loss':<8} | {'Net RRR':<6}")
print("-" * 65)
for lev in [10, 20, 50, 100]:
    res = calculate_new_logic(leverage=lev)
    print(f"{lev:<5} | {res['tp_pct']:>5.2f}% | {res['sl_pct']:>5.2f}% | {res['tp_net']:>8.4f} | {res['sl_net']:>8.4f} | {res['rrr']:>6.2f}")
