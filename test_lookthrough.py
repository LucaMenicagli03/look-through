"""Tests. Expected values come from an independent hand calculation (tolerance 0.01 USD million)."""
import math
from pathlib import Path

import pytest

import lookthrough as lt

DATA = Path(__file__).parent / "data"
P, H, O, L, S = lt.load(DATA)
TOL = 0.01


def run(shocks, scenario="base", variant="pro_rata", **kw):
    return lt.cascade(P, H, O, L, shocks, scenario, variant, **kw)


# (a) agreement with the hand calculation
def test_net_hand_check():
    n = lt.net(P, H, S["gross_core_usd_m"], S["extended_perimeters"])
    exp = {"core": (13960.00, 13673.97, 13705.68),
           "core+USDtb": (14308.30, 13676.55, 13708.26),
           "core+USDtb+USDGO": (15390.02, 13826.41, 13858.12)}
    for k, (g, lo, hi) in exp.items():
        assert n[k]["gross"] == pytest.approx(g, abs=TOL)
        assert n[k]["net_low"] == pytest.approx(lo, abs=TOL)
        assert n[k]["net_high"] == pytest.approx(hi, abs=TOL)


def test_cascade_ousg_30_base_prorata():
    c = run({"OUSG": 0.30})
    assert c["total_demand"] == pytest.approx(93.996, abs=TOL)
    assert c["own_liquidity_paid"]["OUSG"] == pytest.approx(1.095, abs=TOL)
    exp = {"SWEEP": (45.603, 28.43, 17.173), "BUIDL": (30.693, 30.693, 0.0),
           "BENJI": (9.513, 0.0, 9.513), "FYOXX": (7.092, 0.0, 7.092)}
    for f, (r, used, res) in exp.items():
        assert c["funds"][f]["request"] == pytest.approx(r, abs=TOL)
        assert c["funds"][f]["liquidity_used"] == pytest.approx(used, abs=TOL)
        assert c["funds"][f]["residual_t1"] == pytest.approx(res, abs=TOL)
    assert c["immediate_total"] == pytest.approx(60.218, abs=TOL)
    assert c["t1_total"] == pytest.approx(33.778, abs=TOL)


def test_cascade_ousg_30_base_liquid_first():
    c = run({"OUSG": 0.30}, variant="liquid_first")
    assert c["own_liquidity_paid"]["OUSG"] == pytest.approx(3.65, abs=TOL)
    exp = {"SWEEP": 44.349, "BUIDL": 29.849, "BENJI": 9.251, "FYOXX": 6.897}
    for f, r in exp.items():
        assert c["funds"][f]["request"] == pytest.approx(r, abs=TOL)
    assert c["immediate_total"] == pytest.approx(61.929, abs=TOL)
    assert c["t1_total"] == pytest.approx(32.067, abs=TOL)


def test_usdtb_30_base():
    c = run({"USDtb": 0.30})
    b = c["funds"]["BUIDL"]
    assert b["request"] == pytest.approx(103.716, abs=TOL)
    assert b["coverage"] == pytest.approx(75 / 103.716, abs=1e-4)


# (b) conservation: every dollar requested is paid now, settles T+1 or falls off-map
@pytest.mark.parametrize("holder", ["OUSG", "USDtb", "USDGO"])
@pytest.mark.parametrize("variant", lt.VARIANTS)
@pytest.mark.parametrize("scenario", lt.SCENARIOS)
def test_conservation(holder, variant, scenario):
    c = run({holder: 0.30}, scenario, variant)
    funds = sum(f["request"] for f in c["funds"].values())
    assert funds + sum(c["own_liquidity_paid"].values()) + c["outside_total"] == pytest.approx(c["total_demand"], abs=1e-9)
    assert c["immediate_total"] + c["t1_total"] + c["outside_total"] == pytest.approx(c["total_demand"], abs=1e-9)


# (c) requests are monotone in the shock size
@pytest.mark.parametrize("holder", ["OUSG", "USDtb", "USDGO"])
@pytest.mark.parametrize("variant", lt.VARIANTS)
def test_monotone(holder, variant):
    prev = None
    for s in (0.0, 0.1, 0.3, 0.5, 1.0):
        c = run({holder: s}, "base", variant)
        cur = {f: v["request"] for f, v in c["funds"].items()}
        if prev:
            for f in cur:
                assert cur[f] >= prev.get(f, 0.0) - 1e-12
        prev = cur


# (d) coverage stays in [0, 1] and is undefined (None) when nothing is requested
def test_coverage_range_and_zero_request():
    for holder in ("OUSG", "USDtb", "USDGO"):
        for s in lt.SHOCKS:
            for sc in lt.SCENARIOS:
                for v in lt.VARIANTS:
                    for f in run({holder: s}, sc, v)["funds"].values():
                        assert 0.0 <= f["coverage"] <= 1.0
    c = run({"OUSG": 0.0})
    assert all(f["coverage"] is None for f in c["funds"].values())
    assert c["immediate_share"] is None


# (e) zero liquidity -> coverage 0; infinite liquidity -> coverage 1
def test_liquidity_extremes():
    funds = ["BUIDL", "SWEEP", "BENJI", "FYOXX", "JLTXX"]
    zero = run({"OUSG": 0.3}, liq_override={f: 0.0 for f in funds})
    assert all(f["coverage"] == 0.0 for f in zero["funds"].values())
    inf = run({"OUSG": 0.3}, liq_override={f: math.inf for f in funds})
    assert all(f["coverage"] == 1.0 for f in inf["funds"].values())


