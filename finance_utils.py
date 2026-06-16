"""
Funzioni di supporto per l'app di analisi finanziaria.
Download dati (yfinance) + calcolo indicatori tecnici e fondamentali.
Nessuna dipendenza da TA-Lib: gli indicatori sono calcolati con pandas/numpy.
"""

import os
import json
import math
import datetime

import numpy as np
import pandas as pd
import yfinance as yf
import streamlit as st


# ---------------------------------------------------------------------------
# DOWNLOAD DATI
# ---------------------------------------------------------------------------

_PERIOD_DAYS = {"5d": 8, "1mo": 31, "3mo": 93, "6mo": 186, "1y": 372,
                "2y": 744, "5y": 1860, "max": 0}


def _fmp_history(ticker: str, period: str):
    """Storico prezzi giornaliero da FMP (OHLCV). Ritorna DataFrame stile yfinance."""
    days = _PERIOD_DAYS.get(period, 372)
    path = f"historical-price-eod/full?symbol={ticker}"
    if days:
        frm = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        path += f"&from={frm}"
    data = _fmp_get(path)
    if not isinstance(data, list) or not data:
        return None
    df = pd.DataFrame(data)
    if df.empty or "date" not in df.columns or "close" not in df.columns:
        return None
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")
    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low",
                            "close": "Close", "volume": "Volume"})
    cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    out = df[cols]
    return out[out["Close"].notna()]   # mai righe senza prezzo di chiusura


@st.cache_data(ttl=900, show_spinner=False)
def get_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """Storico prezzi. Fonte primaria: FMP (affidabile dal cloud). Riserva: yfinance."""
    if _fmp_key():
        try:
            df = _fmp_history(ticker, period)
            if df is not None and not df.empty:
                return df
        except Exception:
            pass
    try:
        df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.dropna(how="all")
    if "Close" in df.columns:
        df = df[df["Close"].notna()]   # elimina l'eventuale riga finale senza prezzo (yfinance)
    return df


@st.cache_data(ttl=900, show_spinner=False)
def get_info(ticker: str) -> dict:
    """Metadati/fondamentali. Catena di riserva: FMP → Finnhub → SEC EDGAR (USA) → yfinance."""
    if _fmp_key():
        fmp = info_from_fmp(ticker)
        if fmp:
            return fmp
    if _finnhub_key():
        fh = info_from_finnhub(ticker)
        if fh and len(fh) > 3:
            return fh
    sec = fundamentals_from_sec(ticker)          # riserva ufficiale USA, senza chiave
    if sec and len(sec) > 3:                      # ha davvero dei fondamentali, non solo il nome
        return sec
    try:
        return yf.Ticker(ticker).info or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# FONTE DATI ALTERNATIVA: Financial Modeling Prep (FMP)
# Yahoo blocca i dati di dettaglio dai server cloud → usiamo FMP come riserva.
# Chiave in st.secrets["fmp_api_key"] o env FMP_API_KEY. Se assente, solo yfinance.
# ---------------------------------------------------------------------------
FMP_BASE = "https://financialmodelingprep.com/stable"


def _fmp_key():
    try:
        k = st.secrets["fmp_api_key"]
        if k:
            return k
    except Exception:
        pass
    return os.environ.get("FMP_API_KEY", "")


@st.cache_data(ttl=900, show_spinner=False)
def _fmp_get(path: str):
    key = _fmp_key()
    if not key:
        return None
    import requests
    sep = "&" if "?" in path else "?"
    try:
        r = requests.get(f"{FMP_BASE}/{path}{sep}apikey={key}", timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
        if isinstance(data, dict) and ("Error Message" in data or "error" in data):
            return None
        return data
    except Exception:
        return None


def _first(data):
    return data[0] if isinstance(data, list) and data else {}


@st.cache_data(ttl=900, show_spinner=False)
def info_from_fmp(ticker: str) -> dict:
    """Costruisce un dict 'info' (chiavi stile yfinance) dai nuovi endpoint FMP /stable/."""
    prof = _first(_fmp_get(f"profile?symbol={ticker}"))
    if not prof:
        return {}
    r = _first(_fmp_get(f"ratios-ttm?symbol={ticker}"))
    m = _first(_fmp_get(f"key-metrics-ttm?symbol={ticker}"))
    g = _first(_fmp_get(f"financial-growth?symbol={ticker}&limit=1"))

    def num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    qt = "ETF" if prof.get("isEtf") else ("MUTUALFUND" if prof.get("isFund") else "EQUITY")
    info = {
        "longName": prof.get("companyName"),
        "shortName": prof.get("companyName"),
        "sector": prof.get("sector"),
        "industry": prof.get("industry"),
        "country": prof.get("country"),
        "currency": prof.get("currency"),
        "exchange": prof.get("exchange"),
        "marketCap": num(prof.get("marketCap")),
        "beta": num(prof.get("beta")),
        "currentPrice": num(prof.get("price")),
        "longBusinessSummary": prof.get("description"),
        "quoteType": qt,
    }
    rng = str(prof.get("range") or "")
    if "-" in rng:
        try:
            lo, hi = rng.split("-")
            info["fiftyTwoWeekLow"] = float(lo)
            info["fiftyTwoWeekHigh"] = float(hi)
        except Exception:
            pass
    info["trailingPE"] = num(r.get("priceToEarningsRatioTTM"))
    info["priceToBook"] = num(r.get("priceToBookRatioTTM"))
    info["pegRatio"] = num(r.get("priceToEarningsGrowthRatioTTM"))
    info["returnOnEquity"] = num(m.get("returnOnEquityTTM"))
    info["returnOnAssets"] = num(m.get("returnOnAssetsTTM"))
    info["profitMargins"] = num(r.get("netProfitMarginTTM"))
    info["operatingMargins"] = num(r.get("operatingProfitMarginTTM"))
    d2e = num(r.get("debtToEquityRatioTTM"))
    info["debtToEquity"] = d2e * 100 if d2e is not None else None  # ratio FMP → scala % (yfinance)
    info["currentRatio"] = num(r.get("currentRatioTTM"))
    info["quickRatio"] = num(r.get("quickRatioTTM"))
    dy = num(r.get("dividendYieldTTM"))                            # FMP: frazione (0.0035)
    info["dividendYield"] = dy * 100 if dy is not None else None   # → percento (come yfinance)
    info["payoutRatio"] = num(r.get("dividendPayoutRatioTTM"))
    info["revenueGrowth"] = num(g.get("revenueGrowth") or g.get("growthRevenue"))
    info["earningsGrowth"] = num(g.get("netIncomeGrowth") or g.get("growthNetIncome"))
    return {k: v for k, v in info.items() if v is not None}


# ---------------------------------------------------------------------------
# RISERVA 2: SEC EDGAR (bilanci ufficiali USA, senza chiave) — usata se FMP è
# esaurito/non disponibile. Copre solo aziende USA che depositano alla SEC.
# ---------------------------------------------------------------------------
_SEC_UA = {"User-Agent": "AnalisiFinanziaria - contatto ai@facco.net"}


@st.cache_data(ttl=86400, show_spinner=False)
def _sec_cik_map() -> dict:
    import requests
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json",
                          headers=_SEC_UA, timeout=20)
        if r.status_code != 200:
            return {}
        return {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in r.json().values()}
    except Exception:
        return {}


@st.cache_data(ttl=86400, show_spinner=False)
def _sec_companyfacts(cik: str) -> dict:
    import requests
    try:
        r = requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                          headers=_SEC_UA, timeout=25)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


def _sec_annual(units, n=1):
    """Valori annuali (10-K) più recenti, dal più nuovo."""
    recs = [x for x in units if x.get("val") is not None and str(x.get("form", "")).startswith("10-K")]
    recs = [x for x in recs if x.get("fp") == "FY"] or recs
    recs.sort(key=lambda x: x.get("end", ""), reverse=True)
    out, seen = [], set()
    for x in recs:
        e = x.get("end")
        if e in seen:
            continue
        seen.add(e)
        out.append(x["val"])
        if len(out) >= n:
            break
    return out


def _sec_instant(units):
    """Valore di bilancio (stato patrimoniale) più recente."""
    recs = [x for x in units if x.get("val") is not None]
    recs.sort(key=lambda x: x.get("end", ""), reverse=True)
    return recs[0]["val"] if recs else None


