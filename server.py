#!/usr/bin/env python3
"""Eclipse Strike MCP — v0.1.0, phase M0 (Coinbase public-data
adapter, Wing A).

Powered by Cyan Eclipse Technologies (cetech.ai).

Descriptor: Eclipse Strike — the Coinbase exchange adapter:
the price at which a trade executes, normalized into the
suite's one book.

WRAP POSTURE (spec section 10.1, stated in the README too):
Coinbase ships official MCPs of its own — a remote account-
trading MCP, a Wallet MCP (the DeFi suite's concern), and a
CDP MCP. Strike does NOT re-implement any of them. At M1+ the
account paths are a governed WRAP of the vendor's account MCP
(Orbit precedent: subsetting, drift halt, receipts). Strike
itself, here at M0, is the public-DATA adapter over Coinbase's
public market-data shapes: deterministic, cacheable, and
requiring no account session. NO ACCOUNT TOOLS EXIST in this
build — balances, orders, and transfers belong to the future
wrap, behind the core's T2 gate and the owner's credentials,
neither of which is present here.

One chapter, one upstream (spec 10.1 three-MCP rule): Strike's
capability record names the public data surface only; anything
arriving from the vendor's account/wallet/CDP surfaces is
out-of-scope here.

TRANSPORT SEAM (M0 fixture form): reads run against fixtures
shaped like the real Coinbase public product/book responses,
behind load_fixtures(). Live public reads are a later
verification step, labeled not_tested. No network calls exist
in this build. No accounts, no keys — there is nothing here a
key could unlock.

Core seam: normalization runs through Eclipse Book's
book_engine against the SHARED suite state ($ECLIPSE_BOOK_STATE
or the Book core's data/state.json), loaded fresh per call —
the same canonical builders Forecast uses, which is what makes
cross-adapter parity a testable property rather than a hope.

M0 SCOPE: fixtures only. No certification claimed — bench
pending.

Transport: MCP over stdio, stdlib only.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
CORE_DIR = HERE.parent / "eclipse-book-mcp"
sys.path.insert(0, str(CORE_DIR))

import book_engine as eng  # noqa: E402
from book_engine import ToolError  # noqa: E402

VENUE = "coinbase"

# Coinbase native product status -> core lifecycle. Anything
# outside this map surfaces as UNMAPPED with the native string
# preserved (spec 5.2), never coerced to the nearest state.
COINBASE_STATUS_MAP = {"online": "OPEN"}


def fixture_dir() -> Path:
    return Path(os.environ.get(
        "ECLIPSE_STRIKE_FIXTURES", HERE / "fixtures"))


def load_fixtures() -> dict:
    d = fixture_dir()
    return {
        "products": json.loads(
            (d / "coinbase_products.json").read_text())["products"],
        "books": json.loads(
            (d / "coinbase_books.json").read_text())["books"]}


def core_state_path() -> Path:
    return Path(os.environ.get(
        "ECLIPSE_BOOK_STATE", CORE_DIR / "data" / "state.json"))


def load_core_state() -> dict:
    path = core_state_path()
    if path.exists():
        return json.loads(path.read_text())
    state = eng.empty_state()
    seed = json.loads((CORE_DIR / "fixtures.json").read_text())
    eng.ensure_seeded(state, seed)
    save_core_state(state)
    return state


def save_core_state(state: dict) -> None:
    path = core_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1))


# ------------------------------------------------------------- translation
def parse_coinbase_product(native: dict) -> dict:
    """Coinbase product -> canonical Instrument spec."""
    status = native.get("status")
    return {
        "venue": VENUE, "native_id": native["product_id"],
        "native_symbol": native["product_id"],
        "kind": "SPOT", "title": native.get(
            "display_name", native["product_id"]),
        "underlying": native.get("base_currency_id"),
        "tick": native.get("quote_increment", "0.01"),
        "min_size": native.get("base_increment", "0.00000001"),
        "currency": native.get("quote_currency_id", "USD"),
        "money_class": "REAL",
        "native_status": status,
        "status_mapped": COINBASE_STATUS_MAP.get(status),
        "provenance": {"feed": "coinbase-public-fixture",
                       "fetched_at": "2026-10-25T12:00:00Z",
                       "data_rights": {
                           "source": "Coinbase public market data "
                                     "(fixture-shaped in M0)",
                           "basis": "account-holder consumption, "
                                    "no redistribution (spec 6)",
                           "method": "fixture file behind the "
                                     "transport seam",
                           "retention": "operational snapshots; "
                                        "own ledger permanent"}}}


def parse_coinbase_book(native_book: dict, instrument_id: str) -> dict:
    """Coinbase level-2 shape ([price, size, orders] arrays) ->
    canonical Book via the core builder — the same builder
    Forecast's CLOB parser uses (parity by construction)."""
    bids = [{"price": lv[0], "size": lv[1]}
            for lv in native_book.get("bids", [])]
    asks = [{"price": lv[0], "size": lv[1]}
            for lv in native_book.get("asks", [])]
    return eng.build_book(
        instrument_id, VENUE, "CLOB", bids, asks,
        native_book["time"], tick="0.01",
        native_ref=native_book.get("sequence"))