# (f) two holders hitting the same fund never use its liquidity twice
def test_shared_liquidity():
    c = run({"OUSG": 0.30, "USDtb": 0.30})
    b = c["funds"]["BUIDL"]
    assert b["request"] == pytest.approx(134.409, abs=TOL)
    assert b["liquidity_used"] == pytest.approx(75.0, abs=TOL)
    assert b["coverage"] == pytest.approx(75 / 134.409, abs=1e-4)
    assert sum(o["immediate"] for o in b["by_origin"].values()) == pytest.approx(75.0, abs=TOL)


def test_shared_pool_across_funds():
    liq = [{"product_id": "A", "facility": "pool", "amount": 10.0, "scenario": "base"},
           {"product_id": "B", "facility": "pool", "amount": 10.0, "scenario": "base"}]
    prod = {k: {"supply": 100.0, "in_core": True} for k in ("A", "B", "X")}
    hold = [{"holder_id": "X", "asset_id": "A", "amount": 50.0}, {"holder_id": "X", "asset_id": "B", "amount": 50.0}]
    c = lt.cascade(prod, hold, [], liq, {"X": 0.5}, "base", "pro_rata")
    assert sum(f["liquidity_used"] for f in c["funds"].values()) == pytest.approx(10.0)


# graph
def test_acyclic_real_and_fake():
    assert lt.check_acyclic(H)
    cyc = [{"holder_id": "A", "asset_id": "B"}, {"holder_id": "B", "asset_id": "A"}]
    assert not lt.check_acyclic(cyc)
    with pytest.raises(ValueError):
        lt.cascade({}, [dict(c, amount=1.0) for c in cyc], [], [], {"A": 0.1}, "base", "pro_rata")


def test_wrapper_two_levels():
    # S holds wrapper W (40) and fund F (60); W holds F (100) and has 5 of cash
    prod = {k: {"supply": 1000.0, "in_core": True} for k in ("S", "W", "F")}
    hold = [{"holder_id": "S", "asset_id": "W", "amount": 40.0}, {"holder_id": "S", "asset_id": "F", "amount": 60.0},
            {"holder_id": "W", "asset_id": "F", "amount": 100.0}]
    liq = [{"product_id": "W", "facility": "w_cash", "amount": 5.0, "scenario": "base"},
           {"product_id": "F", "facility": "f", "amount": 0.0, "scenario": "base"}]
    c = lt.cascade(prod, hold, [], liq, {"S": 0.5}, "base", "pro_rata")
    # S asks W for 20 and F for 30; W absorbs 5 and passes 15 on to F
    assert c["own_liquidity_paid"]["W"] == pytest.approx(5.0)
    assert c["funds"]["F"]["request"] == pytest.approx(45.0)


# data integrity: every number on the page must trace to a sourced, dated row
def test_data_integrity():
    ok = {"VERIFIED", "DERIVED", "ASSUMPTION"}
    for p in P.values():
        assert p["status"] in ok and p["source_url"].startswith("https://") and p["as_of"] and p["supply"] > 0
    for h in H:
        assert h["holder_id"] in P and h["asset_id"] in P
        assert h["status"] in ok and h["source_url"].startswith("https://") and h["as_of"]
        assert h["amount"] > 0 and h["amount_high"] >= h["amount"]
        assert h["counted_in_gross"] in {"yes", "no", "unknown"}
        assert h["method"] in {"issuer_disclosure", "onchain"}
    for o in O:
        assert o["holder_id"] in P and o["status"] in ok and o["source_url"].startswith("https://")
    by = {}
    for l in L:
        assert l["status"] in ok and l["source_url"].startswith("https://") and l["amount"] >= 0
        by.setdefault(l["product_id"], {})[l["scenario"]] = l["amount"]
    assert set(by) == set(P)
    for prod, sc in by.items():
        assert set(sc) == set(lt.SCENARIOS)
        assert sc["low"] <= sc["base"] <= sc["high"]


def test_mapped_reserves_do_not_exceed_supply_by_much():
    # a holder's mapped reserves should be close to its supply (sanity check on the inputs)
    liq = {l["product_id"]: l["amount"] for l in L if l["scenario"] == "base"}
    for holder in ("OUSG", "USDtb", "USDGO"):
        total = sum(h["amount"] for h in H if h["holder_id"] == holder) \
            + sum(o["amount"] for o in O if o["holder_id"] == holder) + liq[holder]
        assert abs(total / P[holder]["supply"] - 1) < 0.01


def test_build_output_is_complete():
    d = lt.build(DATA)
    assert d["acyclic"] is True
    assert len(d["cascades"]) == 3 * len(lt.SHOCKS) * len(lt.SCENARIOS) * len(lt.VARIANTS)
    assert set(d["net"]) == {"core", "core+USDtb", "core+USDtb+USDGO"}


# C1: a fund with two supply figures on the snapshot day gives a share range, never a single number
def test_sweep_share_is_a_range():
    d = lt.build(DATA)
    c = next(x for x in d["concentration"] if x["holder"] == "OUSG" and x["asset"] == "SWEEP")
    assert c["share_low"] == pytest.approx(152.01 / 334.30, abs=1e-4)
    assert c["share_high"] == pytest.approx(152.01 / 284.34, abs=1e-4)
    for x in d["concentration"]:
        assert x["share_low"] <= x["share_high"]
        if not P[x["asset"]]["supply_alt"]:
            assert x["share_low"] == x["share_high"] == x["share_of_asset_supply"]


# C2: every on-chain balance links to the explorer pages it was read from
def test_onchain_rows_have_explorer_links():
    for h in H:
        urls = h["balance_source_urls"].split()
        if h["method"] == "onchain":
            assert urls and all(u.startswith("https://") for u in urls)
        else:
            assert not urls
