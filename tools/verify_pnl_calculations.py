"""
1. Summary: Double-checks compounding equity calculations after fee deductions.
2. Description: Validates reinvestment percentages and risk margins on a simulated account.
3. Context: Used to test capital growth models.
"""
import math

def calculate_trade_simulation(
    equity=1000.0,
    risk_per_trade=0.002,
    tp_move=0.01,
    sl_move=0.005,
    leverage=20,
    maker_fee=0.0002,
    taker_fee=0.0006,
    entry_price=100.0,
    fee_aware_sizing=False,
    use_dynamic=False,
    target_roe=0.05
):
    risk_amount = equity * risk_per_trade

    # 0. Dynamic Target Logic (Current models.py)
    if use_dynamic:
        # tp_move = (target_roe / lev) + fees + slippage
        # sl_move remains fixed SL_MOVE
        tp_move = (target_roe / leverage) + (maker_fee * 2) + 0.0005

    # 1. Quantity Calculation
    if fee_aware_sizing:
        # Assuming limit entry and market exit (taker) for SL worst case
        entry_fee_rate = maker_fee
        exit_fee_rate = taker_fee
        fee_per_unit = entry_price * (entry_fee_rate + exit_fee_rate)
        risk_per_unit = (entry_price * sl_move) + fee_per_unit
    else:
        risk_per_unit = entry_price * sl_move

    qty = risk_amount / risk_per_unit
    notional = qty * entry_price
    margin = notional / leverage

    # 2. Entry Fee
    entry_fee = notional * maker_fee

    # 3. TP Scenario (Net)
    tp_price = entry_price * (1 + tp_move)
    tp_gross_pnl = (tp_price - entry_price) * qty
    tp_exit_fee = (qty * tp_price) * maker_fee
    tp_net_pnl = tp_gross_pnl - tp_exit_fee - entry_fee

    # 4. SL Scenario (Net)
    sl_price = entry_price * (1 - sl_move)
    sl_gross_pnl = (sl_price - entry_price) * qty
    sl_exit_fee = (qty * sl_price) * taker_fee # Worst case: Market backup
    sl_net_pnl = sl_gross_pnl - sl_exit_fee - entry_fee

    return {
        "risk_amount": risk_amount,
        "notional": notional,
        "margin": margin,
        "tp_net_pnl": tp_net_pnl,
        "sl_net_pnl": sl_net_pnl,
        "tp_move_pct": tp_move * 100,
        "sl_move_pct": sl_move * 100,
        "rrr_net": abs(tp_net_pnl / sl_net_pnl) if sl_net_pnl != 0 else 0
    }

def audit_configs():
    scenarios = [
        ("Fixed: 1% TP / 0.5% SL (20x Lev)", 1000.0, 0.002, 0.01, 0.005, 20, False, False),
        ("Dynamic: 5% ROE / 0.5% SL (20x Lev)", 1000.0, 0.002, 0.01, 0.005, 20, False, True),
        ("Dynamic: 5% ROE / 0.5% SL (100x Lev)", 1000.0, 0.002, 0.01, 0.005, 100, False, True),
    ]

    print(f"{'Scenario':<40} | {'TP%':<6} | {'SL%':<6} | {'Net Win':<8} | {'Net Loss':<8} | {'Net RRR':<6}")
    print("-" * 95)
    for label, eq, risk, tp, sl, lev, fas, dyn in scenarios:
        res = calculate_trade_simulation(equity=eq, risk_per_trade=risk, tp_move=tp, sl_move=sl, leverage=lev, fee_aware_sizing=fas, use_dynamic=dyn)
        print(f"{label:<40} | {res['tp_move_pct']:>5.2f}% | {res['sl_move_pct']:>5.2f}% | {res['tp_net_pnl']:>8.4f} | {res['sl_net_pnl']:>8.4f} | {res['rrr_net']:>6.2f}")

if __name__ == "__main__":
    audit_configs()
