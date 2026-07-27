"""
1. Summary: Verifies exchange connectivity and API REST credentials.
2. Description: Signs and dispatches standard REST queries to check API permissions.
3. Context: Crucial debugging helper used during live connection setups.
"""
import asyncio
import os
from bitget_client import BitGetClient

async def check():
    client = BitGetClient(
        os.getenv("BITGET_API_KEY"),
        os.getenv("BITGET_SECRET_KEY"),
        os.getenv("BITGET_PASSPHRASE")
    )
    # Check Tickers for volume
    path = "/api/v2/mix/market/tickers"
    params = {"productType": "usdt-futures"}
    res = await client.request("GET", path, params=params)
    tickers = res.get("data", [])
    if tickers:
        print(f"First ticker keys: {tickers[0].keys()}")
        print(f"Sample ticker (BTCUSDT): {[t for t in tickers if t['symbol'] == 'BTCUSDT']}")

    # Check Contracts for leverage
    contracts = await client.get_symbols()
    if contracts:
        print(f"First contract keys: {contracts[0].keys()}")
        print(f"Sample contract (BTCUSDT): {[c for c in contracts if c['symbol'] == 'BTCUSDT']}")

    await client.close()

if __name__ == "__main__":
    asyncio.run(check())