# ------------------------------------------------------------------- tools
def _sync(state):
    done = state.setdefault("adapter_syncs", {}).setdefault(
        "strike", [])
    if "base" in done:
        return {"synced": [], "already_synced": True}
    fx = load_fixtures()
    synced = []
    for native in fx["products"]:
        result = eng.ingest_instrument(state,
                                       parse_coinbase_product(native))
        inst = result["instrument"]
        synced.append(inst["instrument_id"])
        native_book = fx["books"].get(native["product_id"])
        if native_book is not None:
            eng.ingest_book(state, parse_coinbase_book(
                native_book, inst["instrument_id"]))
    done.append("base")
    return {"synced": synced, "count": len(synced)}


def t_product_list(state, args):
    _sync(state)
    out = [{"instrument_id": i["instrument_id"], "title": i["title"],
            "status": i["status"], "native_status": i["native_status"],
            "money_class": i["money_class"]}
           for i in state["instruments"].values()
           if i["venue"] == VENUE]
    return {"products": out, "count": len(out)}


def t_product_get(state, args):
    _sync(state)
    inst = state["instruments"].get(args["instrument_id"])
    if inst is None or inst["venue"] != VENUE:
        raise ToolError(f"PRODUCT_NOT_FOUND: {args['instrument_id']}")
    return {"product": eng.guard_no_probability(inst)}


def t_book_get(state, args):
    _sync(state)
    return {"book": eng.get_book(state, args["instrument_id"])}


def t_quote_get(state, args):
    _sync(state)
    return {"quote": eng.quote_get(
        state, args["instrument_id"], args["size"],
        as_of=args.get("as_of"))}


def t_venue_status(state, args):
    _sync(state)
    status = eng.venue_status(state, VENUE, as_of=args.get("as_of"))
    status["transport"] = "fixtures (Coinbase public-data " \
                          "shaped); live public reads not_tested in M0"
    status["account_surface"] = "ABSENT — M1+ governed wrap of " \
                                "the vendor account MCP (spec 10.1)"
    return status


def t_receipt_list(state, args):
    limit = args.get("limit")
    receipts = state["receipts"]
    if limit is not None:
        receipts = receipts[-int(limit):]
    return {"receipts": receipts, "count": len(state["receipts"]),
            "chain_valid": eng.verify_receipt_chain(state["receipts"])}


_P_INSTRUMENT = {"type": "string", "description": "Canonical instrument id as returned by product_list, for a Coinbase spot product. Must belong to the Coinbase venue; other venues' ids fail with PRODUCT_NOT_FOUND."}
_P_AS_OF = {"type": "string", "description": "Optional ISO-8601 timestamp used for fee-schedule freshness evaluation, e.g. '2026-10-25T13:00:00Z'. Omit to evaluate against the fixture clock."}

