import base64
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2")
API_KEY_ID = os.getenv("KALSHI_API_KEY_ID")
PRIVATE_KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH")


def _sign_request(method: str, path: str) -> dict:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    with open(PRIVATE_KEY_PATH, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    timestamp_ms = str(int(time.time() * 1000))
    message = timestamp_ms + method + path
    signature = private_key.sign(
        message.encode("utf-8"),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    sig_b64 = base64.b64encode(signature).decode("utf-8")

    return {
        "KALSHI-ACCESS-KEY": API_KEY_ID,
        "KALSHI-ACCESS-SIGNATURE": sig_b64,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
    }


def _have_credentials() -> bool:
    return bool(API_KEY_ID and PRIVATE_KEY_PATH and os.path.exists(PRIVATE_KEY_PATH))


def get_market(ticker: str) -> dict:
    path = f"/trade-api/v2/markets/{ticker}"
    headers = _sign_request("GET", path) if _have_credentials() else {}
    resp = requests.get(BASE_URL.rsplit("/trade-api", 1)[0] + path, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_markets(series_ticker: str = None, status: str = "open", limit: int = 200) -> list:
    base = BASE_URL.rsplit("/trade-api", 1)[0] + "/trade-api/v2/markets"
    out, cursor = [], None
    while True:
        params = {"status": status, "limit": limit}
        if series_ticker:
            params["series_ticker"] = series_ticker
        if cursor:
            params["cursor"] = cursor
        headers = _sign_request("GET", "/trade-api/v2/markets") if _have_credentials() else {}
        resp = requests.get(base, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        out.extend(data.get("markets", []))
        cursor = data.get("cursor")
        if not cursor or not data.get("markets"):
            break
    return out


def quote_from_market(market: dict) -> dict:
    def c(v):
        return None if v is None else v / 100.0
    yes_bid, yes_ask = c(market.get("yes_bid")), c(market.get("yes_ask"))
    last = c(market.get("last_price"))
    buy_yes = yes_ask
    buy_no = None if yes_bid is None else round(1.0 - yes_bid, 4)
    if yes_bid is not None and yes_ask is not None:
        mid = round((yes_bid + yes_ask) / 2, 4)
    else:
        mid = last
    return {"ticker": market.get("ticker"), "last": last, "yes_bid": yes_bid,
            "yes_ask": yes_ask, "buy_yes": buy_yes, "buy_no": buy_no, "mid": mid,
            "status": market.get("status")}


def get_orderbook(ticker: str) -> dict:
    path = f"/trade-api/v2/markets/{ticker}/orderbook"
    headers = _sign_request("GET", path) if _have_credentials() else {}
    resp = requests.get(BASE_URL.rsplit("/trade-api", 1)[0] + path, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_quote(ticker: str) -> dict:
    market = get_market(ticker)["market"]
    def c(v):
        return None if v is None else v / 100.0
    yes_bid, yes_ask = c(market.get("yes_bid")), c(market.get("yes_ask"))
    last = c(market.get("last_price"))
    buy_yes = yes_ask
    buy_no = None if yes_bid is None else round(1.0 - yes_bid, 4)
    if yes_bid is not None and yes_ask is not None:
        mid = round((yes_bid + yes_ask) / 2, 4)
    else:
        mid = last
    return {"ticker": ticker, "last": last, "yes_bid": yes_bid, "yes_ask": yes_ask,
            "buy_yes": buy_yes, "buy_no": buy_no, "mid": mid,
            "status": market.get("status")}


def get_yes_price(ticker: str) -> float:
    q = get_quote(ticker)
    if q["mid"] is not None:
        return q["mid"]
    if q["last"] is not None:
        return q["last"]
    raise ValueError(f"No usable price for {ticker}: {q}")


def get_mock_price(base_prob: float = 0.55, noise: float = 0.03) -> float:
    import random
    return min(max(base_prob + random.uniform(-noise, noise), 0.01), 0.99)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        ticker = sys.argv[1]
        print(f"YES price for {ticker}: {get_yes_price(ticker):.3f}")
    else:
        print("No ticker given, using mock price:", get_mock_price())
