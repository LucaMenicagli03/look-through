# Look-Through

**Who holds whom among tokenized US Treasury funds, how big the market really is once double counting is removed, and who is left waiting in a redemption run.**

Live page: **https://look-through-hazel.vercel.app** · Snapshot: 16 November 2026 · Public data only

---

## Why this exists

Tokenized US Treasury and money-market funds are a market of about USD 14 billion. These products don't sit side by side: they sit inside each other.

- **Funds of funds.** Ondo's OUSG doesn't buy Treasuries directly; it holds tokens of other funds (State Street's SWEEP, BlackRock's BUIDL, Franklin's BENJI, Fidelity's FYOXX).
- **Stablecoins.** USDtb and USDGO keep their reserves in BUIDL and in JPMorgan's JLTXX.

So the same dollar can appear in more than one product. Aggregators that add up every product count it twice, and nobody can see who depends on whom. The tokens also trade 24/7, while the funds behind them pay out only on business days. I couldn't find a public tool that maps these holdings, nets them out and stress-tests them together, so I built one.

## What the page answers

| Block | Question | What you see |
| --- | --- | --- |
| 1. Holdings map | Who holds whom? | 8 products, 7 holdings, each with amount, date and source |
| 2. Gross and net size | How big is the market without double counting? | Gross, net and the share counted twice, on three perimeters |
| 3. Redemption cascade | What happens in a run? | Pick a holder, a shock and a liquidity scenario; see per fund what is paid immediately and what waits for the next business day |

A methodology page lists every source, assumption and limit.

## Key findings (snapshot of 16 Nov 2026)

- **Double counting is small inside the fund market:** about **1.8%–2.0%** of USD 13.96 billion, all from funds holding other funds.
- **With the stablecoins backed by these funds, it rises to about 10%**, and over 80% of that comes from the stablecoins.
- **Concentration is the real story:** one stablecoin (USDGO) holds about **96%** of JPMorgan's tokenized fund (JLTXX); three mapped products hold about **39%** of BlackRock's BUIDL.
- **Timing:** a 30% run on USDGO would send about **USD 221 million** to JLTXX, **29% of the fund**, with no instant redemption channel, so all of it waits for the next business day.

This is an emerging concentration risk in a small sector, not a systemic one. Funds redeem at par: the risk measured is time, not price.

## How it works

```
data/*.csv + snapshot.json  →  lookthrough.py  →  site/data.json  →  site/ (static page)
```

1. **Data.** Five files in `data/`. Every row has a `source_url`, an `as_of` date and a `status`.
2. **Script.** `lookthrough.py` (Python standard library only) computes net size, checks the holdings graph for cycles and runs 54 cascade combinations (3 holders × 3 shocks × 3 liquidity scenarios × 2 redemption orders).
3. **Page.** A static HTML/JavaScript site reads only `site/data.json`. No number is typed into the HTML.

### Data provenance

| Status | Meaning |
| --- | --- |
| `VERIFIED` | Read at the cited source on the as-of date |
| `DERIVED` | Product of two issuer-disclosed figures (e.g. reserve share × supply) |
| `ASSUMPTION` | Declared scenario input where no figure is public |

- **Holdings** come from issuer disclosures (Ondo's portfolio table, USDGO's transparency page) or from on-chain balances **only at reserve addresses the issuer itself names** in its attestations.
- **Gross market size** is rwa.xyz's "Distributed Value" for tokenized US Treasury funds.

### Method in brief

- **Netting.** A holding is netted out only if both the holder and the fund are inside the gross total *and* the holding is in tokens counted there. Where the issuer doesn't disclose the form, net is shown as a range.
- **Extended perimeters.** Each stablecoin's supply is added to the gross, then its holdings of core funds are netted out.
- **Cascade.** A holder loses a share *s* of its supply and redeems *s* times its reserves (pro rata, or cash first). Each fund pays immediately up to the liquidity available in the scenario; the rest settles on the next business day (T+1). Shared liquidity is used once and split pro rata.
- **Liquidity.** Only what actually pays that fund's redemptions counts: for BUIDL, the stablecoin leg of the Securitize/Ethena facility (25 / 75 / 100 million in the low / base / high scenarios). SWEEP is parametric (0 / 10% / 25% of AUM). BENJI, FYOXX and JLTXX are set to zero: no 24/7 channel is documented.

## Limits

- Public wallet data attributes only about 36% of BUIDL and 0% of OUSG, which is why the map relies on issuer disclosures.
- Figures are a dated snapshot and are never rescaled; one day later the category total was up 1.7%.
- Stablecoin positions are lower bounds if undisclosed addresses exist.
- Some liquidity inputs are assumptions, all chosen on the conservative side.
- Open source discrepancies are shown, not resolved (FYOXX position vs token supply; two SWEEP sizes on the snapshot day).

The full list (15 items) is on the [methodology page](https://look-through-hazel.vercel.app/methodology.html).

## Repository structure

```
data/
  products.csv        products, supply, in-core flag, source
  holdings.csv        who holds whom, amount, counted-in-gross flag, source
  other_reserves.csv  reserves outside the map
  liquidity.csv       immediate liquidity per fund and scenario
  snapshot.json       snapshot date, gross total, limits
lookthrough.py        netting, cycle check, cascade
test_lookthrough.py   tests
site/                 static page (index.html, methodology.html, data.json)
```

## Run it locally

```bash
python3 -m pip install pytest
python3 -m pytest -q                      # 39 tests
python3 lookthrough.py data site/data.json
cd site && python3 -m http.server 8000    # http://localhost:8000
```

The tests compare the script with an independent hand calculation (tolerance USD 0.01 million) and check conservation, monotonicity in the shock size, coverage bounds, shared liquidity, a two-level wrapper case and data integrity.

## Verification log

- **16 Nov 2026:** all sources read (snapshot).
- **17 Nov 2026:** issuer attestations, USDGO transparency page, stablecoin supply, the Securitize/Ethena release, Galaxy's SWEEP terms, Ondo's portfolio table and the FDIT page re-opened and unchanged. The rwa.xyz category moved after the snapshot and was recorded, not updated.

## Disclaimer

Independent research based on public data. Not investment advice. Figures may contain errors; every number links to its source so it can be checked.

## License

[MIT](LICENSE) © 2026 Luca Menicagli
