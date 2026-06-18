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
def get_info(ticker: str, merge: bool = False) -> dict:
    """Metadati/fondamentali.
    merge=False → prima fonte utile (leggero, per lo scanner delle occasioni).
    merge=True  → combina FMP + Finnhub + SEC + yfinance riempiendo i campi mancanti
                  (per la pagina di analisi: meno «n/d» possibile)."""
    if not merge:
        if _fmp_key():
            fmp = info_from_fmp(ticker)
            if fmp:
                return fmp
        if _finnhub_key():
            fh = info_from_finnhub(ticker)
            if fh and len(fh) > 3:
                return fh
        sec = fundamentals_from_sec(ticker)
        if sec and len(sec) > 3:
            return sec
        try:
            return yf.Ticker(ticker).info or {}
        except Exception:
            return {}

    # merge: priorità FMP > Finnhub > SEC > yfinance; ogni fonte riempie i buchi.
    # Ogni fonte è protetta: se una fallisce, le altre continuano (niente crash).
    def _safe(fn):
        try:
            r = fn()
            return r if isinstance(r, dict) else {}
        except Exception:
            return {}

    sources = [
        _safe(lambda: info_from_fmp(ticker) if _fmp_key() else {}),
        _safe(lambda: info_from_finnhub(ticker) if _finnhub_key() else {}),
        _safe(lambda: fundamentals_from_sec(ticker)),
        _safe(lambda: yf.Ticker(ticker).info or {}),
    ]
    out = {}
    for src in sources:
        for k, v in src.items():
            if v is None:
                continue
            if isinstance(v, float) and v != v:        # NaN
                continue
            if isinstance(v, str) and v.strip() == "":
                continue
            cur = out.get(k)
            if cur is None or (isinstance(cur, str) and cur.strip() == ""):
                out[k] = v
    # PEG calcolato se mancante: P/E ÷ (crescita utili in %)
    if not out.get("pegRatio"):
        pe = out.get("trailingPE")
        g = out.get("earningsGrowth") or out.get("revenueGrowth")
        try:
            if pe and g and float(g) > 0:
                out["pegRatio"] = round(float(pe) / (float(g) * 100), 2)
        except (TypeError, ValueError):
            pass
    return out


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
    info["priceToSalesRatio"] = num(r.get("priceToSalesRatioTTM"))
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


def verify_with_sec(ticker: str, info: dict) -> dict:
    """Controllo incrociato: confronta i valori mostrati (freschi) con i bilanci UFFICIALI SEC.
    Ritorna {checked, coerenti, rows:[(label, valore_app, valore_sec, ok)]} o None (non-USA)."""
    sec = fundamentals_from_sec(ticker)
    if not sec or len(sec) <= 3:
        return None
    campi = [
        ("returnOnEquity", "ROE", True),
        ("profitMargins", "Margine netto", True),
        ("debtToEquity", "Debito/Equity", False),
        ("revenueGrowth", "Crescita ricavi", True),
        ("priceToBook", "P/B", False),
        ("trailingPE", "P/E", False),
    ]
    rows, coer, tot = [], 0, 0
    for key, label, is_pct in campi:
        a, s = info.get(key), sec.get(key)
        if a is None or s is None:
            continue
        try:
            a, s = float(a), float(s)
        except (TypeError, ValueError):
            continue
        tot += 1
        rel = abs(a - s) / max(abs(s), 1e-9)
        ok = ((a >= 0) == (s >= 0)) and rel <= 0.40   # stesso segno e scarto < 40% (TTM vs annuale)
        if ok:
            coer += 1
        fmt = (lambda x: f"{x * 100:.1f}%") if is_pct else (lambda x: f"{x:.2f}")
        rows.append((label, fmt(a), fmt(s), ok))
    if tot == 0:
        return None
    return {"checked": tot, "coerenti": coer, "rows": rows}


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
        if rev and rev > 0:
            info["priceToSalesRatio"] = price * shares / rev
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
    info["priceToSalesRatio"] = num(m.get("psTTM") or m.get("psAnnual"))
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


def get_news_finnhub(ticker: str, count: int = 8, day: str = None) -> list:
    if day:                              # un giorno specifico → chiedo direttamente quel giorno
        frm = to = day
    else:
        today = datetime.date.today()
        frm = (today - datetime.timedelta(days=21)).isoformat()
        to = today.isoformat()
    data = _finnhub_get(f"company-news?symbol={ticker}&from={frm}&to={to}")
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
def get_news(ticker: str, count: int = 8, day: str = None) -> list:
    """Notizie legate a un ticker, ordinate dalla più recente. Ritorna dict normalizzati.
    Fonte primaria: Finnhub (no Yahoo); riserva yfinance (es. indici tipo ^GSPC).
    day = 'YYYY-MM-DD' → notizie di quel giorno specifico (interroga la fonte su quella data).
    Ogni voce ha 'ts' (per ordinare/filtrare) e 'date' (YYYY-MM-DD)."""
    if _finnhub_key():
        fh = get_news_finnhub(ticker, count, day=day)
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
    if day:                                          # riserva yfinance: filtra il giorno (solo recenti)
        out = [x for x in out if x["date"] == day]
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


# ETF noti (USA + i principali europei della tabella TER): riconoscimento robusto
# anche quando la fonte non indica il tipo (es. Finnhub sul cloud).
_KNOWN_ETFS = set(EU_ETF_TER.keys()) | {
    "SPY", "VOO", "IVV", "QQQ", "VTI", "VEA", "VWO", "AGG", "BND", "GLD", "IWM", "EFA",
    "VUG", "VTV", "VIG", "SCHD", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU",
    "ARKK", "DIA", "TLT", "HYG", "LQD", "VNQ", "VXUS", "VT", "VYM", "VGT", "SOXX", "SMH",
    "EEM", "SLV", "VUSA.MI",
}


def is_known_etf(ticker: str) -> bool:
    return (ticker or "").upper() in _KNOWN_ETFS


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


def _fund_data_from_fmp(ticker: str, out: dict) -> None:
    """Riempie composizione ETF (settori, principali titoli, TER, patrimonio) da FMP quando
    yfinance non la fornisce (es. sul cloud). Best effort: silenzioso se la quota è esaurita
    o l'endpoint non risponde."""
    if not _fmp_key():
        return
    sym = ticker.upper()

    if out["expense_ratio"] is None or not out["total_assets"]:
        einfo = _first(_fmp_get(f"etf-info?symbol={sym}"))
        if isinstance(einfo, dict) and einfo:
            er = einfo.get("expenseRatio") or einfo.get("netExpenseRatio")
            if er and out["expense_ratio"] is None:
                try:
                    er = float(er)
                    out["expense_ratio"] = er / 100 if er > 0.02 else er
                    out["expense_ratio_source"] = "FMP"
                except (TypeError, ValueError):
                    pass
            out["total_assets"] = out["total_assets"] or einfo.get("assetsUnderManagement") or einfo.get("aum")
            out["category"] = out["category"] or einfo.get("category")
            out["family"] = out["family"] or einfo.get("etfCompanyName") or einfo.get("domicile")
            out["description"] = out["description"] or einfo.get("description") or ""

    def _pct(w):
        try:
            return round(float(str(w).replace("%", "").strip()) / 100, 4)
        except (TypeError, ValueError):
            return None

    if not out["sector_weightings"]:
        sw = _fmp_get(f"etf-sector-weightings?symbol={sym}")
        if isinstance(sw, list):
            d = {}
            for s in sw:
                if not isinstance(s, dict):
                    continue
                nm = s.get("sector") or s.get("industry")
                v = _pct(s.get("weightPercentage", s.get("weight")))
                if nm and v is not None:
                    d[nm] = v
            if d:
                out["sector_weightings"] = d

    if not out["top_holdings"]:
        h = _fmp_get(f"etf-holdings?symbol={sym}")
        if isinstance(h, list) and h:
            rows = []
            for x in h[:10]:
                if not isinstance(x, dict):
                    continue
                s = x.get("asset") or x.get("symbol") or ""
                nm = x.get("name") or ""
                v = _pct(x.get("weightPercentage", x.get("pctVal", x.get("weight"))))
                rows.append((s, nm, v if v is not None else 0.0))
            if rows:
                out["top_holdings"] = rows


@st.cache_data(ttl=900, show_spinner=False)
def get_fund_data(ticker: str, base_info: dict = None) -> dict:
    """Dati specifici di ETF/fondi: composizione, settori, titoli, costi, patrimonio.
    base_info = info già recuperato (merge) per riconoscere l'ETF e ricavare patrimonio
    anche quando yfinance è bloccato sul cloud."""
    out = {
        "is_fund": False, "category": None, "family": None, "legal_type": None,
        "expense_ratio": None, "expense_ratio_source": None, "total_assets": None, "yield": None,
        "description": "", "asset_classes": {}, "sector_weightings": {}, "top_holdings": [],
    }
    base_info = base_info or {}
    t = None
    info = {}
    try:
        t = yf.Ticker(ticker)            # BUGFIX: serve l'oggetto Ticker per funds_data (prima mancava)
        info = t.info or {}
    except Exception:
        info = {}

    # È un fondo? (yfinance, info già recuperato, o lista nota) — robusto anche sul cloud
    if not (is_fund(info) or is_fund(base_info) or is_known_etf(ticker)):
        return out
    out["is_fund"] = True
    out["category"] = info.get("category") or base_info.get("category")
    out["total_assets"] = info.get("totalAssets") or base_info.get("marketCap")
    out["description"] = base_info.get("longBusinessSummary") or ""
    # TER / costo: yfinance lo espone con nomi diversi (spesso assente per ETF europei)
    out["expense_ratio"] = (
        info.get("annualReportExpenseRatio")
        or info.get("netExpenseRatio")
        or info.get("expenseRatio")
        or EU_ETF_TER.get(ticker.upper())
    )
    # Normalizza a frazione: se >0.02 è quasi certamente già in % (es. yfinance 0.0945 → 0.000945)
    if out["expense_ratio"] is not None and out["expense_ratio"] > 0.02:
        out["expense_ratio"] = out["expense_ratio"] / 100
    out["expense_ratio_source"] = (
        "tabella interna" if (not info.get("annualReportExpenseRatio")
                              and not info.get("netExpenseRatio")
                              and not info.get("expenseRatio")
                              and ticker.upper() in EU_ETF_TER) else "yfinance"
    )
    out["yield"] = info.get("yield")

    # Composizione da yfinance (funziona in locale; spesso bloccata sul cloud)
    if t is not None:
        try:
            fd = t.funds_data
            ov = fd.fund_overview or {}
            out["category"] = out["category"] or ov.get("categoryName")
            out["family"] = ov.get("family")
            out["legal_type"] = ov.get("legalType")
            out["description"] = fd.description or out["description"]
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

    # Fallback FMP quando la composizione resta vuota (es. cloud): best effort,
    # funziona solo se la quota FMP non è esaurita.
    if not out["sector_weightings"] or not out["top_holdings"]:
        try:
            _fund_data_from_fmp(ticker, out)
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
    "P/S (prezzo/vendite)": "Prezzo rispetto ai ricavi (fatturato). Utile quando l'azienda ha pochi o nessun utile. Più basso = più conveniente; sotto 2 è contenuto, sopra 6 è alto.",
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
    pos = sum(1 for r in all_rows if r[2] == "positivo")
    neg = sum(1 for r in all_rows if r[2] == "negativo")
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
    pos = sum(1 for r in rows if r[2] == "positivo")
    neg = sum(1 for r in rows if r[2] == "negativo")
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
# DATA LAYER — persistenza condivisa tra l'app (anche da telefono) e il job
# autonomo che gira su GitHub Actions ogni 15 min (anche a PC spento).
#
# Modello: il job scrive i dati (occasioni osservate + monitoraggio) su un
# branch dedicato del repo (default "auto-data"); l'app li LEGGE da lì via URL
# raw, così vede sempre l'ultimo aggiornamento ovunque. In locale (senza repo
# configurato) tutto resta su file, come prima.
#
# Configurazione (st.secrets o variabili d'ambiente):
#   data_repo   = "utente/repo"   (DATA_REPO)   → attiva la modalità cloud in lettura
#   data_branch = "auto-data"     (DATA_BRANCH) → branch dei dati (default auto-data)
#   github_token = "ghp_..."      (GITHUB_TOKEN)→ opzionale: permette all'app di
#                                   salvare anche da telefono (commit via API)
# ---------------------------------------------------------------------------