@st.cache_data(ttl=86400, show_spinner=False)
def fundamentals_from_sec(ticker: str) -> dict:
    cik = _sec_cik_map().get(ticker.upper())
    if not cik:
        return {}
    facts = _sec_companyfacts(cik)
    gaap = (facts.get("facts") or {}).get("us-gaap", {})
    dei = (facts.get("facts") or {}).get("dei", {})
    if not gaap:
        return {}

    def usd(concept):
        return (gaap.get(concept, {}).get("units", {}) or {}).get("USD", [])

    ni_l = _sec_annual(usd("NetIncomeLoss"), 1)
    ni = ni_l[0] if ni_l else None
    eq = _sec_instant(usd("StockholdersEquity"))
    assets = _sec_instant(usd("Assets"))
    rev_l = (_sec_annual(usd("RevenueFromContractWithCustomerExcludingAssessedTax"), 2)
             or _sec_annual(usd("Revenues"), 2))
    rev = rev_l[0] if rev_l else None
    rev_prev = rev_l[1] if len(rev_l) > 1 else None
    eps_l = _sec_annual((gaap.get("EarningsPerShareDiluted", {}).get("units", {}) or {}).get("USD/shares", []), 1)
    eps = eps_l[0] if eps_l else None
    debt = _sec_instant(usd("LongTermDebt"))
    if debt is None:
        ltc = _sec_instant(usd("LongTermDebtNoncurrent"))
        if ltc is not None:
            debt = ltc + (_sec_instant(usd("LongTermDebtCurrent")) or 0)
    shares = _sec_instant((dei.get("EntityCommonStockSharesOutstanding", {}).get("units", {}) or {}).get("shares", []))

    price = None
    h = get_history(ticker, period="5d")
    if not h.empty:
        closes = h["Close"].dropna()
        if not closes.empty:
            price = float(closes.iloc[-1])

    info = {"quoteType": "EQUITY",
            "shortName": facts.get("entityName") or ticker,
            "longName": facts.get("entityName")}
    if ni is not None and rev:
        info["profitMargins"] = ni / rev
    if ni is not None and eq and eq > 0:
        info["returnOnEquity"] = ni / eq
    if ni is not None and assets and assets > 0:
        info["returnOnAssets"] = ni / assets
    if debt is not None and eq and eq > 0:
        info["debtToEquity"] = debt / eq * 100
    if rev and rev_prev and rev_prev > 0:
        info["revenueGrowth"] = rev / rev_prev - 1
    if price and eps and eps > 0:
        info["trailingPE"] = price / eps
    if price and shares:
        info["marketCap"] = price * shares
        if eq and eq > 0:
            info["priceToBook"] = price * shares / eq
    return {k: v for k, v in info.items() if v is not None}


# ---------------------------------------------------------------------------
# RISERVA: FINNHUB (fondamentali TTM + notizie). Limite al minuto, raramente esaurito.
# Chiave in st.secrets["finnhub_api_key"] o env FINNHUB_API_KEY.
# ---------------------------------------------------------------------------
FINNHUB_BASE = "https://finnhub.io/api/v1"


def _finnhub_key():
    try:
        k = st.secrets["finnhub_api_key"]
        if k:
            return k
    except Exception:
        pass
    return os.environ.get("FINNHUB_API_KEY", "")


@st.cache_data(ttl=900, show_spinner=False)
def _finnhub_get(path: str):
    key = _finnhub_key()
    if not key:
        return None
    import requests
    sep = "&" if "?" in path else "?"
    try:
        r = requests.get(f"{FINNHUB_BASE}/{path}{sep}token={key}", timeout=15)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


@st.cache_data(ttl=900, show_spinner=False)
def info_from_finnhub(ticker: str) -> dict:
    prof = _finnhub_get(f"stock/profile2?symbol={ticker}") or {}
    mraw = _finnhub_get(f"stock/metric?symbol={ticker}&metric=all") or {}
    m = mraw.get("metric", {}) if isinstance(mraw, dict) else {}
    if not prof and not m:
        return {}

    def num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    def frac(x):                     # Finnhub dà percentuali (es. 146.69) → frazione
        v = num(x)
        return v / 100 if v is not None else None

    info = {"quoteType": "EQUITY"}
    if prof:
        info["longName"] = prof.get("name")
        info["shortName"] = prof.get("name")
        info["sector"] = prof.get("finnhubIndustry")
        info["industry"] = prof.get("finnhubIndustry")
        info["country"] = prof.get("country")
        info["currency"] = prof.get("currency")
        info["exchange"] = prof.get("exchange")
        mc = num(prof.get("marketCapitalization"))
        if mc is not None:
            info["marketCap"] = mc * 1e6        # Finnhub in milioni
    info["trailingPE"] = num(m.get("peTTM"))
    info["priceToBook"] = num(m.get("pbQuarterly") or m.get("pbAnnual"))
    info["returnOnEquity"] = frac(m.get("roeTTM"))
    info["returnOnAssets"] = frac(m.get("roaTTM"))
    info["profitMargins"] = frac(m.get("netProfitMarginTTM"))
    info["operatingMargins"] = frac(m.get("operatingMarginTTM"))
    d2e = num(m.get("totalDebt/totalEquityAnnual") or m.get("totalDebt/totalEquityQuarterly"))
    info["debtToEquity"] = d2e * 100 if d2e is not None else None
    info["currentRatio"] = num(m.get("currentRatioAnnual") or m.get("currentRatioQuarterly"))
    info["quickRatio"] = num(m.get("quickRatioAnnual"))
    info["dividendYield"] = num(m.get("dividendYieldIndicatedAnnual"))   # già percento (come yfinance)
    info["revenueGrowth"] = frac(m.get("revenueGrowthTTMYoy"))
    info["beta"] = num(m.get("beta"))
    info["fiftyTwoWeekHigh"] = num(m.get("52WeekHigh"))
    info["fiftyTwoWeekLow"] = num(m.get("52WeekLow"))
    return {k: v for k, v in info.items() if v is not None}


def get_news_finnhub(ticker: str, count: int = 8) -> list:
    today = datetime.date.today()
    frm = (today - datetime.timedelta(days=21)).isoformat()
    data = _finnhub_get(f"company-news?symbol={ticker}&from={frm}&to={today.isoformat()}")
    if not isinstance(data, list):
        return []
    out = []
    for it in data:
        ts = it.get("datetime")
        date = ""
        if ts:
            try:
                date = datetime.datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d")
            except Exception:
                date = ""
        out.append({
            "title": it.get("headline", "(senza titolo)"),
            "summary": it.get("summary", ""),
            "publisher": it.get("source", ""),
            "url": it.get("url", ""),
            "ts": str(ts or ""),
            "date": date,
        })
    out.sort(key=lambda n: n["ts"], reverse=True)
    return out[:count]


@st.cache_data(ttl=900, show_spinner=False)
def ticker_exists(ticker: str) -> bool:
    df = get_history(ticker, period="5d")
    return not df.empty


@st.cache_data(ttl=600, show_spinner=False)
def search_symbols(query: str, max_results: int = 8) -> list:
    """Cerca un titolo per nome o simbolo. Ritorna [(symbol, nome, tipo, borsa), ...]."""
    query = (query or "").strip()
    if len(query) < 2:
        return []
    out = []
    # Fonte primaria: FMP (affidabile dal cloud)
    if _fmp_key():
        from urllib.parse import quote
        data = _fmp_get(f"search-name?query={quote(query)}&limit={max_results}")
        if isinstance(data, list):
            for q in data:
                sym = q.get("symbol")
                if not sym:
                    continue
                out.append((sym, q.get("name") or "", "",
                            q.get("exchange") or q.get("exchangeFullName") or ""))
    if out:
        return out
    # Riserva: yfinance
    try:
        res = yf.Search(query, max_results=max_results)
        for q in res.quotes:
            sym = q.get("symbol")
            if not sym:
                continue
            nome = q.get("shortname") or q.get("longname") or ""
            tipo = q.get("quoteType", "")
            borsa = q.get("exchDisp") or q.get("exchange", "")
            out.append((sym, nome, tipo, borsa))
    except Exception:
        pass
    return out


_FMP_SCREEN = {"day_gainers": "biggest-gainers", "day_losers": "biggest-losers", "most_actives": "most-actives"}


@st.cache_data(ttl=600, show_spinner=False)
def get_screen(name: str, count: int = 15) -> pd.DataFrame:
    """Classifica predefinita. Fonte primaria: FMP (gainers/losers/actives); riserva yfinance."""
    # FMP primario per le classifiche principali
    if _fmp_key() and name in _FMP_SCREEN:
        data = _fmp_get(_FMP_SCREEN[name])
        if isinstance(data, list) and data:
            frows = []
            for q in data[:count]:
                cp = q.get("changesPercentage", q.get("changePercentage"))
                try:
                    cp = float(str(cp).replace("%", "").replace("(", "-").replace(")", ""))
                except (TypeError, ValueError):
                    cp = None
                frows.append({
                    "Ticker": q.get("symbol", ""),
                    "Nome": (q.get("name") or "")[:34],
                    "Prezzo": q.get("price"),
                    "Var %": cp,
                    "Volume": q.get("volume"),
                    "Cap.": q.get("marketCap"),
                })
            return pd.DataFrame(frows)
    # Riserva yfinance (e unica fonte per le classifiche non coperte da FMP)
    try:
        res = yf.screen(name, count=count)
        quotes = res.get("quotes", []) if isinstance(res, dict) else []
    except Exception:
        quotes = []
    rows = [{
        "Ticker": q.get("symbol", ""),
        "Nome": (q.get("shortName") or q.get("longName") or "")[:34],
        "Prezzo": q.get("regularMarketPrice"),
        "Var %": q.get("regularMarketChangePercent"),
        "Volume": q.get("regularMarketVolume"),
        "Cap.": q.get("marketCap"),
    } for q in quotes]
    return pd.DataFrame(rows)


