import asyncio
import os
from bitget_client import BitGetClient

async def check():
    client = BitGetClient(
        os.getenv("BITGET_API_KEY", "bg_001fadae900c2233fb2a3e0be1fe3a65"),
        os.getenv("BITGET_SECRET_KEY", "0592a8b4ae5a20e83c28f83d7df0da809f2f9a95fdfc1fdcc3c32a955693efd4"),
        os.getenv("BITGET_PASSPHRASE", "92449244")
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