APPDIR = os.path.dirname(os.path.abspath(__file__))


def _cfg(secret_key, env_key, default=""):
    try:
        v = st.secrets[secret_key]
        if v:
            return v
    except Exception:
        pass
    return os.environ.get(env_key, default)


def _data_repo():
    return _cfg("data_repo", "DATA_REPO", "")


def _data_branch():
    return _cfg("data_branch", "DATA_BRANCH", "auto-data")


def _github_token():
    return _cfg("github_token", "GITHUB_TOKEN", "")


def cloud_mode() -> bool:
    """True se è configurato un repo dati: l'app legge i dati aggiornati dal job
    autonomo invece di calcolarli da sola."""
    return bool(_data_repo())


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_remote_json(url: str):
    import requests
    r = requests.get(url, timeout=10)
    if r.status_code == 200:
        return r.json()
    return None


def _read_local_json(name: str):
    try:
        with open(os.path.join(APPDIR, name), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def read_data_json(name: str, default):
    """Legge un file dati. Normalmente preferisce il branch remoto (cache 2 min)
    con fallback locale. Nel job autonomo (env DATA_LOCAL_FIRST=1) preferisce il
    file locale, così legge ciò che ha appena scritto (read-your-writes),
    usando il remoto solo come storico iniziale."""
    local_first = os.environ.get("DATA_LOCAL_FIRST") == "1"
    if local_first:
        d = _read_local_json(name)
        if d is not None:
            return d
    repo = _data_repo()
    if repo:
        url = f"https://raw.githubusercontent.com/{repo}/{_data_branch()}/{name}"
        try:
            data = _fetch_remote_json(url)
            if data is not None:
                return data
        except Exception:
            pass
    d = _read_local_json(name)
    return d if d is not None else default


def _commit_to_github(name: str, content_str: str) -> bool:
    """Salva il file sul branch dati via API GitHub (serve un token con permesso
    'contents'). Ritorna True se ok. Usato dall'app per rendere persistenti da
    telefono le scelte manuali (segui/smetti)."""
    repo, token, branch = _data_repo(), _github_token(), _data_branch()
    if not (repo and token):
        return False
    import base64
    import requests
    api = f"https://api.github.com/repos/{repo}/contents/{name}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    try:
        # SHA attuale del file sul branch (necessario per aggiornarlo)
        sha = None
        g = requests.get(f"{api}?ref={branch}", headers=headers, timeout=10)
        if g.status_code == 200:
            sha = g.json().get("sha")
        body = {"message": f"app update {name}", "branch": branch,
                "content": base64.b64encode(content_str.encode("utf-8")).decode("ascii")}
        if sha:
            body["sha"] = sha
        p = requests.put(api, headers=headers, json=body, timeout=12)
        return p.status_code in (200, 201)
    except Exception:
        return False


def write_data_json(name: str, obj) -> None:
    """Scrive un file dati: sempre su file locale; se in modalità cloud con token,
    anche sul branch remoto (così la modifica persiste e si vede dal telefono)."""
    content = json.dumps(obj, ensure_ascii=False, indent=0)
    try:
        with open(os.path.join(APPDIR, name), "w", encoding="utf-8") as f:
            f.write(content)
    except Exception:
        pass
    if _data_repo() and _github_token():
        _commit_to_github(name, content)
    # invalida la cache di lettura remota così la modifica si vede subito
    try:
        _fetch_remote_json.clear()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# NOTIFICHE — Telegram (gratis, push istantaneo sul telefono).
# Token e chat_id in st.secrets o env: telegram_bot_token / telegram_chat_id
# (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID). Usato dal job autonomo per avvisare
# quando un'occasione viene promossa automaticamente.
# ---------------------------------------------------------------------------

def _telegram_cfg():
    return (_cfg("telegram_bot_token", "TELEGRAM_BOT_TOKEN", ""),
            _cfg("telegram_chat_id", "TELEGRAM_CHAT_ID", ""))


def send_telegram_verbose(text: str):
    """Invia un messaggio Telegram. Ritorna (ok, dettaglio) per la diagnosi.
    Il dettaglio NON contiene mai il token (sicuro da scrivere nei log)."""
    token, chat_id = _telegram_cfg()
    if not token:
        return False, "token mancante (Secret TELEGRAM_BOT_TOKEN non impostato)"
    if not chat_id:
        return False, "chat_id mancante (Secret TELEGRAM_CHAT_ID non impostato)"
    import requests
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=12,
        )
        try:
            j = r.json()
        except Exception:
            j = {}
        if r.status_code == 200 and j.get("ok"):
            return True, "inviato correttamente"
        return False, f"HTTP {r.status_code}: {j.get('description', (r.text or '')[:140])}"
    except Exception as e:
        return False, f"eccezione di rete: {e!r}"


