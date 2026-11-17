"""Look-Through: netting and redemption cascade for tokenized Treasury funds.

Standard library only. Amounts are in USD millions.
Usage: python lookthrough.py [data_folder] [output.json]
"""
import csv
import json
import math
import sys
from pathlib import Path

SCENARIOS = ("low", "base", "high")
VARIANTS = ("pro_rata", "liquid_first")
SHOCKS = (0.10, 0.30, 0.50)


def _f(x, default=None):
    x = (x or "").strip()
    return float(x) if x else default


def load(folder):
    folder = Path(folder)

    def rows(name):
        with open(folder / name, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    products = {r["id"]: {**r, "supply": float(r["supply_usd_m"]), "in_core": r["in_core"] == "yes",
                          "supply_alt": _f(r.get("supply_alt_usd_m"))}
                for r in rows("products.csv")}
    holdings = []
    for r in rows("holdings.csv"):
        amount = float(r["amount_usd_m"])
        holdings.append({**r, "amount": amount, "amount_high": _f(r.get("amount_high_usd_m"), amount)})
    other = [{**r, "amount": float(r["amount_usd_m"])} for r in rows("other_reserves.csv")]
    liquidity = [{**r, "amount": float(r["amount_usd_m"])} for r in rows("liquidity.csv")]
    snapshot = json.loads((folder / "snapshot.json").read_text(encoding="utf-8"))
    return products, holdings, other, liquidity, snapshot


def net(products, holdings, gross_core, perimeters):
    """Gross, low net and high net for the core market and each extended perimeter.

    A holding reduces the net only if counted_in_gross is "yes"; if "unknown"
    it reduces the low net only; if "no" it never does. In an extended
    perimeter the stablecoin's supply is added to the gross before its
    holdings of core funds are netted out.
    """
    def deduction(holders_ok):
        low_dc = high_dc = 0.0  # minimum / maximum double count
        for h in holdings:
            if not holders_ok(h["holder_id"]) or not products[h["asset_id"]]["in_core"]:
                continue
            flag = h["counted_in_gross"]
            if flag == "yes":
                low_dc += h["amount"]
                high_dc += h["amount_high"]
            elif flag == "unknown":
                high_dc += h["amount_high"]
        return low_dc, high_dc

    out = {}
    lo, hi = deduction(lambda x: products[x]["in_core"])
    out["core"] = {"gross": gross_core, "net_low": gross_core - hi, "net_high": gross_core - lo,
                   "double_count_low": lo, "double_count_high": hi}
    for name, extra in perimeters.items():
        gross = gross_core + sum(products[e]["supply"] for e in extra)
        lo, hi = deduction(lambda x, extra=extra: products[x]["in_core"] or x in extra)
        out[name] = {"gross": gross, "net_low": gross - hi, "net_high": gross - lo,
                     "double_count_low": lo, "double_count_high": hi}
    return out


def check_acyclic(holdings):
    """True if the holder -> asset graph has no cycles."""
    graph = {}
    for h in holdings:
        graph.setdefault(h["holder_id"], set()).add(h["asset_id"])
    state = {}

    def visit(n):
        if state.get(n) == 1:
            return False
        if state.get(n) == 2:
            return True
        state[n] = 1
        for m in graph.get(n, ()):
            if not visit(m):
                return False
        state[n] = 2
        return True

    return all(visit(n) for n in list(graph))


def _liq(liquidity, scenario):
    """product_id -> (facility, amount) for the scenario."""
    return {r["product_id"]: (r["facility"], r["amount"]) for r in liquidity if r["scenario"] == scenario}


def cascade(products, holdings, other, liquidity, shocks, scenario, variant, liq_override=None):
    """Redemption cascade.

    shocks: {holder: s}, where s is the share of the holder's supply redeemed.
    Returns, per end fund, the redemption request, liquidity used (one pool
    per 'facility' string, shared pro rata), immediate coverage and the
    residual settling T+1 (next business day).
    liq_override: {product_id: amount}, used by the tests (0 or infinity).
    """
    if scenario not in SCENARIOS or variant not in VARIANTS:
        raise ValueError("unknown scenario or variant")
    if not check_acyclic(holdings):
        raise ValueError("the holdings graph has a cycle: cascade undefined")
    liq = _liq(liquidity, scenario)
    if liq_override:
        for k, v in liq_override.items():
            liq[k] = (liq.get(k, (k + "_override", 0.0))[0], v)
    by_holder = {}
    for h in holdings:
        by_holder.setdefault(h["holder_id"], []).append(h)
    other_by = {}
    for o in other:
        other_by.setdefault(o["holder_id"], []).append(o)

    requests = {}       # end fund -> {originating holder: amount}
    own_paid = {}       # node -> paid from its own liquidity
    outside = {}        # holder -> request falling on off-map reserves
    own_left = {k: v[1] for k, v in liq.items() if k in by_holder}

    def push(node, amount, origin, first_level):
        """Push a request onto a node; a node that holds funds absorbs, then propagates."""
        if amount <= 0:
            return
        if node not in by_holder:           # end fund
            requests.setdefault(node, {})
            requests[node][origin] = requests[node].get(origin, 0.0) + amount
            return
        funds = by_holder[node]
        fund_total = sum(h["amount"] for h in funds)
        others = other_by.get(node, [])
        other_total = sum(o["amount"] for o in others)
        cash = own_left.get(node, 0.0)
        if first_level and variant == "pro_rata":
            total = fund_total + other_total + liq.get(node, ("", 0.0))[1]
            k = amount / total
            pay_own = min(cash, k * liq.get(node, ("", 0.0))[1])
        else:
            # "most liquid asset first" variant, and always for downstream wrappers
            pay_own = min(cash, amount)
            k = (amount - pay_own) / (fund_total + other_total)
        own_left[node] = cash - pay_own
        own_paid[node] = own_paid.get(node, 0.0) + pay_own
        if other_total:
            outside[node] = outside.get(node, 0.0) + k * other_total
        for h in funds:
            push(h["asset_id"], k * h["amount"], origin, False)

    demand = {}
    for holder, s in shocks.items():
        if not 0 <= s <= 1:
            raise ValueError("s must be between 0 and 1")
        total = (sum(h["amount"] for h in by_holder.get(holder, []))
                 + sum(o["amount"] for o in other_by.get(holder, []))
                 + liq.get(holder, ("", 0.0))[1])
        demand[holder] = s * total
        push(holder, s * total, holder, True)

    # shared liquidity pools: same facility string = same pool, split pro rata
    pool_req = {}
    for fund, parts in requests.items():
        fac = liq.get(fund, (fund + "_none", 0.0))[0]
        pool_req[fac] = pool_req.get(fac, 0.0) + sum(parts.values())
    pool_amt = {}
    for fund in requests:
        fac, amt = liq.get(fund, (fund + "_none", 0.0))
        pool_amt[fac] = amt

    funds_out = {}
    for fund, parts in requests.items():
        r = sum(parts.values())
        fac = liq.get(fund, (fund + "_none", 0.0))[0]
        tot = pool_req[fac]
        avail = pool_amt[fac]
        if r <= 0:
            used, cov = 0.0, None
        elif math.isinf(avail):
            used, cov = r, 1.0
        else:
            used = min(avail, tot) * (r / tot)
            cov = max(0.0, min(1.0, used / r))
        funds_out[fund] = {
            "request": r, "liquidity_available": avail, "liquidity_used": used,
            "coverage": cov, "residual_t1": r - used,
            "request_over_aum": r / products[fund]["supply"] if fund in products else None,
            "by_origin": {o: {"request": v, "immediate": (used * v / r) if r > 0 else 0.0}
                          for o, v in parts.items()},
        }
    total_demand = sum(demand.values())
    immediate = sum(own_paid.values()) + sum(f["liquidity_used"] for f in funds_out.values())
    return {
        "shocks": shocks, "scenario": scenario, "variant": variant,
        "demand": demand, "total_demand": total_demand,
        "own_liquidity_paid": own_paid, "outside_map": outside,
        "funds": funds_out, "immediate_total": immediate,
        "immediate_share": (immediate / total_demand) if total_demand > 0 else None,
        "t1_total": sum(f["residual_t1"] for f in funds_out.values()),
        "outside_total": sum(outside.values()),
    }


def build(folder):
    products, holdings, other, liquidity, snapshot = load(folder)
    holders = sorted({h["holder_id"] for h in holdings})
    cascades = []
    for holder in holders:
        for s in SHOCKS:
            for sc in SCENARIOS:
                for v in VARIANTS:
                    cascades.append(cascade(products, holdings, other, liquidity, {holder: s}, sc, v))
    def share_range(amount, asset):
        """Share of a fund's supply; a range when the source gives two supply figures."""
        sizes = [products[asset]["supply"]] + ([products[asset]["supply_alt"]] if products[asset]["supply_alt"] else [])
        return amount / max(sizes), amount / min(sizes)

    concentration = []
    for h in holdings:
        share = h["amount"] / products[h["asset_id"]]["supply"]
        low, high = share_range(h["amount"], h["asset_id"])
        # a share above 100% means the two sources disagree: flag it, never headline it
        concentration.append({"holder": h["holder_id"], "asset": h["asset_id"],
                              "share_of_asset_supply": share,
                              "share_low": low, "share_high": high,
                              "source_mismatch": share > 1.0,
                              "counted_in_gross": h["counted_in_gross"]})
    mapped = {}
    for h in holdings:
        mapped[h["asset_id"]] = mapped.get(h["asset_id"], 0.0) + h["amount"]
    mapped_share = {}
    for a, v in mapped.items():
        low, high = share_range(v, a)
        mapped_share[a] = {"mapped_holdings": v, "holders": sum(1 for h in holdings if h["asset_id"] == a),
                           "share_of_asset_supply": v / products[a]["supply"], "share_low": low, "share_high": high}
    return {
        "snapshot": snapshot,
        "products": list(products.values()),
        "holdings": holdings, "other_reserves": other, "liquidity": liquidity,
        "acyclic": check_acyclic(holdings),
        "net": net(products, holdings, snapshot["gross_core_usd_m"], snapshot["extended_perimeters"]),
        "concentration": concentration,
        "mapped_share": mapped_share,
        "cascades": cascades,
    }


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else "data"
    target = sys.argv[2] if len(sys.argv) > 2 else "data.json"
    data = build(folder)
    Path(target).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for name, n in data["net"].items():
        print(f"{name}: gross {n['gross']:.2f}  net {n['net_low']:.2f} - {n['net_high']:.2f}")
    print("acyclic:", data["acyclic"], "| cascades:", len(data["cascades"]), "->", target)
