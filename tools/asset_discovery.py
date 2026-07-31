"""
1. Summary: Centralized asset discovery and universe selection helper.
2. Description: Filters a normalized list of (symbol, volume) tickers to exclude stablecoins, omitted assets, and applies a limit to select the top assets by trading volume.
3. Context: Imported by launcher scripts, downloader tools, and execution loops to standardize asset universe selection across different exchange drivers.
"""
from typing import List, Tuple, Collection

def discover_assets(
    normalized_tickers: List[Tuple[str, float]],
    omitted_assets: Collection[str],
    limit: int
) -> List[str]:
    """
    Filters and selects the top symbol names by volume.

    normalized_tickers: A list of (symbol, volume) tuples.
    omitted_assets: A collection of symbols to strictly skip.
    limit: The maximum number of assets to return.
    """
    # Sort by volume descending
    sorted_tickers = sorted(normalized_tickers, key=lambda x: x[1], reverse=True)

    stablecoins = {"USDC", "DAI", "BUSD", "EUR", "GBP"}
    discovered = []

    for sym, vol in sorted_tickers:
        if sym.endswith("USDT") and sym not in omitted_assets:
            base = sym.replace("USDT", "")
            if base in stablecoins:
                continue
            discovered.append(sym)
            if len(discovered) >= limit:
                break

    return discovered
