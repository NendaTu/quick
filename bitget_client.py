import hmac
import hashlib
import time
import base64
import json
import asyncio
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

    async def request(self, method: str, path: str, params: Dict = None, data: Dict = None) -> Dict:
        session = await self.get_session()

        signed_path = path
        if method.upper() == "GET" and params:
            query = urllib.parse.urlencode(params)
            signed_path += "?" + query

        url = self.base_url + signed_path
        body = json.dumps(data) if data else ""
        headers = self._get_headers(method, signed_path, body)

        try:
            async with session.request(method, url, data=body, headers=headers) as response:
                result = await response.json()
                if result.get("code") != "00000":
                    log.error(f"BitGet Error: {result} on {url}")
                return result
        except Exception as e:
            log.error(f"Request Exception: {e} on {url}")
            return {"code": "error", "msg": str(e), "data": None}

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

                    subscribe_msg = {"op": "subscribe", "args": []}
                    for sym in self.symbols:
                        subscribe_msg["args"].append({"instType": "umc", "channel": "books5", "instId": sym})
                        subscribe_msg["args"].append({"instType": "umc", "channel": "trade", "instId": sym})

                    await ws.send_json(subscribe_msg)
                    hb_task = asyncio.create_task(self._heartbeat(ws))

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            if msg.data == "pong": continue
                            data = json.loads(msg.data)
                            if "data" in data:
                                await self.callback(data)
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break

                    hb_task.cancel()
            except Exception as e:
                log.error(f"WS Error: {e}")
                if not self.stop_event.is_set():
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
