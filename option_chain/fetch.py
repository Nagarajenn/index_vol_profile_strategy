from dhan_client.client import fetch_expiry_list, fetch_option_chain


def get_nearest_expiry(symbol_key: str) -> str:
    expiries = fetch_expiry_list(symbol_key)
    if not expiries:
        raise ValueError(f"No expiries returned for {symbol_key}")
    return sorted(expiries)[0]


def get_option_chain(symbol_key: str, expiry: str | None = None) -> dict:
    expiry = expiry or get_nearest_expiry(symbol_key)
    chain = fetch_option_chain(symbol_key, expiry)
    return {"expiry": expiry, **chain}
