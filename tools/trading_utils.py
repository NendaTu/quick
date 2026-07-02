import config

def calculate_fees(qty, price, is_maker=True):
    fee_rate = config.MAKER_FEE if is_maker else config.TAKER_FEE
    return qty * price * fee_rate

def calculate_pnl(qty, entry_price, exit_price, side):
    """Calculates gross USDT PnL for a position."""
    if side == "buy":
        return (exit_price - entry_price) * qty
    else:
        return (entry_price - exit_price) * qty

def calculate_net_pnl(qty, entry_price, exit_price, side, entry_maker=True, exit_maker=True):
    """Calculates net USDT PnL after all fees."""
    gross_pnl = calculate_pnl(qty, entry_price, exit_price, side)
    entry_fee = calculate_fees(qty, entry_price, entry_maker)
    exit_fee = calculate_fees(qty, exit_price, exit_maker)
    return gross_pnl - entry_fee - exit_fee

def calculate_roe(entry_price, exit_price, side, leverage, entry_maker=True, exit_maker=True, include_slippage=False):
    """
    Calculates net ROE for a position.
    ROE = Net PnL / Margin
    """
    f1 = config.MAKER_FEE if entry_maker else config.TAKER_FEE
    f2 = config.MAKER_FEE if exit_maker else config.TAKER_FEE
    s = config.EXPECTED_SLIPPAGE if include_slippage else 0

    # Gross PnL per unit
    if side == "buy":
        gross_unit = (exit_price - entry_price)
    else:
        gross_unit = (entry_price - exit_price)

    # Fees and slippage per unit
    fees_unit = (entry_price * f1) + (exit_price * f2)
    slippage_unit = (entry_price * s) + (exit_price * s)

    net_unit = gross_unit - fees_unit - slippage_unit
    margin_unit = entry_price / leverage

    return net_unit / margin_unit

def calculate_tp_for_roe(entry_price, target_roe, side, leverage, entry_maker=True, exit_maker=True, include_slippage=True):
    """
    Calculates the exit price required to hit a target net ROE, including slippage.

    Long ROE = ( (Exit - Entry) - Fees - Slippage ) / Margin
    Margin = Entry / Leverage
    Fees = Entry * f1 + Exit * f2
    Slippage = Exit * s (Exit slippage) + Entry * s (Entry slippage)

    Target_ROE * (Entry / Lev) = (Exit - Entry) - (Entry*f1 + Exit*f2) - (Exit*s + Entry*s)
    T * E / L = X - E - E*f1 - X*f2 - X*s - E*s
    T * E / L + E + E*f1 + E*s = X (1 - f2 - s)
    X = (E * (T/L + 1 + f1 + s)) / (1 - f2 - s)

    Short:
    T * E / L = (Entry - Exit) - (Entry*f1 + Exit*f2) - (Exit*s + Entry*s)
    T * E / L - E + E*f1 + E*s = -X (1 + f2 + s)
    X = (E * (1 - f1 - s - T/L)) / (1 + f2 + s)
    """
    f1 = config.MAKER_FEE if entry_maker else config.TAKER_FEE
    f2 = config.MAKER_FEE if exit_maker else config.TAKER_FEE
    s = config.EXPECTED_SLIPPAGE if include_slippage else 0

    L = leverage
    E = entry_price
    T = target_roe

    if side == "buy":
        return (E * (T/L + 1 + f1 + s)) / (1 - f2 - s)
    else:
        return (E * (1 - f1 - s - T/L)) / (1 + f2 + s)

def calculate_target_roe_for_rrr(rrr, entry_price, stop_price, leverage, entry_maker=True, exit_maker=False):
    """
    Calculates the target net ROE required to achieve a specific Reward-to-Risk Ratio (RRR).
    Risk = Abs(Entry - Stop) + EntryFees + StopFees + EntrySlippage + StopSlippage
    Reward = Risk * RRR
    NetReward = Reward (net of all fees and slippage)

    This is complex because NetReward depends on the Exit Price which we don't know yet.
    However, we can approximate the target ROE by looking at the price distance.
    Distance = Abs(Entry - Stop)
    TargetPriceDistance = Distance * RRR

    Actually, a more precise way is to calculate the risk in ROE terms.
    Risk_ROE = calculate_roe(entry_price, stop_price, side, leverage, ...)
    Target_Net_ROE = Abs(Risk_ROE) * RRR
    """
    # Determine side
    side = "buy" if entry_price > stop_price else "sell"

    # Use existing calculate_roe to find net loss on stop out
    risk_roe = calculate_roe(
        entry_price,
        stop_price,
        side,
        leverage,
        entry_maker=entry_maker,
        exit_maker=exit_maker,
        include_slippage=True
    )

    return abs(risk_roe) * rrr

def calculate_position_size(equity, risk_fraction, entry_price, stop_price, entry_maker=True, exit_maker=False, fee_aware=True):
    """
    Calculates position size based on risk and distance to stop loss.
    """
    risk_amount = equity * risk_fraction

    if fee_aware:
        f1 = config.MAKER_FEE if entry_maker else config.TAKER_FEE
        f2 = config.MAKER_FEE if exit_maker else config.TAKER_FEE
        # Fee per unit for entry and exit
        fee_per_unit = (entry_price * f1) + (stop_price * f2)
        risk_per_unit = abs(entry_price - stop_price) + fee_per_unit
    else:
        risk_per_unit = abs(entry_price - stop_price)

    if risk_per_unit <= 0:
        return 0

    return risk_amount / risk_per_unit
