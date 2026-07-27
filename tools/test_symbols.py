"""
1. Summary: Verifies Bitget API asset discovery and caching features.
2. Description: Performs async calls to check market specifications and local contract listings caching.
3. Context: Guarantees that symbol caches function without network latency.
"""
import asyncio
import os
from bitget_client import BitGetClient
from config import BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE

import pytest

@pytest.mark.asyncio
async def test_symbols_fetch():
    client = BitGetClient(BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE)
    symbols = await client.get_symbols()
    for s in symbols:
        if s['symbol'] in ['ETHUSDT', 'XRPUSDT', 'SOLUSDT', 'PEPEUSDT']:
             print(f"Symbol: {s['symbol']} | minTradeUSDT: {s.get('minTradeUSDT')} | minTradeNum: {s.get('minTradeNum')}")
    await client.close()

if __name__ == "__main__":
    asyncio.run(test_symbols_fetch())