@st.cache_data(ttl=600, show_spinner=False)
def get_news(ticker: str, count: int = 8) -> list:
    """Notizie legate a un ticker, ordinate dalla più recente. Ritorna dict normalizzati.
    Fonte primaria: Finnhub (no Yahoo); riserva yfinance (es. indici tipo ^GSPC).
    Ogni voce ha 'ts' (per ordinare/filtrare) e 'date' (YYYY-MM-DD)."""
    if _finnhub_key():
        fh = get_news_finnhub(ticker, count)
        if fh:
            return fh
    try:
        raw = yf.Ticker(ticker).news or []
    except Exception:
        raw = []
    out = []
    for item in raw:
        c = item.get("content", item) if isinstance(item, dict) else {}
        provider = c.get("provider") or {}
        click = c.get("clickThroughUrl") or c.get("canonicalUrl") or {}
        ts = (c.get("pubDate") or c.get("displayTime") or "")
        out.append({
            "title": c.get("title", "(senza titolo)"),
            "summary": c.get("summary") or c.get("description") or "",
            "publisher": provider.get("displayName", "") if isinstance(provider, dict) else "",
            "url": click.get("url", "") if isinstance(click, dict) else "",
            "ts": ts,
            "date": ts[:10],
        })
    out.sort(key=lambda n: n["ts"], reverse=True)   # più recente prima (ISO → ordine lessicografico)
    return out[:count]


# ---------------------------------------------------------------------------
# ETF / FONDI
# ---------------------------------------------------------------------------

SECTOR_IT = {
    "realestate": "Immobiliare", "consumer_cyclical": "Consumi ciclici",
    "basic_materials": "Materie prime", "consumer_defensive": "Consumi difensivi",
    "technology": "Tecnologia", "communication_services": "Comunicazioni",
    "financial_services": "Finanza", "utilities": "Utility",
    "industrials": "Industria", "energy": "Energia", "healthcare": "Salute",
}

ASSET_IT = {
    "stockPosition": "Azioni", "bondPosition": "Obbligazioni",
    "cashPosition": "Liquidità", "preferredPosition": "Azioni privilegiate",
    "convertiblePosition": "Convertibili", "otherPosition": "Altro",
}


# Tabella TER (costo annuo) di ETF europei UCITS comuni — yfinance spesso non li espone.
# Valori indicativi (frazione: 0.0022 = 0,22%). Da verificare sul KID dell'emittente.
EU_ETF_TER = {
    "VWCE.DE": 0.0022, "VWCE.MI": 0.0022, "VWRL.AS": 0.0022, "VWRL.MI": 0.0022,
    "SWDA.MI": 0.0020, "IWDA.AS": 0.0020, "EUNL.DE": 0.0020,
    "CSSPX.MI": 0.0007, "SXR8.DE": 0.0007, "VUSA.MI": 0.0007, "VUSA.AS": 0.0007,
    "EIMI.MI": 0.0018, "IS3N.DE": 0.0018, "VFEM.DE": 0.0022, "EIMI.L": 0.0018,
    "MEUD.PA": 0.0007, "CW8.PA": 0.0038, "LCWD.MI": 0.0012,
    "AGGH.MI": 0.0010, "VAGF.MI": 0.0010, "EUNA.DE": 0.0009,
    "XDWD.DE": 0.0019, "SPYI.DE": 0.0017, "VHYL.MI": 0.0029,
}


def is_fund(info: dict) -> bool:
    return (info.get("quoteType") or "").upper() in ("ETF", "MUTUALFUND")


def default_benchmark(ticker: str) -> str:
    """Indice di riferimento sensato in base alla borsa del titolo."""
    t = (ticker or "").upper()
    if t.endswith(".MI"):
        return "^FTSEMIB.MI"
    if t.endswith((".DE", ".PA", ".AS", ".SW", ".MC", ".BR")):
        return "^STOXX50E"
    if t.endswith(".L"):
        return "^FTSE"
    return "^GSPC"


@st.cache_data(ttl=900, show_spinner=False)
def simulate_investment(ticker: str, amount: float, start_date, benchmark: str = None) -> dict:
    """Simula un investimento di `amount` fatto in `start_date`, con confronto al benchmark."""
    h = get_history(ticker, period="max")
    if h.empty:
        return None
    h = h[h.index.date >= start_date]
    if h.empty or len(h) < 2:
        return None
    close = h["Close"]
    shares = amount / close.iloc[0]
    value = close * shares
    out = pd.DataFrame({"Titolo": value})

    bench_final = None
    if benchmark:
        b = get_history(benchmark, period="max")
        if not b.empty:
            b = b[b.index.date >= start_date]
            if len(b) >= 2:
                bval = b["Close"] * (amount / b["Close"].iloc[0])
                out["Benchmark"] = bval.reindex(out.index).ffill()
                bench_final = float(out["Benchmark"].iloc[-1])

    final = float(value.iloc[-1])
    years = max((h.index[-1] - h.index[0]).days / 365.25, 1e-9)
    cagr = ((final / amount) ** (1 / years) - 1) * 100 if final > 0 else float("nan")
    return {
        "df": out, "final": final, "gain": final - amount,
        "gain_pct": (final / amount - 1) * 100, "cagr": cagr, "years": years,
        "shares": shares, "start_price": float(close.iloc[0]),
        "end_price": float(close.iloc[-1]), "bench_final": bench_final,
    }


def hist_return_vol(hist: pd.DataFrame):
    """Rendimento annuo atteso (semplice) e volatilità annua dai dati storici."""
    if hist.empty or len(hist) < 30:
        return None, None
    log_ret = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
    if log_ret.empty:
        return None, None
    mu_log = log_ret.mean() * 252
    sigma = log_ret.std() * np.sqrt(252)
    annual_return = np.exp(mu_log) - 1  # rendimento semplice atteso
    return float(annual_return), float(sigma)


def _scenario_series(initial, monthly, months, annual_return):
    r = (1 + annual_return) ** (1 / 12) - 1
    val = initial
    series = [val]
    for _ in range(months):
        val = val * (1 + r) + monthly
        series.append(val)
    return np.array(series)


def project_future(initial: float, monthly: float, years: float,
                   annual_return: float, sigma: float, n_sims: int = 500) -> dict:
    """Proiezione a scenari + ventaglio Monte Carlo. NON è una previsione."""
    months = max(int(round(years * 12)), 1)
    invested = initial + monthly * np.arange(months + 1)

    # Scenari deterministici (prudente / base / ottimistico)
    base = _scenario_series(initial, monthly, months, annual_return)
    prudente = _scenario_series(initial, monthly, months, annual_return - sigma)
    ottimistico = _scenario_series(initial, monthly, months, annual_return + sigma)

    # Monte Carlo (moto browniano geometrico, passi mensili) — seed fisso per stabilità
    mu_log = np.log(1 + annual_return)
    dt = 1 / 12
    drift = (mu_log - 0.5 * sigma ** 2) * dt
    vol = sigma * np.sqrt(dt)
    rng = np.random.default_rng(42)
    paths = np.empty((n_sims, months + 1))
    paths[:, 0] = initial
    for m in range(1, months + 1):
        z = rng.standard_normal(n_sims)
        paths[:, m] = paths[:, m - 1] * np.exp(drift + vol * z) + monthly
    pct = {p: np.percentile(paths, p, axis=0) for p in (10, 50, 90)}

    return {
        "months": months, "x_years": np.arange(months + 1) / 12,
        "invested": invested, "total_invested": float(invested[-1]),
        "base": base, "prudente": prudente, "ottimistico": ottimistico,
        "p10": pct[10], "p50": pct[50], "p90": pct[90],
    }


@st.cache_data(ttl=900, show_spinner=False)
def get_fund_data(ticker: str) -> dict:
    """Dati specifici di ETF/fondi: composizione, settori, titoli, costi, patrimonio."""
    out = {
        "is_fund": False, "category": None, "family": None, "legal_type": None,
        "expense_ratio": None, "expense_ratio_source": None, "total_assets": None, "yield": None,
        "description": "", "asset_classes": {}, "sector_weightings": {}, "top_holdings": [],
    }
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
    except Exception:
        return out

    if not is_fund(info):
        return out
    out["is_fund"] = True
    out["category"] = info.get("category")
    out["total_assets"] = info.get("totalAssets")
    # TER / costo: yfinance lo espone con nomi diversi (spesso assente per ETF europei)
    out["expense_ratio"] = (
        info.get("annualReportExpenseRatio")
        or info.get("netExpenseRatio")
        or info.get("expenseRatio")
        or EU_ETF_TER.get(ticker.upper())
    )
    out["expense_ratio_source"] = (
        "tabella interna" if (not info.get("annualReportExpenseRatio")
                              and not info.get("netExpenseRatio")
                              and not info.get("expenseRatio")
                              and ticker.upper() in EU_ETF_TER) else "yfinance"
    )
    out["yield"] = info.get("yield")

    try:
        fd = t.funds_data
        ov = fd.fund_overview or {}
        out["category"] = out["category"] or ov.get("categoryName")
        out["family"] = ov.get("family")
        out["legal_type"] = ov.get("legalType")
        out["description"] = fd.description or ""
        out["asset_classes"] = {k: v for k, v in (fd.asset_classes or {}).items() if v}
        out["sector_weightings"] = fd.sector_weightings or {}
        th = fd.top_holdings
        if th is not None and not th.empty:
            for sym, row in th.iterrows():
                out["top_holdings"].append(
                    (sym, row.get("Name", ""), float(row.get("Holding Percent", 0)))
                )
    except Exception:
        pass
    return out