TOOLS = {
    "product_list": (
        t_product_list,
        "List Coinbase spot products as canonical Instruments, with mapped status and the native Coinbase status preserved (a native status with no mapping surfaces as UNMAPPED, never coerced). Use this first to discover instrument_id values for product_get, book_get, and quote_get. Behaviour: read-only over fixture data shaped like the Coinbase public market-data API; no network calls, no account, no API key — no account surface (balances, orders, transfers) exists in this build at all. Returns {products: [{instrument_id, title, status, native_status, money_class}], count}.",
        {}, []),
    "product_get": (
        t_product_get,
        "Fetch one Coinbase spot product as a full canonical Instrument (tick, minimum size, currency, status mapping, provenance). Use this for one product's exact terms; use product_list to browse or discover ids, and book_get for order-book depth. Behaviour: read-only, fixture data only, no auth. Returns {product: <instrument>}; an unknown or non-Coinbase instrument_id fails with PRODUCT_NOT_FOUND.",
        {"instrument_id": _P_INSTRUMENT}, ["instrument_id"]),
    "book_get": (
        t_book_get,
        "Fetch the canonical order book for one Coinbase spot product: bid/ask levels, computed spread, and a depth summary. Use this to judge liquidity and spread; use quote_get instead when you need the all-in cost at a specific size. Behaviour: read-only, fixture data only, no auth. Returns {book: <levels, spread, depth summary>}.",
        {"instrument_id": _P_INSTRUMENT}, ["instrument_id"]),
    "quote_get": (
        t_quote_get,
        "Price one Coinbase spot product at a stated size: bid/ask, computed mid, all-in cost taken from the venue's dated fee schedule, and a liquidity flag. Use this for a size-aware executable price; use book_get for raw levels. If the fee schedule is stale at the evaluation time the quote reports FEE_UNVERIFIED instead of inventing a fee. Behaviour: read-only, fixture data only, no auth, and no order is placed — this server has no trading tools. Returns {quote: <bid/ask/mid, all-in cost, liquidity flag>}.",
        {"instrument_id": _P_INSTRUMENT,
         "size": {"type": "string", "description": "Size to price, as a decimal string in base-currency units, e.g. '0.5'. Required; the quote walks the book to this size, so larger sizes can change the price and liquidity flag."}, "as_of": _P_AS_OF},
        ["instrument_id", "size"]),
    "venue_status": (
        t_venue_status,
        "Report this Coinbase adapter's health plus its standing capability record, including account_surface = ABSENT in this build (account access is a future governed wrap, not part of this server). Use this to confirm what this build can and cannot do before relying on its data; it returns no product data — use product_list for that. Behaviour: read-only, no auth. Returns the venue status object extended with transport ('fixtures (Coinbase public-data shaped); live public reads not_tested in M0') and the account_surface statement.",
        {"as_of": _P_AS_OF}, []),
    "receipt_list": (
        t_receipt_list,
        "List receipts from the shared Eclipse Book suite ledger (hash-chained) as this adapter sees it, with a chain-validity check. Use this to audit what the shared core state recorded across adapters; it is not market data — use product_list or book_get for that. Behaviour: read-only, no auth. Returns {receipts: [...], count: <total receipts in ledger>, chain_valid: <bool>}; when limit is given, receipts holds only the most recent entries while count still reports the full total.",
        {"limit": {"type": "integer", "description": "Optional maximum number of most-recent receipts to return, e.g. 10. Omit to return the entire ledger."}}, []),
}

# Capability denylist, stated in code (spec 10.1): NO account
# tools exist in Strike at M0. Account anything belongs to the
# future governed wrap, behind vault credentials and the core
# T2 gate — not to a public-data adapter.
FORBIDDEN_TOOL_NAMES = {
    "account_get", "accounts_list", "account_summary",
    "balance_get", "balances_list", "place_order", "order_place",
    "buy", "sell", "withdraw", "withdraw_funds", "transfer",
    "transfer_funds", "deposit", "create_api_key", "api_key_list",
    "margin_open", "futures_trade",
}


def tool_list():
    return [{"name": name, "description": description,
             "inputSchema": {"type": "object", "properties": props,
                             "required": required}}
            for name, (_, description, props, required) in TOOLS.items()]


def handle(req: dict):
    method, rid = req.get("method", ""), req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": req.get("params", {}).get(
                "protocolVersion", "2025-03-26"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "eclipse-strike",
                           "version": "0.1.0"}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid,
                "result": {"tools": tool_list()}}
    if method == "tools/call":
        name = req["params"]["name"]
        args = req["params"].get("arguments", {})
        if name in FORBIDDEN_TOOL_NAMES or name not in TOOLS:
            return {"jsonrpc": "2.0", "id": rid, "error": {
                "code": -32602,
                "message": f"unknown or line-forbidden tool {name}"}}
        state = load_core_state()
        try:
            out = TOOLS[name][0](state, args)
            save_core_state(state)
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps(out, indent=1)}]}}
        except ToolError as exc:
            save_core_state(state)
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps({"error": str(exc)})}],
                "isError": True}}
    if rid is not None:
        return {"jsonrpc": "2.0", "id": rid, "error": {
            "code": -32601, "message": f"method not found: {method}"}}
    return None


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            response = handle(json.loads(line))
        except Exception as exc:  # never crash the transport
            response = {"jsonrpc": "2.0", "id": None, "error": {
                "code": -32603, "message": str(exc)}}
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