def send_telegram(text: str) -> bool:
    """Invia un messaggio Telegram. Ritorna True se inviato. No-op se non configurato."""
    ok, _ = send_telegram_verbose(text)
    return ok


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
    perf_5d = _nn((price / float(h["Close"].iloc[-6]) - 1) * 100) if len(h) > 5 else None  # momentum recente
    perf_1y = _nn((price / float(h["Close"].iloc[0]) - 1) * 100)
    bb_low = last.get("BB_low", np.nan)
    below_bb = bool(price <= bb_low) if not np.isnan(bb_low) else False
    sma200 = last.get("SMA200", np.nan)
    above_sma200 = bool(price > sma200) if not np.isnan(sma200) else None

    # Potenziale di rimbalzo e bersaglio (ritorno alla media a 50 giorni)
    sma50 = last.get("SMA50", np.nan)
    rebound_pot = _nn((sma50 / price - 1) * 100) if (not np.isnan(sma50) and price) else None
    target_price = float(sma50) if not np.isnan(sma50) else None

    # --- ATR e livelli operativi tarati sulla volatilità reale del titolo ---
    # Stop = prezzo − k·ATR (anziché il minimo a 20gg, che ignora la volatilità):
    # setup confrontabili e dimensionabili. Bersaglio = media 50gg (mean reversion).
    atr_ser = atr(h, 14)
    atr_val = float(atr_ser.iloc[-1]) if not np.isnan(atr_ser.iloc[-1]) else None
    atr_pct = _nn(atr_val / price * 100) if (atr_val and price) else None
    if atr_val and atr_val > 0:
        stop_price = price - _ATR_STOP_K * atr_val
    else:
        stop_price = float(h["Close"].tail(20).min())     # ripiego se ATR non calcolabile
    # Rapporto Rischio/Rendimento: reward = (bersaglio − prezzo), risk = (prezzo − stop)
    rr = None
    if target_price and stop_price and price > stop_price and target_price > price:
        rr = round((target_price - price) / (price - stop_price), 2)

    # --- Volume / RVOL: il dato più sottoutilizzato. Conferma capitolazione + ripartenza ---
    rvol = avg_dollar_vol = None
    if "Volume" in h.columns:
        vol = pd.to_numeric(h["Volume"], errors="coerce")
        avg20 = float(vol.tail(20).mean()) if vol.tail(20).notna().any() else None
        last_vol = float(vol.iloc[-1]) if not np.isnan(vol.iloc[-1]) else None
        if avg20 and avg20 > 0 and last_vol is not None:
            rvol = round(last_vol / avg20, 2)
        if avg20 and avg20 > 0:
            avg_dollar_vol = avg20 * price                 # liquidità ~ $ scambiati al giorno

    # --- Conferma d'inversione: non chiamarlo "rimbalzo" finché non ha GIRATO ---
    prev = h.iloc[-2] if len(h) >= 2 else None
    prev_close = float(prev["Close"]) if (prev is not None and not np.isnan(prev["Close"])) else None
    green_day = bool(prev_close is not None and price > prev_close)     # primo giorno verde
    prev_rsi = float(prev["RSI"]) if (prev is not None and not np.isnan(prev.get("RSI", np.nan))) else None
    rsi_rising = bool(rsi is not None and prev_rsi is not None and rsi > prev_rsi)
    prev_bb_low = float(prev["BB_low"]) if (prev is not None and not np.isnan(prev.get("BB_low", np.nan))) else None
    back_in_bb = bool(prev_close is not None and prev_bb_low is not None
                      and prev_close <= prev_bb_low and not np.isnan(bb_low) and price > bb_low)
    reversal_confirmed = bool(green_day and (rsi_rising or back_in_bb))
    # Crollo verticale ancora in caduta (coltello che cade): −15% in 5gg e oggi ancora giù
    vertical_crash = bool(perf_5d is not None and perf_5d < -15 and not green_day)

    spark = [round(float(x), 4) for x in h["Close"].tail(60).tolist()]          # mini-grafico (prezzi)
    spark_dates = [str(d.date()) for d in h.index[-60:]]                         # date per l'asse x

    # Probabilità statistiche (modello normale sui rendimenti storici, drift smorzato).
    # Orizzonte: breve ~1 mese, lungo ~1 anno. NON è una previsione: è una stima dal passato.
    prob_gain, prob_loss, exp_ret, reliab = _gain_loss_prob(
        h, horizon_days=(252 if with_fundamentals else 21))

    # Fattori di rischio/qualità dalla serie storica + affidabilità continua
    rfac = _risk_factors(h)
    reliab_factor = _reliab_factor(rfac.get("sig_a"), rfac.get("n"))

    etf, fscore, name = False, None, ticker
    sector, pe, pb, ps = None, None, None, None
    if with_fundamentals:                    # solo per il lungo periodo (qualità)
        info = get_info(ticker)
        etf = is_fund(info) or is_known_etf(ticker)   # riconosce gli ETF anche sul cloud
        fscore = _fundamental_score(info) if not etf else None
        name = (info.get("shortName") or info.get("longName") or ticker)[:34]
        sector = info.get("sector")
        pe = _nn(info.get("trailingPE"))
        pb = _nn(info.get("priceToBook"))
        ps = _nn(info.get("priceToSalesRatio"))

    return dict(ticker=ticker.upper(), name=name, price=price, rsi=rsi, dd_high=dd_high,
                perf_1m=perf_1m, perf_5d=perf_5d, perf_1y=perf_1y, below_bb=below_bb,
                above_sma200=above_sma200,
                etf=etf, fscore=fscore, prob_gain=prob_gain, prob_loss=prob_loss,
                exp_ret=exp_ret, reliab=reliab, reliab_factor=reliab_factor, rebound_pot=rebound_pot,
                sharpe=rfac.get("sharpe"), sortino=rfac.get("sortino"), ulcer=rfac.get("ulcer"),
                maxdd=rfac.get("maxdd"), hist_z=rfac.get("hist_z"),
                sector=sector, pe=pe, pb=pb, ps=ps,
                atr=atr_val, atr_pct=atr_pct, rr=rr, rvol=rvol, avg_dollar_vol=avg_dollar_vol,
                green_day=green_day, rsi_rising=rsi_rising, back_in_bb=back_in_bb,
                reversal_confirmed=reversal_confirmed, vertical_crash=vertical_crash,
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


def _risk_factors(h) -> dict:
    """Fattori rischio/qualità dalla serie prezzi: Sharpe, Sortino, Ulcer index, max drawdown,
    z-score del prezzo vs la propria storia (negativo = sotto la sua media = a sconto),
    volatilità annua e n. osservazioni. Tutto dai dati già scaricati (nessuna chiamata extra)."""
    out = {"sharpe": None, "sortino": None, "ulcer": None, "maxdd": None,
           "hist_z": None, "sig_a": None, "n": 0}
    try:
        closes = h["Close"].dropna()
        logret = np.log(closes / closes.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
    except Exception:
        return out
    n = len(logret)
    out["n"] = n
    if n < 30:
        return out
    dmean, dstd = float(logret.mean()), float(logret.std())
    out["sig_a"] = dstd * (252 ** 0.5)
    rf_daily = 0.03 / 252.0                      # risk-free ~3% annuo
    if dstd > 0:
        out["sharpe"] = round(((dmean - rf_daily) * 252) / (dstd * (252 ** 0.5)), 2)
    downside = logret[logret < 0]
    dd_std = float(downside.std()) if len(downside) > 2 else dstd
    if dd_std > 0:
        out["sortino"] = round(((dmean - rf_daily) * 252) / (dd_std * (252 ** 0.5)), 2)
    runmax = closes.cummax()
    ddser = (closes / runmax - 1.0) * 100.0      # drawdown % (<= 0)
    out["maxdd"] = round(float(ddser.min()), 1)
    out["ulcer"] = round(float(((ddser ** 2).mean()) ** 0.5), 2)   # Ulcer Index (penalità dolore)
    pmean, pstd = float(closes.mean()), float(closes.std())
    if pstd > 0:
        out["hist_z"] = round((float(closes.iloc[-1]) - pmean) / pstd, 2)
    return out


def _reliab_factor(sig_a, n) -> float:
    """Affidabilità CONTINUA in [0.6, 1.0] (niente gradini con soglie dure): alta con bassa
    volatilità e storico lungo. Smorza la convenienza verso 50 quando la stima è incerta."""
    if sig_a is None or not n:
        return 0.75
    vol_score = max(0.5, min(1.0, 1.0 - max(0.0, sig_a - 0.30) / 0.90))   # vol 30%→1.0, 120%→0.5
    hist_score = max(0.5, min(1.0, n / 250.0))
    return round(max(0.6, min(1.0, vol_score * 0.7 + hist_score * 0.3)), 3)


# --- Parametri operativi del breve periodo (rimbalzo / ipervenduto) ---
_ATR_STOP_K = 2.0          # stop = prezzo − k·ATR (volatilità reale, non minimo a 20gg)
_RR_MIN = 1.5              # scarta i setup con Rischio/Rendimento sotto questa soglia
_MIN_PRICE = 3.0           # sotto questo prezzo l'RSI è inaffidabile (penny) → escluso
_MIN_DOLLAR_VOL = 1_000_000  # liquidità minima (~$ scambiati/giorno) → niente illiquidi


def _short_score(r, regime=1.0):
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

    # --- Conferma d'inversione: premia chi ha GIÀ girato, penalizza chi sta ancora scendendo ---
    if r.get("reversal_confirmed"):
        base += 14                           # chiusura verde + RSI in risalita / rientro in Bollinger
    elif r.get("green_day") is False:
        base -= 18                           # ancora in calo oggi → non segnalare BUY (coltello che cade)
    # --- Conferma di volume (capitolazione + ripartenza): il dato più sottoutilizzato ---
    rv = r.get("rvol")
    if rv is not None and r.get("green_day"):
        if rv >= 1.5:
            base += 10                       # forte volume sul giorno verde = ripartenza credibile
        elif rv >= 1.2:
            base += 5
    # --- Crollo verticale ancora in caduta: declassa (non è un saldo, è una frana) ---
    if r.get("vertical_crash"):
        base -= 22

    base = max(0.0, min(base, 100))
    return base * float(regime)              # regime di volatilità: in un crash il rimbalzo è meno affidabile


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
    # Conferma d'inversione (il rimedio al «coltello che cade»)
    if r.get("vertical_crash"):
        bits.append("⚠️ crollo verticale ancora in caduta (coltello che cade)")
    elif r.get("reversal_confirmed"):
        bits.append("✅ inversione confermata (giorno verde + RSI in risalita / rientro in Bollinger)")
    elif r.get("green_day") is False:
        bits.append("⏳ ancora in calo: nessuna conferma di rimbalzo")
    # Conferma di volume
    rv = r.get("rvol")
    if rv is not None and r.get("green_day") and rv >= 1.2:
        bits.append(f"volume {rv:.1f}× la media (ripartenza con scambi sopra la norma)")
    # Rischio/Rendimento
    if r.get("rr") is not None:
        bits.append(f"rapporto rischio/rendimento ~{r['rr']:.1f}")
    bits.append("trend di fondo ancora positivo" if r["above_sma200"]
                else "⚠️ trend di fondo debole (più rischioso)")
    return " · ".join(bits)


def _short_confirm_label(r) -> str:
    """Etichetta sintetica dello stato di conferma dell'inversione (per la tabella)."""
    if r.get("vertical_crash"):
        return "⚠️ in caduta"
    if r.get("reversal_confirmed"):
        return "✅ confermata"
    if r.get("green_day"):
        return "🟢 1° verde"
    return "⏳ non ancora"


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

# Universo Borsa Italiana / Europa (le classifiche di mercato gratuite coprono solo gli USA,
# quindi i titoli europei li scansioniamo da questa lista curata di nomi liquidi).
_FALLBACK_UNIVERSE_EU = [
    # Italia (FTSE MIB)
    "ENI.MI", "ISP.MI", "UCG.MI", "ENEL.MI", "STLAM.MI", "RACE.MI", "G.MI", "STMMI.MI",
    "TIT.MI", "LDO.MI", "BAMI.MI", "BMED.MI", "MB.MI", "CPR.MI", "MONC.MI", "PST.MI",
    "SRG.MI", "TRN.MI", "A2A.MI", "PIRC.MI", "UNI.MI", "AMP.MI", "BPE.MI", "FBK.MI",
    # Europa (principali blue chip)
    "ASML.AS", "SAP.DE", "SIE.DE", "AIR.PA", "MC.PA", "OR.PA", "SAN.PA", "TTE.PA",
    "VOW3.DE", "BAYN.DE", "BMW.DE", "ALV.DE", "BNP.PA", "AD.AS", "ENGI.PA", "DTE.DE",
]

# ETF liquidi (USA + UCITS europei) inclusi nella ricerca occasioni: le classifiche di
# mercato gratuite contengono soprattutto azioni, quindi gli ETF vanno aggiunti a parte.
_ETF_UNIVERSE = [
    "SPY", "QQQ", "VOO", "VTI", "IWM", "DIA", "VEA", "VWO", "EFA", "EEM",
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLU", "SMH", "SOXX", "ARKK",
    "GLD", "SLV", "TLT", "HYG", "LQD", "AGG", "BND", "VNQ", "SCHD", "VYM",
    "CSSPX.MI", "SWDA.MI", "VWCE.DE", "EIMI.MI", "EUNL.DE", "AGGH.MI",
]

_REL_FACTOR = {"🟢 Alta": 1.0, "🟡 Media": 0.85, "🔴 Bassa": 0.7}


# ---------------------------------------------------------------------------
# CONVENIENZA v2 — punteggio 0-100 «da saldo» costruito su fattori STANDARDIZZATI
# con z-score robusti (mediana/MAD) cross-sezionali sull'universo scansionato, con
# valutazione relativa al SETTORE e allo STORICO del titolo, fattori di rischio
# (Sharpe/Sortino/Ulcer) e affidabilità continua. Pesi su fattori comparabili (z-score).
# ---------------------------------------------------------------------------

CONV_STATS_NAME = "conv_stats.json"   # statistiche dell'ultimo scan (per la versione single-ticker)

_CONV_WEIGHTS = {
    "short": {"oversold": 1.0, "rebound": 0.8, "momentum": 0.7, "discount": 0.5,
              "riskadj": 0.4, "ddpen": 0.5, "histcheap": 0.4, "trend": 0.4, "prob": 0.2},
    "long":  {"quality": 1.0, "valcheap": 0.9, "discount": 0.6, "histcheap": 0.5,
              "riskadj": 0.4, "ddpen": 0.4, "momentum": 0.4, "prob": 0.4},
}
_CONV_K = 11.0   # scala z-score → punti di convenienza


def _robust(vals):
    """(mediana, MAD scalato) robusti agli outlier; fallback a deviazione std, poi a 1.0."""
    arr = [v for v in vals if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if len(arr) < 3:
        return (0.0, 1.0)
    med = float(np.median(arr))
    mad = float(np.median([abs(x - med) for x in arr])) * 1.4826
    if mad <= 1e-9:
        sd = float(np.std(arr))
        mad = sd if sd > 1e-9 else 1.0
    return (med, mad)


def _zc(x, stats):
    """z-score robusto limitato a ±3 (None → 0 = neutro)."""
    if x is None or stats is None:
        return 0.0
    med, mad = stats
    try:
        return max(-3.0, min(3.0, (float(x) - med) / mad))
    except (TypeError, ValueError):
        return 0.0


def _factor_values(r, kind) -> dict:
    """Valori GREZZI dei fattori (più alto = più conveniente). valcheap (settoriale) si riempie a parte."""
    dd = r.get("dd_high")
    mom = r.get("perf_5d")
    mom = r.get("perf_1m") if mom is None else mom
    prob = (r["prob_gain"] - r["prob_loss"]) if (r.get("prob_gain") is not None and r.get("prob_loss") is not None) else None
    f = {
        "discount": (-dd) if dd is not None else None,          # più sceso = più a sconto
        "histcheap": (-r["hist_z"]) if r.get("hist_z") is not None else None,  # sotto la propria media
        "riskadj": r.get("sortino"),                            # sale "pulito"
        "ddpen": (-r["ulcer"]) if r.get("ulcer") is not None else None,        # meno dolore (Ulcer)
        "momentum": (-mom) if mom is not None else None,        # valore: prezzo giù = bonus
        "prob": prob,
    }
    if kind == "short":
        f["oversold"] = (-r["rsi"]) if r.get("rsi") is not None else None
        f["rebound"] = r.get("rebound_pot")
        av = r.get("above_sma200")
        f["trend"] = 1.0 if av else (-1.0 if av is False else None)
    else:
        f["quality"] = r.get("fscore")
        f["valcheap"] = None    # riempito da _fill_valcheap (z relativo al settore)
    return f


def _fill_valcheap(items, facs):
    """Per il lungo: 'convenienza di valutazione' = z robusto, RELATIVO AL SETTORE, della
    convenienza dei multipli (-P/E, -P/B, -P/S). Settori con <5 titoli → statistica globale."""
    def cheap(m):
        return (-m) if (m is not None and m > 0) else None
    glob = {k: _robust([cheap(r.get(k)) for r in items]) for k in ("pe", "pb", "ps")}
    by_sec = {}
    for r in items:
        by_sec.setdefault(r.get("sector") or "_NA_", []).append(r)
    sec_stats = {sec: {k: _robust([cheap(r.get(k)) for r in rs]) for k in ("pe", "pb", "ps")}
                 for sec, rs in by_sec.items() if len(rs) >= 5}
    for r, f in zip(items, facs):
        st = sec_stats.get(r.get("sector") or "_NA_", glob)
        zs = [_zc(cheap(r.get(k)), st.get(k, glob[k])) for k in ("pe", "pb", "ps") if cheap(r.get(k)) is not None]
        f["valcheap"] = (sum(zs) / len(zs)) if zs else None


def _conv_from_factors(f, weights, stats, k, reliab_factor) -> int:
    raw = sum(weights[fk] * _zc(f.get(fk), stats.get(fk)) for fk in weights)
    conv = 50 + k * raw
    conv = 50 + (conv - 50) * (reliab_factor or 0.75)     # affidabilità continua → verso 50
    return int(round(max(0, min(100, conv))))


def _load_conv_stats() -> dict:
    try:
        with open(os.path.join(APPDIR, CONV_STATS_NAME), "r", encoding="utf-8") as fp:
            d = json.load(fp)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_conv_stats(kind, payload) -> None:
    d = _load_conv_stats()
    d[kind] = payload
    try:   # solo file locale (NON sul repo): serve a questo processo per gli snapshot single-ticker
        with open(os.path.join(APPDIR, CONV_STATS_NAME), "w", encoding="utf-8") as fp:
            json.dump(d, fp, ensure_ascii=False)
    except Exception:
        pass


def _score_universe(rlist, kind):
    """Calcola la convenienza per TUTTI i titoli dell'universo (z-score robusti cross-sezionali).
    Ritorna {ticker: convenienza}. Salva le statistiche per la versione single-ticker."""
    items = [r for r in rlist if r]
    weights = _CONV_WEIGHTS[kind]
    if not items:
        return {}
    facs = [_factor_values(r, kind) for r in items]
    if kind == "long":
        _fill_valcheap(items, facs)
    stats = {fk: _robust([f.get(fk) for f in facs]) for fk in weights}
    convmap = {}
    for r, f in zip(items, facs):
        convmap[r["ticker"]] = _conv_from_factors(f, weights, stats, _CONV_K, r.get("reliab_factor"))
    _save_conv_stats(kind, {"weights": weights, "k": _CONV_K,
                            "stats": {fk: list(stats[fk]) for fk in stats}})
    return convmap


def _convenience_single(r, kind) -> int:
    """Convenienza per un singolo titolo (snapshot) usando le statistiche dell'ultimo scan.
    Se non disponibili → 50 (neutro); la valutazione settoriale qui non si applica."""
    payload = _load_conv_stats().get(kind)
    if not payload or "stats" not in payload:
        return 50
    weights = payload.get("weights", _CONV_WEIGHTS[kind])
    stats = {fk: tuple(v) for fk, v in payload.get("stats", {}).items()}
    f = _factor_values(r, kind)
    return _conv_from_factors(f, weights, stats, payload.get("k", _CONV_K), r.get("reliab_factor"))


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


# Parole-spia di problemi STRUTTURALI (non rumore di mercato): su un titolo già ipervenduto
# una frode/causa/indagine fresca è un PROBLEMA, non un saldo. Usate come flag DIFENSIVO,
# mai come bonus di acquisto.
_RED_FLAG_WORDS = set((
    "fraud fraudulent lawsuit lawsuits sued suing subpoena investigation probe sec doj "
    "bankruptcy bankrupt insolvency insolvent default defaults delisting delisted delist "
    "restatement accounting scandal misconduct halted suspension suspended recall recalls "
    "fda-rejection probe indictment indicted settlement"
).split())


def news_red_flags(news: list) -> list:
    """Notizie con segnali strutturali (legale/contabile) — flag difensivo, non un bonus.
    Ritorna la lista dei termini-spia trovati (vuota se nessuno)."""
    import re
    found = set()
    for n in news or []:
        text = (n.get("title", "") + " " + n.get("summary", "")).lower()
        for w in re.findall(r"[a-z']+", text):
            if w in _RED_FLAG_WORDS:
                found.add(w)
    return sorted(found)


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
def volatility_regime() -> dict:
    """Regime di volatilità del mercato (VIX se disponibile, altrimenti vol. realizzata dell'S&P 500).
    Il mean-reversion (rimbalzo da ipervenduto) si ROMPE nei crash: in regime di alta volatilità
    il `factor` < 1 declassa globalmente i punteggi del breve periodo.
    Ritorna {factor, label, vix} con factor in [0.55, 1.0]."""
    vix = None
    hv = get_history("^VIX", period="3mo")
    if not hv.empty:
        c = hv["Close"].dropna()
        if len(c):
            vix = float(c.iloc[-1])
    if vix is None:        # ripiego: vol. realizzata annualizzata dell'S&P 500 (~scala del VIX)
        hs = get_history("^GSPC", period="3mo")
        if not hs.empty:
            r = np.log(hs["Close"] / hs["Close"].shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
            if len(r) >= 10:
                vix = float(r.tail(20).std() * np.sqrt(252) * 100)
    if vix is None:
        return {"factor": 1.0, "label": "⚪ ignoto", "vix": None}
    if vix < 18:
        return {"factor": 1.0, "label": "🟢 calmo", "vix": vix}
    if vix < 26:
        return {"factor": 0.90, "label": "🟡 mosso", "vix": vix}
    if vix < 35:
        return {"factor": 0.75, "label": "🟠 teso", "vix": vix}
    return {"factor": 0.55, "label": "🔴 turbolento (crash)", "vix": vix}


def position_size(capital, risk_pct, price, stop):
    """Dimensionamento a rischio fisso: quante azioni comprare rischiando una frazione data
    del capitale. qty = capitale·risk% / (prezzo − stop). Ritorna None se i dati non bastano."""
    try:
        capital, risk_pct, price, stop = float(capital), float(risk_pct), float(price), float(stop)
    except (TypeError, ValueError):
        return None
    if capital <= 0 or risk_pct <= 0 or price <= 0 or price <= stop:
        return None
    risk_per_share = price - stop
    risk_budget = capital * risk_pct / 100.0
    qty = risk_budget / risk_per_share
    value = qty * price
    if value > capital:           # non investire più del capitale disponibile
        qty = capital / price
        value = qty * price
        risk_budget = qty * risk_per_share
    return {"qty": qty, "value": value, "risk_eur": risk_budget,
            "risk_per_share": risk_per_share, "stop_pct": (stop / price - 1) * 100}


@st.cache_data(ttl=900, show_spinner=False)
def opportunity_candidates(kind: str, include_eu: bool = True, include_etf: bool = True) -> list:
    """Universo di partenza dalle classifiche di mercato (USA); riserva se non disponibili.
    Con include_eu aggiunge titoli di Borsa Italiana / Europa; con include_etf aggiunge ETF
    liquidi (USA + UCITS) — entrambe le categorie non sono coperte dalle classifiche gratuite."""
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
    out = list(dict.fromkeys(names))[:cap]
    if include_eu:                          # aggiunge i titoli italiani/europei (lista curata)
        eu_cap = 16 if kind == "short" else 10
        out += _FALLBACK_UNIVERSE_EU[:eu_cap]
    if include_etf:                         # aggiunge ETF liquidi (USA + UCITS europei)
        etf_cap = 18 if kind == "short" else 14
        out += _ETF_UNIVERSE[:etf_cap]
    return list(dict.fromkeys(out))


def scan_opportunities(tickers: list, kind: str) -> pd.DataFrame:
    # PASSO 1 — scarica i dati di tutti i candidati (universo per gli z-score)
    rmap = {}
    for t in dict.fromkeys([x for x in tickers if x]):
        try:
            r = opportunity_row(t, with_fundamentals=(kind == "long"))
        except Exception:
            r = None
        if r:
            rmap[r["ticker"]] = r
    # PASSO 2 — convenienza con z-score robusti sull'intero universo
    convmap = _score_universe(list(rmap.values()), kind)
    # Regime di volatilità (solo breve): moltiplicatore globale che declassa i rimbalzi nei crash
    regime = volatility_regime()["factor"] if kind == "short" else 1.0
    # PASSO 3 — filtra le vere occasioni e costruisci la tabella
    rows = []
    for tk, r in rmap.items():
        dd = r["dd_high"]
        conv = convmap.get(tk, 50)
        if kind == "short":
            # Filtro liquidità/penny: sotto ~3$ o pochi scambi l'RSI è inaffidabile → escludi
            if r["price"] < _MIN_PRICE:
                continue
            liq = r.get("avg_dollar_vol")
            if liq is not None and liq < _MIN_DOLLAR_VOL:
                continue
            sc = _short_score(r, regime=regime)
            if sc is None or not np.isfinite(sc) or sc < 35:   # setup da ipervenduto / zona bassa
                continue
            if dd is None or dd > -8:           # dev'essere un calo reale, non un titolo ai massimi
                continue
            # Filtro Rischio/Rendimento: via i setup asimmetrici perdenti (R:R < 1,5)
            if r.get("rr") is not None and r["rr"] < _RR_MIN:
                continue
            gain = r["rebound_pot"] if r["rebound_pot"] is not None else r["exp_ret"]
            rows.append({"Ticker": r["ticker"], "Nome": r["name"], "Convenienza": conv,
                         "Prezzo": r["price"], "RSI": r["rsi"], "% dal max": dd, "Perf 1 mese": r["perf_1m"],
                         "Occasione": int(round(sc)), "Conferma": _short_confirm_label(r),
                         "RVOL": r.get("rvol"), "R:R": r.get("rr"),
                         "Prob. salita": r["prob_gain"], "Guadagno atteso": gain,
                         "Rischio perdita": r["prob_loss"], "Affidabilità": r["reliab"],
                         "Perché": _short_reasons(r)})
        else:
            sc = _long_score(r)
            if sc is None or not np.isfinite(sc) or sc < 50:
                continue
            if dd is None or dd > -12:          # richiede uno sconto significativo dai massimi
                continue
            rows.append({"Ticker": r["ticker"], "Nome": r["name"], "Convenienza": conv,
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
# MONITORAGGIO OCCASIONI NEL TEMPO
# Salva i titoli "seguiti" e uno "scatto" (snapshot) dei loro valori per ogni
# giorno: così si può osservarne l'evoluzione per più giorni prima di decidere.
# Persistenza su file JSON (come la watchlist): affidabile in locale; sul cloud
# il file è effimero (si azzera ai riavvii dell'istanza).
# ---------------------------------------------------------------------------

TRACKING_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracking.json")
TRACKING_NAME = "tracking.json"


def _today_iso() -> str:
    """Data odierna (fuso Italia: il server cloud gira in UTC)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("Europe/Rome")).date().isoformat()
    except Exception:
        return datetime.date.today().isoformat()


def _now_iso() -> str:
    """Data e ora correnti (fuso Italia), es. '2026-06-17 16:57'."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")


def _jsonable(v):
    """Converte numpy/NaN in tipi JSON puri (None se mancante)."""
    if v is None:
        return None
    if isinstance(v, (np.floating, float)):
        v = float(v)
        return None if math.isnan(v) else round(v, 4)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (int, str, bool)):
        return v
    try:
        f = float(v)
        return None if math.isnan(f) else round(f, 4)
    except (TypeError, ValueError):
        return v


def load_tracking() -> dict:
    data = read_data_json(TRACKING_NAME, {})
    return data if isinstance(data, dict) else {}


def save_tracking(data: dict) -> None:
    write_data_json(TRACKING_NAME, data)


def opportunity_snapshot(ticker: str, kind: str) -> dict:
    """Calcola uno «scatto» dei valori di un'occasione (ricalcolando con i dati freschi).
    Usato dallo snapshot automatico giornaliero. Ritorna None se i dati non bastano."""
    try:
        r = opportunity_row(ticker, with_fundamentals=(kind == "long"))
    except Exception:
        r = None
    if not r:
        return None
    if kind == "short":
        sc = _short_score(r)
        gain = r["rebound_pot"] if r["rebound_pot"] is not None else r["exp_ret"]
    else:
        sc = _long_score(r)
        gain = r["exp_ret"]
    occ = int(round(sc)) if (sc is not None and np.isfinite(sc)) else None
    return {k: _jsonable(v) for k, v in {
        "name": r["name"], "price": r["price"], "rsi": r["rsi"], "dd_high": r["dd_high"],
        "occasione": occ, "convenienza": _convenience_single(r, kind),
        "prob_gain": r["prob_gain"], "prob_loss": r["prob_loss"],
        "exp_ret": r["exp_ret"], "gain": gain, "reliab": r["reliab"],
        "target": r["target_price"], "stop": r["stop_price"],
    }.items()}


# Campionamento: si misura più volte al giorno (non più 1/giorno), ma solo se il valore cambia
# ed è passato un minimo di tempo → niente punti ridondanti (es. mercati chiusi) e dati contenuti.
_OBS_GAP_MIN = 60       # opp_watch: al più ogni 60 min
_OBS_MAX_DAYS = 12
_OBS_MAX_KEEP = 220
_SNAP_GAP_MIN = 15      # monitoraggio: al più ogni 15 min
_SNAP_MAX_DAYS = 22
_SNAP_MAX_KEEP = 700


def _parse_dt(s):
    s = str(s)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _minutes_since(ts) -> float:
    a, b = _parse_dt(ts), _parse_dt(_now_iso())
    return (b - a).total_seconds() / 60.0 if (a and b) else 1e9


def _should_sample(records, conv, price, gap_min, conv_field) -> bool:
    """True se va registrato un nuovo punto: nessun record, oppure valore cambiato E trascorso gap_min."""
    if not records:
        return True
    last = records[-1]
    if _minutes_since(last.get("date")) < gap_min:
        return False
    return not (last.get(conv_field) == conv and last.get("price") == price)


def _trim_records(records, max_days, max_keep):
    """Tiene gli ultimi `max_days` giorni e al più `max_keep` punti."""
    now = _parse_dt(_now_iso())
    if now:
        cutoff = now - datetime.timedelta(days=max_days)
        records = [r for r in records if (_parse_dt(r.get("date")) or now) >= cutoff]
    return records[-max_keep:]


def _append_snapshot(entry: dict, snapshot: dict) -> None:
    """Aggiunge uno snapshot del monitoraggio (con data+ora); più punti al giorno, con tetto."""
    snaps = entry.setdefault("snapshots", [])
    snap = {k: _jsonable(v) for k, v in snapshot.items()}
    snap["date"] = _now_iso()
    snaps.append(snap)
    snaps.sort(key=lambda s: s.get("date", ""))
    entry["snapshots"] = _trim_records(snaps, _SNAP_MAX_DAYS, _SNAP_MAX_KEEP)
    if snapshot.get("name") and not entry.get("name"):
        entry["name"] = snapshot["name"]


def track_opportunity(ticker: str, kind: str, snapshot: dict = None, note: str = "") -> dict:
    """Inizia a seguire un titolo (o aggiunge lo scatto di oggi se già seguito)."""
    ticker = ticker.upper()
    data = load_tracking()
    if ticker not in data:
        data[ticker] = {"kind": kind, "added": _today_iso(), "note": note,
                        "name": (snapshot or {}).get("name", ticker), "snapshots": []}
    else:
        data[ticker]["kind"] = kind
    if snapshot is None:
        snapshot = opportunity_snapshot(ticker, kind)
    if snapshot:
        _append_snapshot(data[ticker], snapshot)
    save_tracking(data)
    return data


def track_many(picks) -> list:
    """Segue più occasioni con UNA sola scrittura (un solo commit sul cloud), così
    si evita che salvataggi successivi si sovrascrivano. picks = lista di (ticker, kind).
    Ritorna i ticker effettivamente aggiunti (nuovi)."""
    data = load_tracking()
    today = _today_iso()
    added = []
    for tk, kind in picks:
        tk = tk.upper()
        is_new = tk not in data
        if is_new:
            data[tk] = {"kind": kind, "added": today, "note": "", "name": tk, "snapshots": []}
        else:
            data[tk]["kind"] = kind
        snap = opportunity_snapshot(tk, kind)
        if snap:
            _append_snapshot(data[tk], snap)
        if is_new:
            added.append(tk)
    save_tracking(data)
    return added


def untrack_opportunity(ticker: str) -> dict:
    data = load_tracking()
    data.pop(ticker.upper(), None)
    save_tracking(data)
    return data


def set_tracking_note(ticker: str, note: str) -> None:
    data = load_tracking()
    if ticker.upper() in data:
        data[ticker.upper()]["note"] = note
        save_tracking(data)


def auto_snapshot_tracked() -> dict:
    """Registra le variazioni dei titoli seguiti più volte al giorno (al più ogni ~15 min, e solo
    se convenienza o prezzo sono cambiati). Costruisce la storia man mano che il sistema gira."""
    data = load_tracking()
    if not data:
        return data
    changed = False
    for tk, entry in data.items():
        snap = opportunity_snapshot(tk, entry.get("kind", "short"))
        if not snap:
            continue
        if _should_sample(entry.get("snapshots", []), snap.get("convenienza"),
                          snap.get("price"), _SNAP_GAP_MIN, "convenienza"):
            _append_snapshot(entry, snap)
            changed = True
    if changed:
        save_tracking(data)
    return data


def tracking_trend(snapshots: list) -> dict:
    """Verdetto di tendenza dai punti di convenienza accumulati: rafforzamento/stabile/indebolimento.
    Ritorna None se ci sono meno di 2 scatti utili."""
    snaps = [s for s in snapshots if s.get("convenienza") is not None]
    if len(snaps) < 2:
        return None
    first, last = snaps[0], snaps[-1]
    dconv = last["convenienza"] - first["convenienza"]
    dprice = None
    if first.get("price") and last.get("price"):
        dprice = (last["price"] / first["price"] - 1) * 100
    if dconv >= 6:
        label, emoji, color = "Segnale in rafforzamento", "📈", "#1a7f37"
    elif dconv <= -6:
        label, emoji, color = "Segnale in indebolimento", "📉", "#cf222e"
    else:
        label, emoji, color = "Segnale stabile", "➡️", "#9a6700"
    return {"label": label, "emoji": emoji, "color": color,
            "dconv": dconv, "dprice": dprice, "days": len(snaps)}


# ---------------------------------------------------------------------------
# SISTEMA AUTONOMO — osserva l'evoluzione di TUTTE le occasioni e promuove
# automaticamente quelle in miglioramento per più giorni consecutivi.
# Registra un'osservazione/giorno per ogni occasione scansionata (non solo
# quelle seguite); quando la convenienza sale per N giorni di fila, il titolo
# viene aggiunto da solo al monitoraggio (tracking.json).
# ---------------------------------------------------------------------------

OPP_WATCH_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "opp_watch.json")
OPP_WATCH_NAME = "opp_watch.json"


def load_opp_watch() -> dict:
    data = read_data_json(OPP_WATCH_NAME, {})
    return data if isinstance(data, dict) else {}


def save_opp_watch(data: dict) -> None:
    write_data_json(OPP_WATCH_NAME, data)


def record_observations(df, kind: str) -> None:
    """Registra la convenienza di ogni occasione scansionata più volte al giorno (al più ogni ~60 min,
    e solo se convenienza o prezzo sono cambiati). Separata per orizzonte (short/long). Tetto per titolo."""
    if df is None or df.empty:
        return
    watch = load_opp_watch()
    now = _now_iso()
    for tk, r in df.iterrows():
        key = f"{kind}:{tk}"
        e = watch.setdefault(key, {"ticker": tk, "kind": kind, "name": tk, "obs": []})
        e["ticker"], e["kind"] = tk, kind
        e["name"] = r.get("Nome", tk)
        conv = _jsonable(r.get("Convenienza"))
        price = _jsonable(r.get("Prezzo"))
        obs = e.get("obs", [])
        if _should_sample(obs, conv, price, _OBS_GAP_MIN, "conv"):
            obs.append({"date": now, "conv": conv, "price": price,
                        "occ": _jsonable(r.get("Occasione")), "prob_gain": _jsonable(r.get("Prob. salita"))})
            obs.sort(key=lambda o: o.get("date", ""))
            e["obs"] = _trim_records(obs, _OBS_MAX_DAYS, _OBS_MAX_KEEP)
    save_opp_watch(watch)


# Parametri della regola "tendenza positiva tollerante":
_PROMO_MIN_GAIN = 5.0    # punti di convenienza guadagnati nel periodo
_PROMO_MAX_DIP = 4.0     # massimo calo giornaliero ammesso (oltre = inversione, niente promozione)


def _trend_progress(values: list, max_dip: float = _PROMO_MAX_DIP) -> int:
    """Quanti giorni-dato finali formano una **tendenza positiva tollerante**: la striscia
    continua finché un giorno non cala più di `max_dip` (le piccole oscillazioni non la spezzano).
    Es. (max_dip=4): [55,60,58] → 3 (il -2 è tollerato) · [60,52,58] → 2 (il -8 spezza)."""
    if not values:
        return 0
    if len(values) < 2:
        return 1
    run = 1
    for i in range(len(values) - 1, 0, -1):
        if values[i] - values[i - 1] >= -max_dip:
            run += 1
        else:
            break
    return run


def _qualifies_promotion(values: list, min_days: int = 3,
                         min_gain: float = _PROMO_MIN_GAIN, max_dip: float = _PROMO_MAX_DIP) -> bool:
    """True se negli ultimi `min_days` giorni la convenienza è salita **complessivamente** di almeno
    `min_gain` punti **senza cali giornalieri** oltre `max_dip` (tollera le piccole oscillazioni)."""
    if len(values) < min_days:
        return False
    v = values[-min_days:]
    for i in range(1, len(v)):
        if v[i] - v[i - 1] < -max_dip:      # un crollo nel mezzo = inversione → no
            return False
    return (v[-1] - v[0]) >= min_gain        # salita netta sufficiente sul periodo


# Finestre del ciclo automatico (in giorni), per tipo di occasione:
_OBS_WINDOW = {"short": 3, "long": 7}      # osservazione prima della promozione
_REMOVE_WINDOW = {"short": 5, "long": 10}  # dopo quanti giorni, se in perdita, si toglie dal monitoraggio
_NOTIFY_WINDOW = {"short": 3, "long": 7}   # giorni di monitoraggio positivo per la prima notifica


def _days_between(d1, d2) -> int:
    """Giorni di calendario tra due date in formato ISO (YYYY-MM-DD...)."""
    try:
        a = datetime.date.fromisoformat(str(d1)[:10])
        b = datetime.date.fromisoformat(str(d2)[:10])
        return (b - a).days
    except Exception:
        return 0


def auto_promote_opportunities() -> list:
    """FASE 1 — osservazione. Ogni occasione (saldo individuato in «Occasioni») è osservata per una
    finestra (breve 3 giorni, lungo 7 giorni); se alla fine il PREZZO è salito dal primo giorno
    osservato (la ripresa è iniziata) viene inserita nel Monitoraggio. Ritorna i ticker promossi."""
    watch = load_opp_watch()
    tracked = load_tracking()
    promoted = []
    new_records = []
    for key, e in watch.items():
        tk = e.get("ticker", key.split(":")[-1])
        if tk in tracked:
            continue
        kind = e.get("kind", "short")
        obs = [o for o in e.get("obs", []) if o.get("price")]
        if len(obs) < 2:
            continue
        days = _days_between(obs[0]["date"], obs[-1]["date"])
        window = _OBS_WINDOW.get(kind, 3)
        ret = (obs[-1]["price"] / obs[0]["price"] - 1) * 100 if obs[0]["price"] else 0.0
        if days >= window and ret > 0:
            track_opportunity(tk, kind,
                              note=f"🤖 Promossa il {_today_iso()}: dopo {days} giorni di osservazione "
                                   f"il prezzo è salito ({ret:+.1f}%).")
            tr = load_tracking()
            if tk in tr:
                tr[tk]["auto"] = True
                tr[tk]["notified"] = False
                save_tracking(tr)
            promoted.append(tk)
            new_records.append({"ticker": tk, "kind": kind, "date": _today_iso(),
                                "price": obs[-1].get("price"), "conv": obs[-1].get("conv"),
                                "ret_now": None, "ret_7d": None, "ret_30d": None, "last_update": _today_iso()})
    if new_records:
        recs = load_track_record()
        recs.extend(new_records)
        save_track_record(recs)
    return promoted


def manage_monitoring() -> tuple:
    """FASE 2 — monitoraggio (solo occasioni auto-promosse; le scelte manuali non si toccano).
    Valutazione in base al PREZZO rispetto al primo giorno di monitoraggio (l'investimento rende?):
    - rimuove quelle in perdita oltre la finestra (breve 5 giorni, lungo 10 giorni);
    - segnala (prima notifica) quelle in guadagno oltre la finestra (breve 3, lungo 7).
    Ritorna (da_notificare, rimosse)."""
    tracked = load_tracking()
    if not tracked:
        return [], []
    to_notify, removed = [], []
    changed = False
    for tk in list(tracked.keys()):
        e = tracked[tk]
        if not e.get("auto"):
            continue
        snaps = [s for s in e.get("snapshots", []) if s.get("price")]
        if not snaps:
            continue
        kind = e.get("kind", "short")
        added = e.get("added") or snaps[0].get("date")
        days = _days_between(added, _today_iso())
        base = snaps[0]["price"]
        ret = (snaps[-1]["price"] / base - 1) * 100 if base else 0.0   # rendimento dal giorno di promozione
        if days >= _REMOVE_WINDOW.get(kind, 5) and ret <= 0:
            del tracked[tk]
            removed.append(tk)
            changed = True
            continue
        if days >= _NOTIFY_WINDOW.get(kind, 3) and ret > 0 and not e.get("notified"):
            e["notified"] = True
            changed = True
            to_notify.append({"ticker": tk, "kind": kind, "days": days,
                              "ret": round(ret, 1), "name": e.get("name", tk)})
    if changed:
        save_tracking(tracked)
    return to_notify, removed


def observation_status() -> list:
    """Stato della FASE 1: per ogni occasione in osservazione, da quanti giorni è seguita,
    il rendimento di PREZZO dal primo giorno e quanti giorni mancano alla promozione."""
    watch = load_opp_watch()
    out = []
    for key, e in watch.items():
        obs = [o for o in e.get("obs", []) if o.get("price")]
        if not obs:
            continue
        kind = e.get("kind", "short")
        days = _days_between(obs[0]["date"], obs[-1]["date"])
        ret = (obs[-1]["price"] / obs[0]["price"] - 1) * 100 if (len(obs) >= 2 and obs[0]["price"]) else 0.0
        window = _OBS_WINDOW.get(kind, 3)
        out.append({"ticker": e.get("ticker", key.split(":")[-1]), "kind": kind,
                    "name": e.get("name", ""), "days": days, "ret": round(ret, 1),
                    "last_conv": obs[-1].get("conv"), "window": window,
                    "remaining": max(0, window - days)})
    out.sort(key=lambda x: x["ret"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# SCHEDA VOTI / TRACK RECORD — quanto hanno reso davvero le occasioni promosse.
# Ogni promozione viene registrata (prezzo + data); poi si misura il rendimento
# reale subito, a 7 e a 30 giorni. Dà la prova dei fatti sull'efficacia.
# ---------------------------------------------------------------------------

TRACK_RECORD_NAME = "track_record.json"


def load_track_record() -> list:
    data = read_data_json(TRACK_RECORD_NAME, [])
    return data if isinstance(data, list) else []


def save_track_record(records: list) -> None:
    write_data_json(TRACK_RECORD_NAME, records)


def update_track_record() -> list:
    """Aggiorna il rendimento reale di ogni promozione: ora, e (una volta sole) a 7 e 30 giorni.
    I rendimenti a 7/30g si calcolano dal prezzo storico relativo alla data di promozione."""
    records = load_track_record()
    if not records:
        return records
    today = _today_iso()
    changed = False
    for rec in records:
        tk, base = rec.get("ticker"), rec.get("price")
        if not tk or not base:
            continue
        try:
            h = get_history(tk, "1y")
        except Exception:
            h = None
        if h is None or h.empty:
            continue
        closes = h["Close"].dropna()
        if closes.empty:
            continue
        if getattr(closes.index, "tz", None) is not None:
            closes = closes.copy()
            closes.index = closes.index.tz_localize(None)
        rec["ret_now"] = round((float(closes.iloc[-1]) / base - 1) * 100, 1)
        rec["last_update"] = today
        try:
            promo = datetime.date.fromisoformat(rec.get("date"))
        except Exception:
            promo = None
        if promo:
            for horizon, fld in ((7, "ret_7d"), (30, "ret_30d")):
                if rec.get(fld) is None and (datetime.date.today() - promo).days >= horizon:
                    target = pd.to_datetime(promo + datetime.timedelta(days=horizon))
                    after = closes[closes.index >= target]
                    if not after.empty:
                        rec[fld] = round((float(after.iloc[0]) / base - 1) * 100, 1)
        changed = True
    if changed:
        save_track_record(records)
    return records


def track_record_stats() -> dict:
    """Statistiche aggregate sulle promozioni: rendimento medio, % di volte in positivo, migliore/peggiore."""
    records = load_track_record()

    def agg(field):
        vals = [r[field] for r in records if r.get(field) is not None]
        if not vals:
            return None
        return {"n": len(vals), "avg": round(sum(vals) / len(vals), 1),
                "hit": round(100 * sum(1 for v in vals if v > 0) / len(vals)),
                "best": round(max(vals), 1), "worst": round(min(vals), 1)}

    return {"total": len(records), "now": agg("ret_now"),
            "d7": agg("ret_7d"), "d30": agg("ret_30d")}


def track_record_calibration() -> dict:
    """Calibrazione ONESTA e in avanti del punteggio: resa reale delle promozioni divisa per
    FASCIA di convenienza (alta/media/bassa al momento della promozione). Risponde a:
    'la convenienza alta rende davvero più della bassa?'. Ritorna fasce + un verdetto."""
    records = load_track_record()
    bande = [("🟢 Alta (≥70)", lambda c: c is not None and c >= 70),
             ("🟡 Media (50–69)", lambda c: c is not None and 50 <= c < 70),
             ("🔴 Bassa (<50)", lambda c: c is not None and c < 50)]

    def agg(sub, field):
        vals = [r[field] for r in sub if r.get(field) is not None]
        if not vals:
            return None
        return {"n": len(vals), "avg": round(sum(vals) / len(vals), 1),
                "hit": round(100 * sum(1 for v in vals if v > 0) / len(vals))}

    fasce = []
    for label, cond in bande:
        sub = [r for r in records if cond(r.get("conv"))]
        fasce.append({"banda": label, "count": len(sub),
                      "now": agg(sub, "ret_now"), "d7": agg(sub, "ret_7d"), "d30": agg(sub, "ret_30d")})

    # Verdetto: la fascia alta rende più della bassa? (su un orizzonte con dati a sufficienza)
    verdetto, ok = "Dati ancora insufficienti per dire se il punteggio discrimina.", None
    for key in ("d30", "d7", "now"):
        alta = next((f[key] for f in fasce if f["banda"].startswith("🟢") and f[key]), None)
        bassa = next((f[key] for f in fasce if f["banda"].startswith("🔴") and f[key]), None)
        media = next((f[key] for f in fasce if f["banda"].startswith("🟡") and f[key]), None)
        rif = bassa or media
        if alta and rif and (alta["n"] >= 3 and rif["n"] >= 3):
            if alta["avg"] > rif["avg"]:
                verdetto = (f"✅ La convenienza discrimina: le promozioni ad alta convenienza rendono di più "
                            f"({alta['avg']:+.1f}% vs {rif['avg']:+.1f}% delle altre).")
                ok = True
            else:
                verdetto = (f"⚠️ Finora la convenienza alta NON ha rese migliori "
                            f"({alta['avg']:+.1f}% vs {rif['avg']:+.1f}%): pesi da rivedere o servono più dati.")
                ok = False
            break
    return {"fasce": fasce, "verdetto": verdetto, "ok": ok, "total": len(records)}


# ---------------------------------------------------------------------------
# PORTAFOGLIO REALE — posizioni effettivamente acquistate, con guadagno/perdita.
# Persistito come gli altri dati (file locale + branch remoto se configurato).
# ---------------------------------------------------------------------------

PORTFOLIO_NAME = "portfolio.json"


def load_portfolio() -> list:
    data = read_data_json(PORTFOLIO_NAME, [])
    return data if isinstance(data, list) else []


def save_portfolio(positions: list) -> None:
    write_data_json(PORTFOLIO_NAME, positions)


def add_position(ticker, qty, buy_price, date, target=None, stop=None, note="", horizon="lungo") -> list:
    positions = load_portfolio()
    positions.append({
        "ticker": str(ticker).upper(), "qty": float(qty), "buy_price": float(buy_price),
        "date": date, "target": (float(target) if target else None),
        "stop": (float(stop) if stop else None), "note": note,
        "horizon": ("breve" if str(horizon).startswith("breve") else "lungo"),
    })
    save_portfolio(positions)
    return positions


def add_position_by_amount(ticker, amount, target_pct=None, stop_pct=None, note="",
                           horizon="lungo", when=None):
    """Registra un acquisto indicando solo l'IMPORTO investito: prezzo e quantità vengono
    ricavati dal prezzo di mercato attuale, e si memorizza data+ora. Bersaglio/stop si possono
    dare come percentuali (+x% / -y%). Ritorna la posizione creata, o None se manca il prezzo."""
    tk = str(ticker).upper()
    q = quick_quote(tk)
    price = q.get("price")
    if price is None or price <= 0 or not amount or amount <= 0:
        return None
    qty = float(amount) / float(price)
    target = round(price * (1 + float(target_pct) / 100), 4) if target_pct else None
    stop = round(price * (1 - float(stop_pct) / 100), 4) if stop_pct else None
    when = when or _now_iso()
    positions = load_portfolio()
    positions.append({
        "ticker": tk, "qty": qty, "buy_price": float(price), "amount": float(amount),
        "datetime": when, "date": when[:10],
        "target": target, "stop": stop, "note": note,
        "horizon": ("breve" if str(horizon).startswith("breve") else "lungo"),
    })
    save_portfolio(positions)
    return positions[-1]


def remove_position(index: int) -> list:
    positions = load_portfolio()
    if 0 <= index < len(positions):
        positions.pop(index)
        save_portfolio(positions)
    return positions


def portfolio_view():
    """Calcola valore attuale, guadagno/perdita per posizione e totali, più gli avvisi
    target/stop. Ritorna (righe, totali)."""
    positions = load_portfolio()
    rows = []
    tot_cost = 0.0
    tot_val = 0.0
    val_known = True
    for i, p in enumerate(positions):
        tk = p.get("ticker")
        qty = p.get("qty") or 0.0
        buy = p.get("buy_price") or 0.0
        q = quick_quote(tk)
        price = q.get("price")
        cost = qty * buy
        val = (qty * price) if price is not None else None
        pnl = (val - cost) if val is not None else None
        pnl_pct = ((price / buy - 1) * 100) if (price is not None and buy) else None
        tot_cost += cost
        if val is not None:
            tot_val += val
        else:
            val_known = False
        tgt, stp = p.get("target"), p.get("stop")
        status = ""
        if price is not None:
            if tgt and price >= tgt:
                status = "🎯 target raggiunto"
            elif stp and price <= stp:
                status = "🛑 stop raggiunto"
        rows.append({"index": i, "ticker": tk, "qty": qty, "buy_price": buy, "date": p.get("date"),
                     "datetime": p.get("datetime") or p.get("date"),
                     "amount": p.get("amount", cost),
                     "price": price, "cost": cost, "value": val, "pnl": pnl, "pnl_pct": pnl_pct,
                     "target": tgt, "stop": stp, "note": p.get("note", ""), "status": status,
                     "horizon": ("breve" if str(p.get("horizon", "lungo")).startswith("breve") else "lungo")})
    totals = {"cost": tot_cost,
              "value": (tot_val if val_known else None),
              "pnl": (tot_val - tot_cost) if val_known else None,
              "pnl_pct": ((tot_val / tot_cost - 1) * 100) if (val_known and tot_cost) else None}
    return rows, totals


# ---------------------------------------------------------------------------
# CONSULENTE DI VENDITA — quando conviene incassare un titolo acquistato.
# NON prevede il futuro: applica regole (bersaglio, stop, trailing stop dal
# massimo toccato, ipercomprato, rottura del trend) per segnalare un buon
# momento per prendere profitto o tagliare le perdite. Onesto, non infallibile.
# ---------------------------------------------------------------------------

def _last_val(series):
    try:
        v = float(series.iloc[-1])
        return None if np.isnan(v) else v
    except Exception:
        return None


def sell_advice(position: dict) -> dict:
    """Valuta se conviene vendere una posizione. Ritorna verdetto (sell/watch/hold),
    etichetta, motivi, prezzo, guadagno% e picco dall'acquisto."""
    tk = position.get("ticker")
    buy = position.get("buy_price") or 0
    horizon = "breve" if str(position.get("horizon", "lungo")).startswith("breve") else "lungo"
    target, stop = position.get("target"), position.get("stop")
    hold = {"verdict": "hold", "label": "Mantieni", "emoji": "✅", "reasons": [],
            "price": None, "gain_pct": None, "peak": None}
    if not (tk and buy):
        return hold
    try:
        h = get_history(tk, "1y")
    except Exception:
        h = None
    if h is None or h.empty:
        return hold
    h = h[h["Close"].notna()]
    if h.empty:
        return hold
    h = add_indicators(h)
    closes = h["Close"]
    if getattr(closes.index, "tz", None) is not None:
        closes = closes.copy()
        closes.index = closes.index.tz_localize(None)
        h = h.copy()
        h.index = closes.index
    price = float(closes.iloc[-1])
    gain_pct = (price / buy - 1) * 100
    try:
        buy_date = pd.to_datetime(position.get("date"))
    except Exception:
        buy_date = None
    since = closes[closes.index >= buy_date] if buy_date is not None else closes
    peak = float(since.max()) if not since.empty else price
    dd_peak = (price / peak - 1) * 100 if peak else 0.0
    last = h.iloc[-1]
    rsi = _last_val(h["RSI"]) if "RSI" in h else None
    sma50 = _last_val(h["SMA50"]) if "SMA50" in h else None
    sma200 = _last_val(h["SMA200"]) if "SMA200" in h else None
    macd = last.get("MACD", np.nan)
    macd_sig = last.get("MACD_signal", np.nan)
    macd_down = (not np.isnan(macd) and not np.isnan(macd_sig) and macd < macd_sig)

    order = {"hold": 0, "watch": 1, "sell": 2}
    verdict = "hold"
    reasons = []

    def bump(v):
        nonlocal verdict
        if order[v] > order[verdict]:
            verdict = v

    if stop and price <= stop:
        bump("sell")
        reasons.append(f"🛑 Prezzo sotto lo stop di protezione ({stop:.2f}): valuta di uscire per limitare la perdita.")
    if target and price >= target:
        bump("sell")
        reasons.append(f"🎯 Bersaglio {target:.2f} raggiunto (sei a {gain_pct:+.1f}%): valuta di incassare.")
    trail = 8 if horizon == "breve" else 15
    if gain_pct > 3 and dd_peak <= -trail:
        bump("sell")
        reasons.append(f"🪤 Sceso {abs(dd_peak):.0f}% dal massimo toccato ({peak:.2f}) restando in guadagno "
                       f"({gain_pct:+.1f}%): conviene incassare prima che il guadagno si riduca.")
    if horizon == "breve":
        if sma50 and price >= sma50 and gain_pct > 0:
            bump("watch")
            reasons.append("Il prezzo è risalito sulla media a 50 giorni (l'obiettivo tipico di un rimbalzo): "
                           "il grosso del recupero potrebbe essere fatto.")
        if rsi is not None and rsi >= 68 and gain_pct > 0:
            bump("watch")
            reasons.append(f"📈 RSI {rsi:.0f} (ipercomprato): il rimbalzo di breve potrebbe essere quasi esaurito.")
        if macd_down and gain_pct > 2:
            bump("watch")
            reasons.append("Lo slancio (MACD) sta girando verso il basso.")
    else:
        if sma200 and price < sma200:
            bump("watch")
            reasons.append("Il prezzo è sceso sotto la media a 200 giorni: il trend di fondo si è indebolito.")
        if rsi is not None and rsi >= 78:
            bump("watch")
            reasons.append(f"📈 RSI {rsi:.0f}: molto ipercomprato, possibile presa di profitto.")

    if not reasons:
        reasons.append("Nessun segnale di vendita: per ora il titolo si mantiene.")
    labels = {"sell": "Valuta la vendita", "watch": "Tieni d'occhio", "hold": "Mantieni"}
    emojis = {"sell": "🔔", "watch": "👀", "hold": "✅"}
    return {"verdict": verdict, "label": labels[verdict], "emoji": emojis[verdict],
            "reasons": reasons, "price": round(price, 2), "gain_pct": round(gain_pct, 1),
            "peak": round(peak, 2)}


SELL_ALERTS_NAME = "sell_alerts.json"


def load_sell_alerts() -> dict:
    data = read_data_json(SELL_ALERTS_NAME, {})
    return data if isinstance(data, dict) else {}


def save_sell_alerts(d: dict) -> None:
    write_data_json(SELL_ALERTS_NAME, d)


def _position_key(p: dict) -> str:
    return f"{p.get('ticker')}|{p.get('date')}|{p.get('buy_price')}"


def evaluate_portfolio_sales() -> list:
    """Per ogni posizione calcola il consiglio di vendita; ritorna le posizioni appena passate
    a «vendi» (non ancora notificate). Aggiorna lo stato per non ripetere la notifica."""
    positions = load_portfolio()
    if not positions:
        return []
    alerted = load_sell_alerts()
    fired = []
    new_alerted = {}
    for p in positions:
        key = _position_key(p)
        adv = sell_advice(p)
        if adv["verdict"] == "sell":
            new_alerted[key] = True
            if not alerted.get(key):
                fired.append({"position": p, "advice": adv})
        # se non è più «vendi», la chiave non viene riportata → un futuro «vendi» riavvisa
    save_sell_alerts(new_alerted)
    return fired


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


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Average True Range (Wilder): ampiezza media del movimento giornaliero, in valore assoluto.
    Serve a tarare stop e bersagli sulla volatilità reale del titolo. Usa High/Low/Close;
    se High/Low mancano ripiega sulla variazione assoluta delle chiusure."""
    close = df["Close"]
    if "High" in df.columns and "Low" in df.columns:
        high, low = df["High"], df["Low"]
        prev = close.shift(1)
        tr = pd.concat([(high - low).abs(),
                        (high - prev).abs(),
                        (low - prev).abs()], axis=1).max(axis=1)
    else:
        tr = close.diff().abs()
    return tr.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()


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

    # Trend rispetto alle medie mobili (linguaggio chiaro: il significato, non solo i numeri)
    price = last["Close"]
    if not np.isnan(last.get("SMA50", np.nan)):
        if price > last["SMA50"]:
            signals.append(("Trend di breve (media 50 gg)", "prezzo sopra la media → forza nel breve", "positivo"))
        else:
            signals.append(("Trend di breve (media 50 gg)", "prezzo sotto la media → debolezza nel breve", "negativo"))
    if not np.isnan(last.get("SMA200", np.nan)):
        if price > last["SMA200"]:
            signals.append(("Trend di fondo (media 200 gg)", "prezzo sopra la media → tendenza di lungo positiva", "positivo"))
        else:
            signals.append(("Trend di fondo (media 200 gg)", "prezzo sotto la media → tendenza di lungo negativa", "negativo"))

    # Golden / death cross
    if not np.isnan(last.get("SMA50", np.nan)) and not np.isnan(last.get("SMA200", np.nan)):
        if last["SMA50"] > last["SMA200"]:
            signals.append(("Incrocio medie (50 vs 200)", "Golden cross → impostazione rialzista", "positivo"))
        else:
            signals.append(("Incrocio medie (50 vs 200)", "Death cross → impostazione ribassista", "negativo"))

    # RSI
    rsi_val = last.get("RSI", np.nan)
    if not np.isnan(rsi_val):
        if rsi_val >= 70:
            signals.append(("Forza relativa (RSI 14)", f"{rsi_val:.0f} → ipercomprato (può correggere)", "negativo"))
        elif rsi_val <= 30:
            signals.append(("Forza relativa (RSI 14)", f"{rsi_val:.0f} → ipervenduto (può rimbalzare)", "positivo"))
        else:
            signals.append(("Forza relativa (RSI 14)", f"{rsi_val:.0f} → neutro", "neutro"))

    # MACD
    macd_val = last.get("MACD", np.nan)
    sig_val = last.get("MACD_signal", np.nan)
    if not np.isnan(macd_val) and not np.isnan(sig_val):
        if macd_val > sig_val:
            signals.append(("Momentum (MACD)", "positivo → il movimento accelera al rialzo", "positivo"))
        else:
            signals.append(("Momentum (MACD)", "negativo → il movimento accelera al ribasso", "negativo"))

    return signals


def technical_summary(df: pd.DataFrame) -> dict:
    """Verdetto tecnico sintetico (pesa di più il trend di fondo e l'incrocio delle medie)."""
    if df.empty:
        return None
    last = df.iloc[-1]
    price = last["Close"]
    score = 0.0
    long_trend = momentum = rsi_note = None

    sma200 = last.get("SMA200", np.nan)
    if not np.isnan(sma200):
        if price > sma200:
            score += 2; long_trend = "tendenza di fondo **positiva** (sopra la media a 200 giorni)"
        else:
            score -= 2; long_trend = "tendenza di fondo **negativa** (sotto la media a 200 giorni)"
    sma50 = last.get("SMA50", np.nan)
    if not np.isnan(sma50) and not np.isnan(sma200):
        score += 1.5 if sma50 > sma200 else -1.5
    if not np.isnan(sma50):
        score += 1 if price > sma50 else -1
    macd_val, sig_val = last.get("MACD", np.nan), last.get("MACD_signal", np.nan)
    if not np.isnan(macd_val) and not np.isnan(sig_val):
        if macd_val > sig_val:
            score += 1; momentum = "momentum di breve **positivo**"
        else:
            score -= 1; momentum = "momentum di breve **in raffreddamento**"
    rsi_val = last.get("RSI", np.nan)
    if not np.isnan(rsi_val):
        if rsi_val >= 70:
            score -= 0.5; rsi_note = f"RSI {rsi_val:.0f} (ipercomprato)"
        elif rsi_val <= 30:
            score += 0.5; rsi_note = f"RSI {rsi_val:.0f} (ipervenduto)"

    if score >= 1.5:
        emoji, color, label = "🟢", "#1a7f37", "Quadro tecnico positivo (rialzista)"
    elif score <= -1.5:
        emoji, color, label = "🔴", "#cf222e", "Quadro tecnico negativo (ribassista)"
    else:
        emoji, color, label = "🟡", "#9a6700", "Quadro tecnico misto"
    bits = [b for b in (long_trend, momentum, rsi_note) if b]
    line = ("; ".join(bits) + ".") if bits else "Segnali contrastanti."
    return {"emoji": emoji, "color": color, "label": label, "line": line}


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
    psales = info.get("priceToSalesRatio")
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

    # L'azienda è in perdita? (serve a spiegare i campi "n/d" come P/E)
    in_loss = any(x is not None and x < 0 for x in (pmargin, roe, omargin, roa))

    def r_pe(v, j):
        if v is None:
            return "in perdita: senza utili il P/E non si calcola" if in_loss else "dato non disponibile"
        if j == "positivo":
            return "basso: valutazione conveniente sugli utili"
        if j == "negativo":
            return "alto: paghi molto gli utili (il mercato sconta forte crescita)"
        return "nella norma"

    def r_pb(v, j):
        if v is None:
            return "dato non disponibile"
        if j == "positivo":
            return "basso: paghi poco rispetto al patrimonio"
        if j == "negativo":
            return "alto: molto sopra il valore di libro (caro)"
        return "nella norma"

    def r_peg(v, j):
        if v is None:
            return "richiede P/E e crescita degli utili (qui mancano)"
        if j == "positivo":
            return "sotto 1: prezzo giustificato dalla crescita"
        if j == "negativo":
            return "alto: caro rispetto a quanto cresce"
        return "accettabile"

    def r_ps(v, j):
        if v is None:
            return "dato non disponibile"
        if j == "positivo":
            return "contenuto: valutazione bassa sui ricavi"
        if j == "negativo":
            return "alto: valutazione elevata sui ricavi"
        return "nella media"

    def r_profit(v, j, perdita_txt):
        if v is None:
            return "dato non disponibile"
        if v < 0:
            return f"negativo: {perdita_txt}"
        if j == "positivo":
            return "elevato: molto redditizia"
        if j == "negativo":
            return "basso: poco redditizia"
        return "discreto"

    def r_d2e(v, j):
        if v is None:
            return "dato non disponibile"
        if j == "positivo":
            return "basso: poco indebitata, finanziariamente solida"
        if j == "negativo":
            return "alto: molto indebitata (più rischio)"
        return "indebitamento nella media"

    def r_liq(v, j):
        if v is None:
            return "dato non disponibile"
        if j == "positivo":
            return "sopra 1: copre bene i debiti a breve"
        if j == "negativo":
            return "sotto 1: liquidità tirata"
        return "liquidità sufficiente"

    def r_growth(v, j):
        if v is None:
            return "utili negativi: crescita non significativa" if in_loss else "dato non disponibile"
        if v < 0:
            return "in calo rispetto all'anno prima"
        if j == "positivo":
            return "in forte crescita"
        return "in lieve crescita"

    def r_dyield(v, j):
        if v is None or v == 0:
            return "non paga dividendi (o dato assente)"
        if j == "positivo":
            return "rendimento da dividendo interessante"
        return "dividendo modesto"

    def r_payout(v, j):
        if v is None:
            return "non distribuisce dividendi"
        if j == "positivo":
            return "prudente: distribuisce una quota sostenibile degli utili"
        if j == "negativo":
            return "alto: distribuisce quasi tutti gli utili (poco margine)"
        return "nella norma"

    j_pe, j_pb, j_peg, j_ps = (judge(pe, 15, 35, False), judge(pb, 1.5, 4, False),
                               judge(peg, 1, 2, False), judge(psales, 2, 6, False))
    j_roe, j_roa = judge(roe, 0.15, 0.05), judge(roa, 0.08, 0.02)
    j_pm, j_om = judge(pmargin, 0.10, 0.02), judge(omargin, 0.12, 0.03)
    j_d2e, j_cr, j_qr = judge(d2e, 100, 250, False), judge(cratio, 1.5, 1), judge(qratio, 1, 0.7)
    j_rg, j_eg = judge(rev_growth, 0.10, 0), judge(earn_growth, 0.10, 0)
    j_dy, j_po = judge(dyield, 0.03, 0), judge(payout, 0.6, 0.9, False)

    blocks = {
        "Valutazione (è caro o conveniente?)": [
            ("P/E (prezzo/utili)", _fmt(pe), j_pe, r_pe(pe, j_pe)),
            ("P/B (prezzo/patrimonio)", _fmt(pb), j_pb, r_pb(pb, j_pb)),
            ("PEG (P/E su crescita)", _fmt(peg), j_peg, r_peg(peg, j_peg)),
            ("P/S (prezzo/vendite)", _fmt(psales), j_ps, r_ps(psales, j_ps)),
        ],
        "Redditività (quanto guadagna bene?)": [
            ("ROE (rendimento capitale proprio)", _fmt(roe, pct=True), j_roe, r_profit(roe, j_roe, "perde sul capitale dei soci")),
            ("ROA (rendimento attività)", _fmt(roa, pct=True), j_roa, r_profit(roa, j_roa, "perde sulle proprie attività")),
            ("Margine netto", _fmt(pmargin, pct=True), j_pm, r_profit(pmargin, j_pm, "perde su ogni euro di ricavi")),
            ("Margine operativo", _fmt(omargin, pct=True), j_om, r_profit(omargin, j_om, "gestione operativa in perdita")),
        ],
        "Solidità finanziaria (quanto è esposta?)": [
            ("Debito/Equity", _fmt(d2e), j_d2e, r_d2e(d2e, j_d2e)),
            ("Current ratio (liquidità)", _fmt(cratio), j_cr, r_liq(cratio, j_cr)),
            ("Quick ratio", _fmt(qratio), j_qr, r_liq(qratio, j_qr)),
        ],
        "Crescita": [
            ("Crescita ricavi (anno)", _fmt(rev_growth, pct=True), j_rg, r_growth(rev_growth, j_rg)),
            ("Crescita utili (anno)", _fmt(earn_growth, pct=True), j_eg, r_growth(earn_growth, j_eg)),
        ],
        "Dividendo": [
            ("Rendimento dividendo", _fmt(dyield, pct=True), j_dy, r_dyield(dyield, j_dy)),
            ("Payout ratio (utili distribuiti)", _fmt(payout, pct=True), j_po, r_payout(payout, j_po)),
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