def fund_commentary(ticker: str, fdata: dict, info: dict, hist: pd.DataFrame, period_label: str = "il periodo") -> str:
    """Commento testuale per un ETF/fondo."""
    name = info.get("longName") or info.get("shortName") or ticker
    lines = []

    if not hist.empty and len(hist) > 1:
        perf = (hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100
        trend = "in rialzo" if perf > 3 else "in calo" if perf < -3 else "sostanzialmente stabile"
        lines.append(f"**{name}** è un {fdata.get('legal_type') or 'fondo'} "
                     f"({fdata.get('category') or 'categoria n/d'}) gestito da {fdata.get('family') or 'n/d'}. "
                     f"Nel periodo osservato ({period_label}) è {trend} ({perf:+.1f}%).")

    aum = fdata.get("total_assets")
    if aum:
        lines.append(f"**Dimensione:** patrimonio gestito di circa {_fmt_big(aum)} "
                     "(un patrimonio ampio in genere significa maggiore liquidità e spread ridotti).")

    ter = fdata.get("expense_ratio")
    if ter:
        q = "molto basso" if ter <= 0.002 else "basso" if ter <= 0.005 else "medio" if ter <= 0.01 else "alto"
        lines.append(f"**Costi:** TER (costo annuo) {q}, pari a {ter*100:.2f}%. "
                     "I costi erodono il rendimento ogni anno, quindi più sono bassi meglio è.")
    else:
        lines.append("**Costi:** TER non disponibile da questa fonte (frequente per gli ETF europei UCITS); "
                     "verificalo sulla pagina dell'emittente — è un fattore chiave.")

    ac = fdata.get("asset_classes") or {}
    if ac:
        top = max(ac.items(), key=lambda kv: kv[1])
        comp = ", ".join(f"{ASSET_IT.get(k, k)} {v*100:.0f}%" for k, v in sorted(ac.items(), key=lambda kv: -kv[1]) if v >= 0.01)
        lines.append(f"**Composizione:** prevale {ASSET_IT.get(top[0], top[0])} ({top[1]*100:.0f}%). {comp}.")

    sw = fdata.get("sector_weightings") or {}
    if sw:
        top3 = sorted(sw.items(), key=lambda kv: -kv[1])[:3]
        lines.append("**Settori principali:** " +
                     ", ".join(f"{SECTOR_IT.get(k, k)} {v*100:.1f}%" for k, v in top3) + ".")

    th = fdata.get("top_holdings") or []
    if th:
        conc = sum(p for _, _, p in th[:10]) * 100
        names = ", ".join(n or s for s, n, _ in th[:3])
        lines.append(f"**Diversificazione:** i primi 10 titoli pesano circa il {conc:.0f}% "
                     f"(principali: {names}). " +
                     ("Concentrazione elevata." if conc > 50 else "Buona diversificazione."))

    vol = annualized_volatility(hist["Close"]) if not hist.empty else float("nan")
    if not np.isnan(vol):
        lines.append(f"**Rischio:** volatilità annua del {vol*100:.1f}%.")

    lines.append("**In sintesi:** per un ETF contano soprattutto costi (TER), diversificazione, "
                 "dimensione e coerenza con il tuo orizzonte. Non è un consiglio di investimento.")
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# GLOSSARIO — spiegazioni in linguaggio semplice
# ---------------------------------------------------------------------------
GLOSSARY = {
    "P/E (prezzo/utili)": "Quante volte gli utili annui stai pagando il titolo. Basso = potenzialmente conveniente; alto = il mercato si aspetta molta crescita (o è caro).",
    "P/E prospettico": "Come il P/E ma usando gli utili attesi per l'anno prossimo invece di quelli passati.",
    "P/B (prezzo/patrimonio)": "Prezzo rispetto al valore contabile (patrimonio netto). Sotto 1 = paghi meno del valore di libro; tipico per banche e industrie.",
    "PEG (P/E su crescita)": "P/E diviso la crescita degli utili. Sotto 1 indica un prezzo ragionevole rispetto a quanto l'azienda cresce.",
    "ROE (rendimento capitale proprio)": "Quanto utile genera l'azienda per ogni euro di capitale dei soci. Più alto = più redditizia. Sopra il 15% è buono.",
    "ROA (rendimento attività)": "Utile generato per ogni euro di attività totali. Misura l'efficienza nell'uso delle risorse.",
    "Margine netto": "Percentuale di ricavi che resta come utile finale, dopo tutti i costi e le tasse.",
    "Margine operativo": "Percentuale di ricavi che resta dopo i costi operativi, prima di interessi e tasse. Indica l'efficienza del core business.",
    "Debito/Equity": "Quanto debito ha l'azienda rispetto al capitale proprio. Alto = più rischio finanziario. Espresso spesso in % (100 = pari al capitale).",
    "Current ratio (liquidità)": "Attività correnti diviso passività correnti. Sopra 1 significa che riesce a coprire i debiti a breve.",
    "Quick ratio": "Come il current ratio ma esclude le scorte di magazzino: misura la liquidità più immediata.",
    "Crescita ricavi (anno)": "Di quanto sono cresciuti i ricavi rispetto all'anno precedente.",
    "Crescita utili (anno)": "Di quanto sono cresciuti gli utili rispetto all'anno precedente.",
    "Rendimento dividendo": "Dividendo annuo diviso il prezzo: quanto rende in cedole l'investimento, in percentuale.",
    "Payout ratio (utili distribuiti)": "Quota di utili distribuita come dividendo. Troppo alta (>90%) può non essere sostenibile.",
    "Beta": "Quanto il titolo si muove rispetto al mercato. 1 = come il mercato; >1 = più volatile; <1 = più difensivo.",
    "Capitalizzazione": "Valore totale dell'azienda in borsa = prezzo per numero di azioni.",
    "Volatilità annua": "Quanto oscilla il prezzo su base annua. Più alta = più rischio (e potenziale guadagno/perdita).",
    "SMA": "Media mobile semplice: prezzo medio degli ultimi N giorni. Mostra la direzione del trend lisciando il rumore.",
    "EMA": "Media mobile esponenziale: come la SMA ma dà più peso ai giorni recenti, quindi reagisce più in fretta.",
    "RSI (14)": "Indice di forza relativa (0-100). Sopra 70 = ipercomprato (possibile correzione); sotto 30 = ipervenduto (possibile rimbalzo).",
    "MACD": "Confronta due medie mobili per misurare il momentum. Quando supera la sua linea 'signal' è un segnale rialzista, sotto è ribassista.",
    "Bande di Bollinger": "Banda intorno al prezzo basata sulla volatilità. Il prezzo che tocca la banda alta/bassa può indicare estensione del movimento.",
    "Golden cross": "La media a 50 giorni supera quella a 200: segnale di trend rialzista di medio-lungo periodo.",
    "Death cross": "La media a 50 giorni scende sotto quella a 200: segnale di trend ribassista.",
    "Punteggio sintetico": "Voto 0-100 calcolato da valutazione, redditività, debito e crescita. È una sintesi quantitativa indicativa, non un consiglio di acquisto.",
    "ETF": "Fondo quotato in borsa che replica un indice o paniere di titoli: compri con un'unica operazione un portafoglio diversificato.",
    "TER (costo annuo)": "Total Expense Ratio: la spesa annua dell'ETF in % del capitale. Viene sottratta gradualmente dal rendimento; più è basso, meglio è.",
    "Patrimonio (AUM)": "Asset Under Management: quanti soldi gestisce il fondo. Più è grande, di solito più è liquido e con costi di negoziazione (spread) ridotti.",
    "Asset allocation": "Come è ripartito il fondo tra azioni, obbligazioni, liquidità e altro. Determina rischio e rendimento attesi.",
    "Diversificazione": "Quanto il fondo è distribuito su molti titoli. Più è diversificato, meno dipende dall'andamento di una singola azienda.",
    "Top holdings": "I titoli con il peso maggiore nel fondo. La loro somma indica quanto il fondo è concentrato.",
    "Settori": "Ripartizione del fondo tra i settori economici (tecnologia, finanza, salute…). Mostra a cosa sei più esposto.",
}


def help_for(label: str) -> str:
    """Restituisce la spiegazione per un'etichetta (anche con match parziale)."""
    if label in GLOSSARY:
        return GLOSSARY[label]
    for key, text in GLOSSARY.items():
        if key.split(" (")[0].lower() in label.lower():
            return text
    return ""


# ---------------------------------------------------------------------------
# TRADUZIONE (gratuita, senza API key — con fallback al testo originale)
# ---------------------------------------------------------------------------

_STOPWORDS = set(
    "the a an and or of to in for on with is are was were be been being by at from as it "
    "this that these those his her its their our your my we they he she you i do does did has "
    "have had will would can could should may might must not no but if then than so out up "
    "about after before over under into more most some such only also other".split()
)


def summarize_text(text: str, max_sentences: int = 2) -> str:
    """Riassunto estrattivo: seleziona le frasi più informative (per frequenza dei termini).
    Nessun modello esterno, nessun costo. Pensato per condensare la descrizione di una notizia."""
    import re
    text = (text or "").strip()
    if not text:
        return ""
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if len(sents) <= max_sentences:
        return text
    words = re.findall(r"[a-zA-Zàèéìòùç']+", text.lower())
    freq = {}
    for w in words:
        if len(w) <= 2 or w in _STOPWORDS:
            continue
        freq[w] = freq.get(w, 0) + 1
    scored = []
    for i, s in enumerate(sents):
        sw = re.findall(r"[a-zA-Z']+", s.lower())
        score = sum(freq.get(w, 0) for w in sw) / (len(sw) + 1)
        scored.append((score, i, s))
    top = sorted(scored, key=lambda x: -x[0])[:max_sentences]
    top = sorted(top, key=lambda x: x[1])           # rimetti in ordine di lettura
    return " ".join(s for _, _, s in top)


@st.cache_data(ttl=86400, show_spinner=False)
def translate_text(text: str, target: str = "it") -> str:
    text = (text or "").strip()
    if not text:
        return text
    try:
        from deep_translator import GoogleTranslator
        return GoogleTranslator(source="auto", target=target).translate(text[:4900])
    except Exception:
        return text  # se la rete blocca il servizio, restiamo sull'originale


# ---------------------------------------------------------------------------
# SINTESI AUTOMATICA — commento in linguaggio naturale (regole sui numeri)
# ---------------------------------------------------------------------------

def _val(info, key):
    v = info.get(key)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def generate_commentary(ticker: str, info: dict, hist: pd.DataFrame, period_label: str = "il periodo") -> str:
    """Genera un commento testuale in italiano a partire dai dati calcolati.
    Deterministico: nessun modello esterno, nessun costo."""
    name = info.get("longName") or info.get("shortName") or ticker
    sector = info.get("sector")
    lines = []

    # --- Andamento di prezzo ---
    if not hist.empty and len(hist) > 1:
        perf = (hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100
        price = hist["Close"].iloc[-1]
        trend_word = "in rialzo" if perf > 3 else "in calo" if perf < -3 else "sostanzialmente stabile"
        s = f"Nel periodo osservato ({period_label}) **{name}** è {trend_word} ({perf:+.1f}%)."
        lo = _val(info, "fiftyTwoWeekLow")
        hi = _val(info, "fiftyTwoWeekHigh")
        if lo and hi and hi > lo:
            pos = (price - lo) / (hi - lo) * 100
            if pos >= 80:
                s += f" Il prezzo è vicino ai massimi di 52 settimane ({pos:.0f}% del range annuale)."
            elif pos <= 20:
                s += f" Il prezzo è vicino ai minimi di 52 settimane ({pos:.0f}% del range annuale)."
            else:
                s += f" Si colloca a metà del range delle ultime 52 settimane ({pos:.0f}%)."
        lines.append(s)

    # --- Valutazione ---
    pe = _val(info, "trailingPE")
    pb = _val(info, "priceToBook")
    val_bits = []
    if pe is not None:
        if pe <= 15:
            val_bits.append(f"un P/E di {pe:.1f}, contenuto (potenzialmente conveniente)")
        elif pe <= 35:
            val_bits.append(f"un P/E di {pe:.1f}, nella norma")
        else:
            val_bits.append(f"un P/E elevato ({pe:.1f}), il mercato sconta molta crescita futura")
    if pb is not None:
        val_bits.append(f"un prezzo/patrimonio (P/B) di {pb:.2f}")
    if val_bits:
        lines.append("**Valutazione:** il titolo presenta " + " e ".join(val_bits) + ".")

    # --- Redditività ---
    roe = _val(info, "returnOnEquity")
    margin = _val(info, "profitMargins")
    red_bits = []
    if roe is not None:
        q = "ottima" if roe >= 0.2 else "buona" if roe >= 0.12 else "modesta" if roe >= 0.05 else "debole"
        red_bits.append(f"una redditività del capitale (ROE) {q} ({roe*100:.1f}%)")
    if margin is not None:
        q = "alto" if margin >= 0.2 else "discreto" if margin >= 0.1 else "basso"
        red_bits.append(f"un margine netto {q} ({margin*100:.1f}%)")
    if red_bits:
        lines.append("**Redditività:** l'azienda mostra " + " e ".join(red_bits) + ".")

    # --- Solidità ---
    d2e = _val(info, "debtToEquity")
    if d2e is not None:
        if d2e <= 50:
            lines.append(f"**Solidità:** il debito è basso rispetto al capitale (Debito/Equity {d2e:.0f}), quadro finanziario solido.")
        elif d2e <= 150:
            lines.append(f"**Solidità:** livello di debito moderato (Debito/Equity {d2e:.0f}).")
        else:
            lines.append(f"**Solidità:** debito elevato (Debito/Equity {d2e:.0f}), da monitorare in caso di tassi alti o calo dei ricavi.")

    # --- Crescita / dividendo ---
    rev = _val(info, "revenueGrowth")
    dy = div_yield_fraction(info)
    gd_bits = []
    if rev is not None:
        if rev >= 0.1:
            gd_bits.append(f"ricavi in forte crescita ({rev*100:.1f}% sull'anno)")
        elif rev >= 0:
            gd_bits.append(f"ricavi in lieve crescita ({rev*100:.1f}%)")
        else:
            gd_bits.append(f"ricavi in contrazione ({rev*100:.1f}%)")
    if dy is not None and dy > 0:
        gd_bits.append(f"un dividendo che rende il {dy*100:.2f}%")
    if gd_bits:
        lines.append("**Crescita e dividendo:** " + ", ".join(gd_bits) + ".")

    # --- Tecnica ---
    if not hist.empty:
        last = hist.iloc[-1]
        tech_bits = []
        if not np.isnan(last.get("SMA200", np.nan)):
            if last["Close"] > last["SMA200"]:
                tech_bits.append("il prezzo è sopra la media a 200 giorni (trend di fondo positivo)")
            else:
                tech_bits.append("il prezzo è sotto la media a 200 giorni (trend di fondo debole)")
        rsi_v = last.get("RSI", np.nan)
        if not np.isnan(rsi_v):
            if rsi_v >= 70:
                tech_bits.append(f"l'RSI è alto ({rsi_v:.0f}): zona di ipercomprato, possibile pausa/correzione")
            elif rsi_v <= 30:
                tech_bits.append(f"l'RSI è basso ({rsi_v:.0f}): zona di ipervenduto, possibile rimbalzo")
            else:
                tech_bits.append(f"l'RSI è neutro ({rsi_v:.0f})")
        if tech_bits:
            lines.append("**Quadro tecnico:** " + "; ".join(tech_bits) + ".")

    # --- Sintesi finale dai segnali fondamentali ---
    blocks = fundamental_blocks(info)
    all_rows = [r for rows in blocks.values() for r in rows]
    pos = sum(1 for _, _, j in all_rows if j == "positivo")
    neg = sum(1 for _, _, j in all_rows if j == "negativo")
    if pos + neg > 0:
        if pos > neg * 1.5:
            verdict = "Nel complesso i fondamentali appaiono **prevalentemente favorevoli**."
        elif neg > pos * 1.5:
            verdict = "Nel complesso i fondamentali appaiono **prevalentemente sfavorevoli**."
        else:
            verdict = "Il quadro fondamentale è **misto**: luci e ombre da pesare."
        lines.append(f"**In sintesi:** {verdict} ({pos} segnali positivi, {neg} negativi). "
                     "Resta un'analisi quantitativa indicativa: valuta anche contesto, settore e orizzonte temporale.")

    if not lines:
        return "Dati insufficienti per generare una sintesi (tipico per indici ed ETF)."
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# VERDETTO SINTETICO (semaforo) — fonde fondamentale + tecnica in un voto
# ---------------------------------------------------------------------------

def _technical_score(hist: pd.DataFrame):
    sigs = technical_signals(hist)
    pos = sum(1 for _, _, j in sigs if j == "positivo")
    neg = sum(1 for _, _, j in sigs if j == "negativo")
    if pos + neg == 0:
        return None
    return pos / (pos + neg) * 100


def _fundamental_score(info: dict):
    blocks = fundamental_blocks(info)
    rows = [r for rs in blocks.values() for r in rs]
    pos = sum(1 for _, _, j in rows if j == "positivo")
    neg = sum(1 for _, _, j in rows if j == "negativo")
    if pos + neg == 0:
        return None
    return pos / (pos + neg) * 100


def overall_verdict(info: dict, hist: pd.DataFrame, fund: bool = False, fdata: dict = None) -> dict:
    """Voto sintetico 0-100 + colore + etichetta + frase. Indicativo, non un consiglio."""
    tech = _technical_score(hist)

    if fund:
        # Per un ETF: trend + diversificazione + (costo) come proxy di qualità
        parts, weights = [], []
        if tech is not None:
            parts.append(tech); weights.append(0.5)
        fdata = fdata or {}
        th = fdata.get("top_holdings") or []
        if th:
            conc = sum(p for _, _, p in th[:10]) * 100
            div_score = 100 if conc <= 25 else 70 if conc <= 50 else 40 if conc <= 70 else 20
            parts.append(div_score); weights.append(0.3)
        ter = fdata.get("expense_ratio")
        if ter:
            cost_score = 100 if ter <= 0.002 else 80 if ter <= 0.005 else 50 if ter <= 0.01 else 20
            parts.append(cost_score); weights.append(0.2)
        score = sum(p * w for p, w in zip(parts, weights)) / sum(weights) if parts else None
    else:
        fund_s = _fundamental_score(info)
        if fund_s is not None and tech is not None:
            score = fund_s * 0.6 + tech * 0.4
        else:
            score = fund_s if fund_s is not None else tech

    if score is None:
        return {"score": None, "color": "#57606a", "emoji": "⚪",
                "label": "Dati insufficienti",
                "line": "Non ci sono abbastanza dati per un verdetto sintetico su questo strumento."}

    if score >= 66:
        color, emoji, label = "#1a7f37", "🟢", "Quadro complessivamente favorevole"
        line = "I segnali analizzati sono in prevalenza positivi. Resta un'indicazione quantitativa, non un consiglio di acquisto."
    elif score >= 40:
        color, emoji, label = "#9a6700", "🟡", "Quadro misto"
        line = "Ci sono luci e ombre: pesa i pro e i contro e valuta il tuo orizzonte temporale."
    else:
        color, emoji, label = "#cf222e", "🔴", "Quadro da valutare con cautela"
        line = "I segnali analizzati sono in prevalenza negativi. Approfondisci prima di qualsiasi decisione."

    return {"score": round(score), "color": color, "emoji": emoji, "label": label, "line": line}


# ---------------------------------------------------------------------------
# WATCHLIST (preferiti) — salvataggio locale su file JSON
# ---------------------------------------------------------------------------

WATCHLIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.json")


def load_watchlist() -> list:
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def save_watchlist(tickers: list) -> None:
    try:
        with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
            json.dump(list(dict.fromkeys(tickers)), f)
    except Exception:
        pass


@st.cache_data(ttl=300, show_spinner=False)
def quick_quote(ticker: str) -> dict:
    """Prezzo e variazione del giorno per la watchlist (leggero). Fonte: FMP quote, poi storico."""
    if _fmp_key():
        q = _first(_fmp_get(f"quote?symbol={ticker}"))
        if q and q.get("price") is not None:
            try:
                return {"price": float(q["price"]),
                        "change_pct": float(q.get("changePercentage") or 0.0)}
            except (TypeError, ValueError):
                pass
    df = get_history(ticker, period="5d")
    if df.empty:
        return {"price": None, "change_pct": None}
    last = float(df["Close"].iloc[-1])
    prev = float(df["Close"].iloc[-2]) if len(df) > 1 else last
    chg = (last / prev - 1) * 100 if prev else 0.0
    return {"price": last, "change_pct": chg}


# ---------------------------------------------------------------------------
# OCCASIONI — cali con potenziale rimbalzo (breve) o qualità scontata (lungo)
# NB: segnali per regole, NON previsioni. Un calo può continuare ("coltello che cade").
# ---------------------------------------------------------------------------

@st.cache_data(ttl=900, show_spinner=False)
def opportunity_row(ticker: str, with_fundamentals: bool = True) -> dict:
    """Riga occasione. with_fundamentals=False (breve periodo) usa solo lo storico
    (1 sola chiamata API) e salta i fondamentali → molte meno richieste."""
    h = get_history(ticker, period="1y")
    if not h.empty:
        h = h[h["Close"].notna()]            # scarta righe senza prezzo (NaN finale di yfinance)
    if h.empty or len(h) < 60:
        return None
    h = add_indicators(h)
    last = h.iloc[-1]
    price = float(last["Close"])
    if np.isnan(price):
        return None

    def _nn(x):  # NaN/None → None (evita round(NaN) e confronti ingannevoli)
        return None if (x is None or (isinstance(x, float) and np.isnan(x))) else x

    rsi = float(last["RSI"]) if not np.isnan(last.get("RSI", np.nan)) else None
    hi = float(h["Close"].max())   # massimo ~52 settimane dallo storico (niente chiamata extra)
    dd_high = _nn((price / hi - 1) * 100) if hi else None
    perf_1m = _nn((price / float(h["Close"].iloc[-21]) - 1) * 100) if len(h) > 21 else None
    perf_1y = _nn((price / float(h["Close"].iloc[0]) - 1) * 100)
    bb_low = last.get("BB_low", np.nan)
    below_bb = bool(price <= bb_low) if not np.isnan(bb_low) else False
    sma200 = last.get("SMA200", np.nan)
    above_sma200 = bool(price > sma200) if not np.isnan(sma200) else None

    # Potenziale di rimbalzo e livelli operativi (bersaglio = media 50gg, stop = minimo recente)
    sma50 = last.get("SMA50", np.nan)
    rebound_pot = _nn((sma50 / price - 1) * 100) if (not np.isnan(sma50) and price) else None
    target_price = float(sma50) if not np.isnan(sma50) else None
    stop_price = float(h["Close"].tail(20).min())   # minimo delle ultime ~4 settimane
    spark = [round(float(x), 4) for x in h["Close"].tail(60).tolist()]          # mini-grafico (prezzi)
    spark_dates = [str(d.date()) for d in h.index[-60:]]                         # date per l'asse x

    # Probabilità statistiche (modello normale sui rendimenti storici, drift smorzato).
    # Orizzonte: breve ~1 mese, lungo ~1 anno. NON è una previsione: è una stima dal passato.
    prob_gain, prob_loss, exp_ret, reliab = _gain_loss_prob(
        h, horizon_days=(252 if with_fundamentals else 21))

    etf, fscore, name = False, None, ticker
    if with_fundamentals:                    # solo per il lungo periodo (qualità)
        info = get_info(ticker)
        etf = is_fund(info)
        fscore = _fundamental_score(info) if not etf else None
        name = (info.get("shortName") or info.get("longName") or ticker)[:34]

    return dict(ticker=ticker.upper(), name=name, price=price, rsi=rsi, dd_high=dd_high,
                perf_1m=perf_1m, perf_1y=perf_1y, below_bb=below_bb, above_sma200=above_sma200,
                etf=etf, fscore=fscore, prob_gain=prob_gain, prob_loss=prob_loss,
                exp_ret=exp_ret, reliab=reliab, rebound_pot=rebound_pot,
                target_price=target_price, stop_price=stop_price,
                spark=spark, spark_dates=spark_dates)


def _gain_loss_prob(h, horizon_days=21):
    """Stima probabilità salita / perdita>15%, guadagno atteso % e affidabilità della stima.
    Modello normale con drift annuo smorzato a [-25%, +30%]. Indicativo, NON una previsione."""
    try:
        logret = np.log(h["Close"] / h["Close"].shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
    except Exception:
        return None, None, None, None
    n = len(logret)
    if n < 30:
        return None, None, None, None
    mu_a = float(np.clip(logret.mean() * 252, -0.25, 0.30))   # rendimento annuo atteso, smorzato
    sig_a = float(logret.std() * np.sqrt(252))
    if sig_a <= 0:
        return None, None, None, None
    f = horizon_days / 252.0
    mu_h, sig_h = mu_a * f, sig_a * np.sqrt(f)
    cdf = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    p_gain = round(cdf(mu_h / sig_h) * 100)                    # P(prezzo più alto a fine orizzonte)
    p_loss = round(cdf((math.log(0.85) - mu_h) / sig_h) * 100)  # P(perdita > 15%)
    exp_ret = round((math.exp(mu_h) - 1) * 100, 1)            # rendimento atteso (mediano) sull'orizzonte
    # Affidabilità della stima: alta se poca volatilità e storico lungo, bassa se molto volatile
    if sig_a <= 0.35 and n >= 180:
        reliab = "🟢 Alta"
    elif sig_a <= 0.60 and n >= 120:
        reliab = "🟡 Media"
    else:
        reliab = "🔴 Bassa"
    return p_gain, p_loss, exp_ret, reliab


def _short_score(r):
    if r["rsi"] is None:
        return None
    rsi = r["rsi"]
    # quanto è ipervenduto (0-50)
    if rsi <= 25:
        base = 50
    elif rsi <= 30:
        base = 42
    elif rsi <= 35:
        base = 32
    elif rsi <= 40:
        base = 22
    elif rsi <= 45:
        base = 12
    else:
        base = 0
    if r["below_bb"]:
        base += 12                           # prezzo a un estremo
    if r["above_sma200"]:
        base += 13                           # trend di fondo intatto = rimbalzo più probabile
    # possibilità di guadagno = spazio di recupero (quanto è caduto dai massimi), fino a +25
    dd = r["dd_high"]
    if dd is not None:
        base += min(max(-dd, 0) / 60 * 25, 25)
    return min(base, 100)


def _short_reasons(r):
    bits = []
    if r["rsi"] is not None:
        if r["rsi"] <= 30:
            bits.append(f"molto ipervenduto (RSI {r['rsi']:.0f}): dopo cali forti spesso arriva un rimbalzo")
        elif r["rsi"] <= 40:
            bits.append(f"ipervenduto (RSI {r['rsi']:.0f})")
        else:
            bits.append(f"RSI {r['rsi']:.0f} (zona bassa)")
    if r["dd_high"] is not None:
        bits.append(f"sceso {abs(r['dd_high']):.0f}% dai massimi dell'anno")
    if r["below_bb"]:
        bits.append("prezzo a un estremo (sotto la banda di Bollinger)")
    bits.append("trend di fondo ancora positivo" if r["above_sma200"]
                else "⚠️ trend di fondo debole (più rischioso)")
    return " · ".join(bits)


def _discount_score(dd_high):
    if dd_high is None:
        return 0.0
    return min(max(-dd_high, 0) / 40 * 100, 100)   # -40% dal max → 100


def _long_score(r):
    disc = _discount_score(r["dd_high"])
    if r["etf"]:
        return min(disc, 100)
    if r["fscore"] is None:
        return None
    return r["fscore"] * 0.6 + disc * 0.4


def _long_reasons(r):
    bits = []
    if r["etf"]:
        bits.append("ETF diversificato in saldo")
    elif r["fscore"] is not None:
        if r["fscore"] >= 60:
            bits.append(f"buoni fondamentali (punteggio {r['fscore']:.0f}/100)")
        else:
            bits.append(f"fondamentali nella media ({r['fscore']:.0f}/100)")
    if r["dd_high"] is not None:
        bits.append(f"in saldo: {abs(r['dd_high']):.0f}% sotto il massimo dell'anno")
    if r["perf_1y"] is not None:
        bits.append(f"ultimo anno {r['perf_1y']:+.0f}%")
    return " · ".join(bits)


# Universo di riserva: titoli liquidi e diffusi, usato quando le classifiche di mercato
# non sono disponibili (es. FMP esaurito) → le occasioni si calcolano comunque.
_FALLBACK_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "V", "WMT",
    "JNJ", "PG", "KO", "PEP", "DIS", "NFLX", "INTC", "AMD", "BA", "NKE",
    "PFE", "MRK", "XOM", "CVX", "BAC", "CSCO", "ORCL", "CRM", "ADBE", "PYPL",
    "UBER", "PLTR", "F", "GM", "T", "VZ", "QCOM", "TXN", "SBUX", "MCD",
]

_REL_FACTOR = {"🟢 Alta": 1.0, "🟡 Media": 0.85, "🔴 Bassa": 0.7}


def _convenience(r, gain) -> int:
    """Punteggio 0-100 di convenienza: combina prob. salita, guadagno (rimbalzo per il breve,
    atteso per il lungo), rischio di perdita e affidabilità. Centrato su 50;
    l'affidabilità bassa avvicina al neutro (stima incerta)."""
    pg = r["prob_gain"] if r["prob_gain"] is not None else 50
    pl = r["prob_loss"] if r["prob_loss"] is not None else 50
    g = gain if gain is not None else 0
    rf = _REL_FACTOR.get(r["reliab"], 0.8)
    a = (pg - pl) + max(min(g, 40), -20)      # attrattività grezza (~ -120..140)
    base = 50 + 0.45 * a
    conv = 50 + (base - 50) * rf              # affidabilità bassa → verso 50
    return int(round(max(0, min(100, conv))))


_POS_WORDS = set((
    "beat beats surge surges upgrade upgraded growth profit profits rally rallies gain gains "
    "bullish raise raised raises strong record outperform soar soars jump jumps rise rises tops "
    "boost boosts wins win positive optimistic recovery rebound rebounds buy approval expands"
).split())
_NEG_WORDS = set((
    "miss misses plunge plunges downgrade downgraded loss losses lawsuit probe decline declines "
    "cut cuts weak bearish warning warns warn slump slumps fraud recall layoffs falls drop drops "
    "sink sinks tumble tumbles concern concerns risk risks slashed halt investigation negative "
    "crash crashes sell selloff bankruptcy delays delay"
).split())


def news_sentiment(news: list):
    """Tono indicativo delle notizie recenti (parole chiave, gratis). Ritorna (etichetta, score)."""
    import re
    text = " ".join((n.get("title", "") + " " + n.get("summary", "")) for n in news).lower()
    words = re.findall(r"[a-z']+", text)
    pos = sum(1 for w in words if w in _POS_WORDS)
    neg = sum(1 for w in words if w in _NEG_WORDS)
    score = pos - neg
    if pos + neg == 0:
        return "⚪ neutro", 0
    if score >= 2:
        return "🟢 positivo", score
    if score <= -2:
        return "🔴 negativo", score
    return "🟡 misto", score


@st.cache_data(ttl=900, show_spinner=False)
def market_perf_1m() -> float:
    """Performance ~1 mese dell'S&P 500, per contestualizzare i cali dei singoli titoli."""
    h = get_history("^GSPC", period="3mo")
    if h.empty:
        return None
    c = h["Close"].dropna()
    if len(c) <= 21:
        return None
    return float((c.iloc[-1] / c.iloc[-21] - 1) * 100)


@st.cache_data(ttl=900, show_spinner=False)
def opportunity_candidates(kind: str) -> list:
    """Universo di partenza dalle classifiche di mercato; riserva se non disponibili."""
    screens = (["day_losers", "most_actives", "small_cap_gainers"] if kind == "short"
               else ["undervalued_large_caps", "undervalued_growth_stocks", "day_losers"])
    names = []
    for s in screens:
        df = get_screen(s, 12)
        if not df.empty:
            names += [x for x in df["Ticker"].tolist() if x]
    # Per il breve periodo: includi anche titoli economici molto scambiati (anche < 1$),
    # che le classifiche "biggest losers" delle borse principali non mostrano.
    if kind == "short" and _fmp_key():
        pen = _fmp_get("company-screener?isActivelyTrading=true&priceLowerThan=5"
                       "&volumeMoreThan=300000&limit=25")
        if isinstance(pen, list):
            names += [q.get("symbol") for q in pen if q.get("symbol")]
    # Se le classifiche non hanno dato nulla (es. FMP esaurito), usa l'universo di riserva,
    # così le occasioni continuano ad aggiornarsi con i dati di Finnhub/SEC/yfinance.
    if not names:
        names = list(_FALLBACK_UNIVERSE)
    # Breve = 1 chiamata/titolo (si può osare di più); Lungo = ~4 chiamate/titolo (limita la quota FMP)
    cap = 40 if kind == "short" else 20
    return list(dict.fromkeys(names))[:cap]


def scan_opportunities(tickers: list, kind: str) -> pd.DataFrame:
    rows = []
    for t in dict.fromkeys([x for x in tickers if x]):
        try:
            r = opportunity_row(t, with_fundamentals=(kind == "long"))
        except Exception:
            r = None
        if not r:
            continue
        dd = r["dd_high"]
        if kind == "short":
            sc = _short_score(r)
            if sc is None or not np.isfinite(sc) or sc < 35:   # setup da ipervenduto / zona bassa
                continue
            if dd is None or dd > -8:           # dev'essere un calo reale, non un titolo ai massimi
                continue
            gain = r["rebound_pot"] if r["rebound_pot"] is not None else r["exp_ret"]
            rows.append({"Ticker": r["ticker"], "Nome": r["name"], "Convenienza": _convenience(r, gain),
                         "Prezzo": r["price"], "RSI": r["rsi"], "% dal max": dd, "Perf 1 mese": r["perf_1m"],
                         "Occasione": int(round(sc)),
                         "Prob. salita": r["prob_gain"], "Guadagno atteso": gain,
                         "Rischio perdita": r["prob_loss"], "Affidabilità": r["reliab"],
                         "Perché": _short_reasons(r)})
        else:
            sc = _long_score(r)
            if sc is None or not np.isfinite(sc) or sc < 50:
                continue
            if dd is None or dd > -12:          # richiede uno sconto significativo dai massimi
                continue
            rows.append({"Ticker": r["ticker"], "Nome": r["name"],
                         "Convenienza": _convenience(r, r["exp_ret"]),
                         "Prezzo": r["price"], "% dal max": dd, "Perf 1 anno": r["perf_1y"],
                         "Occasione": int(round(sc)),
                         "Prob. salita": r["prob_gain"], "Guadagno atteso": r["exp_ret"],
                         "Rischio perdita": r["prob_loss"], "Affidabilità": r["reliab"],
                         "Perché": _long_reasons(r)})
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Convenienza", ascending=False).set_index("Ticker")
    return df


# ---------------------------------------------------------------------------
# INDICATORI TECNICI
# ---------------------------------------------------------------------------

def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Ritorna (macd_line, signal_line, histogram)."""
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def bollinger(series: pd.Series, window: int = 20, n_std: float = 2.0):
    """Ritorna (media, banda_sup, banda_inf)."""
    mid = sma(series, window)
    std = series.rolling(window=window).std()
    upper = mid + n_std * std
    lower = mid - n_std * std
    return mid, upper, lower


def annualized_volatility(series: pd.Series, periods_per_year: int = 252) -> float:
    """Volatilità annualizzata dai rendimenti giornalieri."""
    returns = series.pct_change().dropna()
    if returns.empty:
        return float("nan")
    return float(returns.std() * np.sqrt(periods_per_year))


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Aggiunge le colonne degli indicatori al dataframe dei prezzi."""
    out = df.copy()
    close = out["Close"]
    out["SMA20"] = sma(close, 20)
    out["SMA50"] = sma(close, 50)
    out["SMA200"] = sma(close, 200)
    out["EMA20"] = ema(close, 20)
    out["RSI"] = rsi(close, 14)
    m, s, h = macd(close)
    out["MACD"] = m
    out["MACD_signal"] = s
    out["MACD_hist"] = h
    mid, up, low = bollinger(close)
    out["BB_mid"] = mid
    out["BB_up"] = up
    out["BB_low"] = low
    return out


# ---------------------------------------------------------------------------
# SEGNALI TECNICI SINTETICI
# ---------------------------------------------------------------------------

def technical_signals(df: pd.DataFrame) -> list:
    """Genera una lista di segnali (etichetta, valore, giudizio) dall'ultima riga."""
    if df.empty:
        return []
    last = df.iloc[-1]
    signals = []

    # Trend rispetto alle medie mobili
    price = last["Close"]
    if not np.isnan(last.get("SMA50", np.nan)):
        if price > last["SMA50"]:
            signals.append(("Prezzo vs SMA50", f"{price:.2f} > {last['SMA50']:.2f}", "positivo"))
        else:
            signals.append(("Prezzo vs SMA50", f"{price:.2f} < {last['SMA50']:.2f}", "negativo"))
    if not np.isnan(last.get("SMA200", np.nan)):
        if price > last["SMA200"]:
            signals.append(("Prezzo vs SMA200 (trend lungo)", f"{price:.2f} > {last['SMA200']:.2f}", "positivo"))
        else:
            signals.append(("Prezzo vs SMA200 (trend lungo)", f"{price:.2f} < {last['SMA200']:.2f}", "negativo"))

    # Golden / death cross
    if not np.isnan(last.get("SMA50", np.nan)) and not np.isnan(last.get("SMA200", np.nan)):
        if last["SMA50"] > last["SMA200"]:
            signals.append(("SMA50 vs SMA200", "Golden cross (rialzista)", "positivo"))
        else:
            signals.append(("SMA50 vs SMA200", "Death cross (ribassista)", "negativo"))

    # RSI
    rsi_val = last.get("RSI", np.nan)
    if not np.isnan(rsi_val):
        if rsi_val >= 70:
            signals.append(("RSI (14)", f"{rsi_val:.1f} — ipercomprato", "negativo"))
        elif rsi_val <= 30:
            signals.append(("RSI (14)", f"{rsi_val:.1f} — ipervenduto", "positivo"))
        else:
            signals.append(("RSI (14)", f"{rsi_val:.1f} — neutro", "neutro"))

    # MACD
    macd_val = last.get("MACD", np.nan)
    sig_val = last.get("MACD_signal", np.nan)
    if not np.isnan(macd_val) and not np.isnan(sig_val):
        if macd_val > sig_val:
            signals.append(("MACD", "Sopra la signal (momentum positivo)", "positivo"))
        else:
            signals.append(("MACD", "Sotto la signal (momentum negativo)", "negativo"))

    return signals


# ---------------------------------------------------------------------------
# METRICHE FONDAMENTALI + GIUDIZI
# ---------------------------------------------------------------------------

def _fmt(value, suffix="", pct=False, decimals=2):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "n/d"
    try:
        if pct:
            return f"{value * 100:.{decimals}f}%"
        return f"{value:,.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return str(value)


def div_yield_fraction(info: dict):
    """yfinance restituisce dividendYield GIÀ in percentuale (es. 2.57 = 2,57%).
    Lo riportiamo a frazione (0.0257) per coerenza con gli altri rapporti."""
    v = info.get("dividendYield")
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v / 100.0


def _fmt_big(value):
    """Formatta numeri grandi (capitalizzazione, ricavi) in K/M/B/T."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "n/d"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    for unit in ["", "K", "M", "B", "T"]:
        if abs(value) < 1000:
            return f"{value:,.2f}{unit}"
        value /= 1000
    return f"{value:,.2f}P"


def fundamental_blocks(info: dict) -> dict:
    """
    Organizza i fondamentali in blocchi tematici con valore formattato e giudizio.
    Ritorna un dict: {nome_blocco: [(etichetta, valore_formattato, giudizio), ...]}
    giudizio ∈ {positivo, negativo, neutro, None}
    """
    def judge(value, good, bad, higher_is_better=True):
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        if higher_is_better:
            if value >= good:
                return "positivo"
            if value <= bad:
                return "negativo"
        else:
            if value <= good:
                return "positivo"
            if value >= bad:
                return "negativo"
        return "neutro"

    pe = info.get("trailingPE")
    fpe = info.get("forwardPE")
    pb = info.get("priceToBook")
    peg = info.get("pegRatio")
    roe = info.get("returnOnEquity")
    roa = info.get("returnOnAssets")
    pmargin = info.get("profitMargins")
    omargin = info.get("operatingMargins")
    d2e = info.get("debtToEquity")
    cratio = info.get("currentRatio")
    qratio = info.get("quickRatio")
    dyield = div_yield_fraction(info)
    payout = info.get("payoutRatio")
    rev_growth = info.get("revenueGrowth")
    earn_growth = info.get("earningsGrowth")

    blocks = {
        "Valutazione (è caro o conveniente?)": [
            ("P/E (prezzo/utili)", _fmt(pe), judge(pe, 15, 35, higher_is_better=False)),
            ("P/E prospettico", _fmt(fpe), judge(fpe, 15, 35, higher_is_better=False)),
            ("P/B (prezzo/patrimonio)", _fmt(pb), judge(pb, 1.5, 4, higher_is_better=False)),
            ("PEG (P/E su crescita)", _fmt(peg), judge(peg, 1, 2, higher_is_better=False)),
        ],
        "Redditività (quanto guadagna bene?)": [
            ("ROE (rendimento capitale proprio)", _fmt(roe, pct=True), judge(roe, 0.15, 0.05)),
            ("ROA (rendimento attività)", _fmt(roa, pct=True), judge(roa, 0.08, 0.02)),
            ("Margine netto", _fmt(pmargin, pct=True), judge(pmargin, 0.10, 0.02)),
            ("Margine operativo", _fmt(omargin, pct=True), judge(omargin, 0.12, 0.03)),
        ],
        "Solidità finanziaria (quanto è esposta?)": [
            ("Debito/Equity", _fmt(d2e), judge(d2e, 100, 250, higher_is_better=False)),
            ("Current ratio (liquidità)", _fmt(cratio), judge(cratio, 1.5, 1)),
            ("Quick ratio", _fmt(qratio), judge(qratio, 1, 0.7)),
        ],
        "Crescita": [
            ("Crescita ricavi (anno)", _fmt(rev_growth, pct=True), judge(rev_growth, 0.10, 0)),
            ("Crescita utili (anno)", _fmt(earn_growth, pct=True), judge(earn_growth, 0.10, 0)),
        ],
        "Dividendo": [
            ("Rendimento dividendo", _fmt(dyield, pct=True), judge(dyield, 0.03, 0)),
            ("Payout ratio (utili distribuiti)", _fmt(payout, pct=True), judge(payout, 0.6, 0.9, higher_is_better=False)),
        ],
    }
    return blocks


def overview_metrics(info: dict, df: pd.DataFrame) -> dict:
    """Metriche per la scheda di panoramica."""
    out = {}
    out["Nome"] = info.get("longName") or info.get("shortName") or "n/d"
    out["Settore"] = info.get("sector", "n/d")
    out["Industria"] = info.get("industry", "n/d")
    out["Paese"] = info.get("country", "n/d")
    out["Valuta"] = info.get("currency", "")
    out["Capitalizzazione"] = _fmt_big(info.get("marketCap"))
    out["Min 52 settimane"] = _fmt(info.get("fiftyTwoWeekLow"))
    out["Max 52 settimane"] = _fmt(info.get("fiftyTwoWeekHigh"))
    out["Beta"] = _fmt(info.get("beta"))
    return out


def screener_row(ticker: str) -> dict:
    """Riga di confronto per lo screener: metriche chiave + punteggio sintetico."""
    info = get_info(ticker)
    df = get_history(ticker, period="1y")

    pe = info.get("trailingPE")
    pb = info.get("priceToBook")
    roe = info.get("returnOnEquity")
    pmargin = info.get("profitMargins")
    d2e = info.get("debtToEquity")
    dyield = div_yield_fraction(info)
    rev_growth = info.get("revenueGrowth")

    perf_1y = np.nan
    vol = np.nan
    if not df.empty and len(df) > 1:
        perf_1y = (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1)
        vol = annualized_volatility(df["Close"])

    # Punteggio sintetico semplice (0-100): premia value + qualità, penalizza debito/volatilità.
    score = 0.0
    n = 0

    def add(cond_value, mapping):
        nonlocal score, n
        if cond_value is None or (isinstance(cond_value, float) and np.isnan(cond_value)):
            return
        score += mapping(float(cond_value))
        n += 1

    add(pe, lambda v: 100 if 0 < v <= 15 else 60 if v <= 25 else 30 if v <= 40 else 10)
    add(pb, lambda v: 100 if 0 < v <= 1.5 else 60 if v <= 3 else 30 if v <= 5 else 10)
    add(roe, lambda v: 100 if v >= 0.20 else 70 if v >= 0.12 else 40 if v >= 0.05 else 10)
    add(pmargin, lambda v: 100 if v >= 0.20 else 70 if v >= 0.10 else 40 if v >= 0.03 else 10)
    add(d2e, lambda v: 100 if v <= 50 else 70 if v <= 100 else 40 if v <= 200 else 10)
    add(rev_growth, lambda v: 100 if v >= 0.15 else 70 if v >= 0.05 else 40 if v >= 0 else 10)

    final_score = round(score / n, 1) if n > 0 else np.nan

    return {
        "Ticker": ticker.upper(),
        "Nome": (info.get("shortName") or info.get("longName") or "n/d")[:45],
        "Prezzo": info.get("currentPrice") or (df["Close"].iloc[-1] if not df.empty else np.nan),
        "P/E": pe,
        "P/B": pb,
        "ROE": roe,
        "Margine": pmargin,
        "Deb/Eq": d2e,
        "Div%": dyield,
        "Cresc.ricavi": rev_growth,
        "Perf.1A": perf_1y,
        "Volatilità": vol,
        "Punteggio": final_score,
    }
