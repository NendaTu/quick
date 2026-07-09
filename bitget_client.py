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
    def __init__(self, api_key: str, secret_key: str, passphrase: str, is_demo: bool = False):
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.is_demo = is_demo
        self.base_url = "https://api.bitget.com"
        self._session: Optional[aiohttp.ClientSession] = None
        self.time_offset = 0

    async def get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _generate_signature(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        if not self.secret_key:
            raise ValueError(f"BITGET_SECRET_KEY missing for {'DEMO' if self.is_demo else 'LIVE'} mode")
        message = timestamp + method.upper() + request_path + body
        mac = hmac.new(self.secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode("utf-8")

    async def sync_time(self):
        try:
            # Public endpoint to get server time
            url = f"{self.base_url}/api/v2/public/time"
            session = await self.get_session()
            async with session.get(url) as response:
                result = await response.json()
                if result.get("code") == "00000":
                    data = result.get("data")
                    if isinstance(data, dict):
                        server_time = int(data.get("serverTime") or data.get("ts") or 0)
                    else:
                        server_time = int(data)
                    local_time = int(time.time() * 1000)
                    self.time_offset = server_time - local_time
                    log.info(f"Synchronized time with Bitget. Offset: {self.time_offset}ms")
        except Exception as e:
            log.error(f"Failed to sync time: {e}")

    def _get_headers(self, method: str, request_path: str, body: str = "") -> Dict[str, str]:
        timestamp = str(int(time.time() * 1000) + self.time_offset)
        sign = self._generate_signature(timestamp, method, request_path, body)
        headers = {
            "ACCESS-KEY": str(self.api_key),
            "ACCESS-SIGN": str(sign),
            "ACCESS-PASSPHRASE": str(self.passphrase),
            "ACCESS-TIMESTAMP": str(timestamp),
            "Content-Type": "application/json",
            "locale": "en-US"
        }
        if self.is_demo:
            headers["paptrading"] = "1"
        return headers

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
                # Add a tiny delay if we've already hit limits to let the bucket drain
                if attempt > 0:
                    await asyncio.sleep(0.1 * attempt)

                async with session.request(method, url, data=body, headers=headers, timeout=10) as response:
                    if response.status == 429:
                        # [REPAIR-20260702] Jittered exponential backoff
                        wait = (2 ** attempt) + (random.random() * 0.5)
                        log.warning(f"Rate limited (429). Retrying in {wait:.2f}s... (Attempt {attempt+1}/{retries})")
                        await asyncio.sleep(wait)
                        continue

                    try:
                        result = await response.json()
                        if not isinstance(result, dict):
                            # Bitget sometimes returns a JSON string instead of an object in error cases
                            log.warning(f"API returned non-dict JSON: {type(result)}: {str(result)[:200]}")
                            result = {"code": "error", "msg": str(result), "data": result}
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
                        # [REPAIR-20260708] Handle timestamp expiry
                        if result.get("code") == "40008":
                            log.warning("Bitget reported timestamp expiry. Re-syncing time and retrying...")
                            await self.sync_time()
                            continue

                        # [REPAIR-20260707] Specific error for incorrect environment (40099)
                        if result.get("code") == "40099":
                            log.critical(f"BITGET CRITICAL: Exchange environment incorrect. Check your API Keys and MODE config. URL: {url}")
                        else:
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
            "productType": "USDT-FUTURES",
            "granularity": granularity, # Do not lowercase
            "limit": str(limit)
        }
        res = await self.request("GET", path, params=params)
        data = res.get("data")
        if isinstance(data, list):
            return data
        return []

    async def get_history_candles(self, symbol: str, granularity: str, end_time: Optional[int] = None, limit: int = 200) -> List:
        path = "/api/v2/mix/market/history-candles"
        params = {
            "symbol": symbol,
            "productType": "USDT-FUTURES",
            "granularity": granularity,
            "limit": str(limit)
        }
        if end_time:
            params["endTime"] = str(end_time)
        res = await self.request("GET", path, params=params)
        data = res.get("data")
        if isinstance(data, list):
            return data
        return []

    async def get_symbols(self) -> List:
        path = "/api/v2/mix/market/contracts"
        params = {"productType": "USDT-FUTURES"}
        res = await self.request("GET", path, params=params)
        data = res.get("data")
        if isinstance(data, list):
            return data
        return []

    async def get_tickers(self) -> List:
        path = "/api/v2/mix/market/tickers"
        params = {"productType": "USDT-FUTURES"}
        res = await self.request("GET", path, params=params)
        data = res.get("data")
        if isinstance(data, list):
            return data
        return []

    async def place_order(self, symbol: str, side: str, order_type: str, qty: float, price: Optional[float] = None,
                          trade_side: str = "open", margin_mode: str = "isolated", tp_price: Optional[float] = None,
                          sl_price: Optional[float] = None, **kwargs) -> Dict:
        path = "/api/v2/mix/order/place-order"
        data = {
            "symbol": symbol,
            "productType": "USDT-FUTURES",
            "marginMode": margin_mode,
            "marginCoin": "USDT",
            "size": str(qty),
            "side": side.lower(),
            "orderType": order_type.lower(),
            "tradeSide": trade_side,
            "force": "gtc" if order_type.lower() == "limit" else None
        }
        if price:
            data["price"] = str(price)
        if tp_price:
            data["presetTakeProfitPrice"] = str(tp_price)
        if sl_price:
            data["presetStopLossPrice"] = str(sl_price)

        data.update(kwargs)
        return await self.request("POST", path, data=data)

    async def get_account_balance(self) -> List[Dict]:
        path = "/api/v2/mix/account/accounts"
        params = {"productType": "USDT-FUTURES"}
        res = await self.request("GET", path, params=params)
        data = res.get("data")
        if isinstance(data, list):
            return data
        return []

    async def get_positions(self, symbol: Optional[str] = None) -> List[Dict]:
        path = "/api/v2/mix/position/all-position"
        params = {"productType": "USDT-FUTURES"}
        if symbol:
            params["symbol"] = symbol
        res = await self.request("GET", path, params=params)
        data = res.get("data")
        if isinstance(data, dict):
            # Bitget V2 positions is actually a list, but handle dict wrapper just in case
            return data.get("list") or data.get("positions") or []
        if isinstance(data, list):
            return data
        return []

    async def cancel_order(self, symbol: str, order_id: str) -> Dict:
        path = "/api/v2/mix/order/cancel-order"
        data = {
            "symbol": symbol,
            "productType": "USDT-FUTURES",
            "orderId": order_id
        }
        return await self.request("POST", path, data=data)

    async def get_order_status(self, symbol: str, order_id: str) -> Dict:
        path = "/api/v2/mix/order/detail"
        params = {
            "symbol": symbol,
            "productType": "USDT-FUTURES",
            "orderId": order_id
        }
        res = await self.request("GET", path, params=params)
        data = res.get("data")
        return data if isinstance(data, dict) else {}

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        path = "/api/v2/mix/order/orders-pending"
        params = {
            "productType": "USDT-FUTURES"
        }
        if symbol:
            params["symbol"] = symbol
        res = await self.request("GET", path, params=params)
        data = res.get("data")
        if isinstance(data, dict):
            return data.get("entrustedList") or []
        if isinstance(data, list):
            return data
        return []

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

class BitGetWSClient:
    def __init__(self, symbols: List[str], callback: Callable, is_private: bool = False,
                 api_key: str = None, secret_key: str = None, passphrase: str = None):
        self.url = "wss://ws.bitget.com/v2/ws/private" if is_private else "wss://ws.bitget.com/v2/ws/public"
        self.symbols = symbols
        self.callback = callback
        self.is_private = is_private
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.stop_event = asyncio.Event()
        self._session: Optional[aiohttp.ClientSession] = None

    async def run(self):
        self._session = aiohttp.ClientSession()
        while not self.stop_event.is_set():
            try:
                async with self._session.ws_connect(self.url) as ws:
                    log.info(f"Connected to BitGet {'PRIVATE ' if self.is_private else ''}WebSocket")

                    if self.is_private:
                        # Authenticate for private WS
                        ts = str(int(time.time()))
                        message = ts + "GET" + "/user/verify"
                        mac = hmac.new(self.secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
                        sign = base64.b64encode(mac.digest()).decode("utf-8")

                        auth_msg = {
                            "op": "login",
                            "args": [{
                                "apiKey": self.api_key,
                                "passphrase": self.passphrase,
                                "timestamp": ts,
                                "sign": sign
                            }]
                        }
                        await ws.send_json(auth_msg)
                        # Wait for login confirmation
                        resp = await ws.receive_json()
                        # Success can be "0" or 0 depending on the API version/response type
                        # Also handle case where code might be in a different field or nested
                        code = resp.get("code") or resp.get("data", {}).get("code") if isinstance(resp.get("data"), dict) else resp.get("code")
                        if str(code) != "0" and resp.get("event") != "login":
                             log.error(f"Private WS Login Failed: {resp}")
                             break
                        elif str(code) != "0" and resp.get("code") is not None:
                             log.error(f"Private WS Login Error: {resp}")
                             break

                    all_args = []
                    if self.is_private:
                        all_args.append({"instType": "USDT-FUTURES", "channel": "orders"})
                        all_args.append({"instType": "USDT-FUTURES", "channel": "positions"})
                        all_args.append({"instType": "USDT-FUTURES", "channel": "account"})
                    else:
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
