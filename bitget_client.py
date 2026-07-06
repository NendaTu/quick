import hmac
import hashlib
import time
import base64
import json
import asyncio
import random
import aiohttp
import logging
import urllib.parse
from typing import Dict, List, Optional, Callable
from config import BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE

log = logging.getLogger("scalper.bitget")

class BitGetClient:
    def __init__(self, api_key: str, secret_key: str, passphrase: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.base_url = "https://api.bitget.com"
        self._session: Optional[aiohttp.ClientSession] = None

    async def get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _generate_signature(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        message = timestamp + method.upper() + request_path + body
        mac = hmac.new(self.secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode("utf-8")

    def _get_headers(self, method: str, request_path: str, body: str = "") -> Dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        sign = self._generate_signature(timestamp, method, request_path, body)
        return {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": sign,
            "ACCESS-PASSPHRASE": self.passphrase,
            "ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
            "locale": "en-US"
        }

    async def request(self, method: str, path: str, params: Dict = None, data: Dict = None, retries: int = 7) -> Dict:
        session = await self.get_session()

        signed_path = path
        if method.upper() == "GET" and params:
            query = urllib.parse.urlencode(params)
            signed_path += "?" + query

        url = self.base_url + signed_path
        body = json.dumps(data) if data else ""

        for attempt in range(retries):
            headers = self._get_headers(method, signed_path, body)
            try:
                async with session.request(method, url, data=body, headers=headers, timeout=30) as response:
                    if response.status == 429:
                        # [REPAIR-20260702] Jittered exponential backoff
                        wait = (2 ** attempt) + (random.random() * 0.5)
                        log.warning(f"Rate limited (429). Retrying in {wait:.2f}s... (Attempt {attempt+1}/{retries})")
                        await asyncio.sleep(wait)
                        continue

                    try:
                        result = await response.json()
                    except Exception as json_err:
                        # Fallback for non-JSON responses
                        text = await response.text()
                        log.error(f"Failed to parse JSON response: {json_err}. Body: {text[:200]}")
                        if attempt < retries - 1:
                            await asyncio.sleep(1)
                            continue
                        return {"code": "error", "msg": f"JSON parse error: {json_err}", "data": None}

                    if result.get("code") in ["429", "400031", "40053"] and "verification failed" not in result.get("msg", ""):
                        # Bitget specific rate limit codes
                        wait = (2 ** attempt) + (random.random() * 0.5)
                        log.warning(f"Rate limited ({result.get('code')}). Retrying in {wait:.2f}s... (Attempt {attempt+1}/{retries})")
                        await asyncio.sleep(wait)
                        continue

                    if result.get("code") != "00000":
                        log.error(f"BitGet Error: {result} on {url}")
                    return result
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                log.error(f"Connection error ({type(e).__name__}): {e} on {url}")
                if attempt < retries - 1:
                    wait = (attempt + 1) * 2
                    await asyncio.sleep(wait)
                    headers = self._get_headers(method, signed_path, body)
                    continue
                return {"code": "error", "msg": f"{type(e).__name__}: {e}", "data": None}
            except Exception as e:
                log.error(f"Unexpected Request Exception ({type(e).__name__}): {e} on {url}")
                if attempt < retries - 1:
                    await asyncio.sleep(1)
                    continue
                return {"code": "error", "msg": str(e), "data": None}

        return {"code": "error", "msg": "Max retries exceeded", "data": None}

    async def get_candles(self, symbol: str, granularity: str, limit: int = 100) -> List:
        # BitGet V2 granularity is case-sensitive for some timeframes (e.g. 1H, 4H, 1D)
        path = "/api/v2/mix/market/candles"
        params = {
            "symbol": symbol,
            "productType": "usdt-futures",
            "granularity": granularity, # Do not lowercase
            "limit": str(limit)
        }
        res = await self.request("GET", path, params=params)
        return res.get("data") or []

    async def get_symbols(self) -> List:
        path = "/api/v2/mix/market/contracts"
        params = {"productType": "usdt-futures"}
        res = await self.request("GET", path, params=params)
        return res.get("data", [])

    async def get_tickers(self) -> List:
        path = "/api/v2/mix/market/tickers"
        params = {"productType": "usdt-futures"}
        res = await self.request("GET", path, params=params)
        return res.get("data", [])

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

class BitGetWSClient:
    def __init__(self, symbols: List[str], callback: Callable):
        self.url = "wss://ws.bitget.com/v2/ws/public"
        self.symbols = symbols
        self.callback = callback
        self.stop_event = asyncio.Event()
        self._session: Optional[aiohttp.ClientSession] = None

    async def run(self):
        self._session = aiohttp.ClientSession()
        while not self.stop_event.is_set():
            try:
                async with self._session.ws_connect(self.url) as ws:
                    log.info("Connected to BitGet WebSocket")

                    all_args = []
                    for sym in self.symbols:
                        all_args.append({"instType": "USDT-FUTURES", "channel": "books15", "instId": sym})
                        all_args.append({"instType": "USDT-FUTURES", "channel": "trade", "instId": sym})

                    # Batch subscriptions to avoid exchange disconnects for large payloads
                    batch_size = 20
                    for i in range(0, len(all_args), batch_size):
                        if self.stop_event.is_set(): break
                        batch = all_args[i:i + batch_size]
                        subscribe_msg = {"op": "subscribe", "args": batch}
                        await ws.send_json(subscribe_msg)
                        await asyncio.sleep(0.1) # Small delay between batches

                    if self.stop_event.is_set(): break

                    hb_task = asyncio.create_task(self._heartbeat(ws))

                    async for msg in ws:
                        if self.stop_event.is_set():
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            if msg.data == "pong": continue
                            try:
                                data = json.loads(msg.data)
                                if "data" in data:
                                    await self.callback(data)
                                elif data.get("event") == "subscribe":
                                    log.debug(f"Subscribed: {data.get('arg')}")
                                elif data.get("action") == "snapshot":
                                    await self.callback(data)
                            except Exception as e:
                                log.error(f"Error parsing WS message: {e}")
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break

                    hb_task.cancel()
                    if self.stop_event.is_set():
                        await ws.close()
                        break
            except Exception as e:
                if not self.stop_event.is_set():
                    log.error(f"WS Error: {e}")
                    await asyncio.sleep(5)

        if not self._session.closed:
            await self._session.close()

    async def _heartbeat(self, ws):
        try:
            while not ws.closed:
                await ws.send_str("ping")
                await asyncio.sleep(20)
        except asyncio.CancelledError:
            pass

    def stop(self):
        self.stop_event.set()
