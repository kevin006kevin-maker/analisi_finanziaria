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
def get_chart_history(ticker: str, period: str = "5d") -> pd.DataFrame:
    """Storico per i GRAFICI a breve termine, con granularità INTRADAY diversa per periodo:
      - '1d' (giornaliero) → barre ogni ~15 min (ripiego 1 ora);
      - '5d' (settimanale) → barre ogni ~1 ora.
    Solo durante le contrattazioni esistono barre intraday (a mercato chiuso non ci sono scambi).
    Per i periodi più lunghi torna ai dati GIORNALIERI (get_history): un valore al giorno.
    NON usata per i calcoli (indicatori/probabilità), che restano su dati daily.
    Ritorna anche l'attributo .attrs['intraday'] = True/False."""
    interval_for = {"1d": ("15m", "60m"), "5d": ("60m",)}   # giorno=15min · settimana=1 ora
    if period not in interval_for:
        df = get_history(ticker, period)
        df.attrs["intraday"] = False
        return df
    for interval in interval_for[period]:
        try:
            df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
        except Exception:
            df = None
        if df is not None and not df.empty:
            df = df.dropna(how="all")
            if "Close" in df.columns:
                df = df[df["Close"].notna()]
            if not df.empty:
                try:
                    df.index = df.index.tz_localize(None)   # tz-aware → naive (confronti/plot semplici)
                except (TypeError, AttributeError):
                    pass
                df.attrs["intraday"] = True
                return df
    df = get_history(ticker, "5d")                    # ripiego: giornaliero, meglio di niente
    df.attrs["intraday"] = False
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
            d = yf.Ticker(ticker).info or {}
            if d:
                d["_source"] = "Yahoo"
            return d
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
    # Trasparenza dati: elenca le fonti che hanno realmente contribuito (per l'indicatore in UI)
    named = [("FMP", sources[0]), ("Finnhub", sources[1]), ("SEC", sources[2]), ("Yahoo", sources[3])]
    contrib = [nm for nm, s in named if any(k != "_source" for k in s)]
    out["_source"] = " + ".join(contrib) if contrib else "—"
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


# Stato dell'ultima chiamata FMP (per l'indicatore "trasparenza dati" in UI). Module-global:
# persiste tra i rerun di Streamlit e funziona anche nel job (nessuna dipendenza da st.session_state).
_FMP_STATE = {"status": None}


@st.cache_data(ttl=900, show_spinner=False)
def _fmp_get(path: str):
    key = _fmp_key()
    if not key:
        _FMP_STATE["status"] = "no_key"
        return None
    import requests
    sep = "&" if "?" in path else "?"
    try:
        r = requests.get(f"{FMP_BASE}/{path}{sep}apikey={key}", timeout=15)
        if r.status_code != 200:
            # 429 = quota giornaliera esaurita / rate limit (il caso più frequente sul piano free)
            _FMP_STATE["status"] = "exhausted" if r.status_code == 429 else f"http_{r.status_code}"
            return None
        data = r.json()
        if isinstance(data, dict) and ("Error Message" in data or "error" in data):
            _FMP_STATE["status"] = "exhausted"   # FMP segnala il limite anche con 200 + messaggio
            return None
        _FMP_STATE["status"] = "ok"
        return data
    except Exception:
        _FMP_STATE["status"] = "error"
        return None


def fmp_status_label() -> str:
    """Etichetta leggibile dello stato FMP per l'indicatore di trasparenza dati."""
    if not _fmp_key():
        return "FMP non configurato"
    return {"ok": "FMP attivo", "exhausted": "⚠️ FMP quota esaurita",
            "error": "FMP irraggiungibile", "no_key": "FMP non configurato",
            None: "FMP pronto"}.get(_FMP_STATE.get("status"), f"FMP {_FMP_STATE.get('status')}")


def data_status_line(info: dict, hist=None) -> str:
    """Riga «trasparenza dati» per la UI: da quale fonte arrivano i fondamentali, qual è la data
    dell'ultimo prezzo e lo stato di FMP. Trasforma i fallback silenziosi in informazione."""
    src = (info or {}).get("_source") or "—"
    parts = [f"fondamentali: **{src}**"]
    try:
        if hist is not None and not hist.empty:
            parts.append(f"ultimo prezzo: **{hist.index[-1].strftime('%d/%m/%Y')}**")
    except Exception:
        pass
    parts.append(fmp_status_label())
    return "📡 " + " · ".join(parts)


def freschezza_dati() -> dict:
    """Da quanto tempo il sistema autonomo NON registra un dato nuovo.

    Serve perché la barra in alto mostrava l'orologio del COMPUTER e lo chiamava «ultimo
    aggiornamento»: con i dati del server fermi, l'app diceva «aggiornato adesso» — il contrario del
    vero. Non è un difetto teorico: il 18/08/2026 ci sono cascato io, convinto da una vista locale
    non aggiornata che il job fosse morto da 17 ore mentre stava lavorando regolarmente.

    Si guarda l'ultimo scatto dei titoli seguiti e l'ultima osservazione: sono le due cose che il job
    scrive a ogni giro in cui qualcosa cambia. Ritorna {quando, ore, testo, allarme}; `allarme` è
    vero solo oltre `_FRESCHEZZA_ALLARME_ORE`, e a mercati chiusi qualche ora di silenzio è normale."""
    candidati = []
    try:
        for e in (load_tracking() or {}).values():
            snaps = [s for s in (e.get("snapshots") or []) if s.get("date")]
            if snaps:
                candidati.append(str(snaps[-1]["date"]))
    except Exception:
        pass
    try:
        for e in (load_opp_watch() or {}).values():
            obs = [o for o in (e.get("obs") or []) if o.get("date")]
            if obs:
                candidati.append(str(obs[-1]["date"]))
    except Exception:
        pass
    if not candidati:
        return {"quando": None, "ore": None, "allarme": True,
                "testo": "nessun dato dal server: il sistema autonomo non ha ancora scritto niente"}
    ultimo = max(candidati)
    d, ora = _parse_dt(ultimo), _parse_dt(_now_iso())
    ore = ((ora - d).total_seconds() / 3600.0) if (d and ora) else None
    if ore is None:
        return {"quando": ultimo, "ore": None, "allarme": False, "testo": f"ultimo dato: {ultimo}"}
    if ore < 1:
        quanto = f"{int(ore * 60)} minuti fa"
    elif ore < 48:
        quanto = f"{ore:.0f} ore fa"
    else:
        quanto = f"{ore / 24:.0f} giorni fa"
    return {"quando": ultimo, "ore": round(ore, 1),
            "allarme": ore > _FRESCHEZZA_ALLARME_ORE,
            "testo": f"ultimo dato registrato dal server: **{str(ultimo)[:16]}** ({quanto})"}


_FRESCHEZZA_ALLARME_ORE = 4     # oltre questo si segnala; a mercati chiusi è comunque normale


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

    # --- Metriche "serie" per la qualità in saldo (dove FMP le espone gratis) ---
    info["roic"] = num(m.get("returnOnInvestedCapitalTTM") or m.get("roicTTM"))           # ROIC (frazione)
    info["grossMargins"] = num(r.get("grossProfitMarginTTM"))                             # margine lordo
    info["interestCoverage"] = num(r.get("interestCoverageTTM"))
    info["evToEbitda"] = num(m.get("enterpriseValueOverEBITDATTM") or r.get("enterpriseValueMultipleTTM"))
    fy = num(m.get("freeCashFlowYieldTTM"))                                                # frazione (0.05)
    if fy is not None:
        info["fcfYield"] = round(fy * 100, 2)                                              # → % del prezzo
    elif num(r.get("priceToFreeCashFlowsRatioTTM")):
        pfcf = num(r.get("priceToFreeCashFlowsRatioTTM"))
        if pfcf and pfcf > 0:
            info["fcfYield"] = round(100.0 / pfcf, 2)
    info["_source"] = "FMP"
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
    """Valori annuali (10-K) più recenti, dal più nuovo. Per i FLUSSI (conto economico/cassa, con
    'start') preferisce la durata ANNUALE (~365g), evitando di pescare un trimestre o un cumulato
    parziale; gli istantanei (stato patrimoniale, senza 'start') sono tenuti così come sono."""
    recs = [x for x in units if x.get("val") is not None and str(x.get("form", "")).startswith("10-K")]
    recs = [x for x in recs if x.get("fp") == "FY"] or recs

    def _annualish(x):
        s, e = x.get("start"), x.get("end")
        if not s or not e:
            return True                       # voce istantanea (bilancio) → tieni
        try:
            d0 = datetime.datetime.strptime(s, "%Y-%m-%d")
            d1 = datetime.datetime.strptime(e, "%Y-%m-%d")
            return 280 <= (d1 - d0).days <= 400
        except Exception:
            return True

    recs = [x for x in recs if _annualish(x)] or recs
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
    info["_source"] = "SEC"
    return {k: v for k, v in info.items() if v is not None}


@st.cache_data(ttl=86400, show_spinner=False)
def altman_z_from_sec(ticker: str) -> dict:
    """Altman Z-Score dai bilanci ufficiali SEC (solo USA, modello per le INDUSTRIALI; banche/REIT
    esclusi a monte). Misura il rischio di dissesto. Ritorna {z, zone, note} o None se i dati mancano.
    Z = 1,2·(CCN/Att) + 1,4·(UtiliReinv/Att) + 3,3·(EBIT/Att) + 0,6·(CapMkt/Pass) + 1,0·(Ricavi/Att)."""
    cik = _sec_cik_map().get(ticker.upper())
    if not cik:
        return None
    facts = _sec_companyfacts(cik)
    gaap = (facts.get("facts") or {}).get("us-gaap", {})
    if not gaap:
        return None

    def usd(c):
        return (gaap.get(c, {}).get("units", {}) or {}).get("USD", [])

    ta = _sec_instant(usd("Assets"))
    ca = _sec_instant(usd("AssetsCurrent"))
    cl = _sec_instant(usd("LiabilitiesCurrent"))
    tl = _sec_instant(usd("Liabilities"))
    re = _sec_instant(usd("RetainedEarningsAccumulatedDeficit"))
    ebit_l = _sec_annual(usd("OperatingIncomeLoss"), 1)
    ebit = ebit_l[0] if ebit_l else None
    rev_l = (_sec_annual(usd("RevenueFromContractWithCustomerExcludingAssessedTax"), 1)
             or _sec_annual(usd("Revenues"), 1))
    rev = rev_l[0] if rev_l else None
    dei = (facts.get("facts") or {}).get("dei", {})
    shares = _sec_instant((dei.get("EntityCommonStockSharesOutstanding", {}).get("units", {}) or {}).get("shares", []))
    price = None
    h = get_history(ticker, period="5d")
    if not h.empty:
        c = h["Close"].dropna()
        if not c.empty:
            price = float(c.iloc[-1])
    mve = price * shares if (price and shares) else None
    if any(x is None for x in (ta, ca, cl, tl, re, ebit, rev, mve)) or ta <= 0 or tl <= 0:
        return None
    wc = ca - cl
    z = (1.2 * (wc / ta) + 1.4 * (re / ta) + 3.3 * (ebit / ta)
         + 0.6 * (mve / tl) + 1.0 * (rev / ta))
    if z > 2.99:
        zone, note = "🟢 solida", "rischio di dissesto basso"
    elif z >= 1.81:
        zone, note = "🟡 zona grigia", "da monitorare"
    else:
        zone, note = "🔴 a rischio", "rischio di dissesto elevato"
    return {"z": round(z, 2), "zone": zone, "note": note}


def _sec_gaap_dei(ticker: str):
    """(facts, us-gaap, dei) dai companyfacts SEC; (None, None, None) se non disponibili.
    La companyfacts è in cache: Altman/EV-EBIT/Piotroski sullo stesso titolo NON ripetono la rete."""
    cik = _sec_cik_map().get(ticker.upper())
    if not cik:
        return None, None, None
    facts = _sec_companyfacts(cik)
    gaap = (facts.get("facts") or {}).get("us-gaap", {})
    dei = (facts.get("facts") or {}).get("dei", {})
    return facts, gaap, dei


def _sec_price_shares(ticker, dei):
    """(prezzo, azioni in circolazione) per la capitalizzazione (mercato), dai dati SEC + ultimo prezzo."""
    shares = _sec_instant((dei.get("EntityCommonStockSharesOutstanding", {}).get("units", {}) or {}).get("shares", []))
    price = None
    h = get_history(ticker, period="5d")
    if not h.empty:
        c = h["Close"].dropna()
        if not c.empty:
            price = float(c.iloc[-1])
    return price, shares


@st.cache_data(ttl=86400, show_spinner=False)
def ev_ebit_from_sec(ticker: str):
    """EV/EBIT REALE dai bilanci SEC (USA). Meglio di EV/EBITDA: include ammortamenti/svalutazioni,
    quindi non «abbellisce» le aziende capital-intensive. None se EBIT≤0 o dati mancanti."""
    facts, gaap, dei = _sec_gaap_dei(ticker)
    if not gaap:
        return None

    def usd(c):
        return (gaap.get(c, {}).get("units", {}) or {}).get("USD", [])

    ebit_l = _sec_annual(usd("OperatingIncomeLoss"), 1)        # EBIT = reddito operativo
    ebit = ebit_l[0] if ebit_l else None
    if not ebit or ebit <= 0:
        return None
    debt = _sec_instant(usd("LongTermDebt"))
    if debt is None:
        ltc = _sec_instant(usd("LongTermDebtNoncurrent"))
        debt = (ltc + (_sec_instant(usd("LongTermDebtCurrent")) or 0)) if ltc is not None else 0
    cash = _sec_instant(usd("CashAndCashEquivalentsAtCarryingValue")) or 0
    price, shares = _sec_price_shares(ticker, dei)
    if not (price and shares):
        return None
    ev = price * shares + (debt or 0) - cash                   # enterprise value
    if ev <= 0:
        return None
    return round(ev / ebit, 1)


@st.cache_data(ttl=86400, show_spinner=False)
def piotroski_from_sec(ticker: str):
    """Piotroski F-Score REALE (i 9 test originali anno-su-anno) dai bilanci SEC (USA): validato per
    separare i value sani dalle trappole. Ritorna {score, max, details:[(test, superato)]} o None.
    ≥7 = solido · ≤3 = debole. (max < 9 se qualche voce di bilancio non è disponibile.)"""
    facts, gaap, dei = _sec_gaap_dei(ticker)
    if not gaap:
        return None

    def usd(c):
        return (gaap.get(c, {}).get("units", {}) or {}).get("USD", [])

    def sh_u(c):
        return (gaap.get(c, {}).get("units", {}) or {}).get("shares", [])

    ni = _sec_annual(usd("NetIncomeLoss"), 2)
    cfo = _sec_annual(usd("NetCashProvidedByUsedInOperatingActivities"), 2)
    assets = _sec_annual(usd("Assets"), 2)
    ca = _sec_annual(usd("AssetsCurrent"), 2)
    cl = _sec_annual(usd("LiabilitiesCurrent"), 2)
    ltd = _sec_annual(usd("LongTermDebt"), 2) or _sec_annual(usd("LongTermDebtNoncurrent"), 2)
    rev = _sec_annual(usd("RevenueFromContractWithCustomerExcludingAssessedTax"), 2) or _sec_annual(usd("Revenues"), 2)
    gp = _sec_annual(usd("GrossProfit"), 2)
    sh = _sec_annual(sh_u("WeightedAverageNumberOfDilutedSharesOutstanding"), 2) \
        or _sec_annual(sh_u("WeightedAverageNumberOfSharesOutstandingBasic"), 2)

    def g(lst, i):
        return lst[i] if (lst and len(lst) > i) else None

    def div(a, b):
        return (a / b) if (a is not None and b not in (None, 0)) else None

    roa0, roa1 = div(g(ni, 0), g(assets, 0)), div(g(ni, 1), g(assets, 1))
    lev0, lev1 = div(g(ltd, 0), g(assets, 0)), div(g(ltd, 1), g(assets, 1))
    cr0, cr1 = div(g(ca, 0), g(cl, 0)), div(g(ca, 1), g(cl, 1))
    gm0, gm1 = div(g(gp, 0), g(rev, 0)), div(g(gp, 1), g(rev, 1))
    at0, at1 = div(g(rev, 0), g(assets, 0)), div(g(rev, 1), g(assets, 1))

    tests = [
        ("Utile positivo (ROA > 0)", None if roa0 is None else roa0 > 0),
        ("Cash flow operativo positivo", None if not cfo else g(cfo, 0) > 0),
        ("Redditività in aumento (ROA ↑)", None if (roa0 is None or roa1 is None) else roa0 > roa1),
        ("Utili di qualità (cassa > utile)", None if (not cfo or not ni) else g(cfo, 0) > g(ni, 0)),
        ("Debito a lungo in calo (leva ↓)", None if (lev0 is None or lev1 is None) else lev0 < lev1),
        ("Liquidità corrente in aumento", None if (cr0 is None or cr1 is None) else cr0 > cr1),
        ("Nessuna diluizione azioni", None if len(sh) < 2 else g(sh, 0) <= g(sh, 1) * 1.01),
        ("Margine lordo in aumento", None if (gm0 is None or gm1 is None) else gm0 > gm1),
        ("Efficienza dell'attivo in aumento", None if (at0 is None or at1 is None) else at0 > at1),
    ]
    details = [(label, bool(ok)) for label, ok in tests if ok is not None]
    if len(details) < 5:
        return None
    return {"score": sum(1 for _, ok in details if ok), "max": len(details), "details": details}


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
    info["earningsGrowth"] = frac(m.get("epsGrowthTTMYoy") or m.get("epsGrowthQuarterlyYoy"))
    info["beta"] = num(m.get("beta"))
    info["fiftyTwoWeekHigh"] = num(m.get("52WeekHigh"))
    info["fiftyTwoWeekLow"] = num(m.get("52WeekLow"))
    info["payoutRatio"] = frac(m.get("payoutRatioTTM") or m.get("payoutRatioAnnual"))

    # --- Metriche "serie" per la qualità in saldo (Finnhub metric=all è il bacino gratis più ricco) ---
    def _firstk(*keys):
        for k in keys:
            if m.get(k) is not None:
                return m.get(k)
        return None
    info["roic"] = frac(_firstk("roicTTM", "roiTTM", "roicAnnual", "roiAnnual"))         # ROIC (frazione)
    info["grossMargins"] = frac(_firstk("grossMarginTTM", "grossMarginAnnual"))          # margine lordo
    info["operatingMargins"] = info.get("operatingMargins")
    info["interestCoverage"] = num(_firstk("netInterestCoverageTTM", "netInterestCoverageAnnual"))
    info["evToEbitda"] = num(_firstk("currentEv/ebitdaTTM", "currentEv/ebitdaAnnual"))   # EV/EBITDA
    pfcf = num(_firstk("pfcfShareTTM", "pfcfShareAnnual"))                                 # prezzo / FCF per azione
    if pfcf and pfcf > 0:
        info["fcfYield"] = round(100.0 / pfcf, 2)                                          # FCF yield (% del prezzo)
    info["revenueGrowth3Y"] = frac(_firstk("revenueGrowth3Y"))                            # CAGR 3 anni (frazione)
    info["revenueGrowth5Y"] = frac(_firstk("revenueGrowth5Y"))
    info["epsGrowth3Y"] = frac(_firstk("epsGrowth3Y"))
    info["epsGrowth5Y"] = frac(_firstk("epsGrowth5Y"))
    info["netMargin5Y"] = frac(_firstk("netProfitMargin5Y", "netMargin5Y"))              # margine netto medio 5 anni
    info["_source"] = "Finnhub"
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


def ewma_vol(logret, lam: float = 0.94):
    """Volatilità annualizzata EWMA (RiskMetrics): pesa di più i giorni recenti → cattura il
    *volatility clustering* (la volatilità si raggruppa). Più reattiva della deviazione standard piatta."""
    r = np.asarray(logret, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 20:
        return None
    var = float(r[0] ** 2)
    for x in r[1:]:
        var = lam * var + (1 - lam) * x * x
    return float(np.sqrt(var * 252))


def _block_bootstrap(src, horizon, n_sims, block, rng):
    """Ricampiona BLOCCHI contigui dei rendimenti reali → percorsi (n_sims, horizon).
    Conserva code grasse e clustering di volatilità (cosa che la normale cancella)."""
    n = len(src)
    nb = int(np.ceil(horizon / block))
    starts = rng.integers(0, max(1, n - block), size=(n_sims, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_sims, nb * block)[:, :horizon]
    idx = np.clip(idx, 0, n - 1)
    return src[idx]


def _simulate_returns(logret_arr, horizon_days, n_sims=800, demean=False,
                      drift_annual=None, block=10, seed=42):
    """Distribuzione dei rendimenti su `horizon_days` via block bootstrap dei rendimenti reali.
    - demean=True (BREVE) → drift ≈ 0: niente estrapolazione del trend recente.
    - drift_annual dato (LUNGO da fondamentali) → ricentra su quel drift.
    - altrimenti usa il drift storico, clampato a [-25%, +30%] annuo.
    Ritorna {final, cum_min, sigma_ewma} (rendimenti LOG cumulati e minimo lungo il percorso)."""
    src = np.asarray(logret_arr, dtype=float)
    src = src[~np.isnan(src)]
    n = len(src)
    if n < 40:
        return None
    mean_day = float(src.mean())
    if drift_annual is not None:
        target_day = float(drift_annual) / 252.0
    elif demean:
        target_day = 0.0
    else:
        target_day = float(np.clip(mean_day * 252, -0.25, 0.30)) / 252.0
    src_c = src - mean_day + target_day              # ricentra il drift, conserva forma/tails/clustering
    rng = np.random.default_rng(seed)
    paths = _block_bootstrap(src_c, horizon_days, n_sims, block, rng)
    cum = np.cumsum(paths, axis=1)                   # rendimento log cumulato giorno per giorno
    return {"final": cum[:, -1], "cum_min": cum.min(axis=1), "sigma_ewma": ewma_vol(src)}


def _seed_from(arr) -> int:
    """Seed deterministico ma DIVERSO per serie diverse: un seed fisso (42) faceva sembrare le
    probabilità 'stabili'/identiche tra titoli e giri. Riproducibile a parità di dati."""
    try:
        return int(abs(hash((len(arr), round(float(arr[-1]), 6),
                             round(float(np.nansum(arr)), 4)))) % (2 ** 31))
    except Exception:
        return 42


def forecast_paths(hist, horizon_days, stop_pct=None, demean=None, drift_annual=None):
    """Statistiche di percorso oneste (NON una previsione del prezzo): P(salita), P(perdita>15%),
    ventaglio p10/p50/p90 del rendimento e — se dato `stop_pct` (es. -0.08) — **P(tocca lo stop
    lungo il percorso)** via first-passage (minimo del cammino), non solo a scadenza."""
    try:
        logret = np.log(hist["Close"] / hist["Close"].shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
    except Exception:
        return None
    if demean is None:
        demean = horizon_days <= 63
    sim = _simulate_returns(logret.values, horizon_days, n_sims=1500, demean=demean, drift_annual=drift_annual)
    if sim is None:
        return None
    final, cmin = sim["final"], sim["cum_min"]
    n = len(final)
    p_up = float((final > 0).mean())
    # Intervallo di confidenza (binomiale) su P(salita): rende esplicito l'errore Monte Carlo
    # (half-width ≈ 1.96·√(p(1−p)/n)), così non si legge una % come fosse esatta.
    ci = 1.96 * math.sqrt(max(p_up * (1.0 - p_up), 1e-9) / n)
    out = {
        "p_up": round(p_up * 100),
        "p_up_lo": round(max(0.0, p_up - ci) * 100),
        "p_up_hi": round(min(1.0, p_up + ci) * 100),
        "p_loss15": round(float((final < math.log(0.85)).mean()) * 100),
        "p_gain5": round(float((final > math.log(1.05)).mean()) * 100),   # P(guadagno > +5%)
        "expectancy": round((float(np.mean(np.exp(final))) - 1.0) * 100, 1),  # rendimento atteso (media)
        "ret_p10": round((math.exp(float(np.percentile(final, 10))) - 1) * 100, 1),
        "ret_p50": round((math.exp(float(np.percentile(final, 50))) - 1) * 100, 1),
        "ret_p90": round((math.exp(float(np.percentile(final, 90))) - 1) * 100, 1),
        "sigma_ewma": sim.get("sigma_ewma"),
    }
    if stop_pct is not None and stop_pct < 0:
        out["p_touch_stop"] = round(float((cmin <= math.log(1 + stop_pct)).mean()) * 100)
    return out


def monthly_logrets(hist):
    """Rendimenti logaritmici MENSILI dallo storico (per il bootstrap della proiezione PAC)."""
    if hist is None or hist.empty or "Close" not in hist:
        return None
    c = hist["Close"].dropna()
    if len(c) < 40:
        return None
    try:
        m = c.resample("ME").last().dropna()
    except Exception:
        m = c.iloc[::21]
    lr = np.log(m / m.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
    return lr.values if len(lr) >= 12 else None


def project_future(initial: float, monthly: float, years: float,
                   annual_return: float, sigma: float, n_sims: int = 600,
                   method: str = "bootstrap", month_logrets=None) -> dict:
    """Proiezione PAC a ventaglio (fan chart p10/p50/p90). NON è una previsione del prezzo.
    method: 'bootstrap' (rendimenti reali a blocchi, code grasse + clustering — consigliato),
            'tstudent' (code grasse, ν=5), 'normale' (gaussiana). Il rendimento atteso scelto
            dall'utente fissa il drift; il metodo decide la FORMA dell'incertezza."""
    months = max(int(round(years * 12)), 1)
    invested = initial + monthly * np.arange(months + 1)
    rng = np.random.default_rng(42)
    mu_m = np.log(1 + annual_return) / 12.0
    sig_m = sigma / np.sqrt(12.0)

    if method == "bootstrap" and month_logrets is not None and len(month_logrets) >= 12:
        src = np.asarray(month_logrets, dtype=float)
        src = src - src.mean() + mu_m               # forma reale, drift = rendimento atteso scelto
        steps = _block_bootstrap(src, months, n_sims, block=3, rng=rng)
        label = "block bootstrap dei rendimenti reali (code grasse + clustering)"
    elif method == "tstudent":
        nu = 5
        t = rng.standard_t(nu, size=(n_sims, months)) / np.sqrt(nu / (nu - 2))   # varianza normalizzata a 1
        steps = (mu_m - 0.5 * sig_m ** 2) + sig_m * t
        label = "t-Student (code grasse, ν=5)"
    else:
        z = rng.standard_normal((n_sims, months))
        steps = (mu_m - 0.5 * sig_m ** 2) + sig_m * z
        label = "normale (gaussiana — code sottili)"

    growth = np.exp(steps)
    paths = np.empty((n_sims, months + 1))
    paths[:, 0] = initial
    for m in range(1, months + 1):
        paths[:, m] = paths[:, m - 1] * growth[:, m - 1] + monthly
    pct = {p: np.percentile(paths, p, axis=0) for p in (10, 50, 90)}
    end = paths[:, -1]
    return {
        "months": months, "x_years": np.arange(months + 1) / 12,
        "invested": invested, "total_invested": float(invested[-1]),
        "p10": pct[10], "p50": pct[50], "p90": pct[90],
        "method_label": label,
        "p_below_invested": round(float((end < invested[-1]).mean()) * 100),
    }


def fundamental_drift(info: dict):
    """Rendimento annuo atteso (proxy) dai FONDAMENTALI, per il drift del LUNGO periodo:
    earnings yield (1/PE) + crescita attesa, clampato. None se i dati non bastano.
    NON è una previsione: è un'ancora ragionata al posto del trend storico estrapolato."""
    pe = info.get("trailingPE")
    g = info.get("epsGrowth3Y")
    if g is None:
        g = info.get("earningsGrowth")
    if g is None:
        g = info.get("revenueGrowth")
    ey = (1.0 / pe) if (pe and pe > 0) else None
    if ey is None and g is None:
        return None
    drift = (ey if ey is not None else 0.04) + min(max(g if g is not None else 0.0, -0.05), 0.15)
    return float(np.clip(drift, -0.10, 0.20))


def reverse_dcf_growth(info: dict, discount: float = 0.09):
    """DCF INVERSA (niente fair value a numero singolo = falsa precisione): la crescita perpetua
    che il prezzo attuale sta scontando, modello di Gordon g = r − 1/PE. Indicativo."""
    pe = info.get("trailingPE")
    if not pe or pe <= 0:
        return None
    return round((discount - 1.0 / pe) * 100, 1)


# ---------------------------------------------------------------------------
# CALIBRAZIONE DELLE PREVISIONI — non per indovinare il prezzo, ma per misurare l'ONESTÀ
# delle probabilità: degli eventi a cui diamo ~70%, quanti si avverano davvero?
# (Brier score + tabella per fasce). Si popola NEL TEMPO: ogni P(salita) viene registrata
# e "risolta" a scadenza confrontando il prezzo. Persistenza sul data layer (come il tracking).
# ---------------------------------------------------------------------------
FORECAST_LOG_NAME = "forecast_log.json"


def log_forecast(ticker, horizon_days, p_up, price):
    """Registra una previsione P(salita) per il backtest di calibrazione (max 1/giorno per ticker+orizzonte)."""
    if p_up is None or not price:
        return
    rec = read_data_json(FORECAST_LOG_NAME, [])
    if not isinstance(rec, list):
        rec = []
    today, tk, hh = _today_iso(), ticker.upper(), int(horizon_days)
    for r in rec:
        if r.get("ticker") == tk and r.get("h") == hh and r.get("date") == today:
            return
    rec.append({"date": today, "ticker": tk, "h": hh,
                "p_up": float(p_up), "price": float(price), "outcome": None})
    # tetto ALTO + archivio: le righe che escono dal vivo vanno in archivio, non nel cestino.
    # Si prova a tenerle vive 400 giorni (l'orizzonte lungo è 252 giorni di Borsa); se il file
    # sfonda il tetto invalicabile vanno in archivio comunque, dove resolve_forecasts le trova.
    salva_registro(FORECAST_LOG_NAME, rec, _FORECAST_MAX, giorni_protetti=400)


def resolve_forecasts():
    """Assegna l'esito (0/1) alle previsioni mature: prezzo a scadenza vs prezzo iniziale. Per il job.
    Lavora su TUTTO il registro (archivi annuali + file vivo): l'orizzonte più lungo è 252 giorni di
    Borsa e una riga può essere finita in archivio prima di maturare — deve restare risolvibile."""
    hist_cache = {}

    def _risolvi(rec):
        changed = 0
        for r in rec:
            if r.get("outcome") is not None:
                continue
            d0 = _parse_dt(r.get("date"))
            if not d0 or not r.get("price") or _trading_days_between(r.get("date"), _today_iso(), r.get("ticker")) < r.get("h", 21):
                continue
            tk = r["ticker"]
            if tk not in hist_cache:
                try:
                    hist_cache[tk] = get_history(tk, period="2y")
                except Exception:
                    hist_cache[tk] = None
            h = hist_cache[tk]
            if h is None or h.empty:
                continue
            try:
                after = h["Close"][h.index.tz_localize(None) >= (d0 + datetime.timedelta(days=round(r["h"] * 7 / 5)))].dropna() \
                    if getattr(h.index, "tz", None) is not None else \
                    h["Close"][h.index >= (d0 + datetime.timedelta(days=round(r["h"] * 7 / 5)))].dropna()
                if after.empty:
                    continue
                r["outcome"] = 1 if float(after.iloc[0]) > r["price"] else 0
                changed += 1
            except Exception:
                continue
        return changed

    return aggiorna_registro_completo(FORECAST_LOG_NAME, _risolvi)


def calibration_report():
    """Brier score + tabella per fasce di probabilità (predetto vs realizzato). None se vuoto.
    Legge lo storico COMPLETO (archivio + vivo): la calibrazione migliora accumulando casi."""
    rec = load_registro_completo(FORECAST_LOG_NAME)
    if not isinstance(rec, list):
        return None
    done = [r for r in rec if r.get("outcome") is not None and r.get("p_up") is not None]
    if not done:
        return {"n_total": len(rec) if isinstance(rec, list) else 0, "n_resolved": 0, "brier": None, "buckets": []}
    brier = sum(((r["p_up"] / 100.0) - r["outcome"]) ** 2 for r in done) / len(done)
    buckets = []
    for lo, hi in [(0, 40), (40, 55), (55, 70), (70, 101)]:
        grp = [r for r in done if lo <= r["p_up"] < hi]
        if grp:
            buckets.append({"range": f"{lo}-{min(hi, 100)}%", "n": len(grp),
                            "predetto": round(sum(r["p_up"] for r in grp) / len(grp)),
                            "realizzato": round(sum(r["outcome"] for r in grp) / len(grp) * 100)})
    return {"n_total": len(rec), "n_resolved": len(done), "brier": round(brier, 3), "buckets": buckets}


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


# ---------------------------------------------------------------------------
# QUALITÀ IN SALDO v2 — punteggio a PILASTRI pesati + radar + anti-trappola.
# Sostituisce il conteggio di "pallini" (dove la qualità del business pesava quanto
# il P/S, con soglie uguali per ogni settore) con pilastri pesati, un radar di
# qualità (stile Simply Wall St) e un controllo anti-trappola di valore.
# ---------------------------------------------------------------------------

# Settori "finanziari" dove ROIC / EV-EBIT / Altman non hanno senso (modello diverso)
_FIN_SECTORS = ("financ", "bank", "insurance", "real estate", "realestate", "reit", "mortgage")
_WACC_PROXY = 9.0   # costo del capitale di riferimento (%) per confrontare il ROIC
_PILLAR_WEIGHTS = {"Qualità": 0.35, "Salute": 0.25, "Valore": 0.25, "Crescita": 0.15}


def _is_financial_sector(sector) -> bool:
    s = (sector or "").lower()
    return any(k in s for k in _FIN_SECTORS)


def _lin(v, lo, hi, higher=True):
    """Mappa v in 0-100 fra lo e hi (clampato). higher=False → più basso è meglio."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if higher:
        if v <= lo:
            return 0.0
        if v >= hi:
            return 100.0
        return (v - lo) / (hi - lo) * 100.0
    if v <= lo:
        return 100.0
    if v >= hi:
        return 0.0
    return (hi - v) / (hi - lo) * 100.0


def _avg_scores(scores):
    vals = [s for s in scores if s is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def _div_fcf_cover(info: dict):
    """Copertura del dividendo col FREE CASH FLOW (non col solo utile): FCF yield ÷ dividend yield
    = FCF / dividendi. ≥ ~1,5 = dividendo ben coperto. None se manca un dato."""
    fy, dyp = info.get("fcfYield"), info.get("dividendYield")
    if fy is not None and dyp and dyp > 0:
        return round(fy / dyp, 2)
    return None


def _health_fscore(info: dict):
    """Indice di SALUTE 0-9 (Piotroski semplificato, dati aggregati gratuiti — non i 9 test YoY).
    NON ripete la redditività (ROE/ROA/margini/ROIC), che pesa già nel pilastro QUALITÀ: qui contano
    la generazione di CASSA e il TREND (ricavi/utili/margini in miglioramento). Così si elimina il
    doppio conteggio cross-pilastro e Salute diventa sensibile al peggioramento (anti-trappola)."""
    fcfy = info.get("fcfYield")
    rg, eg = info.get("revenueGrowth"), info.get("earningsGrowth")
    pm, pm5 = info.get("profitMargins"), info.get("netMargin5Y")
    pts, tot = 0, 0

    def chk(cond):
        nonlocal pts, tot
        if cond is None:
            return
        tot += 1
        if cond:
            pts += 1

    chk(None if fcfy is None else fcfy > 0)                          # genera cassa libera
    chk(None if rg is None else rg > 0)                              # ricavi in crescita
    chk(None if eg is None else eg > 0)                              # utili in crescita
    chk(None if (pm is None or pm5 is None) else pm >= pm5 - 0.005)  # margini non in erosione (trend)
    if tot < 2:
        return None
    return round(pts / tot * 9, 1)


def quality_radar(info: dict) -> dict:
    """Cinque assi di qualità (stile Simply Wall St) 0-100: Valore, Qualità, Salute, Crescita, Dividendo.
    Ogni asse è la media dei sotto-criteri disponibili (None se i dati mancano)."""
    pe, pb, ps = info.get("trailingPE"), info.get("priceToBook"), info.get("priceToSalesRatio")
    ev_ebit, fcfy = info.get("evToEbitda"), info.get("fcfYield")
    roe, roa, roic = info.get("returnOnEquity"), info.get("returnOnAssets"), info.get("roic")
    pm, om, gm = info.get("profitMargins"), info.get("operatingMargins"), info.get("grossMargins")
    d2e, cr, icov = info.get("debtToEquity"), info.get("currentRatio"), info.get("interestCoverage")
    rg, rg3 = info.get("revenueGrowth"), info.get("revenueGrowth3Y")
    eg, eg3 = info.get("earningsGrowth"), info.get("epsGrowth3Y")
    dy, payout = info.get("dividendYield"), info.get("payoutRatio")
    fin = _is_financial_sector(info.get("sector"))
    fscore = _health_fscore(info)

    # PEG con la crescita a 3 anni (CAGR), non solo quella passata di 1 anno
    peg = info.get("pegRatioCagr")
    if peg is None and pe and eg3 and eg3 > 0:
        peg = pe / (eg3 * 100)
    if peg is None:
        peg = info.get("pegRatio")

    def pct(x):
        return x * 100 if x is not None else None

    valore = _avg_scores([
        _lin(pe, 10, 35, False) if (pe and pe > 0) else None,
        _lin(pb, 1, 6, False) if (pb and pb > 0) else None,
        _lin(ps, 1, 8, False) if (ps and ps > 0) else None,
        _lin(ev_ebit, 8, 25, False) if (ev_ebit and ev_ebit > 0) else None,
        _lin(fcfy, 2, 8, True),
        _lin(peg, 0.8, 2.5, False) if (peg and peg > 0) else None,
    ])
    qaxes = [_lin(pct(roe), 8, 25, True), _lin(pct(pm), 3, 20, True),
             _lin(pct(om), 5, 25, True), _lin(pct(gm), 20, 60, True), _lin(pct(roa), 2, 12, True)]
    if roic is not None and not fin:
        qaxes.append(_lin(pct(roic) - _WACC_PROXY, 0, 12, True))   # ROIC oltre il costo del capitale
    qualita = _avg_scores(qaxes)
    salute = _avg_scores([
        _lin(d2e, 40, 200, False) if d2e is not None else None,
        _lin(cr, 1.0, 2.5, True),
        _lin(icov, 2, 12, True),
        _lin(fscore, 3, 8, True) if fscore is not None else None,
    ])
    crescita = _avg_scores([_lin(pct(rg), 0, 18, True), _lin(pct(rg3), 0, 18, True),
                            _lin(pct(eg), 0, 18, True), _lin(pct(eg3), 0, 18, True)])
    if dy and dy > 0:
        dy_score = _lin(dy, 1.5, 6, True)
        if dy > 9:                       # rendimento sospettosamente alto = rischio taglio
            dy_score = 40.0
        dividendo = _avg_scores([dy_score,
                                 _lin(payout, 0.4, 0.95, False) if payout is not None else None,
                                 _lin(_div_fcf_cover(info), 1.0, 2.5, True)])
    else:
        dividendo = None
    return {"Valore": valore, "Qualità": qualita, "Salute": salute,
            "Crescita": crescita, "Dividendo": dividendo}


def fundamental_score_v2(info: dict):
    """Punteggio fondamentale 0-100 a PILASTRI pesati (Qualità 35% / Solidità 25% / Valutazione 25% /
    Crescita 15%), non più conteggio di pallini. None se i dati non bastano (< 2 pilastri)."""
    radar = quality_radar(info)
    num = den = 0.0
    used = 0
    for pillar, w in _PILLAR_WEIGHTS.items():
        s = radar.get(pillar)
        if s is not None:
            num += s * w
            den += w
            used += 1
    if den <= 0 or used < 2:
        return None
    return round(num / den, 1)


def value_trap_check(info: dict) -> dict:
    """Anti-trappola di valore (la protezione n°1): guarda il TREND dei fondamentali.
    Ricavi / utili / margini stabili o in crescita = i conti tengono → vera occasione;
    in calo = probabile trappola. Lo sconto di prezzo è valutato a parte (% dal max).
    Ritorna {verdict, factor, label, reasons}."""
    rg, rg3 = info.get("revenueGrowth"), info.get("revenueGrowth3Y")
    eg, eg3 = info.get("earningsGrowth"), info.get("epsGrowth3Y")
    pm, pm5 = info.get("profitMargins"), info.get("netMargin5Y")
    signals, reasons = 0, []

    rgv = rg if rg is not None else rg3
    if rgv is not None:
        if rgv >= 0.03:
            signals += 1; reasons.append("ricavi in crescita")
        elif rgv <= -0.05:
            signals -= 1; reasons.append("ricavi in calo")
    egv = eg if eg is not None else eg3
    if egv is not None:
        if egv >= 0.03:
            signals += 1; reasons.append("utili in crescita")
        elif egv <= -0.10:
            signals -= 1; reasons.append("utili in forte calo")
    if pm is not None and pm5 is not None:
        if pm >= pm5 - 0.005:
            signals += 1; reasons.append("margini stabili o in miglioramento")
        elif pm < pm5 - 0.03:
            signals -= 1; reasons.append("margini in erosione")
    elif pm is not None and pm < 0:
        signals -= 1; reasons.append("attualmente in perdita")

    # Trappola CONCLAMATA ("forte"): va ESCLUSA del tutto, non solo declassata. Due o più segnali
    # negativi, oppure attualmente in perdita CON margini in erosione.
    pm_eroding = (pm is not None and pm5 is not None and pm < pm5 - 0.03)
    unprofitable = (pm is not None and pm < 0)
    strong = bool(signals <= -2 or (unprofitable and pm_eroding))
    if signals >= 1:
        return {"verdict": "occasione", "factor": 1.08, "signals": signals, "strong": False,
                "label": "✅ conti che tengono", "reasons": reasons}
    if signals <= -1:
        return {"verdict": "trappola", "factor": 0.75, "signals": signals, "strong": strong,
                "label": "🛑 fondamentali in peggioramento (possibile trappola)", "reasons": reasons}
    return {"verdict": "neutro", "factor": 1.0, "signals": signals, "strong": False,
            "label": "⚠️ trend incerto", "reasons": reasons or ["trend dei fondamentali poco leggibile"]}


def _fundamental_score(info: dict):
    """Qualità del business 0-100. Usa i pilastri pesati (v2); ripiega sul vecchio
    conteggio di pallini solo se i pilastri non hanno dati sufficienti."""
    v2 = fundamental_score_v2(info)
    if v2 is not None:
        return v2
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


# File che QUESTA sessione dell'app ha modificato: per essi la lettura preferisce il locale
# (read-your-writes), perché il branch remoto di GitHub si aggiorna con ritardo dopo il commit.
# Senza questo, un'eliminazione/aggiunta dal telefono "ricompariva" leggendo il remoto stantio.
_LOCAL_WRITES = set()
# Registri il cui salvataggio REMOTO è fallito in questa sessione: il lavoro automatico li
# stampa in fondo al giro, così un token scaduto o una rete assente si vedono invece di far
# sparire i dati in silenzio.
_SALVATAGGI_FALLITI = set()

# --- AVVISI DI SALVATAGGIO -------------------------------------------------
# _SALVATAGGI_FALLITI vive nella memoria del processo, quindi un fallimento avvenuto nel lavoro
# automatico non arriva MAI all'app: finiva in una riga di registro sui server di GitHub, che nessuno
# legge. Era l'unico caso in cui un dato poteva svanire senza che se ne sapesse niente.
# Qui il fallimento viene SCRITTO in un file suo, minuscolo, e l'app lo mostra da sola.
# Perché un file a parte funziona anche quando il salvataggio grosso è appena fallito: la causa
# tipica è la dimensione (oltre 1 MB l'API si comporta male) o un rifiuto su quel percorso, e un
# file da poche centinaia di byte ha ottime probabilità di passare comunque. Se non passa nemmeno
# lui, non si perde nulla di più di prima.
AVVISI_NAME = "avvisi_salvataggio.json"
_AVVISI_MAX = 60
_AVVISI_DENTRO = [False]      # anti-ricorsione: l'avviso non deve generare un avviso su se stesso


def _segna_avviso(nome: str, byte_tentati: int = 0) -> None:
    """Mette a verbale che il salvataggio di `nome` non è arrivato al deposito."""
    if nome == AVVISI_NAME or _AVVISI_DENTRO[0]:
        return
    _AVVISI_DENTRO[0] = True
    try:
        avvisi = read_data_json(AVVISI_NAME, None)
        avvisi = avvisi if isinstance(avvisi, list) else []
        quando = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        for a in avvisi:
            if isinstance(a, dict) and a.get("file") == nome and not a.get("risolto"):
                a["ultimo"] = quando
                a["volte"] = int(a.get("volte") or 1) + 1
                a["byte"] = byte_tentati or a.get("byte")
                break
        else:
            avvisi.append({"file": nome, "primo": quando, "ultimo": quando, "volte": 1,
                           "byte": byte_tentati, "risolto": None,
                           "sospetto_dimensione": bool(byte_tentati and byte_tentati > 900_000)})
        write_data_json(AVVISI_NAME, avvisi[-_AVVISI_MAX:], force=True)
    except Exception:
        pass
    finally:
        _AVVISI_DENTRO[0] = False


def _togli_avviso(nome: str) -> None:
    """Segna come risolto un avviso: il salvataggio di quel file è tornato a funzionare. Non lo
    cancella — sapere che ieri qualcosa non è passato resta un'informazione utile."""
    if nome == AVVISI_NAME or _AVVISI_DENTRO[0]:
        return
    _AVVISI_DENTRO[0] = True
    try:
        avvisi = read_data_json(AVVISI_NAME, None)
        if not isinstance(avvisi, list):
            return
        cambiato = False
        for a in avvisi:
            if isinstance(a, dict) and a.get("file") == nome and not a.get("risolto"):
                a["risolto"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                cambiato = True
        if cambiato:
            write_data_json(AVVISI_NAME, avvisi, force=True)
    except Exception:
        pass
    finally:
        _AVVISI_DENTRO[0] = False


def avvisi_salvataggio(solo_aperti: bool = True) -> list:
    """Gli avvisi di salvataggio, i più recenti per primi. È quello che l'app mostra in cima."""
    avvisi = read_data_json(AVVISI_NAME, None)
    if not isinstance(avvisi, list):
        return []
    fuori = [a for a in avvisi if isinstance(a, dict) and (not solo_aperti or not a.get("risolto"))]
    return sorted(fuori, key=lambda a: str(a.get("ultimo") or ""), reverse=True)


def spiega_avviso(a: dict) -> str:
    """L'avviso in italiano, con il sospetto sulla causa quando c'è: serve a poter fare qualcosa,
    non solo a sapere che qualcosa non va."""
    if not isinstance(a, dict):
        return ""
    quante = int(a.get("volte") or 1)
    quando = (f"{quante} volte, l'ultima il {a.get('ultimo')}" if quante > 1
              else f"il {a.get('ultimo')}")
    testo = (f"Il salvataggio di **{a.get('file')}** non è arrivato al deposito dei dati "
             f"({quando}).")
    kb = int((a.get("byte") or 0) / 1024)
    if a.get("sospetto_dimensione"):
        testo += (f" Il file pesa circa {kb} KB: vicino o oltre il limite di 1 MB, dove il deposito "
                  "non si comporta più bene. Va alleggerito spostando la parte vecchia in archivio.")
    elif kb:
        testo += (f" Il file pesa circa {kb} KB, quindi non è un problema di dimensione: le cause "
                  "probabili sono il permesso di scrittura scaduto o la rete.")
    return testo


def read_data_json(name: str, default):
    """Legge un file dati. Normalmente preferisce il branch remoto (cache 2 min)
    con fallback locale. Nel job autonomo (env DATA_LOCAL_FIRST=1) — e per i file che l'app
    ha appena scritto in questa sessione (_LOCAL_WRITES) — preferisce il file locale, così
    legge ciò che ha appena scritto (read-your-writes); il remoto resta lo storico iniziale."""
    local_first = (os.environ.get("DATA_LOCAL_FIRST") == "1") or (name in _LOCAL_WRITES)
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


def _commit_to_github(name: str, content_str: str, force: bool = False) -> bool:
    """Salva il file sul branch dati via API GitHub (serve un token con permesso
    'contents'). Ritorna True se ok. Usato dall'app per rendere persistenti da
    telefono le scelte manuali (segui/smetti). Con force=False rifiuta di ridurre
    un registro storico (vedi _riduce_storico)."""
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
            j = g.json()
            sha = j.get("sha")
            # Se il contenuto sul branch è IDENTICO a quello da scrivere, niente commit:
            # evita decine di commit inutili a ogni giro del job (storia pulita).
            try:
                existing = base64.b64decode("".join(j.get("content", "").split())).decode("utf-8")
                if existing == content_str:
                    return True
                # PROTEZIONE DEFINITIVA dello storico: qui conosciamo con certezza il contenuto
                # attuale del branch (lo abbiamo appena letto), quindi possiamo rifiutare in modo
                # affidabile una scrittura che RIDURREBBE un registro storico. Copre anche il caso
                # che la guardia locale non vede: lettura fallita → lista vuota → append di 1
                # elemento → 1 riga scritta sopra centinaia. Se questa GET non riuscisse, `sha`
                # resterebbe None e l'aggiornamento fallirebbe da sé: nessun danno possibile.
                if _scrittura_pericolosa(name, content_str, existing, force):
                    return False
            except Exception:
                pass
        body = {"message": f"app update {name}", "branch": branch,
                "content": base64.b64encode(content_str.encode("utf-8")).decode("ascii")}
        if sha:
            body["sha"] = sha
        p = requests.put(api, headers=headers, json=body, timeout=12)
        return p.status_code in (200, 201)
    except Exception:
        return False


# Registri che solo CRESCONO (storici): in condizioni normali non possono diventare vuoti.
# Una lista vuota su questi file è il sintomo di una LETTURA FALLITA (read_data_json ritorna il
# valore di ripiego quando la richiesta al branch non riesce), non di un dato reale: scriverla
# cancellerebbe lo storico. Nomi scritti a mano perché le costanti sono definite più sotto nel file
# (test di coerenza: vedi il controllo che confronta questo insieme con le costanti).
_REGISTRI_APPEND_ONLY = frozenset({
    "track_record.json", "forecast_log.json", "conv_log.json",
    "exit_history.json", "scenario_log.json", "presignal_log.json", "diario_eventi.json",
})

# File di STATO VIVO: contengono la situazione corrente (titoli seguiti con la loro storia,
# occasioni in osservazione, posizioni in portafoglio, preferenze). Qui le rimozioni SONO legittime
# — una o due alla volta — ma un crollo improvviso (svuotamento, o meno della metà da un giro
# all'altro) non è un dato reale: è la stessa lettura fallita che il 16/08/2026 ha azzerato i
# registri, e qui costerebbe il monitoraggio intero o il portafoglio. Chi rimuove DAVVERO passa
# force=True: una scelta esplicita, mai un effetto collaterale.
# NON stanno qui exit_cooldown.json e sell_alerts.json: si svuotano da soli per scadenza, è normale.
_FILE_STATO_VIVO = frozenset({"tracking.json", "opp_watch.json", "portfolio.json", "opp_config.json"})
_CROLLO_MIN_VOCI = 8      # sotto questa dimensione si blocca solo lo svuotamento totale

# TETTI del file VIVO, calibrati sulla dimensione REALE di una riga (misurata sul branch) perché
# ogni file vivo deve restare sotto ~600 KB: oltre 1 MB l'API GitHub non restituisce più il
# contenuto e la protezione anti-cancellazione si spegnerebbe in silenzio. Tutto ciò che esce dal
# tetto NON viene buttato: va negli archivi annuali (vedi _archivia_e_pota / load_registro_completo).
# RITARATO (ago 2026): una riga di scenario pesava ~330 byte, ma da quando porta i «passaggi» —
# la fotografia dei quattro momenti — ne pesa 945 (554 sono i soli passaggi), misurati sul branch.
# Col tetto vecchio il file vivo avrebbe raggiunto 1,89 MB, e col margine 2,46 MB: superato 1 MB
# l'API GitHub non restituisce più il contenuto e la protezione anti-cancellazione si spegne PER
# SEMPRE, perché l'archiviazione tiene il vivo a quel numero di righe. Sarebbe successo intorno alle
# 1.100 righe, cioè in circa un anno al ritmo attuale di ~85 righe al mese. Niente si perde: quello
# che esce dal tetto va negli archivi annuali e i risolutori lo completano comunque.
_SCENARIO_MAX_LIVE = 600       # ~945 byte/riga → ~570 KB (col margine 1,3: ~740 KB)
_PRESIGNAL_MAX_LIVE = 4000     # ~122 byte/riga → ~490 KB
_EXIT_HISTORY_MAX_LIVE = 2000  # ~278 byte/riga → ~555 KB
_FORECAST_MAX = 5000           # ~113 byte/riga → ~565 KB
# Misurato adesso: 314 byte/riga su 2.600 righe = 817 KB, cioè il file vivo è GIÀ oltre il tetto e
# oltre il margine, quindi l'archiviazione parte a ogni giro e siamo a un passo dal muro di 1 MB.
_CONV_LOG_MAX = 1500           # ~314 byte/riga → ~470 KB (col margine 1,3: ~610 KB)
_TRACK_RECORD_MAX = 2500       # ~212 byte/riga → ~530 KB
# Di quanto il file vivo può superare il tetto per tenere in vita le righe non ancora mature.
# Oltre questo margine si archivia comunque: un file vivo troppo grande spegne la protezione
# anti-cancellazione, e allora il rischio non è più "un esito non calcolato" ma "il registro intero".
_MARGINE_TETTO = 1.3       # caso peggiore ~860 KB: resta un margine vero sotto il muro di 1 MB


# QUANTE RIGHE DOVREBBE AVERE OGNI REGISTRO. È il dato in più che permette di distinguere «questo
# file non esiste ancora» da «non riesco a leggerlo» — due situazioni che arrivano identiche (lista
# vuota) e che nessun confronto fra vecchio e nuovo potrà mai separare. Senza questo numero, una
# lettura fallita seguita da una scrittura cancella lo storico, ed è esattamente com'è andata il
# 16/08/2026. Sta sotto archivio/, quindi è protetto dalle stesse guardie che protegge.
CONTEGGI_NAME = "archivio/conteggi_registri.json"
_CONTEGGI_MEM = {}        # aggiornato a ogni scrittura riuscita; si salva una volta per giro


def _quante(obj) -> int:
    return len(obj) if isinstance(obj, (list, dict)) else 0


def _conteggi_registri() -> dict:
    d = read_data_json(CONTEGGI_NAME, None)
    d = d if isinstance(d, dict) else {}
    if _CONTEGGI_MEM:
        d = dict(d)
        d.update(_CONTEGGI_MEM)
    return d


def _sotto_il_conteggio_atteso(name: str, obj) -> bool:
    """True se stiamo per scrivere MENO righe di quelle che quel registro dovrebbe avere.
    Vale solo per i registri che possono soltanto crescere: i file di stato vivo si accorciano per
    davvero (una voce rimossa è un dato reale) e li protegge _crollo_stato."""
    if name not in _REGISTRI_APPEND_ONLY and not name.startswith("archivio/"):
        return False
    atteso = (_conteggi_registri().get(name) or {}).get("righe")
    try:
        return bool(atteso) and _quante(obj) < int(atteso)
    except (TypeError, ValueError):
        return False


def _segna_conteggio(name: str, obj) -> None:
    """Ricorda quante righe ha adesso quel registro. In memoria: si scrive una volta per giro,
    perché salvarlo a ogni scrittura raddoppierebbe le chiamate all'API per nulla. Se il giro muore
    prima di salvarlo il numero resta quello vecchio, cioè più BASSO del vero — che è il verso
    innocuo dell'errore: protegge un po' meno, non blocca niente di legittimo."""
    if name in _REGISTRI_APPEND_ONLY or name.startswith("archivio/"):
        _CONTEGGI_MEM[name] = {"righe": _quante(obj), "aggiornato": _now_iso()}


def salva_conteggi() -> bool:
    """Mette su disco i conteggi raccolti in questo giro. Da chiamare una volta, alla fine."""
    if not _CONTEGGI_MEM:
        return True
    letto = read_data_json(CONTEGGI_NAME, None)
    # SE LA LETTURA FALLISCE non si scrive con force. Questa tabella protegge TUTTI i registri:
    # sostituirla con i pochi conteggi di questo giro spegnerebbe la protezione su tutti gli altri
    # in un colpo, e force=True passerebbe sopra a ogni guardia. Senza force, se il file esiste la
    # guardia anti-riduzione lo rifiuta da sola; se non esiste ancora, la scrittura passa.
    letta_bene = isinstance(letto, dict) and bool(letto)
    fuori = dict(letto) if isinstance(letto, dict) else {}
    for k, v in _CONTEGGI_MEM.items():
        vecchio = (fuori.get(k) or {}).get("righe") or 0
        nuovo = v.get("righe") or 0
        # Il conteggio segue SEMPRE la realtà, comprese le riduzioni. E le riduzioni sono legittime:
        # l'archiviazione sposta le righe vecchie, e mettere da parte un registro lo azzera. Quelle
        # passano tutte da force=True, cioè da una scelta dichiarata — e se il conteggio non
        # scendesse con loro, da quel momento bloccherebbe ogni scrittura successiva credendo di
        # difendere righe che nessuno vuole più. Quando scende si annota da quanto veniva, così un
        # calo inatteso resta visibile invece di passare liscio.
        fuori[k] = dict(v) if nuovo >= vecchio else dict(v, era=vecchio)
    return write_data_json(CONTEGGI_NAME, fuori, force=letta_bene)


def azzera_conteggio(name: str) -> bool:
    """Rimette a zero il numero atteso di un registro. Serve quando lo si svuota di proposito —
    per esempio mettendo da parte i dati vecchi — altrimenti la guardia bloccherebbe per sempre
    ogni scrittura successiva, credendo di stare difendendo righe che nessuno vuole più."""
    fuori = read_data_json(CONTEGGI_NAME, None)
    if not isinstance(fuori, dict):
        return False
    _CONTEGGI_MEM.pop(name, None)
    fuori[name] = {"righe": 0, "aggiornato": _now_iso(), "azzerato": True}
    return write_data_json(CONTEGGI_NAME, fuori, force=True)


def _riduce_storico(name: str, nuovo_str: str, vecchio_str: str, force: bool = False) -> bool:
    """True se scrivere `nuovo_str` su un REGISTRO STORICO ne ridurrebbe il numero di elementi.
    Uno storico che si accorcia non è un dato reale: è il sintomo di una lettura fallita a monte
    (chi legge riceve il valore di ripiego, ci aggiunge una riga e riscrive tutto). I casi legittimi
    non riducono nulla: un append aumenta di 1, e lo spostamento in archivio riscrive il file vivo
    con `force=True`. Vale anche per i file d'archivio (archivio/...), che non si toccano più."""
    if force or (name not in _REGISTRI_APPEND_ONLY and not name.startswith("archivio/")):
        return False
    try:
        nuovo, vecchio = json.loads(nuovo_str), json.loads(vecchio_str)
    except Exception:
        return False
    if not isinstance(nuovo, (list, dict)) or not isinstance(vecchio, (list, dict)):
        return False
    if len(nuovo) < len(vecchio):
        return True
    # NON BASTA CONTARE LE RIGHE. La protezione guardava solo QUANTE righe c'erano, quindi una
    # scrittura che tiene tutte le righe ma le SVUOTA dentro passava liscia: due processi che
    # lavorano sullo stesso registro (l'app e il lavoro automatico ogni mezz'ora) leggono, modificano
    # e riscrivono l'intero file, e l'ultimo che salva cancella il lavoro dell'altro senza che nulla
    # protesti. Con i «passaggi» — la fotografia dei quattro momenti, che è la parte più costosa da
    # ricostruire e per lo storico irrecuperabile — questo significherebbe perderla in silenzio.
    # Qui si rifiuta una scrittura che riduce di oltre un quarto il numero di righe che HANNO i
    # passaggi: le perdite fisiologiche (una riga archiviata, un campo che matura) restano possibili.
    try:
        if isinstance(nuovo, list) and isinstance(vecchio, list):
            def _con_passaggi(rs):
                return sum(1 for r in rs if isinstance(r, dict) and (r.get("passaggi") or {}).get("promozione"))
            v, n = _con_passaggi(vecchio), _con_passaggi(nuovo)
            if v >= 8 and n < v * 0.75:
                return True
    except Exception:
        pass
    # …E LO STESSO PER OGNI ALTRO CAMPO, senza doverli elencare a mano. Il controllo qui sopra è
    # scritto per un campo solo, quindi copriva i «passaggi» e lasciava scoperto tutto il resto —
    # comprese le SOGLIE del diario, che sono la parte più costosa da ricostruire e per lo storico
    # irrecuperabile: un bersaglio ricalcolato mesi dopo è il bersaglio di un altro giorno. Un
    # elenco scritto a mano poi divergerebbe appena si aggiunge un campo, quindi qui si guardano
    # TUTTI i campi: se uno era pieno in almeno 8 righe e la scrittura lo svuoterebbe in oltre un
    # quarto di quelle, non è un dato che matura — è un dato che sparisce.
    if _svuota_un_campo(nuovo, vecchio):
        return True
    return False


def _svuota_un_campo(nuovo, vecchio) -> str:
    """Il nome del primo campo che la scrittura svuoterebbe, o "" se nessuno. Conta quante righe
    hanno un valore VERO per ogni campo (zero, None, liste e dizionari vuoti non contano) e
    confronta prima e dopo. Le perdite fisiologiche restano possibili: una riga archiviata, un campo
    che cambia, un episodio che si chiude. Quello che si blocca è lo svuotamento in massa.
    Funziona sia sulle liste di righe sia sui dizionari di voci (i titoli seguiti, le osservazioni):
    in quel caso le «righe» sono i valori del dizionario."""
    if isinstance(nuovo, dict) and isinstance(vecchio, dict):
        nuovo, vecchio = list(nuovo.values()), list(vecchio.values())
    if not isinstance(nuovo, list) or not isinstance(vecchio, list):
        return ""
    try:
        def pieni(rs):
            conta = {}
            for r in rs:
                if not isinstance(r, dict):
                    continue
                for k, x in r.items():
                    if x or x == 0:
                        conta[k] = conta.get(k, 0) + 1
            return conta

        pv, pn = pieni(vecchio), pieni(nuovo)
        for campo, quanti in pv.items():
            if quanti >= 8 and pn.get(campo, 0) < quanti * 0.75:
                return campo
    except Exception:
        return ""
    return ""


def _crollo_stato(name: str, nuovo_str: str, vecchio_str: str, force: bool = False) -> bool:
    """True se la scrittura farebbe CROLLARE un file di stato vivo (titoli seguiti, osservazioni,
    portafoglio, preferenze): svuotarlo, oppure ridurlo a meno della metà in un colpo. Le rimozioni
    normali passano: togliere una o due voci su decine non attiva nulla. Sotto _CROLLO_MIN_VOCI si
    blocca soltanto lo svuotamento, così un portafoglio di poche posizioni resta gestibile.
    Vale sia per i file a dizionario sia per quelli a lista (il portafoglio è una lista)."""
    if force or name not in _FILE_STATO_VIVO:
        return False
    try:
        nuovo, vecchio = json.loads(nuovo_str), json.loads(vecchio_str)
    except Exception:
        return False
    if not isinstance(nuovo, (dict, list)) or not isinstance(vecchio, (dict, list)) or not vecchio:
        return False
    if type(nuovo) is not type(vecchio):
        return False                     # cambio di forma: non è un confronto sensato
    if not nuovo:
        return True                      # da "pieno" a "vuoto" non è mai un dato reale
    if len(vecchio) >= _CROLLO_MIN_VOCI and len(nuovo) * 2 < len(vecchio):
        return True
    # NON BASTA CONTARE LE VOCI, come non bastava per gli storici. Qui dentro c'è la roba che non si
    # ricostruisce: i prezzi d'ingresso dei titoli seguiti, gli scatti, le fotografie iniziali delle
    # osservazioni. Una scrittura che tiene tutte le 78 voci e le svuota DENTRO passerebbe liscia,
    # e il file di stato vivo più grosso (i titoli seguiti) è proprio quello che ha già superato
    # 1 MB, cioè quello dove la protezione remota è spenta. Chi svuota di proposito — l'archiviazione
    # degli scatti — passa da force=True, che qui sopra esce subito.
    return bool(_svuota_un_campo(nuovo, vecchio))


def _scrittura_pericolosa(name: str, nuovo_str: str, vecchio_str: str, force: bool = False) -> bool:
    """Vero se questa scrittura distruggerebbe dati: uno storico che si accorcia (registri e
    archivi) o un file di stato vivo che crolla (titoli seguiti, osservazioni, portafoglio)."""
    return (_riduce_storico(name, nuovo_str, vecchio_str, force)
            or _crollo_stato(name, nuovo_str, vecchio_str, force))


def write_data_json(name: str, obj, force: bool = False) -> bool:
    """Scrive un file dati: sempre su file locale; se in modalità cloud con token,
    anche sul branch remoto (così la modifica persiste e si vede dal telefono).

    PROTEZIONE ANTI-CANCELLAZIONE (due livelli): per i registri storici
    (_REGISTRI_APPEND_ONLY) una scrittura che ne RIDURREBBE il contenuto viene rifiutata, e per i
    file a dizionario (_REGISTRI_DIZIONARIO: titoli seguiti e osservazioni) una che li SVUOTEREBBE
    o li dimezzerebbe di colpo — qui in base a quel che si riesce a leggere in locale/remoto, e in
    modo definitivo dentro _commit_to_github, che il contenuto del branch lo conosce con certezza.
    NB: il secondo livello legge via API dei contenuti, che sopra ~1 MB restituisce contenuto vuoto
    e quindi non protegge (è il caso di tracking.json); il primo livello legge da
    raw.githubusercontent, che non ha quel limite, quindi resta valido a qualsiasi dimensione.
    È così che il 16/08/2026 sono stati azzerati scenario_log (26 KB) ed exit_history (4,7 KB):
    una lettura remota fallita restituiva [] e il salvataggio lo scriveva sopra i dati buoni.
    Per ridurre davvero un registro serve force=True (scelta esplicita, non un effetto collaterale)."""
    content = json.dumps(obj, ensure_ascii=False, indent=0)
    if not force and (name in _REGISTRI_APPEND_ONLY or name in _FILE_STATO_VIVO
                      or name.startswith("archivio/")):
        try:
            esistente = read_data_json(name, None)
        except Exception:
            esistente = None
        if isinstance(esistente, (list, dict)) and _scrittura_pericolosa(
                name, content, json.dumps(esistente, ensure_ascii=False, indent=0)):
            return False    # non distruggo dati
        if esistente is None and _sotto_il_conteggio_atteso(name, obj):
            # ECCO IL BUCO CHE HA FATTO PERDERE I DATI IL 16/08/2026, e questa è la sua chiusura.
            # Quando la rilettura NON riesce, il confronto qui sopra viene saltato del tutto: e
            # allora un chiamante che ha ricevuto [] da una lettura fallita, ci ha aggiunto una
            # riga e riscrive, cancella tutto lo storico senza che nulla protesti. Il punto è che
            # «il file non esiste» e «non riesco a leggerlo» arrivano IDENTICI, quindi nessun
            # confronto potrà mai separarli: serve un dato in più, tenuto altrove — quante righe
            # quel registro dovrebbe avere. Se ne stiamo scrivendo meno, non si scrive.
            return False
    ok_locale = False
    percorso = os.path.join(APPDIR, name)     # fuori dal try: serve anche al ripulisci-temporaneo
    try:
        # i file d'archivio stanno in una sottocartella (archivio/…): va creata, altrimenti la
        # scrittura fallirebbe in silenzio e l'archiviazione non partirebbe mai.
        cartella = os.path.dirname(percorso)
        if cartella:
            os.makedirs(cartella, exist_ok=True)
        # SCRITTURA IN DUE TEMPI: prima su un file temporaneo, poi lo si rinomina sopra
        # l'originale. Aprire direttamente in scrittura azzera il file SUBITO: se il processo muore
        # nel mezzo (o il disco è pieno, o la cartella è in sincronizzazione) resta un file troncato
        # e il contenuto di prima non esiste più. Con la rinomina o c'è il file vecchio o c'è quello
        # nuovo, mai niente in mezzo.
        tmp = percorso + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, percorso)
        _LOCAL_WRITES.add(name)        # read-your-writes: d'ora in poi leggi il locale per questo file
        ok_locale = True
    except Exception:
        try:
            if os.path.exists(percorso + ".tmp"):
                os.remove(percorso + ".tmp")
        except Exception:
            pass
    # ESITO DEL SALVATAGGIO REMOTO: prima veniva chiamato e buttato via. Se il token è scaduto, se
    # la rete non va o se GitHub rifiuta, il salvataggio falliva in SILENZIO — e sui server del
    # lavoro automatico il file locale muore col giro, quindi la riga appena nata svaniva senza che
    # nessuno lo sapesse. Ora l'esito si ritenta una volta, si annota e viene restituito a chi
    # chiama, che può decidere di non fare il passo successivo (vedi _archivia_e_pota).
    ok_remoto = True
    if _data_repo() and _github_token():
        ok_remoto = _commit_to_github(name, content, force)
        if not ok_remoto:
            ok_remoto = _commit_to_github(name, content, force)      # un secondo tentativo
        if not ok_remoto:
            _SALVATAGGI_FALLITI.add(name)
            _segna_avviso(name, len(content.encode("utf-8")))
        else:
            _SALVATAGGI_FALLITI.discard(name)
            _togli_avviso(name)
    # invalida la cache di lettura remota così la modifica si vede subito
    try:
        _fetch_remote_json.clear()
    except Exception:
        pass
    esito = bool(ok_locale or ok_remoto)
    # Quante righe ha adesso: è il numero che permetterà, la prossima volta, di accorgersi che una
    # lettura è fallita invece di scrivere una riga sola sopra tutto il resto. Si segna solo se il
    # salvataggio è andato — e nel lavoro automatico solo se è arrivato DAVVERO sul deposito,
    # perché lì il file locale muore col giro e un conteggio più alto del vero bloccherebbe le
    # scritture successive.
    if esito and ok_remoto:
        try:
            _segna_conteggio(name, obj)
        except Exception:
            pass
    return esito


# ---------------------------------------------------------------------------
# ARCHIVIO STORICO — nessuna riga viene MAI buttata.
#
# Perché i registri "vivi" hanno comunque un tetto: a ogni aggiunta il file viene riletto e
# riscritto INTERO (è un JSON su un branch GitHub), e soprattutto l'API dei contenuti di GitHub
# NON restituisce il contenuto dei file oltre ~1 MB: superata quella soglia si perderebbero il
# confronto anti-duplicato e — cosa grave — la PROTEZIONE anti-cancellazione di _commit_to_github.
# Quindi: file vivo piccolo e veloce (~600 KB al massimo), e tutto ciò che esce dal tetto finisce
# in un archivio per ANNO (archivio/<registro>_<anno>.json) che non viene più potato né riscritto.
# Le statistiche leggono archivio + vivo (load_registro_completo), così il quadro resta COMPLETO
# per sempre; i risolutori lavorano solo sul vivo (le righe archiviate sono già mature).
# ---------------------------------------------------------------------------
ARCHIVIO_DIR = "archivio"
_ANNO_INIZIO_ARCHIVIO = 2026        # primo anno del progetto: prima non esistono dati


def _nome_archivio(name: str, anno) -> str:
    base = name[:-5] if name.endswith(".json") else name
    return f"{ARCHIVIO_DIR}/{base}_{anno}.json"


def _anno_di(riga) -> str:
    """Anno di una riga di registro, dal primo campo-data disponibile."""
    if isinstance(riga, dict):
        for k in ("date", "data", "removed", "added", "obs_date", "pre_date"):
            v = riga.get(k)
            if v and len(str(v)) >= 4 and str(v)[:4].isdigit():
                return str(v)[:4]
    return "senza-data"


def _riga_giovane(riga, giorni: int) -> bool:
    """True se la riga è più recente di `giorni`: non va archiviata perché i suoi esiti
    potrebbero non essere ancora maturi (i risolutori vedono solo il file vivo)."""
    try:
        d = datetime.date.fromisoformat(str(_anno_di(riga)) + "-01-01")  # fallback se manca il giorno
        for k in ("date", "removed", "added"):
            v = (riga or {}).get(k)
            if v:
                d = datetime.date.fromisoformat(str(v)[:10])
                break
        return d >= datetime.date.fromisoformat(_today_iso()) - datetime.timedelta(days=giorni)
    except Exception:
        return True          # data illeggibile: nel dubbio la tengo viva


def _archivia_e_pota(name: str, rows: list, live_max: int, giorni_protetti: int = 0) -> list:
    """Tiene il registro vivo entro `live_max` righe SPOSTANDO le più vecchie negli archivi
    annuali (niente viene perso). Le righe più recenti di `giorni_protetti` restano vive anche se
    oltre il tetto, perché i loro esiti devono ancora maturare — ma solo fino al TETTO INVALICABILE
    (live_max × _MARGINE_TETTO): oltre quello si archiviano comunque. Altrimenti la protezione
    delle righe recenti gonfierebbe il file senza limite (es. conv_log: 120 righe/giorno × 60 giorni
    = 2,1 MB) e sopra 1 MB si spegne la protezione anti-cancellazione. Una riga archiviata prima di
    maturare non è persa e nemmeno abbandonata: i risolutori la completano comunque, perché lavorano
    su archivi + vivo (aggiorna_registro_completo). Se l'archiviazione non riesce NON pota nulla:
    meglio un file vivo più grande che dati buttati. Ritorna le righe da tenere vive."""
    if not isinstance(rows, list) or len(rows) <= live_max:
        return rows
    taglio = len(rows) - live_max
    testa, resto = rows[:taglio], rows[taglio:]
    # Si ragiona per INDICI, non per copie, così l'ordine cronologico resta intatto in entrambe le
    # liste anche quando una parte delle protette torna fra le archiviabili.
    prot = [i for i, r in enumerate(testa) if _riga_giovane(r, giorni_protetti)] if giorni_protetti else []
    troppe = len(prot) + len(resto) - int(live_max * _MARGINE_TETTO)
    if troppe > 0:
        prot = prot[troppe:]        # le più VECCHIE fra le protette si archiviano comunque
    prot = set(prot)
    candidati = [r for i, r in enumerate(testa) if i not in prot]
    protette = [r for i, r in enumerate(testa) if i in prot]
    if not candidati:
        return rows
    per_anno = {}
    for r in candidati:
        per_anno.setdefault(_anno_di(r), []).append(r)
    for anno, righe in per_anno.items():
        arc = _nome_archivio(name, anno)
        try:
            esistenti = read_data_json(arc, [])
            if not isinstance(esistenti, list):
                esistenti = []
            nuovo = esistenti + righe
            # LA POTATURA DIPENDE DALL'ESITO VERO. Prima si scriveva l'archivio e si
            # "verificava" rileggendolo: ma la rilettura prende il file LOCALE appena scritto,
            # quindi la verifica passava sempre — anche quando il salvataggio remoto era stato
            # rifiutato — e il registro vivo veniva potato comunque. Su un archivio oltre il
            # limite di lettura di GitHub questo può sovrascrivere migliaia di righe col solo
            # lotto nuovo e poi accorciare il vivo: perdita doppia, in silenzio.
            if not write_data_json(arc, nuovo):
                return rows          # scrittura d'archivio non riuscita: NON poto il vivo
            # LA RISPOSTA POSITIVA NON BASTA, e la rilettura non aiuta: write_data_json dice
            # "riuscito" anche col solo successo locale, e la verifica qui sotto rilegge proprio
            # quel file locale (il nome e ormai fra le scritture di questa sessione), quindi
            # passerebbe sempre. Nel lavoro automatico il file locale muore col giro: potare il
            # vivo fidandosi di quella verifica butterebbe righe che sul deposito non esistono.
            # L'unico segnale che dice la verita e' _SALVATAGGI_FALLITI.
            if arc in _SALVATAGGI_FALLITI:
                return rows          # arrivato solo in locale: NON poto il vivo
            verifica = read_data_json(arc, None)
            if not isinstance(verifica, list) or len(verifica) < len(nuovo):
                return rows          # archivio non confermato: non poto il vivo
        except Exception:
            return rows
    return protette + resto


def salva_registro(name: str, rows: list, live_max: int, giorni_protetti: int = 0) -> bool:
    """Salva un registro storico spostando l'eccedenza negli archivi annuali.
    USARE QUESTA, non write_data_json: dopo un'archiviazione il file vivo è più CORTO di quello
    esistente, e la protezione anti-cancellazione RIFIUTEREBBE la scrittura. Le righe resterebbero
    sia in archivio sia nel vivo, contate DUE VOLTE dalle statistiche e ri-archiviate a ogni giro del
    job (600 → 1.200 → 1.800 …). Il `force` si passa SOLO quando si è davvero archiviato: in tutti
    gli altri casi la protezione deve restare accesa."""
    tenute = _archivia_e_pota(name, rows, live_max, giorni_protetti)
    archiviato = isinstance(rows, list) and isinstance(tenute, list) and len(tenute) < len(rows)
    # L'ESITO SI RESTITUISCE: chi scrive una riga nuova deve poter sapere se e' arrivata, altrimenti
    # crede di averla messa a verbale e non riprova mai piu.
    return bool(write_data_json(name, tenute, force=archiviato))


def aggiorna_registro_completo(name: str, aggiorna) -> int:
    """Applica `aggiorna(righe)` — che modifica le righe SUL POSTO e ritorna quante ne ha cambiate —
    a TUTTI i pezzi del registro: prima gli archivi annuali, poi il file vivo.
    Serve ai RISOLUTORI: una riga finita in archivio prima che il suo esito fosse maturo (la
    previsione a 1 anno, la resa a 21 giorni di Borsa) deve poter essere completata comunque,
    altrimenti resterebbe senza esito per sempre e la calibrazione si fermerebbe. Riscrivere un
    archivio con lo STESSO numero di righe è consentito dalla protezione anti-cancellazione, che
    guarda soltanto la lunghezza. Ritorna quante righe sono state completate in tutto."""
    tot = 0
    anni = [str(a) for a in range(_ANNO_INIZIO_ARCHIVIO, int(_today_iso()[:4]) + 1)] + ["senza-data"]
    for anno in anni:
        arc = _nome_archivio(name, anno)
        righe = read_data_json(arc, None)
        if not isinstance(righe, list) or not righe:
            continue
        n = aggiorna(righe) or 0
        if n:
            write_data_json(arc, righe)
            tot += n
    vivo = read_data_json(name, [])
    if isinstance(vivo, list) and vivo:
        n = aggiorna(vivo) or 0
        if n:
            write_data_json(name, vivo)      # stessa lunghezza: la protezione non blocca
            tot += n
    return tot


def load_archivio(name: str) -> list:
    """Tutte le righe archiviate di un registro (tutti gli anni disponibili)."""
    out = []
    anni = [str(a) for a in range(_ANNO_INIZIO_ARCHIVIO, int(_today_iso()[:4]) + 1)] + ["senza-data"]
    for anno in anni:
        d = read_data_json(_nome_archivio(name, anno), None)
        if isinstance(d, list) and d:
            out.extend(d)
    return out


def load_registro_completo(name: str, vivo=None) -> list:
    """Registro COMPLETO = archivio + file vivo (in quest'ordine, cioè cronologico).
    È quello che devono usare le STATISTICHE, così il quadro non si accorcia mai."""
    if vivo is None:
        vivo = read_data_json(name, [])
    if not isinstance(vivo, list):
        vivo = []
    return load_archivio(name) + vivo


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
        # MAI il testo grezzo: l'indirizzo chiamato contiene il token, e requests lo mette dentro
        # il messaggio dell'eccezione. Il docstring qui sopra promette che non accade: ora e' vero.
        return False, f"eccezione di rete: {type(e).__name__}"


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

    # Fattori di rischio/qualità dalla serie storica + affidabilità continua
    rfac = _risk_factors(h)
    reliab_factor = _reliab_factor(rfac.get("sig_a"), rfac.get("n"))

    etf, fscore, name = False, None, ticker
    sector, pe, pb, ps = None, None, None, None
    radar = trap = None
    roic = ev_ebit = fcf_yield = gross_m = icov = div_cov = None
    rev_cagr3 = eps_cagr3 = fscore_health = None
    fdr = None                               # rendimento atteso dai fondamentali (drift del lungo)
    if with_fundamentals:                    # solo per il lungo periodo (qualità)
        info = get_info(ticker)
        etf = is_fund(info) or is_known_etf(ticker)   # riconosce gli ETF anche sul cloud
        fscore = _fundamental_score(info) if not etf else None
        name = (info.get("shortName") or info.get("longName") or ticker)[:34]
        sector = info.get("sector")
        pe = _nn(info.get("trailingPE"))
        pb = _nn(info.get("priceToBook"))
        ps = _nn(info.get("priceToSalesRatio"))
        if not etf:
            radar = quality_radar(info)              # 5 assi di qualità (display)
            trap = value_trap_check(info)            # anti-trappola di valore (protezione n°1)
            roic = _nn(info.get("roic"))
            ev_ebit = _nn(info.get("evToEbitda"))
            fcf_yield = _nn(info.get("fcfYield"))
            gross_m = _nn(info.get("grossMargins"))
            icov = _nn(info.get("interestCoverage"))
            div_cov = _div_fcf_cover(info)
            rev_cagr3 = _nn(info.get("revenueGrowth3Y"))
            eps_cagr3 = _nn(info.get("epsGrowth3Y"))
            fscore_health = _health_fscore(info)
            fdr = fundamental_drift(info)            # earnings yield + crescita → drift del lungo

    # Probabilità statistiche (block bootstrap dei rendimenti reali). Orizzonte: breve ~1 mese
    # (drift ≈ 0), lungo ~1 anno (drift dai FONDAMENTALI se disponibile, altrimenti storico).
    # NON è una previsione: è una stima della distribuzione dei rendimenti passati.
    prob_gain, prob_loss, exp_ret, reliab = _gain_loss_prob(
        h, horizon_days=(252 if with_fundamentals else 21),
        drift_annual=(fdr if with_fundamentals else None))

    return dict(ticker=ticker.upper(), name=name, price=price, rsi=rsi, dd_high=dd_high,
                perf_1m=perf_1m, perf_5d=perf_5d, perf_1y=perf_1y, below_bb=below_bb,
                above_sma200=above_sma200,
                etf=etf, fscore=fscore, prob_gain=prob_gain, prob_loss=prob_loss,
                exp_ret=exp_ret, reliab=reliab, reliab_factor=reliab_factor, rebound_pot=rebound_pot,
                sharpe=rfac.get("sharpe"), sortino=rfac.get("sortino"), ulcer=rfac.get("ulcer"),
                maxdd=rfac.get("maxdd"), hist_z=rfac.get("hist_z"),
                sector=sector, pe=pe, pb=pb, ps=ps,
                radar=radar, trap=trap, roic=roic, ev_ebit=ev_ebit, fcf_yield=fcf_yield,
                gross_m=gross_m, interest_cov=icov, div_cov=div_cov,
                rev_cagr3=rev_cagr3, eps_cagr3=eps_cagr3, fscore_health=fscore_health,
                atr=atr_val, atr_pct=atr_pct, rr=rr, rvol=rvol, avg_dollar_vol=avg_dollar_vol,
                green_day=green_day, rsi_rising=rsi_rising, back_in_bb=back_in_bb,
                reversal_confirmed=reversal_confirmed, vertical_crash=vertical_crash,
                target_price=target_price, stop_price=stop_price,
                spark=spark, spark_dates=spark_dates)


def _reliab_label(sig_a, n):
    """Affidabilità a 3 livelli: alta con bassa volatilità e storico lungo, bassa se molto volatile."""
    if sig_a <= 0.35 and n >= 180:
        return "🟢 Alta"
    if sig_a <= 0.60 and n >= 120:
        return "🟡 Media"
    return "🔴 Bassa"


def _gain_loss_prob_normal(logret, horizon_days, sig_a, n):
    """Ripiego: modello normale (usato solo se lo storico è troppo corto per il bootstrap)."""
    mu_a = float(np.clip(logret.mean() * 252, -0.25, 0.30))
    f = horizon_days / 252.0
    mu_h, sig_h = mu_a * f, sig_a * np.sqrt(f)
    cdf = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    p_gain = round(cdf(mu_h / sig_h) * 100)
    p_loss = round(cdf((math.log(0.85) - mu_h) / sig_h) * 100)
    exp_ret = round((math.exp(mu_h) - 1) * 100, 1)
    return p_gain, p_loss, exp_ret, _reliab_label(sig_a, n)


def _gain_loss_prob(h, horizon_days=21, drift_annual=None):
    """P(salita), P(perdita>15%), guadagno atteso % e affidabilità — da **BLOCK BOOTSTRAP dei
    rendimenti reali** (code grasse + volatility clustering), non più da una normale: le
    probabilità sono molto più oneste. Drift ≈ 0 sul breve (niente trend estrapolato); sul LUNGO
    usa `drift_annual` se fornito (ancora dai FONDAMENTALI: earnings yield + crescita), altrimenti
    il drift storico clampato. Ripiego al modello normale se lo storico è troppo corto. NON è una previsione."""
    try:
        logret = np.log(h["Close"] / h["Close"].shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
    except Exception:
        return None, None, None, None
    n = len(logret)
    if n < 30:
        return None, None, None, None
    sig_a = float(logret.std() * np.sqrt(252))
    if sig_a <= 0:
        return None, None, None, None
    # breve → drift 0 (demean); lungo → drift dai fondamentali se dato, altrimenti storico clampato
    sim = _simulate_returns(logret.values, horizon_days, n_sims=800,
                            demean=(horizon_days <= 63 and drift_annual is None),
                            drift_annual=drift_annual, seed=_seed_from(logret.values))
    if sim is None:
        return _gain_loss_prob_normal(logret, horizon_days, sig_a, n)
    final = sim["final"]
    p_gain = round(float((final > 0).mean()) * 100)
    p_loss = round(float((final < math.log(0.85)).mean()) * 100)
    exp_ret = round((math.exp(float(np.median(final))) - 1) * 100, 1)
    return p_gain, p_loss, exp_ret, _reliab_label(sig_a, n)


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


# ===========================================================================
# INDICE DEI PARAMETRI CONFIGURABILI (tutte le "manopole" del sistema occasioni)
# Sono definite vicino alla logica che le usa; qui l'elenco unico per ritrovarle.
#   FILTRI SCAN:        _MIN_PRICE / _MIN_DOLLAR_VOL (breve) · _MIN_PRICE_LONG / _MIN_DOLLAR_VOL_LONG
#                       (lungo) · _RR_MIN · _ATR_STOP_K · _SECTOR_CAP_LONG
#   CONVENIENZA:        _CONV_WEIGHTS (pesi per fattore, breve/lungo) · _CONV_K (scala tanh) ·
#                       pesi APPRESI in conv_weights.json (override, vedi _active_weights/fit_conv_weights)
#   FONDAMENTALI:       _WACC_PROXY · _PILLAR_WEIGHTS (vicino a quality_radar)
#   OSSERVAZIONE:       _OBS_ENTRY_CONV (ingresso) · _OBS_WINDOW (giorni di Borsa) · _OBS_GAP_MIN ·
#                       _OBS_MAX_DAYS/_OBS_MAX_KEEP · _STICKY_CAP
#   PROMOZIONE:         _PROMO_MIN_RET (+% prezzo) · _PROMO_MIN_CONV · _PROMO_MAX_CONV_DECAY ·
#                       _PROMO_USE_CONV_TREND (+ _PROMO_MIN_GAIN/_PROMO_MAX_DIP)
#   MONITORAGGIO:       _REMOVE_WINDOW · _NOTIFY_WINDOW · _NOTIFY_MIN_RET · _SNAP_GAP_MIN/_SNAP_MAX_*
#   FEEDBACK PESI:      _FIT_MIN_SAMPLES · _FIT_MAX_LEARNED (vicino a fit_conv_weights)
#   FISCALITÀ:          CAPITAL_GAINS_TAX (26%, usata da net_return_pct e portfolio_view)
# ===========================================================================

# --- Parametri operativi del breve periodo (rimbalzo / ipervenduto) ---
_ATR_STOP_K = 2.0          # stop = prezzo − k·ATR (volatilità reale, non minimo a 20gg)
_RR_MIN = 1.5              # scarta i setup con Rischio/Rendimento sotto questa soglia
_MIN_PRICE = 3.0           # sotto questo prezzo l'RSI è inaffidabile (penny) → escluso
_MIN_DOLLAR_VOL = 1_000_000  # liquidità minima (~$ scambiati/giorno) → niente illiquidi
_SECTOR_CAP_LONG = 4       # max occasioni di lungo per settore (no liste tutte-banche)
# Filtri liquidità/prezzo anche sul LUNGO (prima assenti): soglia più bassa del breve, così
# restano incluse small/mid cap europee legittime ma si escludono penny/illiquidi inaffidabili.
_MIN_PRICE_LONG = 1.0        # prezzo minimo per le occasioni di lungo
_MIN_DOLLAR_VOL_LONG = 300_000  # liquidità minima sul lungo (~$ scambiati/giorno)


def _short_score(r, regime=1.0):
    if r["rsi"] is None:
        return None
    rsi = r["rsi"]
    # quanto è ipervenduto (0-50) in modo CONTINUO (niente gradini/cliff arbitrari):
    # ~12 a RSI 45, ~50 a RSI 25, →0 oltre ~48; ricalca i vecchi scalini ma senza salti.
    base = max(0.0, min(50.0, 12.0 + (45.0 - rsi) * 1.9))
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
        # ETF: non solo lo sconto. Combina sconto + rischio-aggiustato (Sortino) + tendenza (SMA200)
        # − dolore (Ulcer): così un ETF obbligazionario stabile e uno azionario in caduta non hanno
        # lo stesso metro del solo "quanto è sceso".
        sc = 0.60 * disc
        so = r.get("sortino")
        if so is not None:
            sc += max(-1.5, min(1.5, so)) / 1.5 * 22.0
        av = r.get("above_sma200")
        sc += 13.0 if av is True else (-10.0 if av is False else 0.0)
        ul = r.get("ulcer")
        if ul is not None:
            sc -= min(max(ul, 0.0), 25.0) / 25.0 * 10.0
        return max(0.0, min(100.0, sc))
    if r["fscore"] is None:
        return None
    base = r["fscore"] * 0.6 + disc * 0.4       # qualità del business (pilastri) + sconto
    trap = r.get("trap") or {}
    base *= trap.get("factor", 1.0)             # anti-trappola: declassa i fondamentali in peggioramento
    return max(0.0, min(100.0, base))


def _long_reasons(r):
    bits = []
    if r["etf"]:
        bits.append("ETF diversificato in saldo")
    elif r["fscore"] is not None:
        bits.append(f"qualità del business {r['fscore']:.0f}/100" if r["fscore"] >= 60
                    else f"qualità nella media {r['fscore']:.0f}/100")
    trap = r.get("trap")
    if trap and not r["etf"]:
        bits.append(trap["label"])              # ✅ conti che tengono / ⚠️ incerto / 🛑 trappola
    if r.get("roic") is not None and not r["etf"]:
        bits.append(f"ROIC {r['roic'] * 100:.0f}%")
    if r["dd_high"] is not None:
        bits.append(f"in saldo: {abs(r['dd_high']):.0f}% sotto il massimo dell'anno")
    if r.get("rev_cagr3") is not None:
        bits.append(f"ricavi 3 anni {r['rev_cagr3'] * 100:+.0f}%/anno")
    elif r["perf_1y"] is not None:
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
              "riskadj": 0.4, "ddpen": 0.5, "histcheap": 0.4, "trend": 0.4, "prob": 0.2,
              "relstrength": 0.5},
    "long":  {"quality": 1.0, "valcheap": 0.9, "discount": 0.6, "histcheap": 0.5,
              "riskadj": 0.4, "ddpen": 0.4, "momentum": 0.4, "prob": 0.4, "trappen": 0.6},
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
        # forza relativa: rendimento del titolo − indice (positivo = regge meglio del mercato →
        # rimbalzo più credibile; in un sell-off non premia chi scende solo perché scende tutto)
        bm = r.get("bench_5d") if r.get("perf_5d") is not None else r.get("bench_1m")
        f["relstrength"] = (mom - bm) if (mom is not None and bm is not None) else None
    else:
        f["quality"] = r.get("fscore")
        f["valcheap"] = None    # riempito da _fill_valcheap (z relativo al settore)
        # anti-trappola come fattore: segnali negativi (fondamentali in peggioramento) abbassano
        # la convenienza; positivi ("conti che tengono") la alzano. None per ETF → neutro.
        f["trappen"] = (r.get("trap") or {}).get("signals")
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
    # Squashing morbido (tanh) invece del taglio netto a [0,100]: un titolo solo un po' migliore
    # della mediana NON satura più a 100 e l'informazione agli estremi resta leggibile.
    conv = 50.0 + 50.0 * math.tanh(k * raw / 50.0)
    conv = 50.0 + (conv - 50.0) * (reliab_factor or 0.75)   # affidabilità continua → verso 50
    return int(round(max(0.0, min(100.0, conv))))


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
    weights = _active_weights(kind)     # pesi appresi dai rendimenti se disponibili, altrimenti prior
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
    """Convenienza 'a sconto rispetto a SÉ' per un singolo titolo (snapshot di monitoraggio):
    ANCORATA alla storia del titolo, NON all'universo di uno scan (che cambierebbe il voto a seconda
    di cosa altro è stato scansionato, ereditando statistiche scorrelate). Combina sconto dai massimi,
    posizione vs media storica (hist_z), ipervenduto (breve), rischio (Sortino/Ulcer), qualità (lungo)
    e vantaggio di probabilità. Stabile nel tempo → NON confrontabile con la colonna dello scan."""
    score = 50.0
    dd = r.get("dd_high")
    if dd is not None:
        score += min(max(-dd, 0.0), 40.0) / 40.0 * 18.0          # −40% dai massimi → +18
    hz = r.get("hist_z")
    if hz is not None:
        score += max(-2.0, min(2.0, -hz)) * 6.0                  # sotto la propria media = a sconto
    rsi = r.get("rsi")
    if kind == "short" and rsi is not None:
        score += max(-1.0, min(1.0, (45.0 - rsi) / 25.0)) * 10.0  # ipervenduto = +
    so = r.get("sortino")
    if so is not None:
        score += max(-1.5, min(1.5, so)) * 4.0
    ul = r.get("ulcer")
    if ul is not None:
        score -= min(max(ul, 0.0), 25.0) / 25.0 * 6.0            # più "dolore" = −
    pg, pl = r.get("prob_gain"), r.get("prob_loss")
    if pg is not None and pl is not None:
        score += max(-40.0, min(40.0, pg - pl)) / 40.0 * 8.0
    if kind == "long" and r.get("fscore") is not None:
        score += (r["fscore"] - 50.0) / 50.0 * 10.0              # qualità del business
        if (r.get("trap") or {}).get("strong"):
            score -= 12.0                                        # trappola conclamata
    rf = r.get("reliab_factor") or 0.75
    score = 50.0 + (score - 50.0) * rf                           # smorza verso 50 se stima incerta
    return int(round(max(0.0, min(100.0, score))))


# ---------------------------------------------------------------------------
# LOOP DI FEEDBACK — logga convenienza + fattori vs RESA FORWARD (5/21 giorni) e, quando ci sono
# abbastanza esiti, stima i pesi della convenienza con una regressione RIDGE fusa con i pesi a mano
# (prior). Resta DORMIENTE (usa i prior) finché i campioni risolti non bastano: niente overfitting.
# ---------------------------------------------------------------------------
CONV_LOG_NAME = "conv_log.json"          # storia: fattori + resa forward, per stimare i pesi
CONV_WEIGHTS_NAME = "conv_weights.json"  # pesi APPRESI (override dei prior quando validi)
_FIT_MIN_SAMPLES = 150                   # esiti risolti minimi per attivare i pesi appresi
_FIT_MAX_LEARNED = 0.6                   # quota massima dei pesi appresi (il resto resta prior)
# Le righe di uno STESSO giorno non sono prove indipendenti: condividono il mercato di quel giorno.
# Il registro cresce di ~120 righe al giorno, quindi 150 righe possono essere UN SOLO giorno di
# scansione. Serve una soglia su qualcosa di indipendente: le giornate distinte.
_FIT_MIN_GIORNI = 15
# Le rese estreme si TAGLIANO (non si buttano) prima della regressione: se un frazionamento sfugge
# alla guardia, non deve decidere lui i pesi. Il taglio è doppio: un limite fisso (±50%) e uno
# ricavato dai dati (mediana ± k volte la dispersione tipica), perché un limite fisso da solo non
# basta — una riga tagliata a +50% resta enorme rispetto a rese che si muovono di qualche punto.
_FIT_WINSOR = 50.0
_FIT_WINSOR_K = 5.0
_FIT_TEST_QUOTA = 0.30      # ultima parte delle GIORNATE, usata solo per verificare (mai per imparare)
_FIT_MARGINE = 0.010        # di quanto i pesi appresi devono battere quelli a mano per essere adottati
_FIT_VERSIONE = 2           # timbro: i pesi scritti prima della verifica fuori campione non si usano


def _log_convenience(kind, items, convmap) -> None:
    """Logga (1/giorno per ticker+kind) i fattori grezzi + convenienza + prezzo, per calibrare poi i
    pesi dai rendimenti realizzati. Chiamata SOLO dal job (vedi scan_opportunities)."""
    items = [r for r in items if r]
    if not items:
        return
    rec = read_data_json(CONV_LOG_NAME, [])
    if not isinstance(rec, list):
        rec = []
    today = _today_iso()
    have = {(x.get("ticker"), x.get("kind"), x.get("date")) for x in rec}
    facs = [_factor_values(r, kind) for r in items]
    if kind == "long":
        _fill_valcheap(items, facs)
    added = False
    for r, f in zip(items, facs):
        if (r["ticker"], kind, today) in have:
            continue
        rec.append({"date": today, "ticker": r["ticker"], "kind": kind,
                    "price": _jsonable(r.get("price")), "conv": _jsonable(convmap.get(r["ticker"])),
                    "factors": {k: _jsonable(v) for k, v in f.items()},
                    "ret_5d": None, "ret_21d": None})
        added = True
    if added:
        # NB: il vecchio tetto di 6000 righe superava 1,8 MB — oltre il limite in cui l'API GitHub
        # smette di restituire il contenuto (e quindi la protezione anti-cancellazione). Ora il
        # file vivo è più piccolo ma NIENTE si perde: l'eccedenza va in archivio.
        # 35 giorni: la resa forward più lunga è a 21 giorni di Borsa (~29 di calendario).
        salva_registro(CONV_LOG_NAME, rec, _CONV_LOG_MAX, giorni_protetti=35)


_SPLIT_TOLL = 0.25        # scostamento oltre il quale il prezzo registrato è su un'altra SCALA
_RESA_IMPOSSIBILE = 100.0  # oltre questa resa si sospetta un frazionamento e si va a verificare


def resolve_convenience_log() -> int:
    """Riempie la resa forward (5/21 giorni di Borsa) delle righe mature, dal prezzo storico. Per il job.
    Lavora su archivi + file vivo: questo registro cresce di ~120 righe al giorno, quindi una riga
    può finire in archivio prima dei 21 giorni di Borsa e senza questo resterebbe senza esito —
    cioè inutile all'apprendimento dei pesi della convenienza.

    GUARDIA ANTI-FRAZIONAMENTO (aggiunta ago 2026). Era l'unico dei quattro risolutori senza questo
    controllo, e le conseguenze erano gravi: dopo un raggruppamento di azioni lo storico viene
    riscalato mentre il prezzo registrato no, quindi la resa risultava assurda (misurato: +50.421%
    su DFNS, +16.854% su INLF, 81 righe oltre il +100%). E questo registro non è una vetrina: le sue
    rese sono il BERSAGLIO con cui si imparano i pesi della convenienza, e la regressione minimizza
    l'errore al QUADRATO — quindi quelle poche righe decidevano quali fattori contano. Qui le righe
    fuori scala vengono marcate `bad_data` (non cancellate: restano visibili) e le già risolte con
    valori impossibili vengono ri-verificate contro lo storico e marcate a loro volta."""
    cache = {}

    def _storico(tk):
        if tk not in cache:
            try:
                cache[tk] = get_history(tk, "1y")
            except Exception:
                cache[tk] = None
        h = cache[tk]
        if h is None or getattr(h, "empty", True):
            return None
        closes = h["Close"].dropna()
        if getattr(closes.index, "tz", None) is not None:
            closes = closes.copy()
            closes.index = closes.index.tz_localize(None)
        return closes

    def _fuori_scala(closes, x):
        """True se il prezzo registrato non è sulla stessa scala della chiusura di quel giorno."""
        try:
            s0 = closes[closes.index >= pd.Timestamp(str(x["date"])[:10])]
            return (not s0.empty) and abs(float(s0.iloc[0]) / float(x["price"]) - 1) > _SPLIT_TOLL
        except Exception:
            return False

    def _risolvi(rec):
        changed = 0
        for x in rec:
            if x.get("bad_data") or not x.get("price"):
                continue
            rese = [abs(x[c]) for c in ("ret_5d", "ret_21d") if x.get(c) is not None]
            # 1) riparazione delle righe GIÀ risolte con valori impossibili (scritte prima di questa
            #    guardia): si va a controllare la scala e, se è cambiata, si marcano.
            if rese and max(rese) > _RESA_IMPOSSIBILE:
                closes = _storico(x.get("ticker"))
                if closes is not None and _fuori_scala(closes, x):
                    x["bad_data"] = True
                    changed += 1
                continue
            if x.get("ret_21d") is not None:
                continue
            # 2) risoluzione normale, con il controllo di scala PRIMA di scrivere qualsiasi resa
            attesi = [(h, f) for h, f in ((5, "ret_5d"), (21, "ret_21d"))
                      if x.get(f) is None
                      and _trading_days_between(x.get("date"), _today_iso(), x.get("ticker")) >= h]
            if not attesi:
                continue
            closes = _storico(x.get("ticker"))
            if closes is None:
                continue
            if _fuori_scala(closes, x):
                x["bad_data"] = True
                changed += 1
                continue
            for h_days, fld in attesi:
                try:
                    start = datetime.date.fromisoformat(str(x["date"])[:10])
                    target = pd.to_datetime(start + datetime.timedelta(days=round(h_days * 7 / 5)))
                    after = closes[closes.index >= target]
                    if not after.empty:
                        x[fld] = round((float(after.iloc[0]) / x["price"] - 1) * 100, 2)
                        changed += 1
                except Exception:
                    continue
        return changed

    return aggiorna_registro_completo(CONV_LOG_NAME, _risolvi)


def _giorno_di(x) -> str:
    return str((x or {}).get("date") or "")[:10]


def _limiti_resa(valori):
    """Limiti entro cui tagliare le rese: mediana ± k volte la dispersione tipica, mai oltre il
    limite fisso. La dispersione si misura con lo scarto MEDIANO (non la deviazione standard, che
    sarebbe già rovinata dai valori assurdi che vogliamo tagliare)."""
    v = np.asarray([float(x) for x in valori], dtype=float)
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med)))
    if mad > 0:
        largo = _FIT_WINSOR_K * 1.4826 * mad
        return max(-_FIT_WINSOR, med - largo), min(_FIT_WINSOR, med + largo)
    return -_FIT_WINSOR, _FIT_WINSOR


def _ridge_pesi(rows, keys, prior):
    """Pesi grezzi dalla regressione ridge, con due accorgimenti che prima mancavano:
    - la resa si demedia GIORNO PER GIORNO, non una volta su tutto: altrimenti i pesi imparano
      l'andamento generale del mercato (se un giorno sale tutto, sale anche chi era peggio) invece
      di imparare a distinguere i titoli fra loro, che è l'unica cosa che serve alla selezione;
    - la resa si taglia a ±_FIT_WINSOR: la ridge minimizza l'errore al quadrato, quindi senza il
      taglio una sola riga da +2000% (raggruppamento sfuggito) deciderebbe tutti i pesi.
    Ritorna i pesi riscalati alla stessa grandezza dei prior, oppure None."""
    stats = {k: _robust([x["factors"].get(k) for x in rows]) for k in keys}
    X = np.array([[_zc(x["factors"].get(k), stats[k]) for k in keys] for x in rows], dtype=float)
    lo, hi = _limiti_resa([x["ret_21d"] for x in rows])
    y = np.array([float(np.clip(x["ret_21d"], lo, hi)) for x in rows], dtype=float)
    giorni = np.array([_giorno_di(x) for x in rows])
    for g in np.unique(giorni):
        m = giorni == g
        y[m] = y[m] - y[m].mean()
    try:
        w = np.linalg.solve(X.T @ X + 5.0 * np.eye(X.shape[1]), X.T @ y)
    except Exception:
        return None, stats
    if np.sum(np.abs(w)) > 1e-9:
        w = w / np.sum(np.abs(w)) * np.sum(np.abs(prior))
    return w, stats


def _ic_medio(rows, keys, pesi, stats) -> float:
    """Quanto bene un insieme di pesi ORDINA i titoli: correlazione di rango fra punteggio e resa
    calcolata DENTRO ogni giornata (mai fra giornate diverse, altrimenti misurerebbe il mercato),
    poi media fra le giornate. È il metro con cui si decide se i pesi appresi valgono qualcosa."""
    per_giorno = {}
    for x in rows:
        per_giorno.setdefault(_giorno_di(x), []).append(x)
    lo, hi = _limiti_resa([x["ret_21d"] for x in rows])
    ic = []
    for _g, gr in per_giorno.items():
        if len(gr) < 8:
            continue
        punt = [sum(pesi[i] * _zc(x["factors"].get(k), stats[k]) for i, k in enumerate(keys)) for x in gr]
        rese = [float(np.clip(x["ret_21d"], lo, hi)) for x in gr]
        if len(set(punt)) < 3:
            continue
        c = pd.Series(punt).corr(pd.Series(rese), method="spearman")
        if c is not None and not np.isnan(c):
            ic.append(float(c))
    return float(np.mean(ic)) if ic else float("nan")


def fit_conv_weights(kind: str):
    """Stima i pesi della convenienza dai rendimenti realizzati (resa a 21 giorni di Borsa) con
    regressione RIDGE sui fattori standardizzati, FUSA con i pesi a mano in base alla numerosità.

    NOVITÀ (ago 2026) — I PESI DEVONO DIMOSTRARE DI FUNZIONARE. Prima venivano adottati senza alcuna
    verifica: imparati e giudicati sugli stessi dati, con l'unico controllo «almeno 150 righe».
    Misurato: fuori campione non aggiungevano nulla sul breve e sul lungo erano PEGGIORI dei pesi
    impostati a mano. Ora: si impara sulle giornate più VECCHIE, si verifica su quelle più recenti
    (che il calcolo non ha visto) e si adottano solo se ordinano i titoli meglio dei pesi a mano.
    Si escludono le righe marcate `bad_data` (frazionamenti) e si richiedono abbastanza GIORNATE
    distinte, non solo righe.

    Ritorna (pesi | None, diagnostica): None significa «tengo i pesi impostati a mano», e la
    diagnostica dice perché — va salvata, altrimenti la scelta resta invisibile."""
    rec = load_registro_completo(CONV_LOG_NAME)
    audit = {"versione": _FIT_VERSIONE, "data": _today_iso(), "adottati": False}
    if not isinstance(rec, list):
        audit["esito"] = "registro non leggibile"
        return None, audit
    rows = [x for x in rec if x.get("kind") == kind and x.get("ret_21d") is not None
            and x.get("factors") and not x.get("bad_data")]
    giorni = sorted({_giorno_di(x) for x in rows if _giorno_di(x)})
    audit.update({"righe": len(rows), "giorni": len(giorni),
                  "scartate_frazionamenti": sum(1 for x in rec if x.get("kind") == kind and x.get("bad_data"))})
    if len(rows) < _FIT_MIN_SAMPLES or len(giorni) < _FIT_MIN_GIORNI:
        audit["esito"] = (f"servono almeno {_FIT_MIN_SAMPLES} righe e {_FIT_MIN_GIORNI} giornate "
                          f"distinte: ho {len(rows)} righe in {len(giorni)} giornate")
        return None, audit
    keys = list(_CONV_WEIGHTS[kind].keys())
    prior = np.array([_CONV_WEIGHTS[kind][k] for k in keys], dtype=float)
    confine = giorni[max(1, int(len(giorni) * (1 - _FIT_TEST_QUOTA)))]
    train = [x for x in rows if _giorno_di(x) < confine]
    test = [x for x in rows if _giorno_di(x) >= confine]
    audit.update({"confine": confine, "righe_train": len(train), "righe_verifica": len(test)})
    if len(train) < _FIT_MIN_SAMPLES // 2 or len(test) < 50:
        audit["esito"] = "dati insufficienti per separare apprendimento e verifica"
        return None, audit
    w_tr, stats_tr = _ridge_pesi(train, keys, prior)
    if w_tr is None:
        audit["esito"] = "la regressione non ha prodotto un risultato"
        return None, audit
    alpha_tr = min(_FIT_MAX_LEARNED, len(train) / 1000.0)
    fusi_tr = np.clip((1 - alpha_tr) * prior + alpha_tr * w_tr, 0.0, None)
    ic_app = _ic_medio(test, keys, fusi_tr, stats_tr)
    ic_prior = _ic_medio(test, keys, prior, stats_tr)
    audit.update({"ordina_meglio_appresi": None if np.isnan(ic_app) else round(ic_app, 4),
                  "ordina_meglio_a_mano": None if np.isnan(ic_prior) else round(ic_prior, 4)})
    # L'asticella non è «meglio dei pesi a mano», è «meglio dei pesi a mano E utile in assoluto»:
    # se sulle giornate di verifica entrambi ordinano al CONTRARIO (correlazione negativa), essere
    # «meno peggio» non significa niente e adottare i pesi imparati sarebbe una scelta a caso.
    asticella = max(0.0, ic_prior) + _FIT_MARGINE
    audit["asticella"] = round(asticella, 4)
    if np.isnan(ic_app) or np.isnan(ic_prior) or not (ic_app > asticella):
        audit["esito"] = ("sulle giornate di verifica i pesi imparati non ordinano i titoli meglio di "
                          "quelli impostati a mano (o non li ordinano affatto): tengo quelli a mano")
        return None, audit
    # Superata la verifica: si ri-stima su TUTTE le giornate (più dati = pesi più stabili) e si adotta.
    w_all, _ = _ridge_pesi(rows, keys, prior)
    if w_all is None:
        audit["esito"] = "verifica superata ma la stima finale è fallita"
        return None, audit
    alpha = min(_FIT_MAX_LEARNED, len(rows) / 1000.0)
    blended = np.clip((1 - alpha) * prior + alpha * w_all, 0.0, None)
    spenti = [k for k, v in zip(keys, blended) if v <= 0]
    audit.update({"esito": "adottati: ordinano meglio dei pesi a mano", "adottati": True,
                  "quota_appresa": round(alpha, 2), "fattori_spenti": spenti})
    return {k: round(float(v), 3) for k, v in zip(keys, blended)}, audit


def update_conv_weights() -> dict:
    """Aggiorna (se possibile) i pesi appresi per breve e lungo. Chiamata dal job.
    Salva SEMPRE la diagnostica in conv_weights.json sotto "_audit", anche quando i pesi vengono
    rifiutati: così «perché sto usando i pesi a mano» è una domanda con risposta scritta."""
    learned = read_data_json(CONV_WEIGHTS_NAME, {})
    if not isinstance(learned, dict):
        learned = {}
    audit_tot = learned.get("_audit") if isinstance(learned.get("_audit"), dict) else {}
    changed = False
    for kind in ("short", "long"):
        w, audit = fit_conv_weights(kind)
        audit_tot[kind] = audit
        if w:
            learned[kind] = w
        else:
            learned.pop(kind, None)      # niente pesi non verificati in giro
        changed = True
    if changed:
        learned["_audit"] = audit_tot
        write_data_json(CONV_WEIGHTS_NAME, learned)
    return learned


def _active_weights(kind: str) -> dict:
    """Pesi della convenienza: quelli APPRESI se hanno superato la verifica fuori campione,
    altrimenti quelli impostati a mano. Mantiene SEMPRE le stesse chiavi (niente chiavi spurie).

    I pesi appresi si usano SOLO se portano il timbro della versione con verifica: quelli scritti
    prima (ago 2026) erano tarati su rese falsate dai frazionamenti — bastava il 3,8% delle righe per
    spostarli del 173% — e non erano mai stati messi alla prova. Senza timbro si ignorano."""
    base = dict(_CONV_WEIGHTS[kind])
    learned = read_data_json(CONV_WEIGHTS_NAME, {})
    if not isinstance(learned, dict) or not isinstance(learned.get(kind), dict):
        return base
    audit = (learned.get("_audit") or {}).get(kind) if isinstance(learned.get("_audit"), dict) else None
    if not (isinstance(audit, dict) and audit.get("versione") == _FIT_VERSIONE and audit.get("adottati")):
        return base
    for k in base:
        v = learned[kind].get(k)
        if isinstance(v, (int, float)) and v >= 0:
            base[k] = float(v)
    return base


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
def _benchmark_perf(symbol: str = "^GSPC") -> dict:
    """Rendimento ~5 giorni e ~1 mese dell'indice di riferimento, per la FORZA RELATIVA del breve.
    Una sola chiamata per scan (cache 15 min): non viola il design 'breve = 1 chiamata per titolo'."""
    try:
        c = get_history(symbol, period="3mo")["Close"].dropna()
    except Exception:
        return {"perf_5d": None, "perf_1m": None}
    p5 = float(c.iloc[-1] / c.iloc[-6] - 1) * 100 if len(c) > 6 else None
    p1m = float(c.iloc[-1] / c.iloc[-21] - 1) * 100 if len(c) > 21 else None
    return {"perf_5d": p5, "perf_1m": p1m}


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


# Da quale porta è entrata un'occasione, in italiano. Serve all'archivio dell'apprendimento: «da
# dove arriva» è gratis da registrare e potrebbe rivelarsi fra le cose più predittive che abbiamo,
# perché un titolo pescato fra i maggiori ribassi e uno pescato fra i più scambiati sono due
# situazioni diverse anche a parità di tutti gli altri numeri.
_ORIGINI = {
    "day_losers": "maggiori ribassi", "most_actives": "più scambiati",
    "small_cap_gainers": "società piccole in salita",
    "undervalued_large_caps": "grandi sottovalutate",
    "undervalued_growth_stocks": "crescita sottovalutata",
    "penny": "titoli a basso prezzo molto scambiati",
    "riserva": "lista di riserva (classifiche non disponibili)",
    "europa": "Europa e Borsa Italiana", "etf": "ETF",
}


@st.cache_data(ttl=900, show_spinner=False)
def _candidati_e_origine(kind: str, include_eu: bool = True, include_etf: bool = True) -> dict:
    """L'universo di partenza E da quale porta è entrato ogni nome. Una funzione sola per non
    tenere due elenchi che col tempo divergono: chi vuole solo i nomi usa opportunity_candidates.
    Ritorna {"ordine": [ticker…], "origine": {ticker: etichetta}, "troncati": n}."""
    screens = (["day_losers", "most_actives", "small_cap_gainers"] if kind == "short"
               else ["undervalued_large_caps", "undervalued_growth_stocks", "day_losers"])
    names, origine = [], {}

    def aggiungi(tk, da):
        if not tk:
            return
        names.append(tk)
        origine.setdefault(tk, _ORIGINI.get(da, da))    # la PRIMA porta che l'ha pescato

    for s in screens:
        df = get_screen(s, 12)
        if not df.empty:
            for x in df["Ticker"].tolist():
                aggiungi(x, s)
    # Per il breve periodo: includi anche titoli economici molto scambiati (anche < 1$),
    # che le classifiche "biggest losers" delle borse principali non mostrano.
    if kind == "short" and _fmp_key():
        pen = _fmp_get("company-screener?isActivelyTrading=true&priceLowerThan=5"
                       "&volumeMoreThan=300000&limit=25")
        if isinstance(pen, list):
            for q in pen:
                aggiungi(q.get("symbol"), "penny")
    # Se le classifiche non hanno dato nulla (es. FMP esaurito), usa l'universo di riserva,
    # così le occasioni continuano ad aggiornarsi con i dati di Finnhub/SEC/yfinance.
    if not names:
        for x in _FALLBACK_UNIVERSE:
            aggiungi(x, "riserva")
    # Breve = 1 chiamata/titolo (si può osare di più); Lungo = ~4 chiamate/titolo (limita la quota FMP)
    cap = 40 if kind == "short" else 20
    unici = list(dict.fromkeys(names))
    out = unici[:cap]
    # I nomi oltre il tetto non vengono MAI guardati: non sono scarti, sono un punto cieco a monte.
    # Si tengono i loro NOMI, non solo il conteggio: così fra qualche mese si potrà controllare come
    # sono andati e sapere se il tetto ci costa occasioni — che è l'unico modo di rispondere a
    # quella domanda, perché a posteriori di loro non esiste nessun altro dato.
    tagliati = unici[cap:]
    if include_eu:                          # aggiunge i titoli italiani/europei (lista curata)
        eu_cap = 16 if kind == "short" else 10
        for x in _FALLBACK_UNIVERSE_EU[:eu_cap]:
            out.append(x)
            origine.setdefault(x, _ORIGINI["europa"])
    if include_etf:                         # aggiunge ETF liquidi (USA + UCITS europei)
        etf_cap = 18 if kind == "short" else 14
        for x in _ETF_UNIVERSE[:etf_cap]:
            out.append(x)
            origine.setdefault(x, _ORIGINI["etf"])
    return {"ordine": list(dict.fromkeys(out)), "origine": origine, "tagliati": tagliati}


def opportunity_candidates(kind: str, include_eu: bool = True, include_etf: bool = True) -> list:
    """Universo di partenza dalle classifiche di mercato (USA); riserva se non disponibili.
    Con include_eu aggiunge titoli di Borsa Italiana / Europa; con include_etf aggiunge ETF
    liquidi (USA + UCITS) — entrambe le categorie non sono coperte dalle classifiche gratuite."""
    return _candidati_e_origine(kind, include_eu, include_etf)["ordine"]


def origine_candidati(kind: str, include_eu: bool = True, include_etf: bool = True) -> dict:
    """Da quale porta è entrato ogni candidato. Gratis: rilegge la stessa cache dei candidati."""
    return _candidati_e_origine(kind, include_eu, include_etf)["origine"]


def scan_opportunities(tickers: list, kind: str) -> pd.DataFrame:
    # PASSO 1 — scarica i dati di tutti i candidati (universo per gli z-score)
    rmap = {}
    _senza_storia = []
    for t in dict.fromkeys([x for x in tickers if x]):
        try:
            r = opportunity_row(t, with_fundamentals=(kind == "long"))
        except Exception:
            r = None
        if r:
            rmap[r["ticker"]] = r
        else:
            # L'UNICO scarto che avviene prima di calcolare qualsiasi caratteristica: meno di 60
            # sedute di storico, o prezzo non disponibile. Non ha un profilo, ma il suo NOME va a
            # verbale: un punto cieco contato è un punto cieco, un punto cieco silenzioso è una
            # bugia sui dati.
            _senza_storia.append(t)
    # Forza relativa (solo breve): rendimento dell'indice condiviso attaccato a ogni riga (1 chiamata)
    if kind == "short":
        _b = _benchmark_perf()
        for _r in rmap.values():
            _r["bench_5d"], _r["bench_1m"] = _b.get("perf_5d"), _b.get("perf_1m")
    # PASSO 2 — convenienza con z-score robusti sull'intero universo
    convmap = _score_universe(list(rmap.values()), kind)
    if os.environ.get("DATA_LOCAL_FIRST") == "1":   # SOLO nel job autonomo: logga per calibrare i pesi
        try:
            _log_convenience(kind, list(rmap.values()), convmap)
        except Exception:
            pass
    # Regime di volatilità (solo breve): moltiplicatore globale che declassa i rimbalzi nei crash
    regime = volatility_regime()["factor"] if kind == "short" else 1.0
    # ARCHIVIO DELL'APPRENDIMENTO: il contesto si prepara UNA volta per scansione (24 chiamate al
    # giorno in tutto, condivise), e ogni scarto qui sotto viene messo in coda col MOTIVO preso
    # nell'istante esatto — a posteriori metà degli scarti non è ricostruibile, quindi è ora o mai.
    # Solo nel lavoro automatico: nell'app rallenterebbe ogni caricamento di pagina senza aggiungere
    # niente, perché il lavoro automatico guarda lo stesso universo ogni mezz'ora.
    _arc_on = os.environ.get("DATA_LOCAL_FIRST") == "1"
    _arc_ctx = _prepara_contesto_scansione(kind, list(rmap.values())) if _arc_on else None

    def _scarta(r, motivo, dettaglio=None, conv=None, punteggio=None):
        if _arc_on:
            _accoda_scarto(r, kind, motivo, dettaglio, conv, punteggio, _arc_ctx)

    if _arc_on:
        # I due punti ciechi, messi a verbale col nome: quelli senza storia sufficiente e quelli
        # che il tetto dell'universo ha tagliato prima ancora di aprirli. Di loro non c'è un
        # profilo, ma fra qualche mese si potrà andare a vedere come sono andati e sapere se quel
        # tetto ci costa qualcosa — invece di supporlo.
        try:
            accoda_senza_profilo(kind, _senza_storia, "storico_insufficiente",
                                 (_arc_ctx or {}).get("giorno"))
            accoda_senza_profilo(kind, _candidati_e_origine(kind).get("tagliati") or [],
                                 "mai_guardata", (_arc_ctx or {}).get("giorno"))
        except Exception:
            pass

    # PASSO 3 — filtra le vere occasioni e costruisci la tabella
    rows = []
    for tk, r in rmap.items():
        dd = r["dd_high"]
        conv = convmap.get(tk, 50)
        if kind == "short":
            # Filtro liquidità/penny: sotto ~3$ o pochi scambi l'RSI è inaffidabile → escludi
            if r["price"] < _MIN_PRICE:
                _scarta(r, "prezzo_basso", r["price"], conv)
                continue
            liq = r.get("avg_dollar_vol")
            if liq is not None and liq < _MIN_DOLLAR_VOL:
                _scarta(r, "poco_scambiato", liq, conv)
                continue
            sc = _short_score(r, regime=regime)
            if sc is None or not np.isfinite(sc) or sc < 35:   # setup da ipervenduto / zona bassa
                _scarta(r, "punteggio_basso", (None if sc is None else round(float(sc), 1)), conv)
                continue
            if dd is None or dd > -8:           # dev'essere un calo reale, non un titolo ai massimi
                _scarta(r, "sconto_insufficiente", dd, conv, sc)
                continue
            # Filtro Rischio/Rendimento: via i setup asimmetrici perdenti (R:R < 1,5)
            if r.get("rr") is not None and r["rr"] < _RR_MIN:
                _scarta(r, "rischio_rendimento", r["rr"], conv, sc)
                continue
            # In regime di alta volatilità scarta chi crolla MOLTO più del mercato (coltello che cade
            # beta-driven): pretende forza relativa non troppo negativa vs l'indice.
            if regime < 0.85:
                _mom = r.get("perf_5d") if r.get("perf_5d") is not None else r.get("perf_1m")
                _bm = r.get("bench_5d") if r.get("perf_5d") is not None else r.get("bench_1m")
                if _mom is not None and _bm is not None and (_mom - _bm) < -3.0:
                    _scarta(r, "cade_piu_del_mercato", round(_mom - _bm, 2), conv, sc)
                    continue
            gain = r["rebound_pot"] if r["rebound_pot"] is not None else r["exp_ret"]
            rows.append({"Ticker": r["ticker"], "Nome": r["name"], "Convenienza": conv,
                         "Prezzo": r["price"], "RSI": r["rsi"], "% dal max": dd, "Perf 1 mese": r["perf_1m"],
                         "Occasione": int(round(sc)), "Conferma": _short_confirm_label(r),
                         "RVOL": r.get("rvol"), "R:R": r.get("rr"),
                         "Prob. salita": r["prob_gain"], "Guadagno atteso": gain,
                         "Guadagno netto": net_return_pct(gain),
                         "Rischio perdita": r["prob_loss"], "Affidabilità": r["reliab"],
                         "Perché": _short_reasons(r)})
        else:
            # Liquidità/prezzo anche sul lungo (prima assenti): via penny/illiquidi inaffidabili
            if r["price"] < _MIN_PRICE_LONG:
                _scarta(r, "prezzo_basso", r["price"], conv)
                continue
            liq = r.get("avg_dollar_vol")
            if liq is not None and liq < _MIN_DOLLAR_VOL_LONG:
                _scarta(r, "poco_scambiato", liq, conv)
                continue
            # Trappola di valore CONCLAMATA: esclusa del tutto (non solo declassata del 25%)
            if (r.get("trap") or {}).get("strong"):
                _scarta(r, "trappola_di_valore", (r.get("trap") or {}).get("signals"), conv)
                continue
            sc = _long_score(r)
            if sc is None or not np.isfinite(sc) or sc < 50:
                _scarta(r, "punteggio_basso", (None if sc is None else round(float(sc), 1)), conv)
                continue
            if dd is None or dd > -12:          # richiede uno sconto significativo dai massimi
                _scarta(r, "sconto_insufficiente", dd, conv, sc)
                continue
            rows.append({"Ticker": r["ticker"], "Nome": r["name"], "Convenienza": conv,
                         "Settore": r.get("sector"),
                         "Qualità trend": (r.get("trap") or {}).get("label"),
                         "Prezzo": r["price"], "% dal max": dd, "Perf 1 anno": r["perf_1y"],
                         "Occasione": int(round(sc)),
                         "Prob. salita": r["prob_gain"], "Guadagno atteso": r["exp_ret"],
                         "Guadagno netto": net_return_pct(r["exp_ret"]),
                         "Rischio perdita": r["prob_loss"], "Affidabilità": r["reliab"],
                         "Perché": _long_reasons(r)})
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Convenienza", ascending=False)
        # Cap per settore (solo lungo): evita liste tutte-banche o tutte-stesso-settore
        if kind == "long" and "Settore" in df.columns:
            df["_sec"] = df["Settore"].fillna("—")
            _prima = set(df["Ticker"].tolist())
            df = df.groupby("_sec", group_keys=False, sort=False).head(_SECTOR_CAP_LONG)
            df = df.drop(columns="_sec")
            # Questo è l'unico taglio che butta righe GIÀ complete, e finora non lasciava traccia
            # da nessuna parte: nei registri risultavano identiche a una passata. Sono occasioni
            # rifiutate non per un difetto loro ma per far posto ad altre, quindi come contro-esempio
            # valgono meno di zero se non si sa che sono state rifiutate per questo motivo.
            for _tk in _prima - set(df["Ticker"].tolist()):
                _rr = rmap.get(_tk)
                if _rr:
                    _scarta(_rr, "troppi_dello_stesso_settore", _rr.get("sector"),
                            convmap.get(_tk))
        df = df.set_index("Ticker")
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


def save_tracking(data: dict, force: bool = False) -> bool:
    """Salva i titoli seguiti. `force=True` va usato SOLO da chi ha appena deciso una rimozione
    (l'utente che smette di seguire, il job che toglie un'occasione confermata): sono gli unici casi
    in cui il file può legittimamente accorciarsi molto o svuotarsi. In tutti gli altri (scatti,
    note, ancoraggi) resta attiva la protezione che rifiuta un crollo del file — vedi
    _crollo_dizionario: senza `force` togliere l'ULTIMA occasione verrebbe rifiutato.
    Ritorna True se il salvataggio e riuscito: senza questo esito chi salva non puo sapere se il
    dato e stato conservato, ed e' proprio il modo in cui questo progetto ha perso dei registri."""
    return write_data_json(TRACKING_NAME, data, force=force)


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
        # stesso regime di volatilità della pagina Occasioni → punteggi coerenti col monitoraggio
        sc = _short_score(r, regime=volatility_regime()["factor"])
        gain = r["rebound_pot"] if r["rebound_pot"] is not None else r["exp_ret"]
    else:
        sc = _long_score(r)
        gain = r["exp_ret"]
    occ = int(round(sc)) if (sc is not None and np.isfinite(sc)) else None
    # Prezzo LIVE (quote intraday, cache 15 min) così cambia anche infragiornata → lo snapshot
    # viene registrato ogni ora durante le contrattazioni (non resta fermo alla chiusura del giorno).
    price = r["price"]
    try:
        q = quick_quote(ticker)
        if isinstance(q, dict) and q.get("price"):
            price = float(q["price"])
    except Exception:
        pass
    return {k: _jsonable(v) for k, v in {
        "name": r["name"], "price": price, "rsi": r["rsi"], "dd_high": r["dd_high"],
        "occasione": occ, "convenienza": _convenience_single(r, kind),
        "prob_gain": r["prob_gain"], "prob_loss": r["prob_loss"],
        "exp_ret": r["exp_ret"], "gain": gain, "reliab": r["reliab"],
        "target": r["target_price"], "stop": r["stop_price"],
    }.items()}


# Campionamento: si misura più volte al giorno (non più 1/giorno), ma solo se il valore cambia
# ed è passato un minimo di tempo → niente punti ridondanti (es. mercati chiusi) e dati contenuti.
_OBS_GAP_MIN = 60       # opp_watch: al più ogni 60 min
_OBS_MAX_DAYS = 12          # giorni con TUTTI i campionamenti (la finestra "densa")
_OBS_MAX_DIRADATI = 400     # oltre i quali si tiene UN punto al giorno: la storia non si cancella
_OBS_MAX_KEEP = 420         # tetto assoluto di punti per voce (~55 KB per 41 voci: sotto il muro)
# Ingresso selettivo in osservazione: una NUOVA occasione entra solo se abbastanza conveniente
# (riduce il rumore della watchlist); quelle GIÀ osservate continuano comunque ad aggiornarsi.
_OBS_ENTRY_CONV = 60    # convenienza minima per ENTRARE in osservazione
_SNAP_GAP_MIN = 60      # monitoraggio: al più ogni 60 min (1 punto/ora)
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


def _trim_records(records, max_days, max_keep, giorni_diradati=None):
    """Tiene i punti recenti TUTTI, e quelli piu vecchi DIRADATI a uno al giorno invece di buttarli.

    Prima si cancellava tutto oltre `max_days` giorni (dodici), e con dodici giorni di storia una
    domanda come «com era questo titolo tre settimane fa» non aveva piu risposta. Cancellare non era
    nemmeno necessario: il problema e la DIMENSIONE del file (oltre 1 MB la protezione
    anti-cancellazione si spegne), e la dimensione dipende da quanti punti si tengono, non da quanti
    giorni coprono. Campionando ogni ora, un giorno costa ~8 punti: tenendone UNO al giorno oltre la
    finestra densa si conserva quattro mesi di storia nello stesso spazio che prima bastava per dodici
    giorni. Del giorno si tiene l ultimo punto, che e quello con la chiusura piu vicina al vero.
    `max_keep` resta l ultima difesa sulla dimensione."""
    now = _parse_dt(_now_iso())
    if not now:
        return records[-max_keep:]
    limite_totale = now - datetime.timedelta(days=giorni_diradati or max_days)
    limite_denso = now - datetime.timedelta(days=max_days)
    densi, per_giorno = [], {}
    for r in records:
        d = _parse_dt(r.get("date")) or now
        if d >= limite_denso:
            densi.append(r)
        elif d >= limite_totale:
            per_giorno[str(r.get("date"))[:10]] = r      # uno per giorno: vince l ultimo
    tenuti = sorted(list(per_giorno.values()) + densi, key=lambda r: str(r.get("date") or ""))
    return tenuti[-max_keep:]


def _append_snapshot(entry: dict, snapshot: dict) -> None:
    """Aggiunge uno snapshot del monitoraggio (con data+ora); più punti al giorno, con tetto.
    Al PRIMISSIMO scatto congela anche i valori d'ingresso (entry_price/target/stop/conv): sono
    fuori dalla lista potata, quindi restano veri per sempre — vedi _ingresso()."""
    snaps = entry.setdefault("snapshots", [])
    primo = not snaps
    snap = {k: _jsonable(v) for k, v in snapshot.items()}
    snap["date"] = _now_iso()
    if primo and snap.get("price") and not entry.get("entry_price"):
        entry.update({"entry_price": snap.get("price"), "entry_target": snap.get("target"),
                      "entry_stop": snap.get("stop"), "entry_conv": snap.get("convenienza"),
                      "entry_date": snap["date"], "entry_src": "scatto"})
    # MASSIMO RAGGIUNTO, aggiornato a ogni scatto e conservato fuori dalla lista potata: serve alla
    # presa di profitto («quanto sei sceso dal massimo»). Senza questo, per le posizioni seguite da
    # più di qualche settimana il massimo non era più ricostruibile da nessun dato salvato.
    if snap.get("price") is not None:
        try:
            p = float(snap["price"])
            if entry.get("max_price") is None or p > float(entry["max_price"]):
                entry["max_price"], entry["max_date"] = round(p, 4), snap["date"]
        except (TypeError, ValueError):
            pass
    snaps.append(snap)
    snaps.sort(key=lambda s: s.get("date", ""))
    entry["snapshots"] = _trim_records(snaps, _SNAP_MAX_DAYS, _SNAP_MAX_KEEP)
    if snapshot.get("name") and not entry.get("name"):
        entry["name"] = snapshot["name"]


def _livelli_validi(prezzo, target, stop):
    """Scarta i livelli IMPOSSIBILI, restituendo (target, stop) con None al posto dei non plausibili.
    Serve perché su titoli molto volatili il calcolo produce livelli senza senso e nessuno se ne
    accorgeva: misurato sui dati veri, un titolo aveva lo stop a −3,95 (un prezzo NEGATIVO: non
    poteva scattare per definizione, ed è infatti uscito solo per la regola del tempo dopo 28 giorni
    di perdita) e 7 titoli su 83 avevano il bersaglio SOTTO il prezzo d'ingresso, cioè un obiettivo
    già raggiunto il giorno dell'acquisto. Un livello che mente è peggio di un livello assente."""
    try:
        p = float(prezzo) if prezzo else None
    except (TypeError, ValueError):
        p = None
    def _num(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None
    t, s = _num(target), _num(stop)
    if p:
        if t is not None and t <= p:      # un bersaglio già raggiunto non è un bersaglio
            t = None
        if s is not None and (s <= 0 or s >= p):   # stop negativo, o sopra il prezzo pagato
            s = None
    else:
        if s is not None and s <= 0:
            s = None
    return t, s


def _ingresso(entry: dict) -> dict:
    """Valori del MOMENTO D'INGRESSO di un'occasione seguita: prezzo, bersaglio, stop, convenienza.
    Legge gli ancoraggi congelati (entry_price/entry_target/…); se mancano ripiega sul primo scatto
    ancora in memoria, ma dichiara `sicuro=False` quando quello scatto NON è del giorno d'ingresso.
    Serve perché la potatura fa scorrere in avanti il «primo scatto»: misurare il rendimento da lì
    dà numeri falsi (misurato sul branch: 13 titoli su 83, con perdite inesistenti fino a −9%).
    Chi DECIDE (avvisi, rimozioni, notifiche) quando `sicuro` è falso si astiene invece di sbagliare."""
    snaps = [s for s in (entry.get("snapshots") or []) if s.get("price")]
    s0 = snaps[0] if snaps else {}
    if entry.get("entry_price"):
        t, s = _livelli_validi(entry.get("entry_price"), entry.get("entry_target"), entry.get("entry_stop"))
        return {"price": entry.get("entry_price"), "target": t, "stop": s,
                "conv": entry.get("entry_conv"),
                "date": entry.get("entry_date") or entry.get("added"),
                "sicuro": True, "src": entry.get("entry_src") or "scatto"}
    added = str(entry.get("added") or "")[:10]
    coerente = bool(s0) and bool(added) and str(s0.get("date"))[:10] <= added
    t, s = _livelli_validi(s0.get("price"), s0.get("target"), s0.get("stop"))
    return {"price": s0.get("price"), "target": t, "stop": s,
            "conv": s0.get("convenienza"), "date": s0.get("date"),
            "sicuro": coerente, "src": "scatto" if coerente else "potato"}


def _chiusura_del_giorno(ticker: str, giorno: str):
    """Chiusura del primo giorno di BORSA a partire da `giorno`. Serve il «primo da» e non «quel
    giorno esatto» perché la data d'ingresso può cadere di sabato o in un festivo (sul branch è il
    caso di KGC e AXTI). None se lo storico non è disponibile (titolo delistato)."""
    try:
        closes = get_history(ticker, period="2y")["Close"].dropna()
        try:
            closes.index = closes.index.tz_localize(None)
        except (TypeError, AttributeError):
            pass
        s = closes[closes.index >= pd.Timestamp(str(giorno)[:10])]
        return float(s.iloc[0]) if not s.empty else None
    except Exception:
        return None


_ANCORA_VERIFICA_GIORNI = 1     # ri-verifica dell'ancoraggio: al più una volta al giorno per titolo
_ANCORA_MAX_RETE = 25           # chiamate di rete al massimo per giro del job (83 titoli → ~1 ora)
_ANCORA_SOGLIA_SPLIT = 0.25     # oltre questo scostamento è un frazionamento, non un movimento


def ancora_ingressi(max_rete: int = _ANCORA_MAX_RETE) -> dict:
    """Congela i valori d'INGRESSO delle occasioni seguite e li tiene allineati alla scala dei
    prezzi. Va chiamata dal job PRIMA delle decisioni di monitoraggio. Fa tre cose:

      1. ANCORAGGIO MANCANTE (occasioni già seguite prima di questa modifica). Se il primo scatto è
         coerente col giorno d'ingresso lo copia da lì; altrimenti riscarica la chiusura del primo
         giorno di Borsa da `added` (entry_src="storico"). Il bersaglio si prende dallo scatto più
         vecchio superstite; lo stop si ricostruisce conservandone la DISTANZA dal prezzo, perché lo
         stop è «prezzo − 2×ATR»: la distanza regge, il livello assoluto no.
      2. RI-VERIFICA, una volta al giorno per titolo. Se l'ancoraggio si scosta di oltre il 25%
         dalla chiusura di quel giorno, allora è cambiata la SCALA dei prezzi (frazionamento o
         raggruppamento): non è una perdita. Si ri-ancora sulla scala nuova, altrimenti un prezzo
         congelato prima di un frazionamento farebbe scattare stop e crollo per sempre.
      3. Se lo storico non c'è (delistato), entry_src="ignoto" e l'ancoraggio resta vuoto: le regole
         che misurano il rendimento dall'ingresso si astengono (mai "non lo so" letto come perdita).

    Il numero di chiamate di rete per giro è limitato, così il job resta breve.
    Ritorna {ancorati, riancorati, ignoti, saltati}."""
    tracked = load_tracking()
    out = {"ancorati": 0, "riancorati": 0, "ignoti": 0, "saltati": 0}
    if not tracked:
        return out
    oggi = _today_iso()
    rete, changed = 0, False
    for tk, e in tracked.items():
        snaps = [s for s in (e.get("snapshots") or []) if s.get("price")]
        added = str(e.get("added") or (snaps[0].get("date") if snaps else ""))[:10]
        if not added:
            out["saltati"] += 1
            continue
        ha_ancora = bool(e.get("entry_price"))
        coerente = bool(snaps) and str(snaps[0].get("date"))[:10] <= added
        if not ha_ancora and coerente:
            s0 = snaps[0]
            e.update({"entry_price": s0.get("price"), "entry_target": s0.get("target"),
                      "entry_stop": s0.get("stop"), "entry_conv": s0.get("convenienza"),
                      "entry_date": s0.get("date"), "entry_src": "scatto", "entry_check": oggi})
            out["ancorati"] += 1
            changed = True
            continue
        scaduta = (not e.get("entry_check")
                   or _days_between(e.get("entry_check"), oggi) >= _ANCORA_VERIFICA_GIORNI)
        if (ha_ancora and not scaduta) or rete >= max_rete:
            out["saltati"] += 1
            continue
        rete += 1
        chiusura = _chiusura_del_giorno(tk, added)
        e["entry_check"] = oggi
        changed = True
        if chiusura is None:
            if not ha_ancora:
                e["entry_src"] = "ignoto"
                out["ignoti"] += 1
            else:
                out["saltati"] += 1
            continue
        if not ha_ancora:
            dist = None
            if snaps and snaps[0].get("price") and snaps[0].get("stop") is not None:
                dist = float(snaps[0]["price"]) - float(snaps[0]["stop"])
            e.update({"entry_price": round(chiusura, 4),
                      "entry_target": (snaps[0].get("target") if snaps else None),
                      "entry_stop": (round(chiusura - dist, 4) if dist is not None else None),
                      "entry_conv": (snaps[0].get("convenienza") if snaps else None),
                      "entry_date": added, "entry_src": "storico"})
            out["ancorati"] += 1
            continue
        base = float(e["entry_price"])
        if base > 0 and abs(chiusura / base - 1) > _ANCORA_SOGLIA_SPLIT:
            fatt = chiusura / base
            for campo in ("entry_price", "entry_target", "entry_stop"):
                if e.get(campo):
                    e[campo] = round(float(e[campo]) * fatt, 4)
            e["entry_src"] = "riancorato"
            out["riancorati"] += 1
    if changed:
        save_tracking(tracked)
    return out


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
    tk = ticker.upper()
    if tk in data:
        _append_exit_record(tk, data[tk], "rimozione manuale")   # lapide anche per le uscite manuali
    data.pop(tk, None)
    save_tracking(data, force=True)     # scelta esplicita dell'utente: può anche svuotare l'elenco
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


def tracking_trend(snapshots: list, conv0=None, prezzo0=None) -> dict:
    """Verdetto di tendenza dai punti di convenienza accumulati: rafforzamento/stabile/indebolimento.
    Se `conv0`/`prezzo0` sono forniti (i valori d'INGRESSO congelati) il confronto parte da lì
    invece che dal primo scatto ancora in memoria, che dopo la potatura non è più l'ingresso.
    Ritorna None se non c'è abbastanza materiale per un confronto."""
    snaps = [s for s in snapshots if s.get("convenienza") is not None]
    if not snaps or (conv0 is None and len(snaps) < 2):
        return None
    first, last = snaps[0], snaps[-1]
    dconv = last["convenienza"] - (conv0 if conv0 is not None else first["convenienza"])
    base_p = prezzo0 if prezzo0 is not None else first.get("price")
    dprice = None
    if base_p and last.get("price"):
        dprice = (last["price"] / base_p - 1) * 100
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


# Config della sezione Occasioni (ticker extra + watchlist + preferenze EU/ETF) salvata dall'app
# sul data-layer, così il JOB autonomo osserva lo STESSO universo che vedi nella sezione
# (non solo l'universo standard): tutte le occasioni della sezione finiscono sotto osservazione.
OPP_CONFIG_NAME = "opp_config.json"
_OPP_CONFIG_DEFAULT = {"extra": [], "include_eu": True, "include_etf": True}


def load_opp_config() -> dict:
    data = read_data_json(OPP_CONFIG_NAME, dict(_OPP_CONFIG_DEFAULT))
    if not isinstance(data, dict):
        return dict(_OPP_CONFIG_DEFAULT)
    return {"extra": list(data.get("extra", [])),
            "include_eu": bool(data.get("include_eu", True)),
            "include_etf": bool(data.get("include_etf", True))}


def save_opp_config(extra, include_eu: bool, include_etf: bool) -> bool:
    """Salva la config delle Occasioni SOLO se è cambiata (evita commit GitHub inutili).
    Ritorna True se ha scritto."""
    cfg = {"extra": list(dict.fromkeys([str(t).upper() for t in (extra or []) if t])),
           "include_eu": bool(include_eu), "include_etf": bool(include_etf)}
    if cfg == load_opp_config():
        return False
    write_data_json(OPP_CONFIG_NAME, cfg)
    return True


_STICKY_CAP = 80   # tetto ai ticker "sticky" re-iniettati nello scan (contiene la quota API)


def sticky_watch_tickers(kind: str) -> list:
    """Ticker GIÀ in osservazione (opp_watch) con la FINESTRA ancora aperta: vanno ri-scansionati
    ad ogni giro anche se sono usciti dagli screener giornalieri di mercato. Così la lista
    «in osservazione» è STABILE — chi entra resta osservato per tutta la sua finestra (breve 3 /
    lungo 7 giorni) e accumula punti su più giorni — invece di sparire dopo un solo giorno."""
    watch = load_opp_watch()
    window = _OBS_WINDOW.get(kind, 3)
    out = []
    for e in watch.values():
        if e.get("kind") != kind:
            continue
        obs = [o for o in e.get("obs", []) if o.get("price")]
        if not obs:
            continue
        if _trading_days_between(obs[0]["date"], _today_iso(), e.get("ticker")) < window + 1:   # finestra non ancora conclusa
            out.append(e.get("ticker"))
    return list(dict.fromkeys([t for t in out if t]))[:_STICKY_CAP]


def opportunity_universe(kind: str) -> list:
    """Universo COMPLETO della sezione Occasioni per il job autonomo: classifiche/universo standard
    (con le preferenze EU/ETF salvate) + i ticker extra/watchlist dell'utente + i ticker già in
    osservazione con finestra aperta (sticky watch → lista stabile, niente rotazione giornaliera)."""
    cfg = load_opp_config()
    base = opportunity_candidates(kind, include_eu=cfg["include_eu"], include_etf=cfg["include_etf"])
    return list(dict.fromkeys(list(base) + list(cfg["extra"]) + sticky_watch_tickers(kind)))


def record_observations(df, kind: str) -> None:
    """Registra la convenienza di ogni occasione scansionata più volte al giorno (al più ogni ~60 min,
    e solo se convenienza o prezzo sono cambiati). Separata per orizzonte (short/long). Tetto per titolo.

    LE OSSERVAZIONI SCADONO (ago 2026). Un'occasione che smette di comparire fra quelle scansionate
    congelava la propria storia: il primo e l'ultimo punto restavano quelli di settimane prima, e la
    regola «il prezzo è risalito del 2% nella finestra di 3 giorni» diventava «il prezzo di oggi è più
    alto di quello di un mese fa» — vera per sempre e senza alcun rimbalzo in corso. Misurato sui dati
    veri: 11 promozioni su 60 di breve termine avevano una finestra più lunga del previsto, e un titolo
    è stato promosso l'11 agosto con osservazioni iniziate il 29 giugno, a un prezzo identico alla
    seconda cifra decimale a quello della promozione precedente. Ora, se l'osservazione si è interrotta
    per più della finestra, la storia riparte da zero e va ri-superato il cancello d'ingresso."""
    if df is None or df.empty:
        return
    watch = load_opp_watch()
    now = _now_iso()
    finestra = _OBS_WINDOW.get(kind, 3)
    mkt = _jsonable(market_perf_1m())   # contesto di mercato (~1 mese indice): per stimare poi l'alpha
    for tk, r in df.iterrows():
        key = f"{kind}:{tk}"
        conv = _jsonable(r.get("Convenienza"))
        vecchia = watch.get(key)
        if vecchia and (vecchia.get("obs") or []):
            ultima = str((vecchia["obs"][-1] or {}).get("date") or "")
            if ultima and _trading_days_between(ultima, _today_iso(), tk) > finestra + 2:
                vecchia["obs"] = []                 # storia interrotta: si riparte da capo
                vecchia["ripartita"] = _today_iso()
        # Ingresso selettivo: una NUOVA occasione (o una ripartita) entra in osservazione solo se
        # abbastanza conveniente (meno rumore); quelle già in corso continuano ad aggiornarsi.
        if not (watch.get(key) or {}).get("obs") and (conv is None or conv < _OBS_ENTRY_CONV):
            if os.environ.get("DATA_LOCAL_FIRST") == "1":
                scarto_cancello_osservazione(kind, tk, conv)   # per l'archivio dell'apprendimento
            continue
        e = watch.setdefault(key, {"ticker": tk, "kind": kind, "name": tk, "obs": []})
        e["ticker"], e["kind"] = tk, kind
        e["name"] = r.get("Nome", tk)
        price = _jsonable(r.get("Prezzo"))
        obs = e.get("obs", [])
        if _should_sample(obs, conv, price, _OBS_GAP_MIN, "conv"):
            punto = {"date": now, "conv": conv, "price": price, "mkt": mkt,
                     "occ": _jsonable(r.get("Occasione")), "prob_gain": _jsonable(r.get("Prob. salita")),
                     # servono ai filtri di qualità delle sezioni Osservazione/Anticipo
                     "prob_loss": _jsonable(r.get("Rischio perdita")), "reliab": r.get("Affidabilità")}
            obs.append(punto)
            obs.sort(key=lambda o: o.get("date", ""))
            # FOTOGRAFIA DEL PRIMO ISTANTE, in un campo a parte che la potatura non tocca.
            # Perché non basta obs[0]: la lista viene potata a _OBS_MAX_DAYS giorni, quindi per
            # un'occasione che resta in osservazione più a lungo obs[0] SCIVOLA IN AVANTI e il
            # prezzo di «inizio osservazione» diventa quello di qualche giorno dopo, senza che
            # niente lo dica. Con `primo` il momento dell'ingresso resta a verbale per sempre.
            # Se la storia è stata interrotta e riparte (campo `ripartita`), anche questa si azzera:
            # il nuovo ingresso è un ingresso nuovo.
            if not e.get("primo") or (e.get("ripartita") and
                                      str(e["primo"].get("date", ""))[:10] < str(e["ripartita"])[:10]):
                # ATTENZIONE: si prende obs[0], il punto più VECCHIO ancora noto, non `punto` (quello
                # di adesso). Per un'occasione appena entrata sono lo stesso punto; per una già in
                # osservazione da giorni — cioè tutte quelle in corso il giorno in cui questa
                # fotografia è stata introdotta — timbrare l'istante attuale come «ingresso in
                # osservazione» sarebbe un dato falso, con la data e i valori sbagliati di parecchi
                # giorni. Così invece si conserva il più antico che esista ancora.
                e["primo"] = dict(obs[0])
                # …e l EVENTO nel diario permanente, con i valori di quell istante. La voce di
                # opp_watch e un registro di lavoro (si dirada, e stata anche troncata una volta);
                # il diario e append-only e non si cancella mai.
                registra_evento(kind, tk, "ingresso_osservazione",
                                valori={"data": e["primo"].get("date"),
                                        "prezzo": e["primo"].get("price"),
                                        "conv": e["primo"].get("conv"),
                                        "prob_gain": e["primo"].get("prob_gain"),
                                        "prob_loss": e["primo"].get("prob_loss"),
                                        "reliab": e["primo"].get("reliab"),
                                        "mkt": e["primo"].get("mkt"), "fonte": "osservazione"},
                                episodio=f"{kind}:{str(tk).upper()}:{str(e['primo'].get('date'))[:10]}")
            e["obs"] = _trim_records(obs, _OBS_MAX_DAYS, _OBS_MAX_KEEP, _OBS_MAX_DIRADATI)
    save_opp_watch(watch)


def record_sticky_observations(kind: str, scanned_df) -> None:
    """Per i ticker GIÀ in osservazione con la FINESTRA ancora aperta che OGGI non sono tra le
    occasioni (non superano più i filtri): registra comunque il PREZZO del giorno (convenienza None)
    così i GIORNI di osservazione avanzano e la finestra può concludersi → la promozione resta
    POSSIBILE (ma sempre condizionata alla ripresa del prezzo, regola invariata). Riusa
    opportunity_row già in cache dallo scan → nessuna chiamata API extra."""
    watch = load_opp_watch()
    window = _OBS_WINDOW.get(kind, 3)
    scanned = set(scanned_df.index) if (scanned_df is not None and not scanned_df.empty) else set()
    now = _now_iso()
    changed = False
    for e in watch.values():
        if e.get("kind") != kind:
            continue
        tk = e.get("ticker")
        if not tk or tk in scanned:                    # già registrato dallo scan di oggi
            continue
        obs_p = [o for o in e.get("obs", []) if o.get("price")]
        if not obs_p or _trading_days_between(obs_p[0]["date"], _today_iso(), tk) >= window + 1:
            continue                                   # niente storia valida o finestra già conclusa
        try:
            r = opportunity_row(tk, with_fundamentals=(kind == "long"))   # cache dallo scan
        except Exception:
            r = None
        price = _jsonable(r.get("price")) if r else None
        if not price:
            continue
        full = e.get("obs", [])
        if _should_sample(full, None, price, _OBS_GAP_MIN, "conv"):
            full.append({"date": now, "conv": None, "price": price, "stale": True})
            full.sort(key=lambda o: o.get("date", ""))
            e["obs"] = _trim_records(full, _OBS_MAX_DAYS, _OBS_MAX_KEEP)
            changed = True
    if changed:
        save_opp_watch(watch)


# Parametri della regola "tendenza positiva tollerante":
_PROMO_MIN_GAIN = 5.0    # punti di convenienza guadagnati nel periodo
_PROMO_MAX_DIP = 4.0     # massimo calo giornaliero ammesso (oltre = inversione, niente promozione)
_PROMO_MIN_RET = 2.0     # rialzo MINIMO del prezzo (%) sulla finestra per promuovere (no rumore: +0,1% non basta)
# Quality-gate "tesi ancora viva": la promozione NON deve basarsi solo sul +2% di prezzo, ma anche
# sulla CONVENIENZA (tutto il motore di scoring). Si promuove solo se la tesi regge ancora.
_PROMO_MIN_CONV = 55     # convenienza ATTUALE minima per promuovere (sotto = tesi troppo debole)
_PROMO_MAX_CONV_DECAY = 10  # massimo calo di convenienza tollerato sulla finestra (oltre = tesi decaduta)


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


_PROMO_USE_CONV_TREND = False   # se True la promozione richiede ANCHE un trend di convenienza positivo
_OBS_MIN_DAYS_FOR_TREND = 2     # minimo di giorni distinti per emettere un verdetto di trend


def _daily_conv_values(obs) -> list:
    """Convenienza aggregata PER GIORNO di calendario (MEDIANA dei punti intraday del giorno).
    La mediana assorbe i cali temporanei di mezza giornata: un dip intraday non sposta il valore
    del giorno, così il trend si giudica sull'andamento GIORNALIERO e non sul rumore infragiornaliero.
    Esempio: mezza giornata giù ma il resto su → il giorno resta alto → la finestra è tenuta."""
    buckets = {}
    for o in (obs or []):
        c = o.get("conv")
        if c is None:
            continue
        day = str(o.get("date", ""))[:10]
        if day:
            buckets.setdefault(day, []).append(c)
    return [float(np.median(buckets[d])) for d in sorted(buckets)]


# Finestre del ciclo automatico (in giorni), per tipo di occasione:
_OBS_WINDOW = {"short": 3, "long": 7}      # osservazione prima della promozione
_REMOVE_WINDOW = {"short": 5, "long": 10}  # dopo quanti giorni, se in perdita, si toglie dal monitoraggio
_NOTIFY_WINDOW = {"short": 3, "long": 7}   # giorni di monitoraggio positivo per la prima notifica
_NOTIFY_MIN_RET = 3.0   # guadagno minimo (%) per la notifica di conferma (niente notifiche banali a +0,1%)
# Rimozione autonoma PRUDENTE: si toglie un'occasione solo se il deterioramento (`warn`) PERSISTE per
# questi giorni di Borsa (CONFERMA, non al primo calo). Se recupera, il conto si azzera → niente churn.
_EXIT_CONFIRM_DAYS = {"short": 4, "long": 10}
# ...TRANNE quando il motivo è lo STOP: un livello di prezzo è già la conferma di sé stesso, e
# aspettare fa uscire molto più in basso del livello che doveva proteggere (misurato: fino al 10,6%
# sotto il proprio stop). La conferma serve dove il tempo è l'informazione, non dove lo è il prezzo.
_SUBITO_ALLO_STOP = True
_EXIT_COOLDOWN_DAYS = 5           # giorni di Borsa in cui un titolo tolto NON si ri-promuove (anti-churn)
EXIT_COOLDOWN_NAME = "exit_cooldown.json"

# --- Storico delle occasioni RIMOSSE dal Monitoraggio (lapidi anti-survivorship): senza di questo
# ogni simulazione retrospettiva vede solo le sopravvissute e i risultati sembrano migliori del vero. ---
EXIT_HISTORY_NAME = "exit_history.json"
_EXIT_HISTORY_MAX = _EXIT_HISTORY_MAX_LIVE   # tetto del file VIVO; l'eccedenza va in archivio


def load_exit_history() -> list:
    data = read_data_json(EXIT_HISTORY_NAME, [])
    return data if isinstance(data, list) else []


def _append_exit_record(tk: str, entry: dict, reason: str) -> None:
    """Registra una 'lapide' quando un'occasione esce dal Monitoraggio (rimozione automatica o
    manuale): ticker, periodo, prezzi primo/ultimo e livelli iniziali. Tollerante ai dati mancanti
    (la rimozione va registrata comunque). Usata dal simulatore per includere anche le perdenti."""
    try:
        snaps = [s for s in entry.get("snapshots", []) if s.get("price")]
        last = snaps[-1] if snaps else {}
        # I prezzi d'ingresso vengono dagli ANCORAGGI, non dal primo scatto superstite: questa riga
        # è definitiva (il registro non si corregge più) e prima congelava per sempre un prezzo
        # d'ingresso sbagliato, falsando il conto «quanto avrei guadagnato». `first_src` dichiara la
        # provenienza, così una statistica può escludere gli ingressi ricostruiti.
        ing = _ingresso(entry)
        hist = load_exit_history()
        hist.append({
            "ticker": str(tk).upper(), "kind": entry.get("kind", "short"),
            "added": entry.get("added"), "removed": _today_iso(), "reason": reason,
            "auto": bool(entry.get("auto")),
            "first_price": ing.get("price"), "last_price": last.get("price"),
            "first_target": ing.get("target"), "first_stop": ing.get("stop"),
            "first_src": ing.get("src"), "first_sicuro": bool(ing.get("sicuro")),
            "my_target_price": entry.get("my_target_price"),
            # GLI SCATTI, non solo i prezzi. Quando un'occasione esce, la sua voce di monitoraggio
            # viene cancellata e con essa TUTTI gli scatti — che sono l'unica fonte dei numeri di
            # qualità del momento «dopo i giorni di verifica». Un titolo che esce prima dei 5 o 10
            # giorni di Borsa della verifica perdeva quel momento per sempre: sono già 8 occasioni
            # (AEO, MPLT, STRL, WSO, BIOA, SSTK, AZN, USNA), irrecuperabili perché la lapide salvava
            # soltanto i prezzi. Qui la lista viene messa a verbale nella lapide, che è un registro
            # storico e non si cancella: da adesso quel momento si può ricostruire anche dopo l'uscita.
            "snapshots": snaps,
        })
        salva_registro(EXIT_HISTORY_NAME, hist, _EXIT_HISTORY_MAX)
        registra_evento(entry.get("kind", "short"), tk, "uscita",
                        valori={"data": _now_iso(), "prezzo": last.get("price")},
                        note=reason)
    except Exception:
        pass   # la lapide non deve mai bloccare la rimozione


def _days_between(d1, d2) -> int:
    """Giorni di calendario tra due date in formato ISO (YYYY-MM-DD...)."""
    try:
        a = datetime.date.fromisoformat(str(d1)[:10])
        b = datetime.date.fromisoformat(str(d2)[:10])
        return (b - a).days
    except Exception:
        return 0


# --- Calendario di Borsa: le finestre a giorni contano i giorni di MERCATO (weekend E festivi esclusi),
# col calendario dell'exchange del titolo (dal suffisso). Se la libreria manca/fallisce → giorni feriali. ---
_MIC_BY_SUFFIX = {".MI": "XMIL", ".DE": "XETR", ".PA": "XPAR", ".AS": "XAMS", ".SW": "XSWX",
                  ".L": "XLON", ".MC": "XMAD", ".BR": "XBRU", ".LS": "XLIS", ".VI": "XWBO",
                  ".HE": "XHEL", ".ST": "XSTO", ".OL": "XOSL", ".CO": "XCSE", ".TO": "XTSE",
                  ".AX": "XASX", ".T": "XTKS", ".HK": "XHKG"}
_CAL_CACHE = {}


def _exchange_for(ticker) -> str:
    """Codice MIC del mercato di un ticker dal suffisso (default XNYS = NYSE per i titoli USA)."""
    t = str(ticker or "").upper()
    for suf, mic in _MIC_BY_SUFFIX.items():
        if t.endswith(suf):
            return mic
    return "XNYS"


def _market_calendar(code):
    """Calendario di Borsa (cached) con margini attorno all'anno corrente (indipendente dall'orologio
    di sistema). Solleva se la libreria non è disponibile → gestito dal chiamante col ripiego."""
    if code not in _CAL_CACHE:
        import exchange_calendars as xcals
        import pandas as _pd
        y = int(_today_iso()[:4])
        _CAL_CACHE[code] = xcals.get_calendar(
            code, start=_pd.Timestamp(f"{y - 6}-01-01"), end=_pd.Timestamp(f"{y + 2}-12-31"))
    return _CAL_CACHE[code]


def _trading_days_between(d1, d2, ticker=None) -> int:
    """Giorni di BORSA tra due date ISO, esclusivo su d1 e inclusivo su d2. Usa il vero calendario
    dell'exchange del `ticker` (weekend E festivi esclusi); ripiega ai soli giorni feriali (lun-ven,
    festivi NON esclusi) se la libreria del calendario non è disponibile o fallisce."""
    try:
        a = datetime.date.fromisoformat(str(d1)[:10])
        b = datetime.date.fromisoformat(str(d2)[:10])
    except Exception:
        return 0
    if b == a:
        return 0
    if b < a:
        a, b = b, a
    try:  # 1) vero calendario di Borsa (weekend + festivi del mercato del titolo)
        import pandas as _pd
        cal = _market_calendar(_exchange_for(ticker))
        return int(len(cal.sessions_in_range(_pd.Timestamp(a) + _pd.Timedelta(days=1), _pd.Timestamp(b))))
    except Exception:
        pass
    days, cur = 0, a   # 2) ripiego: giorni feriali (weekend esclusi, festivi no)
    while cur < b:
        cur += datetime.timedelta(days=1)
        if cur.weekday() < 5:
            days += 1
    return days


def _is_value_trap_now(ticker: str) -> bool:
    """True se i fondamentali del titolo risultano ORA in peggioramento (trappola conclamata):
    serve a NON promuovere un'occasione di lungo la cui tesi è decaduta. Usa opportunity_row (in
    cache dallo scan dello stesso giro → di norma nessuna chiamata extra). ETF → mai trappola."""
    try:
        r = opportunity_row(ticker, with_fundamentals=True)
    except Exception:
        return False
    trap = (r or {}).get("trap") or {}
    return bool(trap.get("strong")) or (trap.get("factor", 1.0) <= 0.75)


def auto_promote_opportunities() -> list:
    """FASE 1 — osservazione. Ogni occasione (saldo individuato in «Occasioni») è osservata per una
    finestra (breve 3 giorni, lungo 7 giorni); se alla fine il PREZZO è salito dal primo giorno
    osservato (la ripresa è iniziata) viene inserita nel Monitoraggio. Ritorna i ticker promossi."""
    watch = load_opp_watch()
    tracked = load_tracking()
    cooldown = _load_exit_cooldown()
    promoted = []
    new_records = []
    for key, e in watch.items():
        tk = e.get("ticker", key.split(":")[-1])
        if tk in tracked:
            continue
        if _in_exit_cooldown(tk, cooldown):
            continue   # tolta di recente per deterioramento confermato: niente ri-promozione (anti-churn)
        kind = e.get("kind", "short")
        obs = [o for o in e.get("obs", []) if o.get("price")]
        if len(obs) < 2:
            continue
        days = _trading_days_between(obs[0]["date"], obs[-1]["date"], tk)
        window = _OBS_WINDOW.get(kind, 3)
        ret = (obs[-1]["price"] / obs[0]["price"] - 1) * 100 if obs[0]["price"] else 0.0
        # La FINESTRA deve essere conclusa: senza questo non c'è nulla da valutare.
        if days < window:
            continue
        # --- Quality-gate "tesi ancora viva": qui entra la CONVENIENZA, non solo il +2% di prezzo ---
        # 1) livello: ultima convenienza NOTA ≥ soglia (se ignota, non promuovere alla cieca)
        last_conv = next((o.get("conv") for o in reversed(e.get("obs", []))
                          if o.get("conv") is not None), None)
        if last_conv is None or last_conv < _PROMO_MIN_CONV:
            continue
        # 2) non-decadimento: convenienza non crollata sulla finestra (mediana giornaliera)
        vals = _daily_conv_values(e.get("obs", []))
        if len(vals) >= 2 and (vals[-1] - vals[0]) < -_PROMO_MAX_CONV_DECAY:
            continue
        # 3) (lungo) fondamentali non in peggioramento: niente trappole conclamate
        if kind == "long" and _is_value_trap_now(tk):
            continue
        # 4) (opzionale) trend di convenienza positivo, solo se attivato
        if _PROMO_USE_CONV_TREND and not _qualifies_promotion(
                vals, window, _PROMO_MIN_GAIN, _PROMO_MAX_DIP):
            continue
        # RIMBALZO REALE DEL PREZZO (≥ _PROMO_MIN_RET %, non rumore): è l'ULTIMO cancello, e da qui in
        # poi le due strade si separano. Chi lo supera viene promosso. Chi lo manca — avendo superato
        # tutto il resto — NON viene promosso, ma viene REGISTRATO negli scenari come «candidata che il
        # +2% ha scartato»: è l'unico modo di rispondere alla domanda «e se il +2% non ci fosse?», che
        # la matrice degli scenari da sola non può affrontare, perché contiene solo i titoli promossi
        # (cioè solo quelli che il +2% ha già ammesso). Serve perché i numeri dicono che la soglia
        # arriva tardi: al momento della promozione metà del movimento è già avvenuto.
        if ret < _PROMO_MIN_RET:
            _log_scenario_senza_soglia(tk, kind, obs, ret, last_conv)
            continue
        track_opportunity(tk, kind,
                          note=f"🤖 Promossa il {_today_iso()}: dopo {days} giorni di Borsa di osservazione "
                               f"il prezzo è risalito di {ret:+.1f}% e la convenienza ({last_conv:.0f}) regge.")
        tr = load_tracking()
        if tk in tr:
            tr[tk]["auto"] = True
            tr[tk]["notified"] = False
            save_tracking(tr)
        # Ancoraggi per gli SCENARI acquisto/vendita. Bersaglio e stop vengono dai valori
        # d'INGRESSO appena congelati da track_opportunity (prima si leggeva "lo scatto numero 0",
        # corretto solo perché l'entry era appena nata: ora è esplicito e non dipende dall'ordine).
        _ing = _ingresso(tr.get(tk, {}))
        # Lo scatto iniziale del monitoraggio nasce da una chiamata di rete: se non riesce, resta un
        # dizionario vuoto e la promozione perde i suoi quattro numeri di qualità — mentre l'ultimo
        # punto dell'osservazione, che li ha, è già qui a portata di mano. Si ripiega sull'INTERO
        # punto e non campo per campo: mescolare due istanti diversi è lo stesso errore che ha
        # prodotto le fotografie sfasate del registro dei pre-segnali.
        snap0 = (tr.get(tk, {}).get("snapshots") or [{}])[0]
        if snap0.get("convenienza") is None and snap0.get("prob_gain") is None:
            _p = next((o for o in reversed(obs) if o.get("conv") is not None), None)
            if _p:
                snap0 = {"reliab": _p.get("reliab"), "prob_gain": _p.get("prob_gain"),
                         "prob_loss": _p.get("prob_loss"), "convenienza": _p.get("conv")}
        _log_promotion_scenario(tk, kind, promo_price=obs[-1].get("price"),
                                obs_price=obs[0].get("price"),
                                obs_date=str(obs[0].get("date", ""))[:10],
                                target=_ing.get("target"), stop=_ing.get("stop"),
                                # qualità del segnale al momento dell'acquisto: serve ai filtri
                                reliab=snap0.get("reliab"), prob_gain=snap0.get("prob_gain"),
                                prob_loss=snap0.get("prob_loss"), conv=snap0.get("convenienza"))
        promoted.append(tk)
        registra_evento(kind, tk, "promozione",
                        valori={"data": _now_iso(), "prezzo": obs[-1].get("price"),
                                "conv": snap0.get("convenienza"),
                                "prob_gain": snap0.get("prob_gain"),
                                "prob_loss": snap0.get("prob_loss"),
                                "reliab": snap0.get("reliab"), "fonte": "promozione"},
                        note=f"entrata in monitoraggio dopo {days} giorni di Borsa di osservazione")
        new_records.append({"ticker": tk, "kind": kind, "date": _today_iso(),
                            "price": obs[-1].get("price"), "conv": obs[-1].get("conv"),
                            # prezzo/data di INIZIO osservazione: servono a misurare quanto rimbalzo
                            # "si perde" aspettando la conferma (confronto ingresso anticipato vs promozione)
                            "obs_price": obs[0].get("price"), "obs_date": str(obs[0].get("date", ""))[:10],
                            "ret_now": None, "ret_7d": None, "ret_30d": None, "last_update": _today_iso()})
    if new_records:
        recs = load_track_record()
        recs.extend(new_records)
        save_track_record(recs)
    return promoted


# ---------------------------------------------------------------------------
# PRESA DI PROFITTO — l'altra metà del monitoraggio, che prima non esisteva.
#
# Perché serve. Il sistema aveva QUATTRO modi di dire «questa sta perdendo» (crollo, dati fermi,
# sotto lo stop, in perdita da troppi giorni) e NESSUNO di dire «questa ha già dato quello che
# doveva dare». Non è una sfumatura: essendo tutte le regole di rimozione dei motivi di perdita, il
# registro delle uscite non poteva contenere un vincitore — e infatti le prime 18 uscite sono 18
# perdite. Intanto, sui titoli seguiti, il guadagno massimo toccato era in media +12,5% contro
# +8,9% attuale: 3,6 punti restituiti per posizione, e in tre casi un guadagno oltre il 5% è
# diventato una perdita. Il bersaglio d'ingresso è stato toccato da 31 titoli su 83 senza che
# succedesse nulla.
#
# Come funziona. Nessuna chiamata di rete (come monitoring_warn): si guardano il prezzo d'ingresso
# congelato, l'ultimo scatto e il MASSIMO raggiunto (che ora si memorizza sull'occasione, perché gli
# scatti si conservano poche settimane e per le posizioni vecchie il massimo non era più
# ricostruibile). Questa funzione NON vende e non rimuove niente: segnala.
# ---------------------------------------------------------------------------
_TRAIL_DAL_MAX = {"short": 8.0, "long": 15.0}   # quanto si tollera di scendere dal massimo toccato
_TRAIL_MIN_GAIN = 3.0        # sotto questo guadagno non è «proteggere un utile», è normale oscillare
_RSI_CALDO = {"short": 68.0, "long": 78.0}      # ipercomprato: il rimbalzo potrebbe essere esaurito


def _massimo_raggiunto(entry: dict):
    """Massimo prezzo toccato dall'ingresso: dal valore memorizzato sull'occasione, con ripiego sugli
    scatti ancora in memoria. Ritorna (prezzo, data) oppure (None, None)."""
    mx, md = entry.get("max_price"), entry.get("max_date")
    snaps = [s for s in (entry.get("snapshots") or []) if s.get("price")]
    if snaps:
        s = max(snaps, key=lambda x: float(x["price"]))
        if mx is None or float(s["price"]) > float(mx):
            mx, md = s["price"], s.get("date")
    return (float(mx), md) if mx is not None else (None, None)


def presa_profitto(entry: dict, ticker=None):
    """Motivo per cui un'occasione seguita sarebbe DA VALUTARE PER L'INCASSO (o None).
    Quattro motivi, dal più netto al più prudente: bersaglio raggiunto · soglia personale raggiunta ·
    guadagno che si sta sgonfiando dal massimo · rimbalzo forse esaurito (ipercomprato).
    Non rimuove nulla: come monitoring_warn, è una diagnosi. Ritorna un dizionario con motivo,
    urgenza ("incassa" o "tieni d'occhio"), guadagno attuale, massimo toccato e discesa dal massimo."""
    snaps = [s for s in (entry.get("snapshots") or []) if s.get("price")]
    if not snaps:
        return None
    ing = _ingresso(entry)
    base, last = ing.get("price"), snaps[-1].get("price")
    if not (base and last and ing.get("sicuro")):
        return None          # senza un prezzo d'ingresso affidabile non si parla di guadagno
    gain = (last / base - 1) * 100
    kind = entry.get("kind", "short")
    mx, md = _massimo_raggiunto(entry)
    giu = ((last / mx - 1) * 100) if mx else None
    esito = {"gain": round(gain, 1), "max": (round(mx, 4) if mx else None), "max_date": md,
             "giu_dal_max": (round(giu, 1) if giu is not None else None)}
    tgt = ing.get("target")
    mio = entry.get("my_target_price")
    if mio and last >= float(mio):
        return dict(esito, motivo=f"soglia personale raggiunta ({float(mio):,.2f}): incassa",
                    urgenza="incassa", tipo="soglia")
    if tgt and last >= float(tgt):
        return dict(esito, motivo=f"bersaglio {float(tgt):,.2f} raggiunto (sei a {gain:+.1f}%): "
                                  f"valuta di incassare", urgenza="incassa", tipo="bersaglio")
    trail = _TRAIL_DAL_MAX.get(kind, 8.0)
    if gain > _TRAIL_MIN_GAIN and giu is not None and giu <= -trail:
        return dict(esito, motivo=f"scesa {abs(giu):.0f}% dal massimo ({mx:,.2f}) restando in guadagno "
                                  f"({gain:+.1f}%): il guadagno si sta sgonfiando",
                    urgenza="incassa", tipo="sgonfia")
    rsi = snaps[-1].get("rsi")
    if rsi is not None and gain > 0 and float(rsi) >= _RSI_CALDO.get(kind, 68.0):
        return dict(esito, motivo=f"ipercomprato (RSI {float(rsi):.0f}) con {gain:+.1f}% di guadagno: "
                                  f"il rimbalzo potrebbe essere quasi esaurito",
                    urgenza="tieni d'occhio", tipo="ipercomprato")
    return None


def aggiorna_presa_profitto() -> list:
    """Per il job: aggiorna il verdetto di incasso su ogni occasione seguita e ritorna quelle da
    NOTIFICARE (una volta sola, e l'avviso si ri-arma se il motivo rientra). Non rimuove nulla:
    la decisione di vendere resta all'utente, perché il sistema non sa quanto hai comprato."""
    tracked = load_tracking()
    if not tracked:
        return []
    da_notificare, changed = [], False
    for tk, e in tracked.items():
        p = presa_profitto(e, tk)
        if p:
            if e.get("incasso", {}).get("motivo") != p["motivo"]:
                changed = True
            e["incasso"] = p
            if p["urgenza"] == "incassa" and not e.get("incasso_notified"):
                e["incasso_notified"] = True
                changed = True
                da_notificare.append({"ticker": tk, "name": e.get("name", tk),
                                      "kind": e.get("kind", "short"), **p})
        else:
            if e.pop("incasso", None) is not None or e.pop("incasso_notified", None) is not None:
                changed = True
    if changed:
        save_tracking(tracked)
    return da_notificare


_PRE_GIA_CORSA = 8.0      # risalita (%) dall'inizio dell'osservazione oltre la quale il grosso è fatto
_PRE_RITRACCIA = 5.0      # quanto può scendere dal proprio massimo prima di dire «si sta sgonfiando»


def gia_corsa(e_watch: dict, stato: dict = None):
    """Per la sezione «In anticipo»: questa candidata ha GIÀ FATTO il movimento?
    È il gemello di presa_profitto sul lato opposto — qui non hai comprato, quindi «è al massimo e
    potrebbe scendere» non vuol dire «incassa» ma «troppo tardi per entrare». Serve perché il sistema
    consegna metà del rimbalzo prima di segnalare (misurato: +4,8% mediano già avvenuto al momento
    della promozione), e senza questo avviso si finisce per comprare la coda del movimento.

    Si usa solo ciò che le osservazioni contengono (prezzo e convenienza: non c'è né il bersaglio né
    l'RSI). Due motivi: la risalita dall'inizio dell'osservazione è già ampia, oppure il prezzo ha
    già ritracciato dal proprio massimo restando in risalita. None se non è il caso."""
    obs = [o for o in ((e_watch or {}).get("obs") or []) if o.get("price")]
    if len(obs) < 2:
        return None
    try:
        primo = float(obs[0]["price"])
        ultimo = float(obs[-1]["price"])
        mx = max(float(o["price"]) for o in obs)
    except (TypeError, ValueError):
        return None
    if not primo or not mx:
        return None
    salita = (ultimo / primo - 1) * 100      # dove sta ADESSO rispetto all'inizio
    corsa = (mx / primo - 1) * 100           # quanto ha corso al MASSIMO: è il movimento avvenuto
    giu = (ultimo / mx - 1) * 100            # quanto ha già restituito da lì
    base = {"salita": round(salita, 1), "corsa": round(corsa, 1), "max": round(mx, 4),
            "giu_dal_max": round(giu, 1),
            "kind": (e_watch or {}).get("kind") or (stato or {}).get("kind")}
    if salita >= _PRE_GIA_CORSA:
        return dict(base, motivo=f"già risalita {salita:+.1f}% da quando è osservata: il grosso del "
                                 f"movimento è avvenuto", tipo="salita")
    # Il movimento si misura fino al MASSIMO, non al prezzo di adesso: un titolo salito dell'8% e poi
    # ripiegato al +2% ha già fatto la sua corsa, e guardando solo il +2% non si vedrebbe.
    if corsa >= _PRE_GIA_CORSA * 0.6 and giu <= -_PRE_RITRACCIA:
        return dict(base, motivo=f"era arrivata a {corsa:+.1f}% e ha già restituito {abs(giu):.0f}% dal "
                                 f"massimo ({mx:,.2f}): il movimento si sta sgonfiando", tipo="ritraccia")
    return None


def _collapsed_or_stale(entry: dict, ticker=None):
    """Rileva un titolo CROLLATO/delistato o con DATI FERMI, dagli scatti di monitoraggio.
    - "collapse": perdita > 90% dal prezzo d'INGRESSO (fallimento/delisting) → va rimosso.
    - "stale": l'ultimo scatto con prezzo è vecchio di ≥3 giorni di Borsa (il titolo non riceve
      più dati: possibile delisting) → si segnala soltanto. None se tutto regolare."""
    snaps = [s for s in entry.get("snapshots", []) if s.get("price")]
    if not snaps:
        return None
    # base = prezzo d'INGRESSO congelato (non il primo scatto superstite, che la potatura sposta in
    # avanti). Il job lo tiene allineato ai frazionamenti: senza quello un titolo che si frazionava
    # 12:1 risultava «crollato del 92%» e veniva rimosso subito, senza periodo di conferma.
    base, last = _ingresso(entry).get("price"), snaps[-1].get("price")
    if base and last is not None and (last / base - 1) <= -0.90:
        return "collapse"
    if snaps[-1].get("date") and _trading_days_between(snaps[-1]["date"], _now_iso(), ticker) >= 3:
        return "stale"
    return None


def monitoring_warn(entry, ticker=None):
    """Motivo per cui un'occasione monitorata sarebbe DA VALUTARE PER L'USCITA (o None): è ciò che il
    sistema, coi vecchi criteri, avrebbe tolto da solo (sotto lo stop, in perdita da troppo, dati fermi,
    crollo). NON rimuove nulla. Calcolato dagli scatti già in memoria (nessuna chiamata di rete), così
    sia il job sia l'app possono usarlo (l'app lo mostra dal vivo nella sezione 'Candidate all'uscita')."""
    snaps = [s for s in entry.get("snapshots", []) if s.get("price")]
    if not snaps:
        return None
    state = _collapsed_or_stale(entry, ticker)
    if state == "collapse":
        return "crollo/delisting (perdita >90%)"
    if state == "stale":
        return "dati non aggiornati (possibile delisting)"
    kind = entry.get("kind", "short")
    added = entry.get("added") or snaps[0].get("date")
    days = _trading_days_between(added, _today_iso(), ticker)
    ing = _ingresso(entry)
    base, last_price = ing.get("price"), snaps[-1].get("price")
    # Le due regole che seguono misurano il rendimento DALL'INGRESSO: se il prezzo d'ingresso non è
    # quello vero (occasione non ancora ancorata e primo scatto già potato) ci si ASTIENE. Un avviso
    # falso non resta un avviso: dopo il periodo di conferma diventa una rimozione autonoma di una
    # posizione sana. Il job sistema l'ancoraggio da sé (ancora_ingressi) al primo giro utile.
    if not (base and last_price and ing.get("sicuro")):
        return None
    stop = ing.get("stop")
    if stop is not None and last_price <= stop:
        return "sceso sotto lo stop (−2×ATR): valuta l'uscita"
    if days >= _REMOVE_WINDOW.get(kind, 5) and (last_price / base - 1) <= 0:
        return f"in perdita da {days} giorni di Borsa: valuta l'uscita"
    return None


def _load_exit_cooldown() -> dict:
    d = read_data_json(EXIT_COOLDOWN_NAME, {})
    return d if isinstance(d, dict) else {}


def _in_exit_cooldown(tk: str, cooldown: dict = None) -> bool:
    """True se il ticker è stato tolto di recente (entro _EXIT_COOLDOWN_DAYS): non ri-promuoverlo (anti-churn)."""
    d = cooldown if cooldown is not None else _load_exit_cooldown()
    v = d.get(str(tk).upper())
    return bool(v and _trading_days_between(v, _today_iso(), tk) < _EXIT_COOLDOWN_DAYS)


def _mark_exit_cooldown(tk: str) -> None:
    """Registra un ticker appena tolto dal monitoraggio (per non ri-promuoverlo subito) e pota i vecchi."""
    d = _load_exit_cooldown()
    d[str(tk).upper()] = _today_iso()
    d = {k: v for k, v in d.items() if _trading_days_between(v, _today_iso(), k) < _EXIT_COOLDOWN_DAYS}
    write_data_json(EXIT_COOLDOWN_NAME, d)


def manage_monitoring() -> tuple:
    """FASE 2 — monitoraggio (solo occasioni auto-promosse; le scelte manuali non si toccano).
    Rimozione autonoma PRUDENTE: un'occasione viene tolta solo se il deterioramento (`warn`) PERSISTE
    per alcuni giorni di Borsa (_EXIT_CONFIRM_DAYS: breve 4 / lungo 10) — NON al primo calo — oppure
    subito in caso di crollo/delisting (>90%). Se recupera, il conto (`warn_since`) si azzera → niente
    churn; i titoli tolti vanno in cooldown per non essere ri-promossi subito. Invia la prima notifica
    per le occasioni in guadagno oltre la finestra. Ritorna (da_notificare, rimosse)."""
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
        days = _trading_days_between(added, _today_iso(), tk)
        ing = _ingresso(e)
        base = ing.get("price")
        last_price = snaps[-1]["price"]
        # rendimento dal giorno di promozione. None se il prezzo d'ingresso non è affidabile: la
        # notifica di guadagno non deve partire su un numero inventato (e nemmeno mancare per un
        # numero sbagliato: senza ancoraggio si notificava il rialzo dal primo scatto superstite).
        ret = ((last_price / base - 1) * 100
               if (base and last_price and ing.get("sicuro")) else None)
        # Crollo estremo / delisting (>90%): rimozione IMMEDIATA + cooldown.
        if _collapsed_or_stale(e, tk) == "collapse":
            _append_exit_record(tk, e, "crollo/delisting (perdita >90%)")
            del tracked[tk]
            removed.append(tk)
            _mark_exit_cooldown(tk)
            changed = True
            continue
        # Deterioramento: si SEGNALA (`warn`) e si tiene traccia da QUANDO (`warn_since`). La rimozione
        # autonoma scatta SOLO se il deterioramento PERSISTE per _EXIT_CONFIRM_DAYS giorni di Borsa
        # (conferma, non al primo calo). Se recupera → si azzera tutto (niente churn).
        warn = monitoring_warn(e, tk)
        if warn:
            if not e.get("warn_since"):
                e["warn_since"] = _today_iso()
                changed = True
            if e.get("warn") != warn:
                e["warn"] = warn
                changed = True
            # LO STOP NON CHIEDE CONFERMA. Un motivo basato su un LIVELLO di prezzo è già la propria
            # conferma: aspettare altri 4 giorni significa uscire molto più in basso del livello che
            # avrebbe dovuto proteggere. Misurato sulle 4 uscite per stop: due hanno perso circa il
            # doppio di quanto lo stop prometteva (una è uscita il 10,6% sotto il proprio stop).
            # Le altre cause (perdita prolungata, dati fermi) restano con il periodo di conferma,
            # perché lì il tempo È l'informazione.
            if _SUBITO_ALLO_STOP and "stop" in warn.lower():
                _append_exit_record(tk, e, warn)
                del tracked[tk]
                removed.append(tk)
                _mark_exit_cooldown(tk)
                changed = True
                continue
            if _trading_days_between(e["warn_since"], _today_iso(), tk) >= _EXIT_CONFIRM_DAYS.get(kind, 5):
                _append_exit_record(tk, e, e.get("warn") or "deterioramento confermato")
                del tracked[tk]
                removed.append(tk)
                _mark_exit_cooldown(tk)
                changed = True
                continue
        elif e.get("warn") is not None or e.get("warn_since") is not None:
            e.pop("warn", None)
            e.pop("warn_since", None)
            changed = True
        if (ret is not None and days >= _NOTIFY_WINDOW.get(kind, 3)
                and ret >= _NOTIFY_MIN_RET and not e.get("notified")):
            e["notified"] = True
            changed = True
            to_notify.append({"ticker": tk, "kind": kind, "days": days,
                              "ret": round(ret, 1), "name": e.get("name", tk)})
    if changed:
        # force solo se si è davvero deciso di togliere qualcosa in questo giro: è l'unico caso in
        # cui l'elenco si accorcia legittimamente (e non può derivare da una lettura fallita, che
        # avrebbe dato un elenco vuoto e sarebbe uscita subito qui sopra).
        save_tracking(tracked, force=bool(removed))
    return to_notify, removed


def exit_signals(r, kind) -> dict:
    """Tesi di USCITA dal monitoraggio: motivi per cui l'idea è (probabilmente) esaurita — NON è un
    ordine di vendita, è un avviso. Ipercomprato (RSI alto) / (lungo) fondamentali in peggioramento.
    NB: il ritorno alla media 50gg (SMA50) NON è più un'uscita — il backtest su 5 anni mostra che
    incassare al bersaglio CAPPA i vincitori e azzera il rendimento; l'SMA50 resta solo un livello
    indicativo di potenziale, mentre la protezione dalle perdite è lo stop 2×ATR. Ritorna {exit, reasons}."""
    reasons = []
    rsi = r.get("rsi")
    thr = 75 if kind == "long" else 70
    if rsi is not None and rsi >= thr:
        reasons.append(f"RSI {rsi:.0f}: ipercomprato (rimbalzo forse esaurito)")
    if kind == "long":
        trap = r.get("trap") or {}
        if trap.get("strong") or trap.get("factor", 1.0) <= 0.75:
            reasons.append("fondamentali in peggioramento (possibile trappola)")
    return {"exit": bool(reasons), "reasons": reasons}


def monitoring_exit_alerts() -> list:
    """Avviso di USCITA (una volta sola) per le occasioni in monitoraggio la cui tesi è esaurita;
    si ri-arma se il segnale rientra. Ritorna [{ticker, name, reasons}]."""
    tracked = load_tracking()
    if not tracked:
        return []
    out, changed = [], False
    for tk, e in tracked.items():
        if not e.get("snapshots"):
            continue
        try:
            r = opportunity_row(tk, with_fundamentals=(e.get("kind") == "long"))
        except Exception:
            r = None
        if not r:
            continue
        ex = exit_signals(r, e.get("kind", "short"))
        if ex["exit"] and not e.get("exit_notified"):
            e["exit_notified"] = True
            changed = True
            out.append({"ticker": tk, "name": e.get("name", tk), "reasons": ex["reasons"]})
        elif not ex["exit"] and e.get("exit_notified"):
            e["exit_notified"] = False     # ri-arma per un eventuale avviso futuro
            changed = True
    if changed:
        save_tracking(tracked)
    return out


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
        days = _trading_days_between(obs[0]["date"], obs[-1]["date"], e.get("ticker"))
        ret = (obs[-1]["price"] / obs[0]["price"] - 1) * 100 if (len(obs) >= 2 and obs[0]["price"]) else 0.0
        window = _OBS_WINDOW.get(kind, 3)
        # Trend di CONVENIENZA su valori GIORNALIERI (mediana), tollerante ai cali temporanei:
        # run = giorni consecutivi di tendenza positiva tollerante; trend_ok = salita netta sulla finestra.
        vals = _daily_conv_values(e.get("obs", []))
        run = _trend_progress(vals, _PROMO_MAX_DIP)
        trend_ok = (_qualifies_promotion(vals, _OBS_WINDOW.get(kind, 3), _PROMO_MIN_GAIN, _PROMO_MAX_DIP)
                    if len(vals) >= _OBS_MIN_DAYS_FOR_TREND else False)
        dconv = round(vals[-1] - vals[0], 1) if len(vals) >= 2 else 0.0
        # ultima convenienza NOTA (i punti "stale" giornalieri hanno conv=None)
        last_conv = next((o.get("conv") for o in reversed(e.get("obs", [])) if o.get("conv") is not None), None)
        # ultimi valori NOTI di qualità (i punti "stale" non li hanno): servono ai filtri
        def _ultimo(campo):
            return next((o.get(campo) for o in reversed(e.get("obs", []))
                         if o.get(campo) is not None), None)
        # L'ULTIMO PUNTO COMPLETO, non i singoli campi risaliti uno per uno. Serve a chi deve
        # scrivere una fotografia coerente (il registro dei pre-segnali): prendendo il prezzo
        # dall'ultimo punto e la convenienza dall'ultimo punto che ce l'ha, si mette a verbale un
        # istante che non è mai esistito — ENEL.MI il 19/08 aveva prezzo del 19 e convenienza del 18.
        # I punti campionati fuori orario non hanno i numeri di qualità, ed è da lì che nasce lo
        # sfasamento.
        _completo = next((o for o in reversed(e.get("obs", []))
                          if o.get("conv") is not None and o.get("price") is not None), None)
        out.append({"ticker": e.get("ticker", key.split(":")[-1]), "kind": kind,
                    "name": e.get("name", ""), "days": days, "ret": round(ret, 1),
                    "last_conv": last_conv, "window": window,
                    "remaining": max(0, window - days),
                    "last_price": obs[-1].get("price"),   # per la sezione "In anticipo" (pre-segnale)
                    "punto_completo": _completo,          # fotografia coerente, tutti i campi dello stesso istante
                    "reliab": _ultimo("reliab"), "prob_gain": _ultimo("prob_gain"),
                    "prob_loss": _ultimo("prob_loss"), "occ": _ultimo("occ"),
                    "run": run, "trend_ok": trend_ok, "dconv": dconv, "n_days": len(vals)})
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
    # prima non aveva tetto: crescendo avrebbe superato 1 MB, spegnendo la protezione
    # anti-cancellazione. Ora il vivo è limitato e l'eccedenza va in archivio (niente si perde).
    salva_registro(TRACK_RECORD_NAME, records, _TRACK_RECORD_MAX, giorni_protetti=60)


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
        # GUARDIA ANTI-FRAZIONAMENTO. Lo storico viene riscalato retroattivamente dopo un
        # frazionamento o un raggruppamento, il prezzo registrato no: il rendimento diventa
        # fantasioso. È il caso degli ETF a leva, che raggruppano spesso (SOXS registrato a 3,86
        # contro una chiusura vera di 45,10 → +1081% inventato, che da solo portava la media delle
        # promozioni da +3% a +32%). Qui il prezzo si riporta sulla scala nuova e gli orizzonti già
        # fissati si ricalcolano, invece di scartare il caso (che falserebbe il campione).
        s0 = closes[closes.index >= pd.Timestamp(str(rec.get("date"))[:10])]
        if not s0.empty and abs(float(s0.iloc[0]) / base - 1) > 0.25:
            nuovo = round(float(s0.iloc[0]), 4)
            if rec.get("obs_price"):
                rec["obs_price"] = round(float(rec["obs_price"]) * nuovo / base, 4)
            rec["price"], rec["price_src"] = nuovo, "riancorato"
            rec["ret_7d"] = rec["ret_30d"] = None      # erano calcolati sulla scala sbagliata
            base = nuovo
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


def track_record_stats(kind: str = None) -> dict:
    """Statistiche aggregate sulle promozioni: rendimento medio e MEDIANO, % di volte in positivo,
    migliore/peggiore. Su TUTTO lo storico (archivio + file vivo).
    La mediana c'è perché la media è fragile: un singolo caso fuori scala (o un titolo che
    decuplica) la sposta di decine di punti, mentre la mediana dice com'è andata «di solito»."""
    records = load_registro_completo(TRACK_RECORD_NAME, load_track_record())
    # IL TIPO CONTA: la pagina dichiara che il selettore Breve/Lungo vale per tutte le schede, e
    # questa lo ignorava, mescolando 63 titoli di breve con 15 di lungo — orizzonti e regole
    # diversi. I record vecchi senza il campo si considerano di breve, come altrove nel progetto.
    if kind:
        records = [r for r in records if (r.get("kind") or "short") == kind]

    def agg(field):
        vals = sorted(r[field] for r in records if r.get(field) is not None)
        if not vals:
            return None
        n = len(vals)
        med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
        return {"n": n, "avg": round(sum(vals) / n, 1), "med": round(med, 1),
                "hit": round(100 * sum(1 for v in vals if v > 0) / n),
                "best": round(max(vals), 1), "worst": round(min(vals), 1)}

    return {"total": len(records), "now": agg("ret_now"),
            "d7": agg("ret_7d"), "d30": agg("ret_30d")}


def track_record_entry_comparison() -> dict:
    """Confronta 'ingresso a INIZIO OSSERVAZIONE' vs 'ingresso alla PROMOZIONE' sulle promozioni
    che hanno registrato entrambi i prezzi (campo obs_price, presente sui record nuovi). Nessuna
    chiamata di rete: il prezzo attuale è ricavato da price*(1+ret_now/100). Ritorna
    {n, avg_promo, avg_obs, avg_head_start} dove head_start = rimbalzo medio già avvenuto tra
    l'inizio dell'osservazione e la promozione ("quanto si paga l'attesa della conferma").
    Con meno di 3 campioni ritorna solo {n} (troppo poco per dire qualcosa)."""
    promo_rets, obs_rets, heads = [], [], []
    for r in load_registro_completo(TRACK_RECORD_NAME, load_track_record()):
        op, p, rn = r.get("obs_price"), r.get("price"), r.get("ret_now")
        if not op or not p or op <= 0 or p <= 0 or rn is None:
            continue
        last = p * (1 + rn / 100.0)
        promo_rets.append(rn)
        obs_rets.append((last / op - 1) * 100.0)
        heads.append((p / op - 1) * 100.0)
    n = len(promo_rets)
    if n < 3:
        return {"n": n}
    return {"n": n,
            "avg_promo": round(sum(promo_rets) / n, 2),
            "avg_obs": round(sum(obs_rets) / n, 2),
            "avg_head_start": round(sum(heads) / n, 2)}


# ---------------------------------------------------------------------------
# SCENARI ACQUISTO/VENDITA — per ogni promozione il sistema registra i prezzi chiave e poi,
# maturando i giorni, calcola DA SOLO il rendimento di 9 combinazioni (3 momenti d'acquisto ×
# 3 regole di vendita). Nel tempo dice QUALE combinazione è più precisa/affidabile, coi dati
# veri e senza senno di poi. Le vendite sono ancorate alla data di PROMOZIONE, così gli
# ingressi si confrontano ad armi pari (stessa uscita, entrata diversa).
# ---------------------------------------------------------------------------
SCENARIO_LOG_NAME = "scenario_log.json"
_SCENARIO_MAX = _SCENARIO_MAX_LIVE      # tetto del file VIVO; l'eccedenza va in archivio
# MOMENTI D'ACQUISTO: quando entra in «In anticipo» (pre-segnale solido) · a inizio osservazione ·
# alla promozione (regola attuale) · dopo il periodo di conferma (5 gg di Borsa breve, 10 lungo).
_SCENARIO_BUYS = ("anticipo", "osservazione", "promozione", "conferma")
# REGOLE DI VENDITA: al bersaglio (se toccato entro 30 gg, altrimenti si vende a 30 gg) · a 7 giorni ·
# a 30 giorni · a 1 anno. Quali mostrare dipende dal tipo (vedi SCENARIO_SELLS_PER_TIPO).
_SCENARIO_SELLS = ("bersaglio", "7g", "30g", "365g")
_SELL_DAYS = {"7g": 7, "30g": 30, "bersaglio": 30, "365g": 365}
_CONF_DAYS = {"short": 5, "long": 10}   # giorni di Borsa del "periodo di conferma" (= _REMOVE_WINDOW)
# COMBINAZIONI SENZA SENSO per costruzione, da non calcolare e da ripulire se già registrate.
# Per il breve il periodo di conferma dura 5 giorni di Borsa, cioè ~7 giorni di calendario: comprare
# «dopo la conferma» e vendere «dopo 1 settimana» significa comprare e vendere LO STESSO GIORNO —
# 0% lordo e −1€ di commissione. In tabella si leggeva «media +0,00%, in positivo 0%», cioè come una
# strategia che perde sempre: non lo è, è una casella che non esiste.
_SCENARI_ESCLUSI = {("short", "conferma", "7g")}
# Cosa si mostra nella matrice: 4 acquisti × 3 vendite, con orizzonti diversi per tipo.
# «osservazione» è stato AGGIUNTO alla matrice (ago 2026): era già calcolato e salvato da sempre in
# _SCENARIO_BUYS, ha tanti esiti quanti la promozione (45 contro 45 sul breve) e non era visibile in
# nessuna scheda — si intravedeva solo nel confronto della scheda voti. Ha lo stesso limite di
# «anticipo» (il prezzo è registrato solo per le occasioni POI promosse, quindi la riga è più bella
# del vero), e l'avvertenza accanto lo dice.
# L'ORDINE è quello CRONOLOGICO VERO, non quello dei nomi: prima il sistema mette un titolo in
# osservazione, poi ne riconosce il pre-segnale («In anticipo»), poi lo promuove. Sui dati reali
# «In anticipo» arriva DOPO l'inizio dell'osservazione in 39 righe su 41, quindi metterlo per primo
# faceva leggere la matrice come una scala temporale che non esiste.
SCENARIO_BUYS_UI = ("osservazione", "anticipo", "promozione", "conferma")
SCENARIO_SELLS_PER_TIPO = {"short": ("bersaglio", "7g", "30g"),
                           "long": ("bersaglio", "30g", "365g")}
SCENARIO_ETICHETTE = {
    "anticipo": "🔭 All'ingresso in «In anticipo»", "osservazione": "👀 A inizio osservazione",
    "promozione": "📌 All'ingresso in Monitoraggio", "conferma": "⏳ Dopo il periodo di conferma",
    "bersaglio": "🎯 Alla soglia", "soglia": "🎯 Alla soglia", "7g": "📅 Dopo 1 settimana",
    "30g": "📅 Dopo 1 mese", "365g": "📅 Dopo 1 anno",
}


def load_scenario_log() -> list:
    data = read_data_json(SCENARIO_LOG_NAME, [])
    return data if isinstance(data, list) else []


def _rel_rank(reliab) -> int:
    """Affidabilità in numero: 2 = 🟢 Alta, 1 = 🟡 Media, 0 = 🔴 Bassa/ignota."""
    s = str(reliab or "")
    return 2 if "Alta" in s else (1 if "Media" in s else 0)


def _pre_row_for(tk, kind, entro_data, dal_data=None):
    """La RIGA della prima comparsa di un titolo tra i pre-segnali solidi (sezione «In anticipo»)
    DENTRO L'EPISODIO in corso, oppure None. Serve anche ai «passaggi»: da questa riga si prendono
    prezzo, convenienza e probabilità del momento in cui l'occasione è entrata lì.

    `dal_data` delimita l'episodio (di norma l'inizio dell'osservazione di quella riga) e non è un
    dettaglio: senza limite inferiore si prendeva il pre-segnale PIÙ VECCHIO di tutta la storia,
    archivio compreso. Finché nessun titolo era rientrato in «In anticipo» il difetto non si vedeva,
    perché non c'erano doppioni; ma la regola anti-doppione dei pre-segnali dura 30 giorni, quindi
    dal 27/08/2026 (trenta giorni dalle prime righe, del 27/07) lo stesso titolo può avere una
    seconda riga, e la scelta «il più vecchio» avrebbe cominciato a datare l'ingresso in «In
    anticipo» a un episodio chiuso settimane prima, con il prezzo di allora.
    Se nell'episodio non c'è nessun pre-segnale si ritorna None — cioè «questa occasione non è mai
    passata da In anticipo», che è la verità — invece di ripiegare su una riga di un altro episodio."""
    try:
        cand = [r for r in load_registro_completo(PRESIGNAL_NAME, load_presignal_log())
                if str(r.get("ticker", "")).upper() == str(tk).upper()
                and r.get("kind") == kind and r.get("price")
                and str(r.get("date", ""))[:10] <= str(entro_data)[:10]]
        if dal_data:
            cand = [r for r in cand if str(r.get("date", ""))[:10] >= str(dal_data)[:10]]
        if not cand:
            return None
        return min(cand, key=lambda r: str(r.get("date")))
    except Exception:
        return None


def _pre_entry_for(tk, kind, entro_data):
    """Prima comparsa di un titolo tra i pre-segnali SOLIDI (sezione «In anticipo») prima della
    promozione: ritorna (prezzo, data) oppure (None, None) se non c'è mai passato."""
    r = _pre_row_for(tk, kind, entro_data)
    if not r:
        return None, None
    try:
        return float(r["price"]), str(r.get("date"))[:10]
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# I «PASSAGGI» — la fotografia dei valori VERI a ogni cambio di sezione.
#
# Il problema che risolvono: la riga di scenario nasceva solo alla promozione e portava UN SOLO
# gruppo di numeri di qualità, quelli di quel giorno. Ma la matrice confronta QUATTRO momenti
# d'acquisto: filtrando la riga «compro quando entra in osservazione» con la probabilità di salita
# del giorno della promozione si usa un'informazione che quel giorno non esisteva ancora — e il
# risultato sembra migliore di quello che una regola eseguibile avrebbe dato.
# Con `passaggi` ogni momento porta i suoi numeri, e i filtri di ogni sotto-sezione usano i suoi.
# Cosa si riesce a mettere a verbale, e da dove:
#   osservazione → campo `primo` del registro delle osservazioni (fotografia dell'ingresso)
#   anticipo     → prima riga del registro dei pre-segnali
#   monitoraggio → i valori che il monitoraggio ha in mano quando promuove (già disponibili)
#   conferma     → dagli scatti del monitoraggio alla data di fine verifica (la riempie
#                  resolve_scenarios quando ricava conf_price, anche a posteriori)
# ---------------------------------------------------------------------------
MOMENTI = ("osservazione", "anticipo", "promozione", "conferma")
# Quanti giorni di distanza si accettano fra la data di fine verifica e lo scatto del monitoraggio da
# cui si prendono i numeri di qualità. Serve perché il lavoro automatico può saltare un giro (il 6
# agosto non ha girato, e 30 voci su 77 hanno un giorno di Borsa mancante): un paio di giorni di
# scarto è fisiologico, tre settimane è un altro momento.
_CONF_SNAP_MAX_GG = 4


def _passaggio(data=None, prezzo=None, conv=None, prob_gain=None, prob_loss=None,
               reliab=None, mkt=None) -> dict:
    """Una voce di passaggio, sempre con gli stessi campi (anche vuoti): così chi legge non deve
    indovinare se un campo manca perché non c'era o perché non è stato scritto."""
    return {"data": (str(data)[:16] if data else None),
            "prezzo": (float(prezzo) if prezzo not in (None, "") else None),
            "conv": conv, "prob_gain": prob_gain, "prob_loss": prob_loss,
            "reliab": reliab, "mkt": mkt}


def _primo_osservazione(tk, kind, entro_data=None) -> dict:
    """La fotografia dell'ingresso in osservazione, dal registro delle osservazioni. Preferisce il
    campo `primo` (immune alla potatura) e ripiega sul primo punto ancora presente in lista.

    `entro_data` è OBBLIGATORIA nella pratica: il registro delle osservazioni contiene l'episodio
    IN CORSO, non quello di mesi fa. Uno stesso titolo può tornare in osservazione dopo essere già
    stato promosso, e in quel caso la fotografia che si trova lì appartiene al nuovo episodio.
    Senza questo controllo si scriveva come «inizio osservazione» una data SUCCESSIVA alla
    promozione — un dato falso, non mancante: su 70 righe erano 7, con date fino a 34 giorni dopo
    e prezzi lontani fino al 24% da quello di promozione. Se la fotografia è più recente del
    limite, si ritorna vuoto e chi chiama ripiega sul prezzo già noto nella riga."""
    try:
        e = (load_opp_watch() or {}).get(f"{kind}:{str(tk).upper()}") or {}
        p = e.get("primo") or (e.get("obs") or [{}])[0]
        if not p:
            return _passaggio()
        if entro_data and str(p.get("date") or "")[:10] > str(entro_data)[:10]:
            return _passaggio()          # è un episodio successivo: non c'entra con questa riga
        return _passaggio(p.get("date"), p.get("price"), p.get("conv"), p.get("prob_gain"),
                          p.get("prob_loss"), p.get("reliab"), p.get("mkt"))
    except Exception:
        return _passaggio()


def _punto_osservazione_alla_data(tk, kind, data):
    """Il punto di osservazione di quel titolo ALLA DATA indicata (l'ultimo di quel giorno, o il più
    recente precedente), oppure None. Serve a completare una riga già scritta con i valori del
    giorno a cui si riferisce, invece che con quelli di oggi: riempire il passato coi numeri del
    presente è lo stesso errore che ha prodotto sette osservazioni datate dopo la promozione.
    Se il punto è già stato potato dalla lista (la finestra è di pochi giorni) si ritorna None e il
    campo resta vuoto, che è la risposta corretta."""
    if not data:
        return None
    try:
        e = (load_opp_watch() or {}).get(f"{kind}:{str(tk).upper()}") or {}
        d = str(data)[:10]
        prima = [o for o in (e.get("obs") or []) if str(o.get("date", ""))[:10] <= d
                 and o.get("conv") is not None]
        if not prima:
            return None
        return max(prima, key=lambda o: str(o.get("date")))
    except Exception:
        return None


def _snap_alla_data(tk, kind, data) -> dict:
    """I valori del monitoraggio alla data indicata: il primo scatto da quel giorno in poi, o in
    mancanza l'ultimo precedente. Serve al passaggio «dopo i giorni di verifica», che non ha un
    momento in cui qualcuno lo scrive: il periodo di verifica finisce da solo, e i numeri di quel
    giorno stanno negli scatti che il monitoraggio prende comunque. È anche il modo di RECUPERARE
    quel passaggio sulle occasioni già registrate."""
    if not data:
        return _passaggio()
    try:
        e = (load_tracking() or {}).get(str(tk).upper()) or {}
        if e.get("kind") and kind and e.get("kind") != kind:
            e = {}
        # STORIA COMPLETA, non solo il file vivo. Questa funzione cerca i valori a una data che può
        # essere di settimane prima, e il file vivo ne tiene pochi giorni: cercarli lì darebbe None
        # proprio nei casi che contano. L'archivio degli scatti invece non butta più niente, quindi
        # da adesso questa ricerca funziona MEGLIO di prima, non peggio.
        snaps = storia_scatti(tk) if e else []
        if not snaps:
            snaps = sorted([s for s in (e.get("snapshots") or []) if s.get("date")],
                           key=lambda s: str(s.get("date")))
        if not snaps:
            # RIPIEGO SULLA LAPIDE: se il titolo è già uscito dal monitoraggio la sua voce non
            # esiste più, ma da adesso gli scatti sono a verbale nella lapide dell'uscita, che è un
            # registro storico. Senza questo ripiego il momento della verifica restava vuoto per
            # sempre a ogni uscita anticipata, che è il caso più frequente di tutti.
            lap = [h for h in load_registro_completo(EXIT_HISTORY_NAME, load_exit_history())
                   if str(h.get("ticker", "")).upper() == str(tk).upper()
                   and (not kind or not h.get("kind") or h.get("kind") == kind)
                   and h.get("snapshots")]
            if lap:
                ultima = max(lap, key=lambda h: str(h.get("removed") or ""))
                snaps = sorted([s for s in (ultima.get("snapshots") or []) if s.get("date")],
                               key=lambda s: str(s.get("date")))
        if not snaps:
            return _passaggio()
        d = str(data)[:10]
        # LIMITE DI DISTANZA: prima si prendeva il primo scatto dalla data in poi e, se non c'era,
        # l'ULTIMO disponibile — cioè un giorno qualunque, anche settimane dopo, e per un titolo
        # ripromosso anche di un altro episodio. Un dato di un altro giorno è peggio di un dato
        # mancante, perché il vuoto si vede e il numero sbagliato no. Ora si accetta solo uno scatto
        # abbastanza vicino (in avanti si preferisce il primo, indietro si tollera lo stesso numero
        # di giorni); se non c'è, si ritorna vuoto e la scheda lo dichiara.
        vicini = [s for s in snaps
                  if abs(_days_between(str(s.get("date"))[:10], d) or 999) <= _CONF_SNAP_MAX_GG]
        if not vicini:
            return _passaggio()
        dopo = [s for s in vicini if str(s.get("date"))[:10] >= d]
        s = dopo[0] if dopo else vicini[-1]
        return _passaggio(s.get("date"), s.get("price"), s.get("convenienza"), s.get("prob_gain"),
                          s.get("prob_loss"), s.get("reliab"))
    except Exception:
        return _passaggio()


def _passaggio_conferma(r) -> dict:
    """Il passaggio «dopo i giorni di verifica» di una riga: i numeri di QUALITÀ dallo scatto del
    monitoraggio più vicino alla data di fine verifica, ma data e prezzo SEMPRE quelli su cui il
    rendimento è stato calcolato. Regola scritta una volta sola perché la riempivano tre punti
    diversi, ed è il tipo di regola che, ripetuta a mano, diventa tre regole leggermente diverse."""
    if not r.get("conf_date"):
        return _passaggio()
    p = _snap_alla_data(r.get("ticker"), r.get("kind"), r.get("conf_date"))
    p["data"], p["prezzo"] = r.get("conf_date"), r.get("conf_price")
    return p


def completa_passaggi() -> int:
    """Riempie i «passaggi» delle righe di scenario che non li hanno, con quello che è davvero
    ricostruibile dai registri. Ritorna quante righe ha completato.

    ONESTÀ SU COSA SI RECUPERA E COSA NO:
      · promozione → sempre: i suoi numeri sono già nella riga;
      · conferma   → dagli scatti del monitoraggio, quindi per le occasioni ancora seguite;
      · anticipo   → dal registro dei pre-segnali: prezzo e convenienza sì, le probabilità solo per
                     le candidate registrate da quando quel registro le salva;
      · osservazione → solo per le occasioni ancora presenti nel registro delle osservazioni; per
                     le altre resta il solo prezzo già noto nella riga, senza i numeri di qualità.
    Quello che non si recupera resta vuoto, e le schede mostrano quante righe ne sono prive invece
    di far finta che il dato ci sia."""
    rows = load_scenario_log()
    if not rows:
        return 0
    fatte = 0
    for r in rows:
        if isinstance(r.get("passaggi"), dict) and r["passaggi"].get("promozione"):
            # già presenti: manca solo eventualmente la conferma, che matura dopo
            # La conferma si riempie quando matura, E si RIALLINEA se il prezzo a verbale non è
            # quello su cui il rendimento è calcolato: le prime versioni prendevano il prezzo dallo
            # scatto del monitoraggio (un campionamento a orario qualunque), quindi la riga diceva
            # «comprata a X» mentre il conto era fatto su Y. Erano 54 righe su 54.
            _c = r["passaggi"].get("conferma") or {}
            # `conf_price` nella condizione: senza di esso il passaggio resterebbe senza prezzo e la
            # riga verrebbe contata come «completata» a ogni giro pur non completando niente — con
            # il registro riscritto a vuoto ogni mezz'ora. Il contatore deve dire la verità.
            if r.get("conf_date") and r.get("conf_price") and (
                    not _c.get("prezzo")
                    or _c.get("prezzo") != r.get("conf_price")
                    or str(_c.get("data") or "")[:10] != str(r.get("conf_date"))[:10]):
                r["passaggi"]["conferma"] = _passaggio_conferma(r)
                fatte += 1
            # RIPARAZIONE di un dato FALSO già scritto: un'osservazione datata DOPO la promozione
            # appartiene a un episodio successivo dello stesso titolo. Si rimette il prezzo già
            # noto nella riga, che è quello su cui i rendimenti sono stati calcolati.
            _o = r["passaggi"].get("osservazione") or {}
            if str(_o.get("data") or "")[:10] > str(r.get("date"))[:10]:
                r["passaggi"]["osservazione"] = _passaggio(r.get("obs_date"), r.get("obs_price"))
                fatte += 1
            # Stessa riparazione sull'ALTRO lato: un pre-segnale datato PRIMA dell'inizio
            # dell'osservazione non può appartenere a questo episodio (per essere «solido» un titolo
            # deve prima essere osservato), quindi è di un episodio precedente e va svuotato.
            _a = r["passaggi"].get("anticipo") or {}
            _oss_d = str((r["passaggi"].get("osservazione") or {}).get("data") or r.get("obs_date") or "")[:10]
            if _a.get("prezzo") and _oss_d and str(_a.get("data") or "")[:10] < _oss_d:
                r["passaggi"]["anticipo"] = _passaggio()
                fatte += 1
            continue
        tk, kind = r.get("ticker"), r.get("kind")
        oss = _primo_osservazione(tk, kind, entro_data=r.get("date"))
        if not oss.get("prezzo") and r.get("obs_price"):
            oss = _passaggio(r.get("obs_date"), r.get("obs_price"))    # solo il prezzo, è quel che c'è
        pre = _pre_row_for(tk, kind, r.get("date"),
                           dal_data=str(oss.get("data") or r.get("obs_date") or "")[:10] or None)
        r["passaggi"] = {
            "osservazione": oss,
            "anticipo": (_passaggio(pre.get("date"), pre.get("price"), pre.get("conv"),
                                    pre.get("prob_gain"), pre.get("prob_loss"), pre.get("reliab"))
                         if pre else _passaggio(r.get("pre_date"), r.get("pre_price"))),
            "promozione": _passaggio(r.get("date"), r.get("promo_price"), r.get("conv"),
                                     r.get("prob_gain"), r.get("prob_loss"), r.get("reliab")),
            "conferma": _passaggio_conferma(r),
        }
        fatte += 1
    if fatte:
        salva_registro(SCENARIO_LOG_NAME, rows, _SCENARIO_MAX, giorni_protetti=400)
    return fatte


def _log_promotion_scenario(tk, kind, promo_price, obs_price, obs_date, target, stop,
                            reliab=None, prob_gain=None, prob_loss=None, conv=None) -> None:
    """Registra gli 'ancoraggi' di una promozione: i prezzi dei momenti d'acquisto (pre-segnale,
    inizio osservazione, promozione — quello dopo la conferma si risolve nei giorni seguenti),
    bersaglio/stop e la QUALITÀ del segnale al momento dell'acquisto (affidabilità, probabilità,
    convenienza), che serve ai filtri «comprerei solo se…»."""
    try:
        # L'osservazione si calcola PRIMA perché la sua data delimita l'episodio: il pre-segnale da
        # cercare è quello di QUESTO episodio, non il più vecchio mai registrato per il titolo.
        p_oss = _primo_osservazione(tk, kind, entro_data=_today_iso())
        dal = str(p_oss.get("data") or obs_date or "")[:10] or None
        pre_row = _pre_row_for(tk, kind, _today_iso(), dal_data=dal)
        pre_price = float(pre_row["price"]) if pre_row and pre_row.get("price") else None
        pre_date = str(pre_row.get("date"))[:10] if pre_row else None
        # I PASSAGGI: i valori veri di ogni momento, non solo quelli della promozione.
        passaggi = {
            # entro oggi: alla promozione l'episodio in corso è quello giusto, ma il limite protegge
            # dai casi in cui la data del registro fosse avanti (fuso o orologio sfasato).
            "osservazione": p_oss,
            "anticipo": (_passaggio(pre_row.get("date"), pre_row.get("price"), pre_row.get("conv"),
                                    pre_row.get("prob_gain"), pre_row.get("prob_loss"),
                                    pre_row.get("reliab")) if pre_row else _passaggio()),
            "promozione": _passaggio(_now_iso(), promo_price, conv, prob_gain, prob_loss, reliab),
            "conferma": _passaggio(),      # la riempie resolve_scenarios a fine periodo di verifica
        }
        # il prezzo di inizio osservazione a verbale nel passaggio è più affidabile di quello
        # ricavato dalla lista potata: se c'è, vince lui.
        if passaggi["osservazione"].get("prezzo"):
            obs_price = passaggi["osservazione"]["prezzo"]
            obs_date = str(passaggi["osservazione"]["data"])[:10]
        rows = load_scenario_log()
        rows.append({"ticker": str(tk).upper(), "kind": kind, "date": _today_iso(),
                     "promo_price": promo_price, "obs_price": obs_price, "obs_date": obs_date,
                     "pre_price": pre_price, "pre_date": pre_date,
                     "conf_price": None, "conf_date": None,
                     "target": target, "stop": stop,
                     "reliab": reliab, "prob_gain": prob_gain, "prob_loss": prob_loss, "conv": conv,
                     "passaggi": passaggi,
                     "res": {}})
        salva_registro(SCENARIO_LOG_NAME, rows, _SCENARIO_MAX, giorni_protetti=400)
    except Exception:
        pass   # il log degli scenari non deve mai bloccare una promozione


_VARIANTE_DEDUP_GG = 30      # uno stesso titolo non si ri-registra come scartato entro un mese


def _log_scenario_senza_soglia(tk, kind, obs, salita, conv=None) -> None:
    """Registra una candidata che ha superato TUTTI i cancelli TRANNE il rimbalzo minimo del +2%.

    Non viene promossa e non finisce nel monitoraggio: viene solo messa a verbale negli scenari con
    `promossa=False`, così fra qualche settimana si potrà rispondere con i fatti alla domanda «e se il
    +2% non ci fosse?». Prima non era possibile: la matrice degli scenari confronta i momenti in cui
    COMPRARE, ma contiene solo i titoli che il +2% aveva già ammesso — cioè non poteva dire nulla su
    quelli che scarta. Bersaglio e stop restano vuoti (li calcola track_opportunity, che qui non
    viene chiamata): per queste righe la vendita «al bersaglio» non si potrà valutare, mentre quelle
    a 7 / 30 / 365 giorni sì, e sono le più utili al confronto."""
    try:
        rows = load_scenario_log()
        oggi = _today_iso()
        recenti = {f"{r.get('kind')}:{r.get('ticker')}" for r in rows
                   if 0 <= _days_between(r.get("date"), oggi) <= _VARIANTE_DEDUP_GG}
        if f"{kind}:{str(tk).upper()}" in recenti:
            return
        ultimo = obs[-1] if obs else {}
        rows.append({"ticker": str(tk).upper(), "kind": kind, "date": oggi,
                     "promossa": False, "salita": round(float(salita), 2),
                     "promo_price": ultimo.get("price"),
                     "obs_price": (obs[0].get("price") if obs else None),
                     "obs_date": str((obs[0].get("date") if obs else "") or "")[:10],
                     "pre_price": None, "pre_date": None,
                     "conf_price": None, "conf_date": None,
                     "target": None, "stop": None,
                     "reliab": ultimo.get("reliab"), "prob_gain": ultimo.get("prob_gain"),
                     "prob_loss": ultimo.get("prob_loss"), "conv": conv,
                     "res": {}})
        salva_registro(SCENARIO_LOG_NAME, rows, _SCENARIO_MAX, giorni_protetti=400)
    except Exception:
        pass   # il verbale non deve mai disturbare il ciclo delle promozioni


def _data_dopo_giorni_borsa(dal, n, ticker=None):
    """Data di calendario che cade `n` giorni di BORSA dopo `dal` (per il periodo di conferma)."""
    base = dal if isinstance(dal, datetime.date) else datetime.date.fromisoformat(str(dal)[:10])
    for i in range(1, 60):
        cand = base + datetime.timedelta(days=i)
        if _trading_days_between(base.isoformat(), cand.isoformat(), ticker) >= n:
            return cand
    return None


def resolve_scenarios() -> int:
    """Risolve le combinazioni mature di ogni promozione. VENDITE (giorni di calendario dalla
    promozione): 7g · 30g · 365g · bersaglio (= prezzo target se una chiusura lo tocca entro 30
    giorni, altrimenti la chiusura a 30 giorni). ACQUISTI: pre-segnale «In anticipo», inizio
    osservazione, promozione, e dopo il PERIODO DI CONFERMA (5 giorni di Borsa per il breve, 10 per
    il lungo) — quest'ultimo prezzo viene ricavato qui e memorizzato. Guardia anti-split: se la
    prima chiusura post-promozione dista >25% dal prezzo registrato, la riga è marcata
    inutilizzabile (raggruppamenti azioni). Ritorna quante celle ha risolto."""
    rows = load_scenario_log()
    if not rows:
        return 0
    today = datetime.date.fromisoformat(_today_iso())
    changed = 0
    for r in rows:
        if r.get("bad_data"):
            continue
        try:
            promo = datetime.date.fromisoformat(str(r.get("date"))[:10])
        except Exception:
            continue
        age = (today - promo).days
        res = r.setdefault("res", {})
        kind = r.get("kind", "short")
        tk = r.get("ticker")
        # ripulisce le combinazioni escluse per costruzione: non serve la rete né le date, dipende
        # solo dal tipo, quindi si può fare anche sulle righe già completate (che altrimenti la
        # riga sotto salterebbe, lasciando per sempre le caselle senza senso già registrate).
        for _k, _b, _s in _SCENARI_ESCLUSI:
            if _k == kind and res.pop(f"{_b}|{_s}", None) is not None:
                changed += 1
        # celle che POTREBBERO essere risolte ora (vendita matura e combinazione ancora vuota)
        attese = [(bk, sk) for sk, gg in _SELL_DAYS.items() if age >= gg
                  for bk in _SCENARIO_BUYS
                  if f"{bk}|{sk}" not in res and (kind, bk, sk) not in _SCENARI_ESCLUSI]
        # prezzo del "dopo la conferma": si può ricavare appena passata la finestra di Borsa
        serve_conf = (r.get("conf_price") is None and not r.get("conf_na")
                      and _trading_days_between(promo.isoformat(), _today_iso(), tk)
                      >= _CONF_DAYS.get(kind, 5))
        if not attese and not serve_conf:
            continue
        if age > 400:                      # troppo vecchia e ancora irrisolvibile: smetti di provare
            r["bad_data"] = True
            changed += 1
            continue
        try:
            closes = get_history(tk, period=("6mo" if age < 150 else "2y"))["Close"].dropna()
            try:
                closes.index = closes.index.tz_localize(None)
            except (TypeError, AttributeError):
                pass
        except Exception:
            continue
        after = closes[closes.index > pd.Timestamp(promo)]
        if after.empty:
            continue
        pp = r.get("promo_price")
        if pp and abs(float(after.iloc[0]) / float(pp) - 1) > 0.25:      # split/raggruppamento
            r["bad_data"] = True
            changed += 1
            continue

        def _close_at(days):
            s = closes[closes.index >= pd.Timestamp(promo + datetime.timedelta(days=days))]
            # ritorna anche la DATA della chiusura usata: serve a scartare le combinazioni in cui
            # l'acquisto non precede la vendita (vedi sotto)
            return (float(s.iloc[0]), s.index[0].date().isoformat()) if not s.empty else (None, None)

        if serve_conf:
            d_conf = _data_dopo_giorni_borsa(promo, _CONF_DAYS.get(kind, 5), tk)
            s = closes[closes.index >= pd.Timestamp(d_conf)] if d_conf else None
            if s is not None and not s.empty:
                r["conf_price"] = float(s.iloc[0])
                r["conf_date"] = d_conf.isoformat()
                # …e la fotografia della QUALITÀ a quella data, dagli scatti del monitoraggio:
                # è l'unico momento d'acquisto che nessuno «vive» (il periodo di verifica finisce
                # da solo), quindi senza questo la riga «dopo i giorni di verifica» resterebbe per
                # sempre senza i suoi numeri e i filtri userebbero quelli della promozione.
                if isinstance(r.get("passaggi"), dict):
                    # numeri di qualità dallo scatto vicino, data e prezzo quelli del rendimento:
                    # la regola sta tutta in _passaggio_conferma, usata anche dal recupero.
                    r["passaggi"]["conferma"] = _passaggio_conferma(r)
                changed += 1
            elif age > 60:
                r["conf_na"] = True         # non ricavabile: smetti di riprovare
                changed += 1
        buys = {"anticipo": r.get("pre_price"), "osservazione": r.get("obs_price"),
                "promozione": pp, "conferma": r.get("conf_price")}

        sells = {}
        if age >= 7:
            sells["7g"] = _close_at(7)
        if age >= 30:
            s30, d30 = _close_at(30)
            sells["30g"] = (s30, d30)
            tgt = r.get("target")
            if tgt and s30 is not None:
                win = after[after.index <= pd.Timestamp(promo + datetime.timedelta(days=30))]
                tocchi = win[win >= float(tgt)]
                # la data della vendita al bersaglio è quella del TOCCO, non quella dei 30 giorni:
                # così la regola «l'acquisto deve precedere la vendita» esclude i casi in cui il
                # bersaglio era già stato toccato prima che il periodo di conferma finisse.
                sells["bersaglio"] = ((float(tgt), tocchi.index[0].date().isoformat())
                                      if not tocchi.empty else (s30, d30))
        if age >= 365:
            sells["365g"] = _close_at(365)
        # data di ogni momento d'ACQUISTO: una combinazione ha senso solo se l'acquisto PRECEDE la
        # vendita. Per il breve, «dopo il periodo di conferma» (5 giorni di Borsa) cade proprio sui
        # 7 giorni di calendario della vendita «dopo 1 settimana»: si comprerebbe e si venderebbe lo
        # stesso giorno, cioè 0% lordo e −1€ di commissione. Mostrata in tabella diventava «media
        # +0,00%, in positivo 0%», che si legge come «questa strategia perde sempre». Non è una
        # strategia: è una casella senza senso, e va tolta (anche dalle righe già registrate).
        date_acq = {"anticipo": r.get("pre_date"), "osservazione": r.get("obs_date"),
                    "promozione": str(r.get("date"))[:10], "conferma": r.get("conf_date")}
        for sk, (sp, sd) in sells.items():
            if sp is None:
                continue
            for bk, bp in buys.items():
                key = f"{bk}|{sk}"
                bd = date_acq.get(bk)
                if (kind, bk, sk) in _SCENARI_ESCLUSI or (bd and sd and str(bd)[:10] >= str(sd)[:10]):
                    if res.pop(key, None) is not None:
                        changed += 1
                    continue
                if key in res or not bp or float(bp) <= 0:
                    continue
                res[key] = round((float(sp) / float(bp) - 1) * 100, 2)
                changed += 1
    if changed:
        salva_registro(SCENARIO_LOG_NAME, rows, _SCENARIO_MAX, giorni_protetti=400)
    return changed


# LE TRE SCELTE SONO ALTERNATIVE, non interruttori da combinare, e la terza toglie ENTRAMBE le
# attese. La quarta combinazione possibile — togliere i giorni di osservazione ma pretendere ancora
# il rimbalzo del 2% — non esiste perché non vuole dire niente: il 2% si misura DAL primo giorno di
# osservazione, quindi al primo giorno non può essere ancora avvenuto. Chiedere un rimbalzo e non
# dare tempo perché avvenga darebbe sempre zero candidate.
SCENARIO_VARIANTI = {
    "reale": "Come fa adesso: aspetta i giorni di osservazione e il +2%",
    "senza_soglia": "Senza il +2% (ma aspetta i giorni di osservazione)",
    "senza_osservazione": "Senza nessuna attesa: né giorni di osservazione né +2%",
}

# Le due vendite disponibili per lo scenario «senza finestra di osservazione»: il registro delle
# convenienze misura la resa a 5 e 21 giorni di BORSA, che sono l'equivalente pratico dei 7 e 30
# giorni di CALENDARIO delle altre colonne (5 giorni di mercato ≈ una settimana, 21 ≈ un mese).
# Non sono la stessa misura al giorno: la differenza va dichiarata, non nascosta.
_SENZA_OSS_SELLS = {"7g": "ret_5d", "30g": "ret_21d"}


def scenari_senza_osservazione(kind: str = "short", min_conv: int = 0,
                               importo: float = 30.0, fee: float = 1.0) -> dict:
    """LO SCENARIO «e se non aspettassi l'osservazione?»: compro ogni titolo il primo giorno in cui
    entrerebbe in osservazione, senza aspettare i 3 giorni di Borsa (7 per il lungo) della finestra
    e senza pretendere il rimbalzo del 2%.

    Perché è una domanda diversa dalle altre due varianti: il «+2%» è una condizione sul PREZZO
    verificata alla fine della finestra, la finestra è invece TEMPO — e togliere il tempo è la cosa
    che cambia più radicalmente la strategia, perché si compra molti giorni prima.

    La fonte non è il registro degli scenari (che contiene solo i promossi) ma il registro delle
    convenienze, che mette a verbale OGNI titolo guardato ogni giorno, promosso o scartato: è
    l'unico campione raccolto senza pregiudizio, ed è anche l'unico modo di misurare questo scenario
    a ritroso invece di aspettare mesi. Si prende la PRIMA giornata in cui un titolo supera la
    soglia d'ingresso in osservazione, e la resa che il registro ha già calcolato.

    ATTENZIONE ai limiti, che le schede devono dichiarare:
      · le rese sono a 5 e 21 giorni di BORSA, non a 7 e 30 di calendario come nella matrice;
      · di qualità c'è solo la convenienza (probabilità e affidabilità non sono in questo registro),
        quindi gli altri filtri non sono applicabili;
      · esiste solo il momento d'acquisto «all'ingresso in osservazione»: gli altri tre non hanno
        senso qui, perché nascono da passaggi che queste candidate non hanno mai fatto."""
    rec = load_registro_completo(CONV_LOG_NAME)
    if not isinstance(rec, list):
        return {"celle": {}, "casi": {}, "n_tot": 0, "n_casi": 0}
    sopra = [r for r in rec
             if r.get("kind") == kind and not r.get("bad_data")
             and (r.get("conv") or 0) >= _OBS_ENTRY_CONV and r.get("price")]
    primi = {}
    for r in sorted(sopra, key=lambda r: str(r.get("date") or "")):
        primi.setdefault(str(r.get("ticker") or "").upper(), r)      # la PRIMA volta, non l'ultima
    sel = [r for r in primi.values() if (r.get("conv") or 0) >= (min_conv or 0)]
    celle, casi, scartati = {}, {}, {}
    for sk, campo in _SENZA_OSS_SELLS.items():
        tutti = [{"ticker": r.get("ticker"), "date": _giorno_di(r), "conv": r.get("conv"),
                  "prezzo": r.get("price"), "reliab": None, "prob_gain": None, "prob_loss": None,
                  "data_acquisto": _giorno_di(r), "ret": float(r[campo])}
                 for r in sel if r.get(campo) is not None]
        # RAGGRUPPAMENTI DI AZIONI, non guadagni: in questo registro compaiono rese come +5.874% in
        # cinque giorni di Borsa e +30.817% in ventuno, che non sono movimenti di mercato ma cambi
        # del numero di azioni (un raggruppamento alza il prezzo, un frazionamento lo abbassa).
        # Bastano quattro righe così per portare la MEDIA da +1% a +30% e rendere il numero inutile.
        # Si escludono le code impossibili, con soglie dichiarate, e si CONTA quante sono: il
        # conteggio va mostrato, perché un'esclusione silenziosa fa sembrare completo un campione
        # che non lo è.
        punti = [p for p in tutti if -95.0 <= p["ret"] <= 300.0]
        scartati[f"osservazione|{sk}"] = len(tutti) - len(punti)
        if not punti:
            continue
        vals = sorted(p["ret"] for p in punti)
        n = len(vals)
        med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
        key = f"osservazione|{sk}"
        celle[key] = {"n": n, "avg": round(sum(vals) / n, 2),
                      "hit": round(100 * sum(1 for v in vals if v > 0) / n),
                      "med": round(med, 2), "best": round(vals[-1], 2), "worst": round(vals[0], 2)}
        casi[key] = sorted(punti, key=lambda p: str(p["date"]))
    return {"celle": celle, "casi": casi, "n_tot": len(primi), "n_casi": len(sel),
            "titoli": len(primi), "soglia_ingresso": _OBS_ENTRY_CONV,
            "scartati_estremi": scartati, "limiti_estremi": (-95.0, 300.0)}


def valori_momento(r, momento=None):
    """I numeri di qualità VERI del momento d'acquisto scelto: (affidabilità, salita, perdita,
    convenienza). Senza `momento` ritorna quelli della promozione, come si è sempre fatto.

    È il cuore della correzione di ago 2026: la matrice confronta quattro momenti d'acquisto, ma i
    filtri usavano SEMPRE i numeri del giorno della promozione. Filtrare la riga «compro quando
    entra in osservazione» con la probabilità di salita misurata alla promozione — cioè giorni dopo
    — significa selezionare con informazioni che quel giorno non esistevano, e ottenere un risultato
    che nessuna regola eseguibile avrebbe potuto dare.
    Se il momento richiesto non ha quel numero a verbale si ritorna None: la riga risulterà «senza
    dato» e, con quel filtro attivo, resterà fuori — invece di essere giudicata con i numeri
    sbagliati."""
    if momento:
        p = (r.get("passaggi") or {}).get(momento)
        if isinstance(p, dict):
            return p.get("reliab"), p.get("prob_gain"), p.get("prob_loss"), p.get("conv")
        if momento == "promozione":       # righe vecchie: in cima alla riga ci sono i suoi numeri
            return r.get("reliab"), r.get("prob_gain"), r.get("prob_loss"), r.get("conv")
        return None, None, None, None
    return r.get("reliab"), r.get("prob_gain"), r.get("prob_loss"), r.get("conv")


def _dato_mancante(r, min_pg=0, max_pl=100, min_conv=0, momento=None) -> bool:
    """True se un filtro ATTIVO non è applicabile a questa riga perché quel numero non è stato
    registrato (righe vecchie, o momento d'acquisto di cui non si conosce la qualità)."""
    _, pg, pl, cv = valori_momento(r, momento)
    return bool((min_pg > 0 and pg is None)
                or (max_pl < 100 and pl is None)
                or (min_conv > 0 and cv is None))


def _seleziona_scenari(kind, min_rel=0, min_pg=0, max_pl=100, min_conv=0, variante="reale",
                       momento=None):
    """Righe degli scenari di un tipo: (tutte, quelle che passano i filtri di qualità).
    Estratta da scenario_report per essere riusata dal calendario per periodi, senza duplicare la
    logica dei filtri (che è il punto dove è più facile che due viste si contraddicano).
    STORICO COMPLETO (archivio + vivo): il quadro non si accorcia mai col passare del tempo.

    ATTENZIONE, qui un dato MANCANTE ESCLUDE — al contrario delle sezioni vive, dove un dato non
    ancora registrato lascia passare la riga. Non è una svista: le due viste rispondono a domande
    diverse. Nel monitoraggio il filtro serve a non nascondere un'occasione appena arrivata che
    forse va bene; qui serve a rispondere a «e se avessi comprato SOLO le migliori?», e una riga di
    cui non si conosce la probabilità di salita non è nota per essere fra le migliori: contarla
    gonfierebbe il campione con casi che il filtro non ha mai giudicato. Con una soglia stretta
    (per esempio salita ≥ 60%) era la differenza fra 5 casi veri e 11 casi di cui 6 ignoti.
    Quante righe restano fuori per questo motivo lo dicono `scenario_report` e `scenari_calendario`
    nel campo `n_senza_dato`, così l'esclusione non è silenziosa."""
    tutte = [r for r in load_registro_completo(SCENARIO_LOG_NAME, load_scenario_log())
             if not r.get("bad_data") and r.get("kind") == kind
             and (variante == "senza_soglia" or r.get("promossa", True))]
    def _passa(r):
        rel, pg, pl, cv = valori_momento(r, momento)
        return (_rel_rank(rel) >= min_rel
                and (min_pg <= 0 or (pg is not None and pg >= min_pg))
                and (max_pl >= 100 or (pl is not None and pl <= max_pl))
                and (min_conv <= 0 or (cv is not None and cv >= min_conv)))

    sel = [r for r in tutte if _passa(r)]
    sel.sort(key=lambda r: str(r.get("date")))
    return tutte, sel


def _celle_da_righe(righe, kind):
    """Aggrega un insieme di righe nelle caselle acquisto|vendita: (celle, casi).
    Il numero principale è la MEDIANA, la media resta accanto: su campioni piccoli un solo caso
    estremo sposta la media di decine di punti e racconta una storia mai avvenuta."""
    # Il prezzo per azione DEL MOMENTO D'ACQUISTO di quella riga: serve a dire quando l'operazione
    # simulata è impossibile (un titolo da 1.256 $ non si compra con 30 €), cosa che l'app calcolava
    # in euro senza accorgersene su 34 righe su 70.
    _CAMPO_PREZZO = {"anticipo": "pre_price", "osservazione": "obs_price",
                     "promozione": "promo_price", "conferma": "conf_price"}
    celle, casi = {}, {}
    for bk in SCENARIO_BUYS_UI:
        for sk in SCENARIO_SELLS_PER_TIPO.get(kind, SCENARIO_SELLS_PER_TIPO["short"]):
            key = f"{bk}|{sk}"
            # I numeri di qualità mostrati sono quelli DEL MOMENTO D'ACQUISTO di questa riga della
            # matrice, non quelli della promozione: sotto «compro a inizio osservazione» si leggono
            # la convenienza e le probabilità di quando l'occasione è entrata in osservazione.
            punti = []
            for r in righe:
                if (r.get("res") or {}).get(key) is None:
                    continue
                _rel, _pg, _pl, _cv = valori_momento(r, bk)
                punti.append({"ticker": r.get("ticker"), "date": str(r.get("date"))[:10],
                              "reliab": _rel, "prob_gain": _pg, "prob_loss": _pl, "conv": _cv,
                              "prezzo": r.get(_CAMPO_PREZZO.get(bk, "promo_price")),
                              "data_acquisto": ((r.get("passaggi") or {}).get(bk) or {}).get("data"),
                              "ret": r["res"][key]})
            if not punti:
                continue
            vals = sorted(p["ret"] for p in punti)
            n = len(vals)
            med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
            celle[key] = {"n": n, "avg": round(sum(vals) / n, 2),
                          "hit": round(100 * sum(1 for v in vals if v > 0) / n),
                          "med": round(med, 2), "best": round(vals[-1], 2), "worst": round(vals[0], 2)}
            casi[key] = punti
    return celle, casi


def scenario_report(kind: str = "short", min_rel: int = 0, min_pg: int = 0,
                    max_pl: int = 100, min_conv: int = 0, variante: str = "reale",
                    momento: str = None) -> dict:
    """La «pagella» degli scenari per un tipo di occasione, con i filtri di qualità applicati al
    momento dell'ACQUISTO (affidabilità minima, probabilità di salita minima, rischio massimo,
    convenienza minima). Ritorna:
      {n_tot, n_casi, maturi, celle: {"acquisto|vendita": {n, avg, hit, med, best, worst}},
       casi: {"acquisto|vendita": [{ticker, date, reliab, prob_gain, prob_loss, conv, ret}, …]}}
    I «casi» sono in ordine di data: servono sia all'elenco di dettaglio sia al grafico cumulato.

    `variante` sceglie QUALI candidate entrano nel conto, senza cambiare nulla della matrice:
      "reale"        → solo le occasioni davvero promosse (comportamento di sempre);
      "senza_soglia" → anche quelle che avevano superato tutti i controlli TRANNE il rimbalzo minimo
                       del +2%, cioè la matrice «come se quella soglia non esistesse». Le righe delle
                       scartate hanno `promossa=False` e non hanno bersaglio, quindi la colonna «alla
                       soglia» resta popolata solo dalle promosse: il confronto onesto è sulle colonne
                       a 7 / 30 / 365 giorni.
    Le righe registrate prima di questa modifica non hanno il campo `promossa` e contano come promosse."""
    tutte, sel = _seleziona_scenari(kind, min_rel, min_pg, max_pl, min_conv, variante, momento)
    celle, casi = _celle_da_righe(sel, kind)
    return {"n_tot": len(tutte), "n_casi": len(sel), "celle": celle, "casi": casi,
            "variante": variante,
            "n_senza_dato": sum(1 for r in tutte
                               if _dato_mancante(r, min_pg, max_pl, min_conv, momento)),
            "n_scartate": sum(1 for r in tutte if r.get("promossa") is False),
            "n_totale_log": len([r for r in load_scenario_log() if not r.get("bad_data")])}


def scenari_attesa(kind: str = "short", min_rel: int = 0, min_pg: int = 0, max_pl: int = 100,
                   min_conv: int = 0, variante: str = "reale", momento: str = None) -> dict:
    """Per ogni casella della matrice: quante occasioni la stanno MATURANDO e quando compare la
    prima. Serve a non lasciare più scritto solo «nessun caso ancora maturo», che non distingue
    «manca un giorno» da «manca un anno» — e il dato per dirlo c'era già: data di ingresso più i
    giorni della colonna.

    Ritorna {"acquisto|vendita": {"attesa": n, "prima": "AAAA-MM-GG" | None, "mai": n}}.
    Le combinazioni escluse per costruzione non compaiono.

    ATTENZIONE alla differenza fra le due cose, che è il punto della funzione:
      · `attesa` = occasioni che matureranno, con la data della prima;
      · `mai`    = occasioni che NON matureranno mai per quella casella, perché non hanno il prezzo
                   di quel momento d'acquisto a verbale (per esempio il prezzo dell'ingresso in
                   «In anticipo» esiste solo su 41 righe su 70, e il prezzo «dopo i giorni di
                   verifica» solo su quelle abbastanza vecchie).
    Senza questa distinzione la casella scriveva «la prima il 4 agosto» — una data già passata, per
    occasioni che non arriveranno mai."""
    _, sel = _seleziona_scenari(kind, min_rel, min_pg, max_pl, min_conv, variante, momento)
    _CAMPO_PREZZO = {"anticipo": "pre_price", "osservazione": "obs_price",
                     "promozione": "promo_price", "conferma": "conf_price"}
    oggi = datetime.date.fromisoformat(_today_iso())
    out = {}
    for bk in SCENARIO_BUYS_UI:
        campo = _CAMPO_PREZZO.get(bk, "promo_price")
        for sk in SCENARIO_SELLS_PER_TIPO.get(kind, SCENARIO_SELLS_PER_TIPO["short"]):
            if (kind, bk, sk) in _SCENARI_ESCLUSI:
                continue
            key = f"{bk}|{sk}"
            gg = _SELL_DAYS.get(sk, 30)
            date_attesa, mai = [], 0
            for r in sel:
                if (r.get("res") or {}).get(key) is not None:
                    continue
                if not r.get(campo):
                    mai += 1                     # manca il prezzo d'acquisto: non si calcolerà mai
                    continue
                try:
                    d = datetime.date.fromisoformat(str(r.get("date"))[:10])
                except Exception:
                    continue
                scad = d + datetime.timedelta(days=gg)
                if scad >= oggi:
                    date_attesa.append(scad)
                else:
                    mai += 1                     # già scaduta e ancora vuota: non arriverà da sola
            out[key] = {"attesa": len(date_attesa),
                        "prima": min(date_attesa).isoformat() if date_attesa else None,
                        "mai": mai}
    return out


def universo_benchmark(kind: str = "short", orizzonte: str = "21g", dal=None, al=None) -> dict:
    """IL TERMINE DI CONFRONTO che mancava: «+4% rispetto a cosa?».

    Prende TUTTI i titoli che il sistema ha guardato nel periodo (il registro della convenienza
    contiene anche gli scartati, non solo i promossi: è l'unico campione raccolto senza pregiudizio) e
    dice come sono andati nello stesso orizzonte. Senza questo numero non si può sapere se la
    selezione aggiunge qualcosa: misurato una volta, le promozioni facevano +4,01% a 7 giorni contro
    +2,65% dei titoli semplicemente guardati, cioè +1,4 punti e la stessa percentuale di volte in
    positivo. È la differenza fra «il sistema funziona» e «il mercato saliva».

    Si usa la MEDIANA come numero principale: la media di questo registro è dominata da pochi casi
    estremi. Le righe marcate `bad_data` (frazionamenti) sono escluse."""
    campo = {"5g": "ret_5d", "7g": "ret_5d", "21g": "ret_21d", "30g": "ret_21d"}.get(orizzonte, "ret_21d")
    righe = [x for x in load_registro_completo(CONV_LOG_NAME)
             if x.get("kind") == kind and not x.get("bad_data") and x.get(campo) is not None]
    if dal:
        righe = [x for x in righe if _giorno_di(x) >= str(dal)[:10]]
    if al:
        righe = [x for x in righe if _giorno_di(x) <= str(al)[:10]]
    if not righe:
        return {"n": 0, "campo": campo}
    v = sorted(float(x[campo]) for x in righe)
    n = len(v)
    med = v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2
    giorni = {_giorno_di(x) for x in righe}
    return {"n": n, "giorni": len(giorni), "titoli": len({x.get("ticker") for x in righe}),
            "campo": campo, "orizzonte": orizzonte,
            "med": round(med, 2), "avg": round(sum(v) / n, 2),
            "hit": round(100 * sum(1 for x in v if x > 0) / n),
            "dal": min(giorni), "al": max(giorni)}


def resa_regole_sistema(importo: float = 30.0, fee: float = 1.0, kind: str = None) -> dict:
    """LA MISURA CHE MANCAVA: quanto avrebbe reso seguire il sistema ALLA LETTERA.

    Nessuno dei registri lo diceva. La scheda voti misura «quanto si è mosso il prezzo dopo la
    promozione» (e continua a seguire anche i titoli che il sistema ha già tolto, migliorando le
    perdite); la matrice degli scenari vende a 7 / 30 / 365 giorni o al bersaglio, cioè con regole che
    il sistema non applica. Lo stop e la regola «in perdita da troppi giorni» non erano MAI misurati,
    pur essendo le uniche due che agiscono davvero.

    Qui la strategia è quella eseguibile: compro alla promozione, vendo quando il sistema toglie
    l'occasione. Le posizioni ancora aperte si valutano al prezzo di oggi e sono contate a parte,
    perché una posizione aperta non è un risultato: è una scommessa in corso.
    Il netto in euro conta DUE commissioni (acquisto e vendita)."""
    chiuse, aperte = [], []
    for r in load_registro_completo(EXIT_HISTORY_NAME, load_exit_history()):
        p_in, p_out = r.get("first_price"), r.get("last_price")
        if not p_in or not p_out:
            continue
        ret = (float(p_out) / float(p_in) - 1) * 100
        if kind and (r.get("kind") or "short") != kind:
            continue        # il selettore Breve/Lungo vale anche qui
        chiuse.append({"ticker": r.get("ticker"), "kind": r.get("kind", "short"), "ret": ret,
                       "motivo": r.get("reason"), "dal": r.get("added"), "al": r.get("removed"),
                       "ingresso_certo": r.get("first_sicuro", None)})
    for tk, e in load_tracking().items():
        snaps = [s for s in (e.get("snapshots") or []) if s.get("price")]
        ing = _ingresso(e)
        if not (snaps and ing.get("price") and ing.get("sicuro")):
            continue
        if kind and (e.get("kind") or "short") != kind:
            continue
        aperte.append({"ticker": tk, "kind": e.get("kind", "short"),
                       "ret": (float(snaps[-1]["price"]) / float(ing["price"]) - 1) * 100,
                       "dal": e.get("added")})

    def _agg(items):
        if not items:
            return {"n": 0}
        v = sorted(x["ret"] for x in items)
        n = len(v)
        med = v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2
        netti = [net_eur(x, importo, fee) for x in v]
        return {"n": n, "med": round(med, 2), "avg": round(sum(v) / n, 2),
                "hit": round(100 * sum(1 for x in v if x > 0) / n),
                "netto_medio": round(sum(netti) / n, 2), "netto_totale": round(sum(netti), 2),
                "in_utile": sum(1 for x in netti if x > 0),
                "peggiore": round(v[0], 2), "migliore": round(v[-1], 2)}

    per_motivo = {}
    for x in chiuse:
        m = str(x.get("motivo") or "?")
        etichetta = ("sotto lo stop" if "stop" in m.lower() else
                     "in perdita da troppo" if "perdita" in m.lower() else
                     "crollo/delisting" if "crollo" in m.lower() else
                     "dati fermi" if "dati" in m.lower() else
                     "scelta tua" if "manuale" in m.lower() else m[:28])
        per_motivo.setdefault(etichetta, []).append(x)
    return {"importo": importo, "fee": fee, "pareggio_pct": round(pareggio_pct(importo, fee), 2),
            "chiuse": _agg(chiuse), "aperte": _agg(aperte),
            "per_motivo": {k: _agg(v) for k, v in sorted(per_motivo.items(),
                                                         key=lambda kv: -len(kv[1]))},
            "righe_chiuse": sorted(chiuse, key=lambda x: str(x.get("al") or ""), reverse=True)}


_LATI_OPERAZIONE = 2      # un'operazione completa paga la commissione DUE volte: comprare e vendere


_MESI_IT = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
            "agosto", "settembre", "ottobre", "novembre", "dicembre")


def _periodo_di(giorno: str, granularita: str = "settimana"):
    """(chiave ordinabile, etichetta leggibile, primo giorno, ultimo giorno) del periodo che contiene
    `giorno`. La settimana è quella ISO, da lunedì a domenica."""
    d = datetime.date.fromisoformat(str(giorno)[:10])
    if granularita == "mese":
        primo = d.replace(day=1)
        ultimo = (primo + datetime.timedelta(days=31)).replace(day=1) - datetime.timedelta(days=1)
        return f"{d.year:04d}-{d.month:02d}", f"{_MESI_IT[d.month - 1]} {d.year}", primo, ultimo
    anno, sett, _gg = d.isocalendar()
    primo = d - datetime.timedelta(days=d.weekday())
    ultimo = primo + datetime.timedelta(days=6)
    etichetta = (f"sett. {sett} · {primo.day} {_MESI_IT[primo.month - 1][:3]}"
                 f" – {ultimo.day} {_MESI_IT[ultimo.month - 1][:3]}")
    return f"{anno:04d}-W{sett:02d}", etichetta, primo, ultimo


def scenari_calendario(kind: str = "short", granularita: str = "settimana", min_rel: int = 0,
                       min_pg: int = 0, max_pl: int = 100, min_conv: int = 0,
                       variante: str = "reale", importo: float = 30.0, fee: float = 1.0,
                       momento: str = None) -> dict:
    """CALENDARIO DEGLI SCENARI: gli stessi risultati, ma divisi per periodo di tempo.

    A che serve: la matrice mette tutto insieme e risponde a «quale momento d'acquisto rende di
    più». Non risponde a «sta migliorando o peggiorando?», che è una domanda diversa e altrettanto
    importante: un sistema può avere una media buona costruita in una sola settimana fortunata.
    Qui ogni riga è un periodo, così l'andamento nel tempo si vede.

    I periodi sono quelli della PROMOZIONE (quando l'occasione è entrata), non della vendita: è la
    data che il registro conserva con certezza, e raggruppare per «coorti d'ingresso» è anche il
    modo corretto di confrontare periodi diversi. La resa di una coorte matura nei giorni dopo.

    Ritorna {granularita, periodi: [...]}, ogni periodo con chiave, etichetta, estremi, quante
    occasioni, e le caselle acquisto|vendita calcolate SOLO su quel periodo (con il netto in euro)."""
    # `momento`: i filtri usano i numeri del momento d'acquisto che si sta guardando, come nelle
    # sotto-sezioni della matrice. Senza, valgono quelli della promozione (comportamento di prima).
    _tutte, sel = _seleziona_scenari(kind, min_rel, min_pg, max_pl, min_conv, variante, momento)
    n_senza_dato = sum(1 for r in _tutte
                       if _dato_mancante(r, min_pg, max_pl, min_conv, momento))
    gruppi = {}
    for r in sel:
        g = str(r.get("date") or "")[:10]
        if not g:
            continue
        try:
            chiave, etichetta, primo, ultimo = _periodo_di(g, granularita)
        except Exception:
            continue
        gruppi.setdefault(chiave, {"chiave": chiave, "etichetta": etichetta,
                                   "dal": primo.isoformat(), "al": ultimo.isoformat(),
                                   "righe": []})["righe"].append(r)
    periodi = []
    for chiave in sorted(gruppi, reverse=True):          # dal più recente
        g = gruppi[chiave]
        celle, casi = _celle_da_righe(g["righe"], kind)
        for k, c in celle.items():
            # I netti si calcolano CASO PER CASO e poi si fa la media: «il netto della resa tipica»
            # e «la media dei netti» sono numeri diversi, perché la commissione è fissa e la tassa
            # colpisce solo i guadagni. Quello utile è il secondo — è ciò che ti resta in tasca a
            # operazione — ed è lo stesso che mostra la matrice, così le due viste non si
            # contraddicono sugli stessi dati.
            netti = [n for n in (net_eur(p["ret"], importo, fee) for p in casi[k]) if n is not None]
            c["netto_medio"] = round(sum(netti) / len(netti), 2) if netti else None
            c["netto_totale"] = round(sum(netti), 2)
            c["in_utile"] = sum(1 for n in netti if n > 0)
        periodi.append({"chiave": chiave, "etichetta": g["etichetta"], "dal": g["dal"],
                        "al": g["al"], "n_occasioni": len(g["righe"]),
                        "titoli": sorted({str(r.get("ticker")) for r in g["righe"]}),
                        "celle": celle, "casi": casi})
    return {"granularita": granularita, "kind": kind, "variante": variante,
            "importo": importo, "fee": fee, "pareggio_pct": round(pareggio_pct(importo, fee), 2),
            "n_senza_dato": n_senza_dato,
            "periodi": periodi, "n_periodi": len(periodi)}


def scenari_perche_vuoto(kind: str = "short", min_rel: int = 0, min_pg: int = 0,
                         max_pl: int = 100, min_conv: int = 0, variante: str = "reale") -> dict:
    """Quando la matrice degli scenari e' vuota, dice PERCHE': i filtri o il tempo.

    Serve perche' il messaggio di prima dava sempre la colpa al tempo («nessun risultato maturo»)
    anche quando la causa erano i filtri, e non c'era modo di capirlo dall'interno dell'app. Con
    «Solo le migliori» accade davvero: chiedere una probabilita' di salita >= 60% quando quel numero
    ha mediana 52 e massimo 85 lascia fuori quasi tutto, e combinato con «affidabilita' Alta» non
    resta niente.

    Prova a togliere una condizione alla volta: se togliendone UNA la tabella si ripopola, quella e'
    la condizione che blocca. Ritorna {causa, testo, vincoli, n_senza_filtri, distribuzione}."""
    pieno = scenario_report(kind, 0, 0, 100, 0, variante)
    if not pieno["celle"]:
        return {"causa": "tempo", "vincoli": [], "n_senza_filtri": pieno["n_casi"],
                "distribuzione": {},
                "testo": (f"Non dipende dai filtri: per questo tipo non c'è ancora **nessun** "
                          f"risultato maturo, nemmeno senza filtri "
                          f"({pieno['n_casi']} occasioni registrate, in attesa che passino i giorni).")}
    # i filtri c'entrano: quale condizione blocca?
    prove = (("affidabilità minima", (0, min_pg, max_pl, min_conv)),
             ("probabilità di salita minima", (min_rel, 0, max_pl, min_conv)),
             ("rischio di perdita massimo", (min_rel, min_pg, 100, min_conv)),
             ("convenienza minima", (min_rel, min_pg, max_pl, 0)))
    vincoli = []
    for nome, (a, b, c, d) in prove:
        if scenario_report(kind, a, b, c, d, variante)["celle"]:
            vincoli.append(nome)
    # com'e' distribuito, nella realta', cio' che i filtri chiedono
    righe = [r for r in load_registro_completo(SCENARIO_LOG_NAME, load_scenario_log())
             if not r.get("bad_data") and r.get("kind") == kind
             and (variante == "senza_soglia" or r.get("promossa", True))]
    dist = {}
    for campo in ("prob_gain", "prob_loss", "conv"):
        v = sorted(r[campo] for r in righe if r.get(campo) is not None)
        if v:
            dist[campo] = {"n": len(v), "min": v[0], "max": v[-1],
                           "med": v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2}
    alte = sum(1 for r in righe if _rel_rank(r.get("reliab")) >= 2)
    dist["affidabilita_alta"] = {"n": alte, "su": len(righe)}
    if vincoli:
        quali = ", ".join(f"**{v}**" for v in vincoli)
        testo = (f"Sono i **filtri**, non il tempo: senza filtri ci sarebbero "
                 f"**{pieno['n_casi']}** casi. Basta allentare {quali} per rivedere i dati.")
    else:
        testo = (f"Sono i filtri **combinati**: ognuno da solo lascerebbe passare qualcosa, ma tutti "
                 f"insieme no. Senza filtri ci sarebbero **{pieno['n_casi']}** casi.")
    return {"causa": "filtri", "vincoli": vincoli, "n_senza_filtri": pieno["n_casi"],
            "distribuzione": dist, "testo": testo}


def _promozioni_per_titolo() -> dict:
    """{(kind, TICKER): [date di TUTTE le promozioni]} dal registro delle promozioni.
    Serve a sapere se una candidata vista in «In anticipo» è poi stata promossa o no. Si tengono
    tutte le date, non solo la prima: un titolo può essere promosso, tolto e ripromosso più tardi,
    e guardando solo la prima volta la seconda candidatura risulterebbe «mai promossa»."""
    out = {}
    for r in load_registro_completo(TRACK_RECORD_NAME, load_track_record()):
        chiave = (r.get("kind"), str(r.get("ticker") or "").upper())
        giorno = str(r.get("date") or "")[:10]
        if not chiave[1] or not giorno:
            continue
        out.setdefault(chiave, []).append(giorno)
    return {k: sorted(v) for k, v in out.items()}


def _gruppo_anticipo(righe, campo, importo, fee) -> dict:
    """Statistiche di un insieme di candidate su un orizzonte: caso tipico, media, quante in
    positivo e il risultato in EURO calcolato caso per caso (non sul rendimento medio)."""
    vals = [float(r[campo]) for r in righe if r.get(campo) is not None]
    if not vals:
        return {"n": 0}
    v = sorted(vals)
    n = len(v)
    med = v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2
    netti = [n_ for n_ in (net_eur(x, importo, fee) for x in vals) if n_ is not None]
    return {"n": n, "med": round(med, 2), "avg": round(sum(vals) / n, 2),
            "hit": round(100 * sum(1 for x in vals if x > 0) / n),
            "best": round(v[-1], 2), "worst": round(v[0], 2),
            "netto_medio": round(sum(netti) / len(netti), 2) if netti else None,
            "netto_totale": round(sum(netti), 2),
            "in_utile": sum(1 for x in netti if x > 0)}


def scenari_anticipo(kind: str = "short", min_pg: int = 0, max_pl: int = 100, min_conv: int = 0,
                     importo: float = 30.0, fee: float = 1.0) -> dict:
    """«E se comprassi appena un'occasione entra in «In anticipo»?» — la versione ESEGUIBILE.

    A che serve, e perché non basta la riga «All'ingresso in In anticipo» della matrice: quella riga
    contiene **solo le candidate che poi sono state promosse**, perché gli scenari nascono alla
    promozione. È una selezione fatta col senno del poi: il giorno in cui una candidata entra in
    «In anticipo» non sai quali saranno promosse, quindi quel risultato non era ottenibile.

    Qui si parte dall'altro capo: si prendono **tutte** le candidate registrate quando sono entrate
    in «In anticipo» — il prezzo di quel giorno è già a verbale nel registro dei pre-segnali — e si
    guarda come sono andate dopo 1 settimana e dopo 1 mese, **comprese quelle mai promosse**. È la
    strategia che avresti potuto eseguire davvero: compro tutto quello che compare lì.

    Le due parti si mostrano anche separate («poi promosse» / «mai promosse»), perché la differenza
    fra le due È la distorsione che la matrice non può evitare.

    La vendita «alla soglia» non c'è: bersaglio e stop li calcola la promozione, quindi per le
    candidate mai promosse non esistono. Restano i due orizzonti a giorni fissi, che sono anche
    quelli che si confrontano meglio.

    I filtri di qualità valgono solo per le righe che hanno quei numeri: sono registrati dal
    momento in cui questa funzione è nata (vedi `record_presignals`), quindi all'inizio `filtrabili`
    è 0 e con un filtro attivo non passa nessuno — detto esplicitamente invece di far sembrare che
    non ci siano dati."""
    righe = [r for r in load_registro_completo(PRESIGNAL_NAME, load_presignal_log())
             if r.get("kind") == kind and not r.get("bad_data") and r.get("price")]
    prom = _promozioni_per_titolo()
    # copertura per campo: la probabilità di salita e il rischio si registrano solo dalle candidate
    # nuove, quindi all'inizio quei due contatori sono a zero e i filtri corrispondenti non possono
    # lasciar passare niente. La convenienza invece c'è da sempre.
    copertura = {c: sum(1 for r in righe if r.get(c) is not None)
                 for c in ("prob_gain", "prob_loss", "conv")}
    attivi = bool(min_pg > 0 or max_pl < 100 or min_conv > 0)
    sel, scartate_senza_dato = [], 0
    for r in righe:
        if attivi and _dato_mancante(r, min_pg, max_pl, min_conv):
            scartate_senza_dato += 1
            continue
        if attivi and not ((min_pg <= 0 or (r.get("prob_gain") is not None and r["prob_gain"] >= min_pg))
                           and (max_pl >= 100 or (r.get("prob_loss") is not None and r["prob_loss"] <= max_pl))
                           and (min_conv <= 0 or (r.get("conv") is not None and r["conv"] >= min_conv))):
            continue
        giorno = str(r.get("date"))[:10]
        dopo = [d for d in prom.get((r.get("kind"), str(r.get("ticker") or "").upper()), [])
                if d >= giorno]
        sel.append(dict(r, date=giorno, promossa=bool(dopo),
                        data_promozione=(dopo[0] if dopo else None)))
    sel.sort(key=lambda r: str(r.get("date")))
    gruppi = {"tutte": sel,
              "poi_promosse": [r for r in sel if r["promossa"]],
              "mai_promosse": [r for r in sel if not r["promossa"]]}
    orizzonti = {"7g": "ret_7d", "30g": "ret_30d"}
    celle = {nome: {g: _gruppo_anticipo(righe_g, campo, importo, fee)
                    for g, righe_g in gruppi.items()}
             for nome, campo in orizzonti.items()}
    return {"kind": kind, "n": len(sel), "n_registrate": len(righe),
            "n_senza_dato": scartate_senza_dato, "copertura": copertura,
            "filtri_attivi": attivi,
            "celle": celle, "casi": gruppi,
            "importo": importo, "fee": fee,
            "pareggio_pct": round(pareggio_pct(importo, fee), 2),
            "dal": (sel[0]["date"] if sel else None), "al": (sel[-1]["date"] if sel else None)}


# ---------------------------------------------------------------------------
# QUALI INDICATORI FUNZIONANO DAVVERO — la domanda «è più corretta l'affidabilità
# o la convenienza?» misurata sui dati, non risolta per opinione.
# ---------------------------------------------------------------------------
# ATTENZIONE, differenza concettuale che l'app non diceva da nessuna parte:
#   * AFFIDABILITÀ non giudica l'occasione, giudica il DATO. Deriva solo da due cose
#     (vedi _reliab_label): la volatilità annua del titolo e quante giornate di storico
#     esistono. Alta = vol <= 35% e >= 180 giornate. Non guarda il prezzo, l'azienda, i
#     conti, né quanto potrebbe salire. Serve a sapere quanto fidarsi degli altri numeri,
#     e per costruzione premia i titoli TRANQUILLI: usarla come filtro d'acquisto scarta
#     i titoli che si muovono, non quelli che perdono.
#   * CONVENIENZA, PROBABILITÀ DI SALITA e RISCHIO DI PERDITA sono invece stime
#     sull'ESITO. Fra l'altro la convenienza CONTIENE GIÀ l'affidabilità in forma
#     continua (_reliab_factor smorza il punteggio verso 50 quando la stima è incerta):
#     filtrare per entrambe conta due volte la stessa cosa.
# Non essendo la stessa unità di misura, non si possono ordinare per «correttezza». Si può
# solo misurare quale, di fatto, ha separato i risultati: è quello che fa questa funzione.
_INDICATORI = (
    ("reliab", "Affidabilità", "ordinale",
     "Non giudica l'occasione ma il dato: volatilità del titolo e lunghezza dello storico."),
    ("conv", "Convenienza", "numerico",
     "Il punteggio 0-100 del sistema. Contiene già l'affidabilità in forma continua."),
    ("prob_gain", "Probabilità di salita", "numerico",
     "Probabilità stimata che il prezzo sia più alto alla scadenza."),
    ("prob_loss", "Rischio di perdita", "numerico",
     "Probabilità stimata di una perdita oltre il 15%."),
)
_IND_PERMUTAZIONI = 2000     # bastano per un p-value a due cifre; deterministico (seme fisso)


def _p_permutazione(xs, ys, alto, basso, n_perm: int = _IND_PERMUTAZIONI, seed: int = 20260819):
    """Quanto spesso IL CASO produce una differenza fra fasce grande come quella osservata.

    Serve perché su poche decine di casi due fasce hanno quasi sempre mediane diverse: senza
    questo numero qualunque differenza sembra una scoperta. Si rimescolano le rese fra le fasce
    (le fasce restano identiche) e si conta. Seme fisso: lo stesso dato dà sempre lo stesso
    p-value, altrimenti la stessa schermata cambierebbe verdetto a ogni ricarica."""
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    m_hi, m_lo = xs >= alto, xs <= basso
    if m_hi.sum() < 3 or m_lo.sum() < 3:
        return None, None
    oss = float(np.median(ys[m_hi]) - np.median(ys[m_lo]))
    rng = np.random.default_rng(seed)
    conta = 0
    for _ in range(int(n_perm)):
        p = rng.permutation(ys)
        if abs(float(np.median(p[m_hi]) - np.median(p[m_lo]))) >= abs(oss) - 1e-12:
            conta += 1
    return round(oss, 2), round(conta / float(n_perm), 3)


def indicatori_report(kind: str = "short", combo: str = None, variante: str = "reale") -> dict:
    """I quattro indicatori di qualità messi alla prova sullo stesso campione: quale ha davvero
    separato le occasioni andate bene da quelle andate male?

    NB: si misura su TUTTE le occasioni del tipo, **senza** applicare i filtri di qualità. Se si
    filtrasse prima, si toglierebbe proprio la parte di scala su cui la differenza va cercata (con
    «affidabilità almeno Media» non si può più misurare se la Bassa rende meno).

    Per ogni indicatore: numero di casi con il dato, correlazione di rango DENTRO LA GIORNATA
    (confronto fra titoli dello stesso giorno: mescolando i giorni si misurerebbe il mercato, non
    l'indicatore), le fasce con resa tipica e quante volte in positivo, la differenza fra fascia
    alta e bassa e il p-value di permutazione.

    Ritorna {combo, n, giornate, indicatori: [...], verdetto, abbastanza}."""
    tutte, _sel = _seleziona_scenari(kind, 0, 0, 100, 0, variante)
    # Solo le caselle che la matrice mostra davvero. In particolare NON «a inizio osservazione»:
    # quel prezzo viene registrato soltanto per i titoli poi promossi, quindi in quella colonna non
    # può esistere un caso partito male — misurare un indicatore lì darebbe numeri gonfiati.
    visibili = {f"{bk}|{sk}" for bk in SCENARIO_BUYS_UI
                for sk in SCENARIO_SELLS_PER_TIPO.get(kind, SCENARIO_SELLS_PER_TIPO["short"])}
    per_combo = {}
    for r in tutte:
        for k, v in (r.get("res") or {}).items():
            if v is not None and k in visibili:
                per_combo.setdefault(k, []).append(r)
    if not per_combo:
        return {"combo": None, "n": 0, "giornate": 0, "indicatori": [], "abbastanza": False,
                "combo_disponibili": [], "kind": kind, "variante": variante,
                "verdetto": "Nessun risultato ancora maturo: non c'è niente da misurare."}
    if combo not in per_combo:
        # per difetto la casella con più casi; a pari casi vince quella che il sistema esegue
        # davvero (comprare alla promozione), non un momento d'acquisto ipotetico.
        combo = max(per_combo, key=lambda k: (len(per_combo[k]), k.startswith("promozione")))
    righe = per_combo[combo]
    giorni = sorted({str(r.get("date"))[:10] for r in righe})
    out = []
    for campo, nome, tipo, spiega in _INDICATORI:
        if campo == "reliab":
            dati = [(_rel_rank(r.get("reliab")), r["res"][combo], str(r.get("date"))[:10])
                    for r in righe if r.get("reliab")]
        else:
            dati = [(float(r[campo]), r["res"][combo], str(r.get("date"))[:10])
                    for r in righe if r.get(campo) is not None]
        voce = {"campo": campo, "nome": nome, "spiega": spiega, "n": len(dati),
                "ic": None, "giornate_ic": 0, "fasce": [], "delta": None, "p": None,
                "verdetto": "", "utile": None}
        if len(dati) < 10:
            voce["verdetto"] = f"Solo {len(dati)} casi con questo dato: non misurabile."
            out.append(voce)
            continue
        xs = np.array([d[0] for d in dati], float)
        ys = np.array([d[1] for d in dati], float)
        # --- correlazione di rango dentro la giornata (media sulle giornate utili) ---
        per_g = {}
        for x, y, g in dati:
            per_g.setdefault(g, []).append((x, y))
        ics = []
        for g, gg in per_g.items():
            if len(gg) < 4:
                continue
            ax = np.array([q[0] for q in gg], float)
            ay = np.array([q[1] for q in gg], float)
            if len(set(ax.tolist())) < 2:
                continue
            rx = np.argsort(np.argsort(ax)).astype(float)
            ry = np.argsort(np.argsort(ay)).astype(float)
            c = float(np.corrcoef(rx, ry)[0, 1])
            if np.isfinite(c):
                ics.append(c)
        if ics:
            voce["ic"] = round(float(np.mean(ics)), 3)
            voce["giornate_ic"] = len(ics)
        # --- fasce: i 3 livelli per l'affidabilità, i terzili per gli altri ---
        if tipo == "ordinale":
            gruppi = [(et, ys[xs == lv]) for lv, et in ((0, "🔴 Bassa"), (1, "🟡 Media"), (2, "🟢 Alta"))]
            basso, alto = 0.0, 2.0
        else:
            q1, q2 = (float(x) for x in np.quantile(xs, [1 / 3.0, 2 / 3.0]))
            gruppi = [(f"basso (≤{q1:.0f})", ys[xs <= q1]),
                      (f"medio ({q1:.0f}–{q2:.0f})", ys[(xs > q1) & (xs <= q2)]),
                      (f"alto (>{q2:.0f})", ys[xs > q2])]
            basso, alto = q1, q2 + 1e-9
        for et, yy in gruppi:
            if not len(yy):
                voce["fasce"].append({"fascia": et, "n": 0, "med": None, "hit": None})
                continue
            vv = sorted(float(v) for v in yy)
            n = len(vv)
            med = vv[n // 2] if n % 2 else (vv[n // 2 - 1] + vv[n // 2]) / 2
            voce["fasce"].append({"fascia": et, "n": n, "med": round(med, 2),
                                  "hit": round(100 * sum(1 for v in vv if v > 0) / n)})
        delta, p = _p_permutazione(xs, ys, alto, basso)
        voce["delta"], voce["p"] = delta, p
        # «alto è meglio» per tutti tranne il rischio di perdita, dove alto è peggio
        atteso = -1 if campo == "prob_loss" else +1
        if p is None:
            voce["verdetto"] = "Fasce troppo piccole per un confronto."
        elif p >= 0.05:
            voce["utile"] = False
            voce["verdetto"] = (f"Nessuna differenza affidabile: fra fascia alta e bassa ci sono "
                                f"{delta:+.2f} punti, ma il caso fa altrettanto {p * 100:.0f} "
                                f"volte su 100.")
        elif (delta or 0) * atteso > 0:
            voce["utile"] = True
            voce["verdetto"] = (f"Funziona nel verso giusto: {abs(delta):.2f} punti di differenza "
                                f"fra le fasce (il caso lo farebbe {p * 100:.1f} volte su 100).")
        else:
            voce["utile"] = False
            voce["verdetto"] = (f"⚠️ Funziona AL CONTRARIO: la fascia che dovrebbe rendere di più "
                                f"rende {delta:+.2f} punti (il caso lo farebbe {p * 100:.1f} volte "
                                f"su 100). Da rivedere, non da usare come filtro.")
        out.append(voce)
    buoni = [v["nome"] for v in out if v["utile"] is True]
    rovesci = [v["nome"] for v in out if v["utile"] is False and (v["p"] or 1) < 0.05]
    abbastanza = len(righe) >= 30 and len(giorni) >= 20
    if buoni:
        verdetto = ("Separano i risultati in modo non casuale: **" + "**, **".join(buoni) + "**."
                    + (" Al contrario invece: **" + "**, **".join(rovesci) + "**." if rovesci else ""))
    else:
        verdetto = (f"**Nessuno dei quattro separa i risultati** su questo campione "
                    f"({len(righe)} casi in {len(giorni)} giornate). Non vuol dire che siano "
                    f"inutili: vuol dire che con questi numeri non si può ancora dirlo, e che "
                    f"scegliere in base a uno di essi è, per ora, un atto di fiducia.")
    return {"combo": combo, "n": len(righe), "giornate": len(giorni), "kind": kind,
            "variante": variante,
            "combo_disponibili": sorted(per_combo, key=lambda k: -len(per_combo[k])),
            "indicatori": out, "verdetto": verdetto, "abbastanza": abbastanza}


def net_eur(ret_pct, importo: float = 30.0, fee: float = 1.0, tax=None, lati: int = _LATI_OPERAZIONE):
    """Guadagno NETTO in euro di un'operazione completa: lordo − commissioni − 26% sulla plusvalenza.
    È il numero che dice se l'operazione conviene DAVVERO: con importi piccoli la commissione fissa
    può mangiarsi un rendimento positivo.

    ATTENZIONE, correzione di ago 2026: `fee` è la commissione di UNA operazione (un ordine), e
    un'andata e ritorno ne paga DUE (`lati`). Prima se ne contava una sola, quindi ogni «guadagno
    netto» mostrato era ottimista di circa un euro e il punto di pareggio sembrava la metà di quello
    vero: con 30 € e 1 € di commissione il pareggio non è +3,3% ma +6,7%.
    (`tax` si risolve a runtime: CAPITAL_GAINS_TAX è definita più in basso nel file.)"""
    if ret_pct is None:
        return None
    t = CAPITAL_GAINS_TAX if tax is None else tax
    g = float(importo) * float(ret_pct) / 100.0
    costo = float(fee) * int(lati)
    return round(g - costo - t * max(g - costo, 0.0), 2)


def pareggio_pct(importo: float = 30.0, fee: float = 1.0, lati: int = _LATI_OPERAZIONE) -> float:
    """Rendimento LORDO minimo perché un'operazione non perda soldi: copre solo le commissioni
    (sotto quella soglia non c'è plusvalenza, quindi la tassa non entra). Da mostrare accanto a
    qualunque media di rendimento: senza questo numero un +2% sembra un guadagno e non lo è."""
    if not importo:
        return float("inf")
    return float(fee) * int(lati) / float(importo) * 100.0


# ---------------------------------------------------------------------------
# PRE-SEGNALE — affidabilità misurata nel tempo. Ogni giorno il job registra le candidate
# "più solide" ancora in osservazione (stessi criteri della sezione «In anticipo») e, dopo
# 7 e 30 giorni, ne verifica l'esito reale: così anche il pre-segnale ha la sua scheda voti.
# ---------------------------------------------------------------------------
PRESIGNAL_NAME = "presignal_log.json"
_PRESIGNAL_MAX = _PRESIGNAL_MAX_LIVE    # tetto del file VIVO; l'eccedenza va in archivio
_PRE_MIN_CONV = 65        # convenienza minima per dire "solida" (l'osservazione parte da 60)
_PRE_MIN_DAYS = 1         # almeno 2 giorni di osservazione (via il rumore delle appena entrate)


def solid_presignals() -> list:
    """Le occasioni in osservazione considerate PIÙ SOLIDE dal pre-segnale: convenienza ≥65,
    tendenza della convenienza non in calo, almeno 2 giorni di osservazione; escluse quelle già
    seguite o in cooldown. Ordinate: prima il breve poi il lungo, dentro il gruppo per convenienza.
    Usata sia dalla sezione «In anticipo» sia dal registro di affidabilità (stessi criteri)."""
    tracked = load_tracking()
    cooldown = _load_exit_cooldown()
    out = []
    for s in observation_status():
        tk = s.get("ticker")
        if not tk or tk in tracked or _in_exit_cooldown(tk, cooldown):
            continue
        if (s.get("last_conv") or 0) >= _PRE_MIN_CONV and (s.get("dconv") or 0) >= 0 \
                and (s.get("days") or 0) >= _PRE_MIN_DAYS:
            out.append(s)
    out.sort(key=lambda s: (0 if s.get("kind") == "short" else 1, -(s.get("last_conv") or 0)))
    return out


def load_presignal_log() -> list:
    data = read_data_json(PRESIGNAL_NAME, [])
    return data if isinstance(data, list) else []


def record_presignals() -> list:
    """Registra i NUOVI pre-segnali solidi di oggi (prezzo e convenienza del momento), per poterne
    misurare l'esito. Dedup: uno stesso kind:ticker non viene ri-registrato entro 30 giorni."""
    solid = solid_presignals()
    if not solid:
        return []
    rows = load_presignal_log()
    today = _today_iso()
    # DIZIONARIO, non insieme: serve la RIGA, non solo la chiave, perché una riga già registrata
    # negli ultimi 30 giorni va COMPLETATA se le mancano i numeri di qualità, non solo saltata.
    # Prima c'era un salto secco: le 125 righe esistenti non avevano le probabilità e non le
    # avrebbero mai avute, e con esse restavano senza campione tutte le occasioni che nascono da
    # quelle righe (19 candidate erano in quello stato).
    recenti = {}
    for r in rows:
        d = _days_between(r.get("date"), today)
        if d is not None and 0 <= d <= 30:
            recenti[f"{r.get('kind')}:{r.get('ticker')}"] = r
    added, completate = [], 0
    for s in solid:
        key = f"{s.get('kind')}:{s.get('ticker')}"
        # FOTOGRAFIA COERENTE: tutti i campi dallo STESSO punto di osservazione. Prendere il prezzo
        # dall'ultimo punto e la qualità dall'ultimo punto che ce l'ha mette a verbale un istante
        # mai esistito.
        p = s.get("punto_completo") or {}
        data_p = str(p.get("date") or today)[:16]
        prezzo_p = p.get("price") if p.get("price") is not None else s.get("last_price")
        conv_p = p.get("conv") if p.get("conv") is not None else s.get("last_conv")
        pg_p = p.get("prob_gain") if p.get("prob_gain") is not None else s.get("prob_gain")
        pl_p = p.get("prob_loss") if p.get("prob_loss") is not None else s.get("prob_loss")
        rel_p = p.get("reliab") or s.get("reliab")
        vecchia = recenti.get(key)
        if vecchia is not None:
            # già a verbale: completa SOLO i campi mancanti, e con i valori del punto ALLA SUA DATA,
            # non di oggi — riempirla con i numeri di adesso sarebbe rifare l'errore di datare un
            # momento con la fotografia di un altro giorno.
            p_sua = _punto_osservazione_alla_data(s.get("ticker"), s.get("kind"), vecchia.get("date"))
            toccata = False
            for campo, valore in (("reliab", (p_sua or {}).get("reliab")),
                                  ("prob_gain", (p_sua or {}).get("prob_gain")),
                                  ("prob_loss", (p_sua or {}).get("prob_loss"))):
                if vecchia.get(campo) is None and valore is not None:
                    vecchia[campo] = valore
                    toccata = True
            if toccata:
                completate += 1
            continue
        if not prezzo_p:
            continue
        rows.append({"ticker": s["ticker"], "kind": s.get("kind", "short"), "date": today,
                     "data_valori": data_p,      # l'istante da cui vengono TUTTI i numeri qui sotto
                     "price": prezzo_p, "conv": conv_p,
                     # QUALITÀ DEL SEGNALE NEL MOMENTO DELL'INGRESSO in «In anticipo». Prima non si
                     # registrava, e mancava per una ragione precisa: gli scenari nascevano solo
                     # alla promozione, quindi i filtri usavano i numeri di QUEL giorno — cioè
                     # informazioni che al momento dell'acquisto anticipato non erano disponibili.
                     # Registrandoli qui, lo scenario «compro appena entra in In anticipo» diventa
                     # filtrabile con quello che si sapeva davvero quel giorno.
                     "reliab": rel_p, "prob_gain": pg_p, "prob_loss": pl_p,
                     "ret_7d": None, "ret_30d": None})
        added.append(s["ticker"])
        registra_evento(s.get("kind", "short"), s["ticker"], "ingresso_anticipo",
                        valori={"data": data_p, "prezzo": prezzo_p, "conv": conv_p,
                                "prob_gain": pg_p, "prob_loss": pl_p, "reliab": rel_p,
                                "fonte": "osservazione"},
                        note="pre-segnale diventato solido")
    if added or completate:
        salva_registro(PRESIGNAL_NAME, rows, _PRESIGNAL_MAX, giorni_protetti=60)
    return added


def resolve_presignals() -> int:
    """Verifica i pre-segnali maturi: fissa ret_7d/ret_30d (giorni di calendario) dal prezzo di
    registrazione. Guardia anti-split come per gli scenari. Ritorna quanti campi ha risolto."""
    rows = load_presignal_log()
    if not rows:
        return 0
    today = datetime.date.fromisoformat(_today_iso())
    changed = 0
    for r in rows:
        if r.get("bad_data"):
            continue
        try:
            d0 = datetime.date.fromisoformat(str(r.get("date"))[:10])
        except Exception:
            continue
        age = (today - d0).days
        if not ((age >= 7 and r.get("ret_7d") is None) or (age >= 30 and r.get("ret_30d") is None)):
            continue
        base = r.get("price")
        if not base or age > 120:
            r["bad_data"] = True
            changed += 1
            continue
        try:
            closes = get_history(r["ticker"], period="6mo")["Close"].dropna()
            try:
                closes.index = closes.index.tz_localize(None)
            except (TypeError, AttributeError):
                pass
        except Exception:
            continue
        after = closes[closes.index > pd.Timestamp(d0)]
        if after.empty:
            continue
        if abs(float(after.iloc[0]) / float(base) - 1) > 0.25:   # split/raggruppamento
            r["bad_data"] = True
            changed += 1
            continue
        for h, fld in ((7, "ret_7d"), (30, "ret_30d")):
            if r.get(fld) is None and age >= h:
                s = closes[closes.index >= pd.Timestamp(d0 + datetime.timedelta(days=h))]
                if not s.empty:
                    r[fld] = round((float(s.iloc[0]) / float(base) - 1) * 100, 2)
                    changed += 1
    if changed:
        salva_registro(PRESIGNAL_NAME, rows, _PRESIGNAL_MAX, giorni_protetti=60)
    return changed


def presignal_stats() -> dict:
    """Affidabilità del pre-segnale finora: per tipo → esito medio e % positivi a 7 e 30 giorni."""
    rows = [r for r in load_registro_completo(PRESIGNAL_NAME, load_presignal_log())
            if not r.get("bad_data")]          # archivio + vivo: statistica su TUTTO lo storico
    out = {"n_rows": len(rows)}
    for kind in ("short", "long"):
        sel = [r for r in rows if r.get("kind") == kind]
        k = {}
        for fld, lab in (("ret_7d", "d7"), ("ret_30d", "d30")):
            vals = [r[fld] for r in sel if r.get(fld) is not None]
            if vals:
                k[lab] = {"n": len(vals), "avg": round(sum(vals) / len(vals), 2),
                          "hit": round(100 * sum(1 for v in vals if v > 0) / len(vals))}
        out[kind] = k
    return out


def track_record_calibration() -> dict:      # NB: legge lo storico completo (archivio + vivo)
    """Calibrazione ONESTA e in avanti del punteggio: resa reale delle promozioni divisa per
    FASCIA di convenienza (alta/media/bassa al momento della promozione). Risponde a:
    'la convenienza alta rende davvero più della bassa?'. Ritorna fasce + un verdetto."""
    records = load_registro_completo(TRACK_RECORD_NAME, load_track_record())
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


# --- Valute: i titoli quotano in valute diverse (EUR/USD/GBP…). Per un totale di portafoglio
# corretto convertiamo tutto in EUR (valuta base). ---
_CCY_BY_SUFFIX = {
    ".MI": "EUR", ".PA": "EUR", ".DE": "EUR", ".F": "EUR", ".MU": "EUR", ".AS": "EUR",
    ".MC": "EUR", ".BR": "EUR", ".LS": "EUR", ".VI": "EUR", ".HE": "EUR", ".IR": "EUR",
    ".SW": "CHF", ".L": "GBP", ".TO": "CAD", ".HK": "HKD", ".T": "JPY", ".AX": "AUD",
    ".ST": "SEK", ".OL": "NOK", ".CO": "DKK",
}


def ticker_currency(ticker, info=None) -> str:
    """Valuta di quotazione: dal suffisso della borsa (.MI→EUR, .SW→CHF…), poi da info, poi USD."""
    t = (ticker or "").upper()
    for suf, ccy in _CCY_BY_SUFFIX.items():
        if t.endswith(suf):
            return ccy
    if info and info.get("currency"):
        return str(info["currency"]).upper()
    return "USD"


@st.cache_data(ttl=3600, show_spinner=False)
def fx_to_eur(ccy: str):
    """Moltiplicatore per convertire un importo da `ccy` a EUR (valuta base). 1.0 per EUR;
    None se il cambio non è disponibile. NB: i titoli di Londra (.L) quotano spesso in pence (GBp):
    quei valori vanno verificati a mano."""
    ccy = (ccy or "EUR").upper()
    if ccy in ("EUR", ""):
        return 1.0
    for sym, invert in ((f"{ccy}EUR=X", False), (f"EUR{ccy}=X", True)):
        try:
            h = get_history(sym, "5d")
            if not h.empty:
                v = float(h["Close"].dropna().iloc[-1])
                if v > 0:
                    return (1.0 / v) if invert else v
        except Exception:
            pass
    return None


def load_portfolio() -> list:
    data = read_data_json(PORTFOLIO_NAME, [])
    return data if isinstance(data, list) else []


def save_portfolio(positions: list, force: bool = False) -> None:
    """Salva le posizioni. `force=True` solo da chi ha appena TOLTO una posizione: è l'unico caso in
    cui l'elenco può legittimamente accorciarsi molto o svuotarsi (vedi _crollo_stato)."""
    write_data_json(PORTFOLIO_NAME, positions, force=force)


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
    """Registra un acquisto indicando solo l'IMPORTO investito **in EUR** (i soldi dell'utente):
    prezzo e quantità si ricavano dal prezzo di mercato attuale. Per i titoli in altra valuta
    l'importo EUR viene convertito al prezzo nativo, così «Investito (€)» coincide con quanto
    immesso. Bersaglio/stop come percentuali (+x% / -y%). Ritorna la posizione, o None se manca il prezzo."""
    tk = str(ticker).upper()
    q = quick_quote(tk)
    price = q.get("price")
    if price is None or price <= 0 or not amount or amount <= 0:
        return None
    # L'importo è in EUR: converto nella valuta del titolo per ricavare la quantità reale
    ccy = ticker_currency(tk)
    fx = fx_to_eur(ccy) or 1.0                      # native→EUR (1.0 se EUR o cambio ignoto)
    amount_native = float(amount) / fx              # EUR → valuta del titolo
    qty = amount_native / float(price)
    target = round(price * (1 + float(target_pct) / 100), 4) if target_pct else None
    stop = round(price * (1 - float(stop_pct) / 100), 4) if stop_pct else None
    when = when or _now_iso()
    positions = load_portfolio()
    positions.append({
        "ticker": tk, "qty": qty, "buy_price": float(price),
        "amount": round(amount_native, 4),          # investito nella valuta del titolo (per la colonna "nativo")
        "amount_eur": float(amount), "ccy": ccy,     # investito in EUR (i soldi immessi)
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
        save_portfolio(positions, force=True)   # scelta esplicita: può anche svuotare il portafoglio
    return positions


CAPITAL_GAINS_TAX = 0.26   # tassa italiana sulle plusvalenze (rendite finanziarie)


def net_return_pct(gross_pct, tax: float = CAPITAL_GAINS_TAX):
    """Rendimento NETTO stimato (%) da un lordo %: in Italia la plusvalenza è tassata al 26%.
    La tassa si applica solo se in guadagno (le perdite non generano imposta). Le commissioni sono
    importi fissi e si contano a livello di posizione (Portafoglio), non su una % attesa."""
    if gross_pct is None:
        return None
    try:
        g = float(gross_pct)
    except (TypeError, ValueError):
        return None
    return round(g * (1.0 - tax), 1) if g > 0 else round(g, 1)


def personal_levels(price, amount_eur, fee_eur, desired_net_eur=None, tax: float = CAPITAL_GAINS_TAX,
                    lati: int = _LATI_OPERAZIONE):
    """Livelli PERSONALI di vendita, calcolati dai TUOI numeri (importo e commissioni) invece che
    da un livello tecnico: - pareggio = prezzo che copre le sole commissioni;
    - soglia = prezzo che, venduto, lascia in tasca `desired_net_eur` € NETTI (dopo commissioni e
      tassa del 26% sulla plusvalenza). Formula: per N € netti serve un lordo G = commissioni +
      N/(1−tax) → in percentuale target_pct = G/importo*100. Percentuali nella valuta del titolo
      applicate al nominale in EUR: l'oscillazione del cambio è ignorata (trascurabile su importi
      piccoli e pochi giorni rispetto alle commissioni).
    `fee_eur` è la commissione di UNA operazione: comprare e vendere ne paga `lati` (2).
      Ritorna {break_even, be_pct, target, target_pct} (target None se desired_net_eur non è dato)
      oppure None su input non validi."""
    try:
        p, a, f = float(price), float(amount_eur), float(fee_eur) * int(lati)
    except (TypeError, ValueError):
        return None
    if p <= 0 or a <= 0 or f < 0 or not (0 <= tax < 1):
        return None
    be_pct = f / a * 100.0
    out = {"break_even": round(p * (1 + be_pct / 100.0), 4), "be_pct": round(be_pct, 2),
           "target": None, "target_pct": None}
    if desired_net_eur is not None:
        try:
            n = float(desired_net_eur)
        except (TypeError, ValueError):
            return out
        if n > 0:
            target_pct = (f + n / (1.0 - tax)) / a * 100.0
            out["target"] = round(p * (1 + target_pct / 100.0), 4)
            out["target_pct"] = round(target_pct, 2)
    return out


def set_my_target(ticker: str, price) -> None:
    """Imposta (o rimuove, con price falsy) la SOGLIA PERSONALE di vendita di un'occasione seguita.
    Azzera sempre il flag di avviso così la notifica si ri-arma sulla nuova soglia."""
    data = load_tracking()
    tk = str(ticker).upper()
    if tk not in data:
        return
    e = data[tk]
    if price:
        e["my_target_price"] = round(float(price), 4)
        e["my_target_set"] = _today_iso()
    else:
        e.pop("my_target_price", None)
        e.pop("my_target_set", None)
    e.pop("my_target_notified", None)
    save_tracking(data)


def my_target_alerts() -> list:
    """Avviso (una volta sola) quando il prezzo di un'occasione seguita raggiunge la SOGLIA
    PERSONALE impostata dall'utente; si ri-arma se il prezzo torna sotto. Stesso schema one-shot
    di monitoring_exit_alerts. Ritorna [{ticker, name, price, target}]."""
    tracked = load_tracking()
    if not tracked:
        return []
    out, changed = [], False
    for tk, e in tracked.items():
        tgt = e.get("my_target_price")
        if not tgt:
            continue
        snaps = [s for s in e.get("snapshots", []) if s.get("price")]
        if not snaps:
            continue
        last_price = snaps[-1]["price"]
        if last_price >= tgt and not e.get("my_target_notified"):
            e["my_target_notified"] = True
            changed = True
            out.append({"ticker": tk, "name": e.get("name", tk),
                        "price": last_price, "target": tgt})
        elif last_price < tgt and e.get("my_target_notified"):
            e["my_target_notified"] = False    # ri-arma per un eventuale nuovo superamento
            changed = True
    if changed:
        save_tracking(tracked)
    return out


def portfolio_view(base: str = "EUR", tax_rate: float = CAPITAL_GAINS_TAX, fee: float = 1.0,
                   lati: int = _LATI_OPERAZIONE):
    """Calcola valore attuale, guadagno/perdita (lordo e NETTO) per posizione e totali, più gli
    avvisi target/stop. I TOTALI sono convertiti in valuta base (EUR) così valute diverse si
    sommano correttamente. Il **netto** = guadagno lordo − tassa del `tax_rate` sulla plusvalenza
    (solo se in utile) − le commissioni. `fee` è la commissione di UNA operazione: la posizione ne
    paga `lati` (2), perché per incassare devi anche vendere. Stima: la tassa è calcolata per
    singola posizione (non considera la compensazione delle minusvalenze). Ritorna (righe, totali);
    totals['complete']=False se qualche posizione è esclusa dal totale (prezzo o cambio mancanti)."""
    fee = float(fee) * int(lati)
    positions = load_portfolio()
    rows = []
    tot_cost_eur = tot_val_eur = tot_net_eur = tot_tax_eur = tot_fee_eur = 0.0
    complete = True
    currencies = set()
    for i, p in enumerate(positions):
        tk = p.get("ticker")
        qty = p.get("qty") or 0.0
        buy = p.get("buy_price") or 0.0
        q = quick_quote(tk)
        price = q.get("price")
        ccy = ticker_currency(tk)
        currencies.add(ccy)
        fx = fx_to_eur(ccy) if base == "EUR" else 1.0
        cost = qty * buy                                  # valori NATIVI (valuta del titolo)
        val = (qty * price) if price is not None else None
        pnl = (val - cost) if val is not None else None
        pnl_pct = ((price / buy - 1) * 100) if (price is not None and buy) else None
        # Conversione in valuta base (EUR) per totali e calcolo fiscale
        usable = (fx is not None and price is not None)
        cost_eur = (cost * fx) if fx is not None else None
        val_eur = (val * fx) if (val is not None and fx is not None) else None
        # Netto: lordo − tassa (solo su utile, al netto delle commissioni) − commissioni
        gross_eur = (val_eur - cost_eur) if (val_eur is not None and cost_eur is not None) else None
        tax_eur = net_eur = net_value_eur = net_pct = None
        if gross_eur is not None:
            taxable = max(gross_eur - fee, 0.0)           # la tassa colpisce solo la plusvalenza netta
            tax_eur = tax_rate * taxable
            net_eur = gross_eur - fee - tax_eur
            net_value_eur = cost_eur + net_eur            # quanto incasseresti davvero
            net_pct = (net_eur / cost_eur * 100) if cost_eur else None
        if usable:
            tot_cost_eur += cost_eur
            tot_val_eur += val_eur
            tot_tax_eur += tax_eur or 0.0
            tot_fee_eur += fee
            tot_net_eur += net_eur if net_eur is not None else 0.0
        else:
            complete = False
        tgt, stp = p.get("target"), p.get("stop")
        status = ""
        if price is not None:
            if tgt and price >= tgt:
                status = "🎯 target raggiunto"
            elif stp and price <= stp:
                status = "🛑 stop raggiunto"
        rows.append({"index": i, "ticker": tk, "qty": qty, "buy_price": buy, "date": p.get("date"),
                     "datetime": p.get("datetime") or p.get("date"),
                     "amount": p.get("amount", cost), "ccy": ccy,
                     "price": price, "cost": cost, "value": val, "pnl": pnl, "pnl_pct": pnl_pct,
                     "value_eur": val_eur, "cost_eur": cost_eur, "gross_eur": gross_eur,
                     "tax_eur": tax_eur, "net_eur": net_eur, "net_value_eur": net_value_eur,
                     "net_pct": net_pct,
                     "target": tgt, "stop": stp, "note": p.get("note", ""), "status": status,
                     "horizon": ("breve" if str(p.get("horizon", "lungo")).startswith("breve") else "lungo")})
    totals = {"base": base, "currencies": sorted(currencies), "complete": complete,
              "tax_rate": tax_rate, "fee": fee,
              "cost": tot_cost_eur, "value": tot_val_eur,
              "pnl": (tot_val_eur - tot_cost_eur),
              "pnl_pct": ((tot_val_eur / tot_cost_eur - 1) * 100) if tot_cost_eur else None,
              "tax": tot_tax_eur, "fee_total": tot_fee_eur, "net_pnl": tot_net_eur,
              "net_pnl_pct": ((tot_net_eur / tot_cost_eur) * 100) if tot_cost_eur else None,
              "net_value": (tot_cost_eur + tot_net_eur)}
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


# ---------------------------------------------------------------------------
# LE SOGLIE CANDIDATE — piu formule per lo stesso bersaglio, registrate insieme.
#
# Perche piu di una. Il bersaglio di oggi e la media a 50 giorni, e misurata sui dati veri regge
# male: distanza mediana +21% dal prezzo, il 52% delle occasioni oltre il +20%, sei su settantuno
# con il bersaglio SOTTO il prezzo (cioe nessun bersaglio), e un massimo di +531%. Viene toccato nel
# 23% dei casi, e il tasso crolla con la distanza: entro il 5% viene raggiunto sempre, oltre il 50%
# MAI (0 su 15). Il difetto non e la formula in se: e che la distanza non e una scelta, e un effetto
# di quanto il titolo e caduto.
# Nessuna formula alternativa e misurabilmente migliore con i dati di oggi (la media a 20 giorni
# viene toccata il 48% delle volte ma punta a guadagnare meno di quanto si rischia). Quindi invece
# di scegliere a tavolino, si REGISTRANO TUTTE alla data dell'acquisto e si misura quale funziona:
# essendo un confronto sulle stesse righe e nella stessa finestra, servono molti meno casi.
#
# Le formule, con il nome che compare nell'app:
#   media50        la media a 50 giorni: ritorno alla media, e il bersaglio storico dell'app
#   media20        la media a 20 giorni: piu vicina, quindi piu raggiungibile
#   quattro_atr    prezzo + 4 volte l'ATR: rende il rischio/rendimento fisso a 2 (lo stop e 2 ATR)
#   meta_caduta    prezzo + meta della distanza dal massimo degli ultimi 60 giorni
#   bollinger      la banda di Bollinger superiore
#   consigliata    la piu bassa fra media50 e quattro_atr: tiene la logica storica ma taglia gli
#                  assurdi tipo +531%. E quella che l'app usa per la colonna «alla soglia».
# Un valore <= al prezzo non e un bersaglio e viene messo a None: meglio una cella vuota che una
# perdita registrata come «obiettivo raggiunto».
# ---------------------------------------------------------------------------
SOGLIA_USATA = "consigliata"     # quale formula alimenta la colonna «alla soglia»
SOGLIE_NOMI = {
    "media50": "Media a 50 giorni (la storica dell'app)",
    "media20": "Media a 20 giorni (più vicina, più raggiungibile)",
    "quattro_atr": "Prezzo + 4 volte l'ATR (rischio/rendimento fisso a 2)",
    "meta_caduta": "Metà della caduta dal massimo di 60 giorni",
    "bollinger": "Banda di Bollinger superiore",
    "consigliata": "Consigliata: la più bassa fra media 50 e 4 ATR",
}


def _soglie_da_storico(h, price):
    """Le soglie candidate a partire da uno storico prezzi gia caricato e dal prezzo di riferimento.
    Ritorna un dizionario {nome: valore}, con None dove la formula non e calcolabile o darebbe un
    bersaglio non superiore al prezzo (un obiettivo gia raggiunto non e un obiettivo)."""
    out = {k: None for k in SOGLIE_NOMI}
    try:
        if h is None or len(h) == 0 or not price:
            return out
        p = float(price)
        last = h.iloc[-1]
        def _v(col):
            try:
                x = float(last.get(col, float("nan")))
                return x if x == x else None      # scarta i NaN
            except Exception:
                return None
        m50, m20, bb = _v("SMA50"), _v("SMA20"), _v("BB_up")
        try:
            a = atr(h, 14)
            atr_val = float(a.iloc[-1])
            if atr_val != atr_val or atr_val <= 0:
                atr_val = None
        except Exception:
            atr_val = None
        try:
            massimo = float(h["Close"].tail(60).max())
        except Exception:
            massimo = None
        cand = {
            "media50": m50,
            "media20": m20,
            "quattro_atr": (p + 4 * atr_val) if atr_val else None,
            "meta_caduta": (p + (massimo - p) / 2) if (massimo and massimo > p) else None,
            "bollinger": bb,
        }
        validi = [cand["media50"], cand["quattro_atr"]]
        validi = [x for x in validi if x and x > p]
        cand["consigliata"] = min(validi) if validi else None
        for k, v in cand.items():
            out[k] = round(float(v), 4) if (v is not None and float(v) > p) else None
        return out
    except Exception:
        return out


def soglie_ora(ticker, price=None, kind="short", fino_a=None):
    """Le soglie candidate per un titolo ALLA DATA `fino_a`, piu lo stop e l'ATR.

    `fino_a` NON e un dettaglio: senza, lo storico arrivava sempre a oggi mentre il prezzo era quello
    dell'evento, che il lavoro automatico mette a verbale anche giorni dopo (salta dei giri). Misurato
    sul diario vero: 57 momenti d'acquisto su 67 avevano le soglie costruite su barre SUCCESSIVE
    all'acquisto, fino a 5 giorni dopo. E il difetto non era solo inelegante, era un bias in positivo
    proprio sulla misura per cui le soglie esistono: «meta_caduta» e il punto a meta fra il prezzo e
    il massimo delle ultime 60 sedute, quindi se quel massimo cade DOPO l'acquisto, il bersaglio
    risulta raggiunto per costruzione — e la finestra in cui si verifica se e stato toccato contiene
    proprio le barre usate per costruirlo. Il confronto fra le sei formule ne sarebbe uscito falsato
    verso l'ottimismo, cioe inutile.
    Una chiamata di rete per evento, e gli eventi sono pochi al giorno (lo storico e anche in cache)."""
    fuori = {"soglie": {k: None for k in SOGLIE_NOMI}, "stop": None, "atr": None}
    try:
        h = get_history(ticker, period="1y")
        if h is None or h.empty:
            return fuori
        if fino_a:
            # si taglia PRIMA di calcolare gli indicatori: medie, bande e ATR devono essere quelli
            # di allora, non quelli di oggi ricalcolati su una serie piu lunga
            try:
                h = h.copy()
                if getattr(h.index, "tz", None) is not None:
                    h.index = h.index.tz_localize(None)
            except (TypeError, AttributeError):
                pass
            try:
                h = h[h.index <= pd.Timestamp(str(fino_a)[:10]) + pd.Timedelta(days=1)]
            except Exception:
                pass
            if h is None or h.empty:
                return fuori      # meglio nessun bersaglio che il bersaglio di un altro giorno
        h = add_indicators(h)
        p = float(price) if price else float(h["Close"].dropna().iloc[-1])
        s = _soglie_da_storico(h, p)
        try:
            a = atr(h, 14)
            atr_val = float(a.iloc[-1])
            atr_val = atr_val if atr_val == atr_val and atr_val > 0 else None
        except Exception:
            atr_val = None
        stop = round(p - _ATR_STOP_K * atr_val, 4) if atr_val else None
        if stop is not None and (stop <= 0 or stop >= p):
            stop = None               # stop negativo o sopra il prezzo pagato: non e uno stop
        return {"soglie": s, "stop": stop,
                "atr": (round(atr_val, 4) if atr_val else None)}
    except Exception:
        return fuori


def distanze_soglie(prezzo, soglie, atr_val=None) -> dict:
    """Quanto dista ogni soglia dal prezzo, in percentuale e in multipli di ATR. Serve alla scheda
    che mostra il diario: la distanza e il numero che predice se il bersaglio verra toccato, molto
    piu della formula con cui e stato calcolato (entro il 5% viene raggiunto sempre, oltre il 50%
    mai)."""
    out = {}
    try:
        p = float(prezzo)
    except (TypeError, ValueError):
        return out
    for k, v in (soglie or {}).items():
        if v is None or not p:
            continue
        pct = (float(v) / p - 1) * 100
        out[k] = {"pct": round(pct, 2),
                  "atr": (round((float(v) - p) / float(atr_val), 2) if atr_val else None)}
    return out


# ---------------------------------------------------------------------------
# IL DIARIO DEGLI EVENTI — il registro PERMANENTE della vita di ogni occasione.
#
# Perché esiste. Fino a oggi i dati che servono agli scenari non venivano scritti nel momento in cui
# esistevano: si tenevano nei registri di lavoro (le osservazioni, il monitoraggio) e si provava a
# ricostruirli DOPO. Ma quei registri sono buffer — le osservazioni si potano, il monitoraggio si
# svuota all'uscita — e ricostruire a posteriori ha prodotto dati sbagliati (sette righe con l'inizio
# dell'osservazione datato DOPO la promozione) o mancanti per sempre (nove «ingressi in anticipo»,
# otto momenti di fine verifica). Qui ogni evento viene SCRITTO quando avviene, con i valori di
# quell'istante, in un registro che:
#   · è append-only: una riga scritta non si modifica e non si cancella;
#   · non si pota per età: l'eccedenza va negli archivi annuali, che non vengono più toccati;
#   · non viene svuotato quando l'occasione è promossa o esce dal monitoraggio.
#
# I SETTE EVENTI, che sono esattamente i momenti che gli scenari devono poter misurare:
#   ingresso_osservazione  il titolo entra in osservazione
#   fine_osservazione      finiscono i giorni di osservazione (3 breve / 7 lungo)   -> acquisto sc. 1
#   salita_2pct            il prezzo è salito del 2% dall'inizio dell'osservazione  -> acquisto sc. 2
#   ingresso_anticipo      il pre-segnale diventa solido: entra in «In anticipo»
#   promozione             entra nel Monitoraggio                                   -> acquisto sc. 3
#   fine_verifica          finiscono i giorni di verifica (5 breve / 10 lungo)      -> acquisto sc. 4
#   uscita                 il sistema la toglie dal Monitoraggio
# Ogni riga porta data E ORA, prezzo, convenienza, probabilità di salita, rischio di perdita,
# affidabilità e contesto di mercato di QUEL momento: valori veri, non ricostruiti.
# ---------------------------------------------------------------------------
DIARIO_NAME = "diario_eventi.json"
# RITARATO con l'arrivo delle soglie: una riga di momento d'acquisto porta ora sei bersagli
# candidati piu il loro esito, quindi pesa circa 850 byte invece di 300. Col tetto vecchio il file
# vivo avrebbe superato i 2,5 MB e oltre 1 MB la protezione anti-cancellazione si spegne per sempre.
# Niente si perde: l'eccedenza va negli archivi annuali, che non vengono mai potati, e le statistiche
# leggono archivio + file vivo.
_DIARIO_MAX = 700         # ~850 byte/riga -> ~580 KB (col margine 1,3: ~760 KB)

# L ORDINE E QUELLO DEL PERCORSO REALE, misurato sui dati, non quello dei nomi:
#   1 entra in osservazione
#   2 entra in «In anticipo» — arriva DURANTE l osservazione, non dopo: basta un giorno di
#     osservazione e una convenienza di 65 (per entrare in osservazione bastano 60), e la finestra
#     di osservazione NON e richiesta. Sui dati veri arriva prima della fine dell osservazione in
#     41 righe su 42.
#   3 finisce l osservazione (3 giorni di Borsa per il breve, 7 per il lungo)
#   4 e salito del 2% — e la condizione che fa scattare la promozione, quindi sta subito prima
#   5 entra in Monitoraggio
#   6 finisce la verifica (5 giorni di Borsa per il breve, 10 per il lungo)
#   7 esce dal Monitoraggio
# I tre eventi centrali (2, 3, 4) possono scambiarsi fra loro: dipende da quando la convenienza
# sale a 65 e da quando il prezzo fa il 2%. L unico ordine garantito e che la promozione viene
# dopo la fine dell osservazione E dopo la salita del 2%, perche le richiede entrambe.
EVENTI = ("ingresso_osservazione", "ingresso_anticipo", "fine_osservazione", "salita_2pct",
          "promozione", "fine_verifica", "uscita")
# Quali eventi sono un MOMENTO D'ACQUISTO si ricava da SCENARI_ACQUISTO (definito più in basso,
# insieme ai cinque scenari), così la lista sta scritta in un posto solo. Prima c'era qui una mappa
# a quattro voci: quando gli scenari sono diventati cinque è rimasta indietro, e il risolutore
# saltava in silenzio i due momenti che non conosceva. Una lista duplicata è una lista che divergerà.
def eventi_acquisto() -> set:
    """Gli eventi del diario che sono un momento d'acquisto di uno scenario."""
    return {ev for _k, ev, _n, _a in SCENARI_ACQUISTO}


def load_diario() -> list:
    d = read_data_json(DIARIO_NAME, [])
    return d if isinstance(d, list) else []


def _valori_ora(kind, tk) -> dict:
    """I valori più freschi che il sistema conosce ADESSO per un titolo: dal monitoraggio se lo
    segue, altrimenti dalle osservazioni. Serve a scrivere un evento con i numeri di quell'istante
    invece di lasciarli vuoti e provare a ricostruirli mesi dopo, che è ciò che non ha funzionato."""
    TK = str(tk).upper()
    try:
        e = (load_tracking() or {}).get(TK) or {}
        snaps = [s for s in (e.get("snapshots") or []) if s.get("date") and s.get("price")]
        if snaps:
            s = max(snaps, key=lambda x: str(x.get("date")))
            return {"data": s.get("date"), "prezzo": s.get("price"), "conv": s.get("convenienza"),
                    "prob_gain": s.get("prob_gain"), "prob_loss": s.get("prob_loss"),
                    "reliab": s.get("reliab"), "mkt": None, "fonte": "monitoraggio"}
    except Exception:
        pass
    try:
        e = (load_opp_watch() or {}).get(f"{kind}:{TK}") or {}
        pts = [o for o in (e.get("obs") or []) if o.get("price")]
        if pts:
            o = max(pts, key=lambda x: str(x.get("date")))
            return {"data": o.get("date"), "prezzo": o.get("price"), "conv": o.get("conv"),
                    "prob_gain": o.get("prob_gain"), "prob_loss": o.get("prob_loss"),
                    "reliab": o.get("reliab"), "mkt": o.get("mkt"), "fonte": "osservazione"}
    except Exception:
        pass
    return {"data": None, "prezzo": None, "conv": None, "prob_gain": None, "prob_loss": None,
            "reliab": None, "mkt": None, "fonte": None}


def episodio_corrente(kind, tk, crea_se_manca=False):
    """L'identificativo dell'EPISODIO in corso di un titolo: «tipo:TITOLO:data-ingresso».
    Un titolo può passare più volte nella vita del sistema, e mescolare due passaggi diversi è
    l'errore che ha prodotto le osservazioni datate dopo la promozione. L'episodio si apre con
    l'ingresso in osservazione e si chiude con l'uscita dal monitoraggio."""
    TK = str(tk).upper()
    righe = [r for r in load_registro_completo(DIARIO_NAME, load_diario())
             if r.get("ticker") == TK and r.get("kind") == kind]
    ingressi = [r for r in righe if r.get("evento") == "ingresso_osservazione"]
    if ingressi:
        ultimo = max(ingressi, key=lambda r: str(r.get("data") or ""))
        eid = ultimo.get("episodio")
        chiuso = any(r.get("episodio") == eid and r.get("evento") == "uscita" for r in righe)
        if not chiuso:
            return eid
    return f"{kind}:{TK}:{_today_iso()}" if crea_se_manca else None


def registra_evento(kind, tk, evento, valori=None, episodio=None, note=None, dovuto_il=None,
                    profilo=True) -> bool:
    """Scrive un evento nel diario. Ritorna True se l'ha scritto, False se c'era già.
    UN SOLO evento per tipo dentro un episodio: se «fine_osservazione» è già a verbale non viene
    riscritto, altrimenti a ogni giro del lavoro automatico verrebbe sovrascritto con i valori di
    oggi — che è precisamente il difetto per cui questo registro esiste."""
    if evento not in EVENTI:
        return False
    TK = str(tk).upper()
    eid = episodio or episodio_corrente(kind, TK, crea_se_manca=True)
    righe = load_diario()
    if any(r.get("episodio") == eid and r.get("evento") == evento
           for r in load_registro_completo(DIARIO_NAME, righe)):
        return False
    v = dict(_valori_ora(kind, TK))
    for k, x in (valori or {}).items():
        if x is not None:
            v[k] = x
    # LE SOGLIE CANDIDATE, ma solo per gli eventi che sono un momento d ACQUISTO: sono gli unici in
    # cui serve un bersaglio, e calcolarle costa una lettura dello storico (che la scansione ha di
    # norma gia in cache). Si calcolano ADESSO, cioe alla data dell evento: e il punto di tutto il
    # diario — un bersaglio ricostruito mesi dopo sarebbe il bersaglio di un altro giorno.
    liv = {}
    if evento in eventi_acquisto():
        # alla DATA dell'evento, non a oggi: vedi il perche dentro soglie_ora
        liv = soglie_ora(TK, v.get("prezzo"), kind, fino_a=str(v.get("data") or "")[:10] or None)
    righe.append({
        "episodio": eid, "ticker": TK, "kind": kind, "evento": evento,
        "scritto_il": _now_iso(),                 # quando il sistema l'ha messo a verbale
        "data": v.get("data") or _now_iso(),      # il momento a cui i valori si riferiscono
        "prezzo": v.get("prezzo"), "conv": v.get("conv"),
        "prob_gain": v.get("prob_gain"), "prob_loss": v.get("prob_loss"),
        "reliab": v.get("reliab"), "mkt": v.get("mkt"),
        "fonte": v.get("fonte"), "note": note,
        # QUANDO L EVENTO ERA DOVUTO, distinto da quando e stato scritto. Il lavoro automatico gira
        # ogni mezz ora, ma puo saltare dei giri (il 6 agosto non ha girato): in quel caso l evento
        # viene messo a verbale in ritardo e i valori sono di qualche giorno dopo. Il ritardo deve
        # essere VISIBILE, non nascosto: chi legge lo scenario deve poter scartare le righe in cui
        # e troppo grande, invece di fidarsi di un numero preso nel giorno sbagliato.
        # convertita qui e non nei chiamanti: il calcolo dei giorni di Borsa restituisce una data
        # vera, e un oggetto data non si può scrivere in JSON. Meglio una conversione in un punto
        # solo che tre chiamanti che devono ricordarsene.
        "dovuto_il": (dovuto_il.isoformat() if hasattr(dovuto_il, "isoformat")
                      else (str(dovuto_il)[:10] if dovuto_il else None)),
        # i livelli del momento: piu formule per lo stesso bersaglio, cosi si potra misurare quale
        # funziona invece di scegliere a tavolino (vedi SOGLIE_NOMI)
        "soglie": liv.get("soglie") or None,
        "stop": liv.get("stop"),
        "atr": liv.get("atr"),
    })
    # L'ESITO DEL SALVATAGGIO CONTA. Prima si ritornava True comunque: chi chiama credeva che
    # l'evento fosse a verbale e al giro dopo non riprovava, quindi l'ingresso in osservazione di
    # quell'occasione era perso. Ritornando False il chiamante riprova al giro successivo.
    if not salva_registro(DIARIO_NAME, righe, _DIARIO_MAX, giorni_protetti=400):
        return False
    if DIARIO_NAME in _SALVATAGGI_FALLITI:
        return False        # arrivato solo in locale: nel lavoro automatico muore col giro
    # ARCHIVIO DELL'APPRENDIMENTO: se questo evento è un momento in cui si compra, qui si registra
    # il PROFILO COMPLETO dell'occasione — le ~50 caratteristiche che il sistema calcola a ogni giro
    # e finora buttava, più com'era il mondo e il suo settore quel giorno, più le notizie. Sta qui e
    # non nei chiamanti perché registra_evento è il passaggio obbligato di ogni cambio di stato:
    # sette chiamanti, un solo punto da ricordare.
    # `profilo=False` serve a un caso solo, ed è un caso di onestà: gli eventi RICOSTRUITI da un
    # registro più vecchio. Di quelli si conosce la data vera d'ingresso ma NON le caratteristiche
    # di quel giorno, perché nessuno le aveva salvate. Attaccarci il profilo di oggi vorrebbe dire
    # accoppiare le caratteristiche di una data con l'acquisto di un'altra — cioè esattamente il
    # difetto per cui questo archivio esiste. Meglio un profilo che manca, e si vede che manca.
    # LO STESSO PRINCIPIO VALE ANCHE PER GLI EVENTI IN RITARDO, e qui c'era il buco. Un evento
    # "dovuto" giorni prima viene messo a verbale oggi (il lavoro automatico salta dei giri), e il
    # profilo ricalcolava TUTTO col mercato di oggi: prezzo compreso. Misurato sui dati veri del
    # 21/08/2026: su 22 momenti d'acquisto, 4 avevano nell'archivio un prezzo diverso da quello del
    # diario — ENEL.MI 9,4160 del 18 agosto contro 9,5570 del 21, cioe +1,50%; STLAM.MI +2,93%.
    # Conseguenza: gli scenari e l'archivio avrebbero misurato rendimenti DIVERSI per lo stesso
    # acquisto. Il prezzo d'acquisto e uno solo, ed e quello del diario: il profilo lo riceve, e
    # riceve anche di quante ore e in ritardo, cosi le caratteristiche non si spacciano per quelle
    # dell'istante.
    if profilo and evento in eventi_acquisto():
        try:
            _d_ev = str(v.get("data") or "")[:16].replace("T", " ")
            try:
                # LO STESSO OROLOGIO con cui e' scritta la data dell'evento (_now_iso), non
                # datetime.now(): sui server il processo gira in UTC e la data dell'evento e' in ora
                # italiana, quindi il conto perdeva 2 ore e tutto cio' che stava sotto le 2 ore
                # veniva schiacciato a zero — cioe' un profilo in ritardo si presentava come preso
                # nell'istante, il contrario di quello che il campo deve dire.
                _rit = max(0.0, (datetime.datetime.strptime(_now_iso()[:16], "%Y-%m-%d %H:%M")
                                 - datetime.datetime.strptime(_d_ev, "%Y-%m-%d %H:%M")
                                 ).total_seconds() / 3600)
            except Exception:
                _rit = 0.0
            registra_profilo_occasione(kind, TK, evento, episodio=eid,
                                       giorno=(_d_ev[:10] or None), ritardo_ore=_rit,
                                       prezzo_acquisto=v.get("prezzo"))
        except Exception:
            pass        # un profilo mancato non deve mai impedire di scrivere l'evento nel diario
    return True


def riallinea_diario_osservazioni() -> dict:
    """Riporta nel diario le occasioni GIÀ in osservazione che non hanno il loro ingresso a verbale.

    A cosa serve. L'ingresso in osservazione viene messo a verbale una volta sola: nell'istante in
    cui la voce riceve la sua fotografia iniziale. Un'occasione che quella fotografia la ha già —
    43 delle 45 in corso — non riscriverebbe mai più quell'evento. Quindi se il diario viene
    azzerato, quelle occasioni diventano ORFANE per sempre: nessun episodio, nessun momento
    d'acquisto, niente in archivio. E sono proprio quelle che nei prossimi giorni dovrebbero
    riempirlo, perché sono le più avanti di tutte.

    Come lo fa in modo onesto. La data e i valori vengono dalla fotografia iniziale, che è la verità
    congelata di quel giorno — NON da oggi, e non azzerando la fotografia per farla ricalcolare
    (i punti più vecchi si diradano col tempo, quindi ricalcolarla darebbe una data più recente di
    quella vera). E l'evento nasce SENZA profilo: di quel giorno le caratteristiche non esistono, e
    inventarle con quelle di oggi sarebbe peggio che lasciarle mancare.

    È ripetibile senza danno: un evento già a verbale non viene riscritto."""
    watch = load_opp_watch() or {}
    esistenti = {(r.get("kind"), r.get("ticker"))
                 for r in load_registro_completo(DIARIO_NAME, load_diario())
                 if r.get("evento") == "ingresso_osservazione"}
    scritti, gia_presenti, senza_dati = 0, 0, 0
    for chiave, e in sorted(watch.items()):
        e = e or {}
        kind = e.get("kind") or (str(chiave).split(":")[0] if ":" in str(chiave) else "short")
        tk = str(e.get("ticker") or str(chiave).split(":")[-1]).upper()
        if (kind, tk) in esistenti:
            gia_presenti += 1
            continue
        punto = e.get("primo") or ((e.get("obs") or [{}]) or [{}])[0] or {}
        data = str(punto.get("date") or "")
        if not data or punto.get("price") in (None, 0):
            senza_dati += 1
            continue
        if registra_evento(
                kind, tk, "ingresso_osservazione",
                episodio=f"{kind}:{tk}:{data[:10]}",     # l'episodio prende la data VERA, non oggi
                valori={"data": data, "prezzo": punto.get("price"), "conv": punto.get("conv"),
                        "prob_gain": punto.get("prob_gain"), "prob_loss": punto.get("prob_loss"),
                        "reliab": punto.get("reliab"), "mkt": punto.get("mkt"),
                        "fonte": "riallineato dal registro delle osservazioni"},
                note="ingresso ricostruito dalla fotografia iniziale: la data e i valori sono "
                     "quelli veri di quel giorno, ma le altre caratteristiche di allora non "
                     "esistono, quindi questo momento non ha un profilo in archivio",
                profilo=False):
            scritti += 1
    return {"scritti": scritti, "gia_presenti": gia_presenti, "senza_dati": senza_dati,
            "in_osservazione": len(watch)}


def diario_episodi(kind=None) -> dict:
    """Il diario riorganizzato per episodio: {id: {ticker, kind, eventi: {nome: riga}}}.
    È la forma che serve agli scenari: dato un episodio, il momento d'acquisto di ciascuno scenario
    è un evento preciso, coi suoi valori di quel giorno."""
    out = {}
    for r in sorted(load_registro_completo(DIARIO_NAME, load_diario()),
                    key=lambda r: str(r.get("scritto_il") or "")):
        if kind and r.get("kind") != kind:
            continue
        eid = r.get("episodio")
        if not eid:
            continue
        ep = out.setdefault(eid, {"ticker": r.get("ticker"), "kind": r.get("kind"), "eventi": {}})
        ep["eventi"].setdefault(r.get("evento"), r)      # il primo scritto vince, mai sovrascritto
    return out


def aggiorna_eventi() -> int:
    """IL RISOLUTORE DEL DIARIO: rileva gli eventi che scattano col passare del tempo e li mette a
    verbale nel momento in cui avvengono, coi valori di quell'istante.

    Sono i tre eventi che nessuno «vive» e che finora non registrava nessuno:
      · fine_osservazione — passati i giorni di osservazione (3 breve / 7 lungo, di Borsa);
      · salita_2pct       — il prezzo è salito del 2% dall'inizio dell'osservazione;
      · fine_verifica     — passati i giorni di verifica dopo la promozione (5 breve / 10 lungo).
    Girando ogni mezz'ora, il ritardo massimo fra l'evento e la sua registrazione è mezz'ora:
    incomparabilmente meglio di una ricostruzione tentata settimane dopo.
    Ritorna quanti eventi ha scritto."""
    scritti = 0
    episodi = diario_episodi()
    # L ULTIMO ingresso in osservazione per ogni titolo: serve a riconoscere gli episodi SUPERATI.
    # Se la storia di un titolo si interrompe (il sorvegliante salta piu di due giorni oltre la
    # finestra) l osservazione RIPARTE da zero e si apre un episodio nuovo, ma quello vecchio resta
    # aperto nel diario. Senza questa guardia i suoi eventi a tempo scatterebbero comunque, contando
    # dalla data d ingresso vecchia e dal prezzo vecchio: si creerebbe un momento d acquisto che non
    # e mai esistito, perche quell osservazione non e mai arrivata alla fine.
    ultimo_ingresso = {}
    for _e in episodi.values():
        _i = (_e["eventi"].get("ingresso_osservazione") or {}).get("data")
        if not _i:
            continue
        _k = f"{_e.get('kind')}:{_e.get('ticker')}"
        if str(_i) > str(ultimo_ingresso.get(_k, "")):
            ultimo_ingresso[_k] = str(_i)
    for eid, ep in episodi.items():
        kind, tk = ep.get("kind") or "short", ep.get("ticker")
        ev = ep["eventi"]
        ing = ev.get("ingresso_osservazione")
        # episodio superato: c e un ingresso in osservazione piu recente per lo stesso titolo e
        # questo non e mai arrivato alla promozione. Gli eventi PRIMA della promozione non scattano
        # piu; quelli dopo (la fine della verifica) restano possibili, perche appartengono a un
        # episodio che il monitoraggio ha davvero vissuto.
        superato = bool(ing and not ev.get("promozione")
                        and str(ing.get("data") or "") <
                        str(ultimo_ingresso.get(f"{kind}:{tk}", "")))
        if ing and not superato:
            g_oss = _OBS_WINDOW.get(kind, 3)
            if "fine_osservazione" not in ev and \
                    _trading_days_between(str(ing.get("data"))[:10], _today_iso(), tk) >= g_oss:
                scritti += bool(registra_evento(
                    kind, tk, "fine_osservazione", episodio=eid,
                    dovuto_il=_data_dopo_giorni_borsa(str(ing.get("data"))[:10], g_oss, tk),
                    note=f"passati {g_oss} giorni di Borsa dall'ingresso in osservazione"))
            if "salita_2pct" not in ev and ing.get("prezzo"):
                ora = _valori_ora(kind, tk)
                try:
                    salito = (ora.get("prezzo") is not None
                              and float(ora["prezzo"]) >= float(ing["prezzo"]) * (1 + _PROMO_MIN_RET / 100.0))
                except Exception:
                    salito = False
                if salito:
                    scritti += bool(registra_evento(
                        kind, tk, "salita_2pct", valori=ora, episodio=eid,
                        note=f"prezzo salito di almeno il {_PROMO_MIN_RET:.0f}% da {ing['prezzo']}"))
        promo = ev.get("promozione")
        if promo and "fine_verifica" not in ev:
            g_ver = _CONF_DAYS.get(kind, 5)
            if _trading_days_between(str(promo.get("data"))[:10], _today_iso(), tk) >= g_ver:
                scritti += bool(registra_evento(
                    kind, tk, "fine_verifica", episodio=eid,
                    dovuto_il=_data_dopo_giorni_borsa(str(promo.get("data"))[:10], g_ver, tk),
                    note=f"passati {g_ver} giorni di Borsa dalla promozione"))
    return scritti


def diario_riepilogo() -> dict:
    """Quante volte ogni evento è a verbale e da quando. Serve alla sezione che mostra il diario:
    un registro nuovo deve poter dire da sé quanto è pieno e da quando è in funzione."""
    righe = load_registro_completo(DIARIO_NAME, load_diario())
    per_evento = {e: 0 for e in EVENTI}
    for r in righe:
        if r.get("evento") in per_evento:
            per_evento[r["evento"]] += 1
    date = sorted(str(r.get("scritto_il") or "")[:10] for r in righe if r.get("scritto_il"))
    return {"righe": len(righe), "episodi": len({r.get("episodio") for r in righe}),
            "per_evento": per_evento, "dal": (date[0] if date else None),
            "al": (date[-1] if date else None)}


# ---------------------------------------------------------------------------
# I CINQUE SCENARI D'ACQUISTO, costruiti sul DIARIO degli eventi.
#
# Ogni scenario differisce dal precedente per UNA condizione sola: e questo che rende leggibile il
# confronto. Prima la matrice mescolava momenti e selezioni, e non si capiva se un numero migliore
# venisse dal comprare prima o dal comprare meglio.
#   1 appena entra in osservazione        nessun filtro: si compra tutto quello che il sistema guarda
#   2 appena entra in «In anticipo»        +  convenienza almeno 65 (e' una SELEZIONE, non un momento)
#   3 alla fine dei giorni di osservazione +  la finestra conclusa, MA senza pretendere il 2%
#   4 appena entra in monitoraggio         +  il rimbalzo del 2% (la condizione che blocca davvero)
#   5 dopo la verifica nel monitoraggio    +  altri 5 giorni di Borsa (10 per il lungo)
#
# IL FILTRO «SOLO LE MIGLIORI» usa i valori del momento d'acquisto DI QUELLO SCENARIO, presi dal
# diario: la convenienza e le probabilita scritte quando quell'evento e avvenuto. E l'unico modo
# onesto di rispondere a «e se avessi comprato solo le migliori»: giudicare con l'informazione che
# c'era quel giorno. Usare i numeri di oggi, o quelli di un altro passaggio, darebbe un risultato
# che nessuna regola eseguibile avrebbe potuto ottenere.
# ---------------------------------------------------------------------------
# (chiave, evento del diario, nome per l'utente, cosa aggiunge rispetto al precedente)
SCENARI_ACQUISTO = (
    ("s1_osservazione", "ingresso_osservazione", "Appena entra in osservazione",
     "nessuna condizione: si compra tutto quello che entra in osservazione"),
    ("s2_anticipo", "ingresso_anticipo", "Appena entra in «In anticipo»",
     "in piu: convenienza almeno 65 (e una selezione, non un momento diverso)"),
    ("s3_fine_osservazione", "fine_osservazione", "Alla fine dei giorni di osservazione",
     "in piu: la finestra di osservazione conclusa, ma SENZA pretendere il 2%"),
    ("s4_monitoraggio", "promozione", "Appena entra in monitoraggio",
     "in piu: il rimbalzo del 2%, che e la condizione che blocca di piu"),
    ("s5_fine_verifica", "fine_verifica", "Dopo la verifica nel monitoraggio",
     "in piu: altri 5 giorni di Borsa (10 per il lungo)"),
)
_DIARIO_SELLS = {"7g": 7, "30g": 30, "365g": 365}
# LA FINESTRA DELLA SOGLIA: entro quanti giorni di calendario il bersaglio deve essere toccato,
# altrimenti si vende alla chiusura di fine finestra. E l ultimo orizzonte fisso di quel tipo: un
# mese per il breve, un anno per il lungo. Prima era 30 giorni per tutti, e per un occasione di
# lungo periodo — che dichiara orizzonti a un mese e a un anno — quella colonna misurava un
# orizzonte che non c entrava.
# NB: NIENTE soglia a 7 giorni. Misurato: solo il 13% dei bersagli e raggiungibile in cinque sedute,
# quindi quella colonna avrebbe misurato quasi sempre la chiusura di ripiego, non un obiettivo.
_DIARIO_SOGLIA_GG = {"short": 30, "long": 365}
DIARIO_SELLS_PER_TIPO = {"short": ("soglia", "7g", "30g"), "long": ("soglia", "30g", "365g")}


def risolvi_diario() -> int:
    """Calcola, per ogni momento d'acquisto a verbale nel diario, quanto avrebbe reso vendendo dopo
    7, 30 o 365 giorni di calendario. Scrive il risultato UNA VOLTA e non lo ricalcola mai piu.

    Il campo `res` e l'unica parte della riga che si riempie dopo: i valori REGISTRATI (data, prezzo,
    convenienza, probabilita) non si toccano, perche sono la fotografia di quel momento. Il
    rendimento invece e una conseguenza che matura col tempo, e va calcolato quando e maturo.
    Guardia anti-frazionamento: se la prima chiusura dopo l'acquisto dista oltre il 25% dal prezzo
    a verbale, la riga viene marcata inutilizzabile — un raggruppamento di azioni non e un guadagno.
    Ritorna quante caselle ha calcolato."""
    # SU TUTTI I PEZZI, non solo sul file vivo. Un momento d'acquisto aspetta il suo esito fino a
    # 365 giorni: al ritmo attuale la sua riga finisce in archivio molto prima, e lavorando solo sul
    # vivo quell'esito non sarebbe mai stato calcolato — cioe lo scenario a un anno sarebbe rimasto
    # vuoto per sempre. aggiorna_registro_completo e lo stesso schema usato dagli altri risolutori.
    acquisti = eventi_acquisto()
    oggi = datetime.date.fromisoformat(_today_iso())

    def _risolvi(righe):
      fatte = 0
      for r in righe:
          if r.get("evento") not in acquisti or not r.get("prezzo") or r.get("bad_data"):
              continue
          try:
              d0 = datetime.date.fromisoformat(str(r.get("data"))[:10])
          except Exception:
              continue
          eta = (oggi - d0).days
          res = r.setdefault("res", {})
          attese = [sk for sk, gg in _DIARIO_SELLS.items() if eta >= gg and sk not in res]
          # la soglia ha una finestra sua e piu formule: si valuta anche quando le colonne a giorni
          # fissi sono gia tutte calcolate
          gg_s = _DIARIO_SOGLIA_GG.get(r.get("kind"), 30)
          manca_soglia = (eta >= gg_s and (r.get("soglie") or {})
                          and len(r.get("res_soglia") or {}) < len([1 for v in (r.get("soglie") or {}).values() if v]))
          if not attese and not manca_soglia:
              continue
          if eta > 400:
              r["bad_data"] = "troppo vecchia e ancora senza prezzi"
              fatte += 1
              continue
          try:
              closes = get_history(r.get("ticker"), period=("6mo" if eta < 150 else "2y"))["Close"].dropna()
              try:
                  closes.index = closes.index.tz_localize(None)
              except (TypeError, AttributeError):
                  pass
          except Exception:
              continue
          dopo = closes[closes.index > pd.Timestamp(d0)]
          if dopo.empty:
              continue
          if abs(float(dopo.iloc[0]) / float(r["prezzo"]) - 1) > 0.25:
              r["bad_data"] = "salto di prezzo oltre il 25%: probabile raggruppamento di azioni"
              fatte += 1
              continue
          for sk in attese:
              s = closes[closes.index >= pd.Timestamp(d0 + datetime.timedelta(days=_DIARIO_SELLS[sk]))]
              if s.empty:
                  continue
              res[sk] = round((float(s.iloc[0]) / float(r["prezzo"]) - 1) * 100, 2)
              fatte += 1

          # --- LA VENDITA «ALLA SOGLIA», una per ogni formula candidata -----------------------------
          # Si vende al bersaglio se una CHIUSURA lo tocca entro la finestra, altrimenti alla chiusura
          # di fine finestra. Tre cose che il vecchio impianto sbagliava e qui sono giuste:
          #  1) la finestra parte dalla data di QUESTO acquisto, non dalla promozione: chi compra prima
          #     ha davvero piu tempo, e prima si misurava un periodo che non aveva vissuto;
          #  2) un bersaglio <= al prezzo non produce nessuna cella, invece di registrare una perdita
          #     etichettata come «obiettivo raggiunto»;
          #  3) si calcolano TUTTE le formule sulle stesse righe e nella stessa finestra, cosi il
          #     confronto e appaiato e serviranno molti meno casi per capire quale funziona.
          gg_soglia = _DIARIO_SOGLIA_GG.get(r.get("kind"), 30)
          soglie = r.get("soglie") or {}
          if eta >= gg_soglia and soglie:
              res_s = r.setdefault("res_soglia", {})
              fine = closes[closes.index >= pd.Timestamp(d0 + datetime.timedelta(days=gg_soglia))]
              if not fine.empty:
                  finestra = dopo[dopo.index <= pd.Timestamp(d0 + datetime.timedelta(days=gg_soglia))]
                  for nome, liv in soglie.items():
                      if nome in res_s or liv is None:
                          continue
                      try:
                          liv = float(liv)
                      except (TypeError, ValueError):
                          continue
                      if liv <= float(r["prezzo"]):
                          continue          # non e un bersaglio: nessuna cella, e detto nella scheda
                      tocchi = finestra[finestra >= liv]
                      prezzo_vendita = liv if not tocchi.empty else float(fine.iloc[0])
                      res_s[nome] = {"ret": round((prezzo_vendita / float(r["prezzo"]) - 1) * 100, 2),
                                     "toccato": bool(not tocchi.empty),
                                     "giorni": (int((tocchi.index[0].date() - d0).days)
                                                if not tocchi.empty else None)}
                      fatte += 1
                  # la colonna «alla soglia» degli scenari usa la formula consigliata
                  if SOGLIA_USATA in res_s and "soglia" not in res:
                      res["soglia"] = res_s[SOGLIA_USATA]["ret"]
      return fatte

    # La potatura non serve qui: registra_evento chiama gia salva_registro a ogni evento nuovo.
    return aggiorna_registro_completo(DIARIO_NAME, _risolvi)


def _passa_migliori(r, min_pg=0, max_pl=100, min_conv=0):
    """Il filtro «solo le migliori» applicato ai valori DI QUESTA RIGA, cioe del momento d'acquisto
    di questo scenario. Ritorna (passa, dato_mancante): un filtro attivo su un numero che quel
    giorno non era stato registrato NON lascia passare la riga, e il chiamante conta quante ne
    restano fuori per questo motivo — un'esclusione silenziosa farebbe sembrare completo un campione
    che non lo e."""
    if (min_pg > 0 and r.get("prob_gain") is None) or \
            (max_pl < 100 and r.get("prob_loss") is None) or \
            (min_conv > 0 and r.get("conv") is None):
        return False, True
    if min_pg > 0 and (r.get("prob_gain") or 0) < min_pg:
        return False, False
    if max_pl < 100 and (r.get("prob_loss") if r.get("prob_loss") is not None else 999) > max_pl:
        return False, False
    if min_conv > 0 and (r.get("conv") or 0) < min_conv:
        return False, False
    return True, False


def scenari_diario(kind: str = "short", min_pg: int = 0, max_pl: int = 100, min_conv: int = 0,
                   importo: float = 30.0, fee: float = 1.0) -> dict:
    """I cinque scenari con i loro esiti, filtrati sui valori del momento d'acquisto di ciascuno.

    Ritorna {scenari: [{chiave, nome, aggiunge, evento, n_totali, n_passano, n_senza_dato,
                        celle: {vendita: {n, med, avg, hit, best, worst, netto_medio, netto_tot,
                                          in_utile}},
                        casi: {vendita: [...]}}], vendite: (...)}
    `n_passano` e il numero di occasioni che COMPRERESTI: va mostrato accanto al rendimento, perche
    un rendimento piu alto su un decimo delle occasioni puo valere meno in totale."""
    vendite = DIARIO_SELLS_PER_TIPO.get(kind, DIARIO_SELLS_PER_TIPO["short"])
    righe = [r for r in load_registro_completo(DIARIO_NAME, load_diario())
             if r.get("kind") == kind and not r.get("bad_data")]
    per_evento = {}
    for r in righe:
        per_evento.setdefault(r.get("evento"), []).append(r)
    out = []
    for chiave, evento, nome, aggiunge in SCENARI_ACQUISTO:
        tutte = [r for r in per_evento.get(evento, []) if r.get("prezzo")]
        sel, senza = [], 0
        for r in tutte:
            ok, mancante = _passa_migliori(r, min_pg, max_pl, min_conv)
            if ok:
                sel.append(r)
            elif mancante:
                senza += 1
        celle, casi = {}, {}
        for sk in vendite:
            punti = [{"ticker": r.get("ticker"), "data": str(r.get("data"))[:10],
                      "prezzo": r.get("prezzo"), "conv": r.get("conv"),
                      "prob_gain": r.get("prob_gain"), "prob_loss": r.get("prob_loss"),
                      "ret": (r.get("res") or {})[sk]}
                     for r in sel if (r.get("res") or {}).get(sk) is not None]
            if not punti:
                continue
            vals = sorted(p["ret"] for p in punti)
            n = len(vals)
            med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
            nets = [net_eur(p["ret"], importo, fee) for p in punti]
            nets = [x for x in nets if x is not None]
            celle[sk] = {"n": n, "med": round(med, 2), "avg": round(sum(vals) / n, 2),
                         "hit": round(100 * sum(1 for v in vals if v > 0) / n),
                         "best": round(vals[-1], 2), "worst": round(vals[0], 2),
                         "netto_medio": (round(sum(nets) / len(nets), 2) if nets else None),
                         "netto_tot": (round(sum(nets), 2) if nets else None),
                         "in_utile": sum(1 for x in nets if x > 0),
                         "giornate": len({p["data"] for p in punti})}
            casi[sk] = sorted(punti, key=lambda p: p["data"])
        out.append({"chiave": chiave, "nome": nome, "aggiunge": aggiunge, "evento": evento,
                    "n_totali": len(tutte), "n_passano": len(sel), "n_senza_dato": senza,
                    "celle": celle, "casi": casi})
    return {"scenari": out, "vendite": vendite,
            "filtri_attivi": bool(min_pg or max_pl < 100 or min_conv)}


def imbuto_occasioni(kind: str = None) -> dict:
    """L'IMBUTO: quante occasioni raggiungono ciascuna tappa. E il contesto che rende leggibili i
    cinque scenari — e risponde da solo alla domanda «quale condizione blocca di piu».
    Si legge dal diario, quindi conta solo gli episodi registrati da quando il diario e in funzione."""
    righe = [r for r in load_registro_completo(DIARIO_NAME, load_diario())
             if not kind or r.get("kind") == kind]
    per_evento = {}
    for r in righe:
        per_evento.setdefault(r.get("evento"), set()).add(r.get("episodio"))
    tappe = []
    prec = None
    for chiave, evento, nome, _agg in SCENARI_ACQUISTO:
        n = len(per_evento.get(evento, set()))
        tappe.append({"nome": nome, "evento": evento, "quante": n,
                      "passa_pct": (round(100 * n / prec) if prec else None)})
        if prec is None:
            prec = n or None
    return {"tappe": tappe, "episodi": len({r.get("episodio") for r in righe})}


# ---------------------------------------------------------------------------
# ARCHIVIO DELL'APPRENDIMENTO
# Il posto dove il sistema si costruisce l'esperienza. Per ogni occasione che gli passa davanti —
# comprese quelle che scarta — registra COM'ERA nell'istante esatto in cui l'ha vista: le sue
# caratteristiche, il giudizio che le ha dato, com'era il mondo quel giorno, com'era il suo settore,
# che notizie girassero. Poi, quando l'esito matura, registra COM'È ANDATA. Dal confronto ripetuto
# migliaia di volte si ricava il profilo di quelle che guadagnano e di quelle che perdono.
#
# PERCHÉ UN FILE AL GIORNO, E MAI RISCRITTO.
# Il modo in cui questo progetto ha perso dati (il 16/08/2026, due registri azzerati) è sempre lo
# stesso: si rilegge tutto il file, si aggiunge una riga, si riscrive tutto — e se la rilettura
# fallisce, read_data_json restituisce [] in silenzio e la riscrittura cancella lo storico. Qui
# quella sequenza è impossibile per COSTRUZIONE, non per attenzione: si scrive solo il file di OGGI,
# e a mezzanotte quel file è chiuso per sempre. Nel caso peggiore in assoluto si perdono le righe di
# oggi; mai un giorno passato, mai un mese passato. In più i nomi stanno sotto "archivio/", che è
# l'unico prefisso per cui entrambe le guardie anti-cancellazione si attivano da sole.
#
# E PERCHÉ GLI ESITI STANNO IN UN ARCHIVIO SEPARATO.
# Un esito matura 7, 30 o 365 giorni dopo l'acquisto: scriverlo dentro la riga vorrebbe dire
# riaprire in scrittura un file vecchio, cioè buttare via l'unica garanzia vera. Quindi gli esiti
# sono righe nuove, archiviate nel giorno in cui MATURANO, che puntano al profilo con il suo
# identificativo. Così l'intero archivio non riscrive mai niente: solo aggiunge.
#
# COSA VUOL DIRE «IMPARARE» QUI.
# Per i primi mesi: statistica misurata, non modello. Per ogni caratteristica, quanto vale nelle
# occasioni che hanno guadagnato e quanto in quelle che hanno perso, con quanti casi e quanto è
# solido. Un modello addestrato su 200 casi trova regolarità nel rumore e le presenta con la stessa
# faccia sicura di quelle vere: sarebbe il modo più elegante di sbagliare. Prima si accumula.
# ---------------------------------------------------------------------------

ARC_PROFILI = "archivio/profili"      # una riga per occasione×momento, e una per ogni scarto
ARC_ESITI = "archivio/esiti"          # com'è andata: righe nuove il giorno in cui maturano
ARC_MONDO = "archivio/mondo"          # una riga al giorno: com'era il mondo
ARC_SETTORI = "archivio/settori"      # una riga per giorno×settore
ARC_NOTIZIE = "archivio/notizie"      # una riga per titolo×giorno, col riassunto
INDICE_NAME = "archivio/indice_archivio.json"   # cosa esiste e con quante righe
SINTESI_NAME = "profili_sintesi.json"           # le statistiche misurate: le legge l'app

# Tetto di sicurezza per file. Un giorno pieno fa ~200 righe da ~1,2 KB = ~240 KB, quindi il tetto
# non si tocca mai: è la cintura per il giorno anomalo. Oltre il tetto il giorno si spezza in pezzi
# (2026-08-21.json, 2026-08-21_b.json…) invece di crescere verso il muro di 1 MB, dove l'API GitHub
# smette di restituire il contenuto e le protezioni si spengono in silenzio.
_ARC_TETTO_BYTE = 600_000
_ARC_TETTO_RIGHE = 450

# Le notizie sono l'unica cosa che costa chiamate di rete vere. Il limite di Finnhub non è scritto
# da nessuna parte nel codice (solo prosa nei commenti), quindi non lo si indovina: si mette un
# tetto proprio, prudente, e si spende il budget sulle occasioni che contano invece di bruciarlo sui
# candidati qualunque. Senza tetto sarebbero ~3.000 chiamate al giorno in raffiche da 48 giri.
_NOTIZIE_PER_GIRO = 20        # tetto duro per singolo giro: oltre, si aspetta il giro dopo
_NOTIZIE_MAX_RIASSUNTO = 700  # caratteri per riassunto: oltre è prosa, non informazione
_NOTIZIE_PER_TITOLO = 5       # quante notizie per titolo al giorno

# Gli indicatori del mondo, verificati disponibili gratis dalla stessa fonte dei prezzi (21/08/2026:
# 24 su 24). Costano 24 chiamate AL GIORNO IN TUTTO, condivise da ogni occasione di quella giornata:
# è il motivo per cui la fotografia del mondo si può fare per bene invece che al risparmio.
_MONDO_SIMBOLI = (
    ("paura", "^VIX", "indice della paura"),
    ("sp500", "^GSPC", "S&P 500"),
    ("nasdaq", "^IXIC", "Nasdaq"),
    ("piccole", "^RUT", "Russell 2000, le società piccole"),
    ("europa", "^STOXX50E", "Europa"),
    ("tasso_10a", "^TNX", "tasso decennale USA"),
    ("tasso_3m", "^IRX", "tasso a 3 mesi"),
    ("dollaro", "DX-Y.NYB", "dollaro"),
    ("petrolio", "CL=F", "petrolio"),
    ("oro", "GC=F", "oro"),
    ("rame", "HG=F", "rame"),
    ("obbl_rischiose", "HYG", "obbligazioni rischiose"),
    ("obbl_lunghe", "TLT", "obbligazioni lunghe"),
)

# Gli 11 ETF settoriali. Servono a rendere «il settore era in crisi» un NUMERO invece di un
# racconto: senza questi, per le occasioni di breve periodo il settore non esiste affatto, perché i
# fondamentali vengono calcolati solo per il lungo.
_SETTORI_ETF = {
    "Technology": "XLK", "Financial Services": "XLF", "Healthcare": "XLV",
    "Consumer Cyclical": "XLY", "Consumer Defensive": "XLP", "Industrials": "XLI",
    "Energy": "XLE", "Utilities": "XLU", "Real Estate": "XLRE",
    "Basic Materials": "XLB", "Communication Services": "XLC",
}

# NOMI ALTERNATIVI DEI SETTORI. Il sistema prende il settore da DUE fonti diverse che usano nomi
# diversi per le stesse cose: una dice «Financial Services» e «Healthcare», l'altra «Banking» e
# «Biotechnology». Senza questa tabella il collegamento all'ETF settoriale falliva in silenzio, e il
# contesto del settore restava vuoto — misurato sui dati veri del 21/08/2026: 10 nomi su 19 non
# venivano riconosciuti, e solo 8 occasioni su 22 avevano il settore a verbale. Cioè «com'era il
# settore» — una delle cose che l'archivio deve registrare — mancava su due terzi delle righe.
_SETTORI_ALIAS = {
    "banking": "Financial Services", "banks": "Financial Services",
    "insurance": "Financial Services", "financial": "Financial Services",
    "financials": "Financial Services", "capital markets": "Financial Services",
    "biotechnology": "Healthcare", "pharmaceuticals": "Healthcare",
    "health care": "Healthcare", "healthcare": "Healthcare",
    "medical devices": "Healthcare", "life sciences": "Healthcare",
    "metals & mining": "Basic Materials", "chemicals": "Basic Materials",
    "steel": "Basic Materials", "paper & forest": "Basic Materials",
    "logistics & transportation": "Industrials", "transportation": "Industrials",
    "aerospace & defense": "Industrials", "construction": "Industrials",
    "machinery": "Industrials", "airlines": "Industrials",
    "industrial conglomerates": "Industrials", "business services": "Industrials",
    "media": "Communication Services", "telecommunication": "Communication Services",
    "telecommunications": "Communication Services", "entertainment": "Communication Services",
    "retail": "Consumer Cyclical", "retailing": "Consumer Cyclical",
    "automobiles": "Consumer Cyclical", "hotels, restaurants & leisure": "Consumer Cyclical",
    "textiles apparel & luxury goods": "Consumer Cyclical", "apparel": "Consumer Cyclical",
    "food, beverage & tobacco": "Consumer Defensive", "beverages": "Consumer Defensive",
    "food products": "Consumer Defensive", "household products": "Consumer Defensive",
    "tobacco": "Consumer Defensive", "consumer staples": "Consumer Defensive",
    "semiconductors": "Technology", "software": "Technology", "hardware": "Technology",
    "information technology": "Technology", "technology services": "Technology",
    "energy": "Energy", "oil & gas": "Energy", "utilities": "Utilities",
    "real estate": "Real Estate", "reits": "Real Estate",
}
# Nomi che significano «non lo sappiamo»: non sono settori sconosciuti, sono assenze dichiarate.
_SETTORI_VUOTI = {"", "n/a", "na", "none", "unknown", "-", "—", "other", "altro"}


def settore_canonico(nome) -> str:
    """Il nome standard del settore, quello che ha un ETF di riferimento. Ritorna "" se non si sa.
    Serve a non perdere il contesto settoriale solo perché la fonte usa un sinonimo."""
    s = str(nome or "").strip()
    if not s or s.lower() in _SETTORI_VUOTI:
        return ""
    if s in _SETTORI_ETF:
        return s
    diretto = _SETTORI_ALIAS.get(s.lower())
    if diretto:
        return diretto
    # ultimo tentativo: una parola chiave contenuta nel nome (es. «Regional Banks» → banche)
    b = s.lower()
    for chiave, canonico in _SETTORI_ALIAS.items():
        if chiave in b or b in chiave:
            return canonico
    return ""

# Le caratteristiche del titolo che finiscono nel profilo. NON ci sono spark/spark_dates (60 prezzi
# più 60 date): triplicherebbero il peso della riga e il grafico si ricostruisce dallo storico
# quando serve. Tutto il resto di opportunity_row c'è, perché è esattamente ciò che oggi viene
# calcolato a ogni giro e poi buttato.
_PROF_TITOLO = (
    "price", "rsi", "dd_high", "perf_5d", "perf_1m", "perf_1y", "below_bb", "above_sma200",
    "rebound_pot", "sharpe", "sortino", "ulcer", "maxdd", "hist_z", "atr", "atr_pct", "rr",
    "rvol", "avg_dollar_vol", "green_day", "rsi_rising", "back_in_bb", "reversal_confirmed",
    "vertical_crash", "target_price", "stop_price", "bench_5d", "bench_1m",
    "etf", "sector", "industry", "pe", "pb", "ps", "fscore", "fscore_health", "roic", "ev_ebit",
    "fcf_yield", "gross_m", "interest_cov", "div_cov", "rev_cagr3", "eps_cagr3",
)
_PROF_PUNTEGGI = ("prob_gain", "prob_loss", "exp_ret", "reliab", "reliab_factor")

# I motivi di scarto, con il nome che appare nell'archivio e la spiegazione in italiano. Vanno
# catturati NELL'ISTANTE dello scarto: a posteriori 1.377 scarti su 2.826 non sono ricostruibili dai
# soli dati che oggi si salvano, quindi senza questo non si scopre mai se è il filtro a sbagliare.
MOTIVI_SCARTO = {
    "prezzo_basso": "prezzo sotto il minimo: sui titoli da pochi centesimi gli indicatori non tengono",
    "poco_scambiato": "troppo pochi scambi al giorno: non ci si entra e non ci si esce",
    "punteggio_basso": "il punteggio dell'occasione è sotto il minimo",
    "sconto_insufficiente": "non è scesa abbastanza dai suoi massimi: non è un'occasione, è un titolo caro",
    "rischio_rendimento": "quello che si rischia è troppo rispetto a quello che si può guadagnare",
    "cade_piu_del_mercato": "in un mercato teso sta scendendo molto più dell'indice: coltello che cade",
    "trappola_di_valore": "sembra a sconto ma i conti stanno peggiorando: trappola",
    "troppi_dello_stesso_settore": "già scelte altre dello stesso settore, questa è in eccesso",
    "convenienza_sotto_cancello": "non ha raggiunto la convenienza minima per entrare in osservazione",
    # Questi due non hanno un profilo da registrare, e sono qui proprio per questo: erano i due
    # buchi dell'archivio, e una riga che dice «di questa non sappiamo niente, ed ecco perché» vale
    # infinitamente più di un nome che sparisce senza lasciare traccia. Così i punti ciechi si
    # contano invece di essere scoperti fra un anno.
    "storico_insufficiente": "meno di 60 giorni di storia, oppure prezzo non disponibile: le "
                             "caratteristiche non si possono nemmeno calcolare",
    "mai_guardata": "oltre il tetto dell'universo: il sistema non l'ha nemmeno aperta, quindi di "
                    "lei non esiste alcun dato",
    "profilo_non_ricostruibile": "il momento d'acquisto e a verbale nel diario ma le sue "
                                 "caratteristiche non sono state registrate e non si riesce piu a "
                                 "ricostruirle: un giro interrotto, e il dato non torna",
}
# I motivi per cui non esiste un profilo: la riga porta solo il nome e il perché.
MOTIVI_SENZA_PROFILO = ("storico_insufficiente", "mai_guardata",
                        "profilo_non_ricostruibile")

_BUFFER_PROFILI = []      # righe in attesa: si scrive UNA volta per giro, non una per titolo
_BUFFER_NOTIZIE = []      # idem per le notizie
_NOTIZIE_CHIESTE = set()  # (ticker, giorno) già chiesti in questo processo
_NOTIZIE_SPESE = [0]      # contatore del budget di questo giro


_ERRORI_INGHIOTTITI = []      # gli except muti che hanno avuto qualcosa da dire


def _log_silenzioso(msg: str) -> None:
    """Annota un errore che altrimenti sparirebbe in un `except: pass`.

    Non e' un vezzo: un except muto ha nascosto per giorni un difetto che svuotava il giudizio su
    TUTTE le righe dei momenti d'acquisto (42 su 42). Un errore che non lascia traccia non e' un
    errore gestito, e' un errore invisibile. Qui resta in memoria per il giro e il lavoro automatico
    lo stampa alla fine."""
    try:
        _ERRORI_INGHIOTTITI.append("%s  %s" % (_arc_ora(), str(msg)[:300]))
        del _ERRORI_INGHIOTTITI[:-50]
    except Exception:
        pass


def _arc_oggi() -> str:
    return datetime.date.today().isoformat()


def _arc_ora() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _arc_nome(prefisso: str, giorno: str, pezzo: int = 0) -> str:
    """Il nome del file di un giorno. Il pezzo oltre il primo prende un suffisso (_b, _c…): serve
    solo al giorno anomalo, perché un giorno normale ci sta largo in un pezzo solo."""
    coda = "" if pezzo <= 0 else "_" + chr(ord("b") + pezzo - 1)
    return f"{prefisso}/{giorno}{coda}.json"


def indice_archivio() -> dict:
    """Cosa contiene l'archivio: per ogni file, quante righe ha. È la fonte che permette di
    distinguere «questo file non esiste ancora» da «la lettura è fallita» — due situazioni che
    read_data_json restituisce in modo IDENTICO (lista vuota) e che nessuna guardia basata sul
    confronto delle lunghezze potrà mai separare. Senza questa distinzione, un archivio nuovo nasce
    esposto esattamente all'incidente che ha azzerato due registri il 16/08/2026."""
    d = read_data_json(INDICE_NAME, None)
    return d if isinstance(d, dict) else {}


def _indice_scrivi(indice: dict) -> bool:
    """L'indice è sotto archivio/, quindi la guardia anti-riduzione lo protegge da sola: se una
    lettura fallita lo facesse rimpicciolire, la scrittura viene rifiutata."""
    return write_data_json(INDICE_NAME, indice)


def _indice_o_niente():
    """L'indice, oppure None se non si riesce a stabilire lo stato dell'archivio.

    Qui sta il nodo di tutta la faccenda. «Il file non esiste ancora» e «la lettura è fallita»
    arrivano identici — lista o dizionario vuoti — e nessun confronto potrà distinguerli. La prova
    che li separa è provare a CREARE l'indice vuoto: se l'archivio è davvero nuovo la creazione
    passa; se invece l'indice esiste e la lettura era fallita, scriverne uno vuoto lo
    RIMPICCIOLIREBBE, e la guardia anti-riduzione rifiuta la scrittura da sola. In quel caso si
    torna None e non si scrive niente. Costa un giro di archivio; l'alternativa costa l'archivio."""
    d = read_data_json(INDICE_NAME, None)
    if isinstance(d, dict) and d:
        return d
    # NON BASTA che write_data_json dica "riuscito": dice riuscito anche col solo successo LOCALE,
    # e nel lavoro automatico il file locale muore col giro. Se la guardia remota ha rifiutato ma il
    # locale e passato, la rilettura (che a quel punto legge il locale) trova l'indice appena
    # scritto con una chiave sola: un indice "vuoto ma valido" che spegnerebbe tutte e tre le
    # regole di _arc_aggiungi proprio nel momento in cui servono.
    if (not write_data_json(INDICE_NAME, {"_creato": _arc_ora()})
            or INDICE_NAME in _SALVATAGGI_FALLITI):
        return None     # rifiutata, o arrivata solo in locale: non so cosa contiene l'archivio
    d = read_data_json(INDICE_NAME, None)
    return d if isinstance(d, dict) and d else None


def _arc_aggiungi(prefisso: str, righe_nuove: list, chiave=None, giorno: str = None) -> dict:
    """Aggiunge righe al file di OGGI di un archivio, senza poter cancellare niente.

    Restituisce {"scritte": n, "salvate": bool, "motivo": str|None}. In caso di dubbio NON scrive:
    un giro senza archivio costa una manciata di righe, un giro che scrive sopra lo storico costa
    l'archivio. Le tre regole:
      1. se l'indice non si legge, non si scrive niente (l'indice è minuscolo: un suo fallimento è
         un problema di rete vero, non un caso limite);
      2. se il file del giorno non si legge MA l'indice dice che ha righe, si annulla: è
         esattamente la sequenza che cancella gli storici;
      3. si scrive solo il giorno corrente; i giorni chiusi non si riaprono mai.
    """
    if not righe_nuove:
        return {"scritte": 0, "salvate": True, "motivo": None}
    giorno = giorno or _arc_oggi()
    indice = _indice_o_niente()
    if indice is None:
        return {"scritte": 0, "salvate": False,
                "motivo": "non riesco a leggere l'indice dell'archivio: non scrivo niente, "
                          "perché senza indice non posso sapere cosa c'è già"}
    def apri(pezzo):
        """Legge un pezzo del giorno. Ritorna (righe, errore): righe=None se non si deve toccare."""
        nome = _arc_nome(prefisso, giorno, pezzo)
        atteso = (indice.get(nome) or {}).get("righe")
        letto = read_data_json(nome, None)
        if letto is None:
            if atteso:
                return nome, None, (f"lettura di {nome} fallita ma l'indice dice {atteso} righe: "
                                    "non scrivo per non cancellare lo storico")
            return nome, [], None
        if not isinstance(letto, list):
            return nome, None, f"{nome} non contiene una lista"
        if atteso and len(letto) < atteso:
            return nome, None, (f"{nome} ha {len(letto)} righe ma l'indice ne conta {atteso}: "
                                "lettura incompleta, non scrivo")
        return nome, letto, None

    # 1. SI LEGGONO TUTTI I PEZZI DEL GIORNO, non solo fino al primo con posto.
    #
    # Qui c'era un difetto grave. «Dove scrivo» e «fin dove leggo» erano la stessa cosa: il ciclo si
    # fermava al primo pezzo con posto, quindi le chiavi dei pezzi successivi non venivano mai
    # lette. Un pezzo si chiude ANCHE per il tetto dei byte, e in quel caso resta sotto il tetto
    # delle righe: da quel momento il controllo anti-doppione non vedeva più il pezzo _b, e a ogni
    # giro (uno ogni mezz'ora) le stesse righe venivano riscritte come se fossero nuove. Le
    # statistiche avrebbero contato la stessa occasione molte volte.
    # E per i PROFILI il caso non è raro, è la regola: una riga pesa ~1.400 byte, quindi il tetto
    # dei byte (600 KB) scatta intorno alle 429 righe, sempre PRIMA di quello delle righe (450).
    # Quindi: prima si raccolgono le chiavi di ogni pezzo esistente, poi si cerca dove scrivere.
    pezzi_noti = sorted({p for p in range(25)
                         if _arc_nome(prefisso, giorno, p) in indice} | {0})
    viste, primo_con_posto, nome, esistenti = set(), None, None, []
    for p in pezzi_noti:
        n_p, righe_p, err = apri(p)
        if err:
            return {"scritte": 0, "salvate": False, "motivo": err}
        if chiave:
            viste |= {chiave(r) for r in righe_p}
        if primo_con_posto is None and len(righe_p) < _ARC_TETTO_RIGHE:
            primo_con_posto, nome, esistenti = p, n_p, righe_p
    if primo_con_posto is None:
        # tutti i pezzi noti sono pieni: si apre il primo successivo
        pezzo = min(pezzi_noti[-1] + 1, 24)
        nome, esistenti, err = apri(pezzo)
        if err:
            return {"scritte": 0, "salvate": False, "motivo": err}
        if chiave:
            viste |= {chiave(r) for r in esistenti}
    else:
        pezzo = primo_con_posto

    da_aggiungere = []
    for r in righe_nuove:
        k = chiave(r) if chiave else None
        if k is not None and k in viste:
            continue
        if k is not None:
            viste.add(k)
        da_aggiungere.append(r)
    if not da_aggiungere:
        return {"scritte": 0, "salvate": True, "motivo": None}

    # 2. si riempie pezzo per pezzo, e nessun pezzo può superare i tetti. Il controllo va fatto
    # sull'ESITO della scrittura, non sul punto di partenza: un blocco di righe scavalcherebbe in
    # un colpo un tetto controllato solo all'inizio, ed è precisamente il muro di 1 MB — che non dà
    # errore, spegne le protezioni anti-cancellazione e non lo dice a nessuno.
    scritte, rimaste = 0, list(da_aggiungere)
    while rimaste:
        posto = max(0, _ARC_TETTO_RIGHE - len(esistenti))
        if posto == 0 and pezzo < 24:
            pezzo += 1
            nome, esistenti, err = apri(pezzo)
            if err:
                return {"scritte": scritte, "salvate": False, "motivo": err}
            continue
        lotto = rimaste[:posto] if posto else rimaste
        # taglia il lotto finché il file che ne risulta sta sotto il tetto dei byte
        while lotto:
            corpo = json.dumps(esistenti + lotto, ensure_ascii=False, indent=0)
            if len(corpo.encode("utf-8")) <= _ARC_TETTO_BYTE or len(lotto) == 1:
                break
            lotto = lotto[:max(1, len(lotto) // 2)]
        tutte = esistenti + lotto
        if not write_data_json(nome, tutte):
            return {"scritte": scritte, "salvate": False,
                    "motivo": f"scrittura di {nome} non riuscita"}
        if nome in _SALVATAGGI_FALLITI:
            # La risposta positiva non basta: write_data_json dice «riuscito» anche col solo
            # successo locale, e nel lavoro automatico il file locale muore col giro.
            return {"scritte": scritte, "salvate": False,
                    "motivo": f"{nome} salvato solo in locale: il commit remoto non è passato"}
        indice[nome] = {"righe": len(tutte), "aggiornato": _arc_ora()}
        # L'esito dell'indice va guardato come quello del file: se le righe arrivano al deposito ma
        # l'indice no, quel file diventa INVISIBILE a chi legge (tutti i lettori enumerano
        # dall'indice) e resta senza la guardia che lo protegge dalla riscrittura. Meglio fermarsi e
        # riprovare al giro dopo, con le righe che restano in coda.
        if not _indice_scrivi(indice) or INDICE_NAME in _SALVATAGGI_FALLITI:
            return {"scritte": scritte, "salvate": False,
                    "motivo": f"{nome} e stato salvato ma l'elenco dell'archivio non e arrivato al "
                              "deposito: mi fermo, altrimenti quel file resterebbe invisibile"}
        scritte += len(lotto)
        rimaste = rimaste[len(lotto):]
        if rimaste:
            if pezzo >= 24:
                return {"scritte": scritte, "salvate": False,
                        "motivo": f"il giorno {giorno} ha esaurito i pezzi disponibili"}
            pezzo += 1
            nome, esistenti, err = apri(pezzo)
            if err:
                return {"scritte": scritte, "salvate": False, "motivo": err}
    return {"scritte": scritte, "salvate": True, "motivo": None}


def _arc_leggi_giorni(prefisso: str, dal: str = None, al: str = None) -> list:
    """Rilegge un archivio enumerando l'indice — non elencando cartelle, che sul ramo remoto non si
    possono elencare. Perciò l'indice va tenuto aggiornato: è la mappa dell'archivio."""
    fuori = []
    for nome in sorted(indice_archivio()):
        if not nome.startswith(prefisso + "/"):
            continue
        g = os.path.basename(nome)[:10]
        if (dal and g < dal) or (al and g > al):
            continue
        righe = read_data_json(nome, None)
        if isinstance(righe, list):
            fuori += righe
    return fuori


# --- COM'ERA IL MONDO -------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def _serie_mondo(simbolo: str) -> dict:
    """Valore e variazioni di un indicatore del mondo. Una chiamata, poi calcolo locale."""
    try:
        c = get_history(simbolo, period="6mo")["Close"].dropna()
    except Exception:
        return {}
    if c.empty:
        return {}
    ultimo = float(c.iloc[-1])

    def var(n):
        return round(float(c.iloc[-1] / c.iloc[-n] - 1) * 100, 2) if len(c) > n else None

    return {"valore": round(ultimo, 4), "var_5g": var(6), "var_1m": var(21), "var_3m": var(63)}


def contesto_mondo(giorno: str = None) -> dict:
    """Com'era il mondo oggi: paura, indici, tassi, dollaro, materie prime, credito. Una riga al
    giorno, condivisa da tutte le occasioni di quella giornata — è il motivo per cui non finisce
    dentro ogni riga di profilo: scriverla 200 volte al giorno significherebbe sfondare i limiti e,
    peggio, non poter mai aggiungere un indicatore nuovo senza riscrivere la storia."""
    giorno = giorno or _arc_oggi()
    dati = {"giorno": giorno, "ora": _arc_ora()}
    for chiave, simbolo, _etichetta in _MONDO_SIMBOLI:
        dati[chiave] = _serie_mondo(simbolo)
    try:
        reg = volatility_regime()
        dati["regime"] = {"etichetta": reg.get("label"), "fattore": reg.get("factor"),
                          "vix": reg.get("vix")}
    except Exception:
        dati["regime"] = {}
    # curva dei tassi: differenza fra 10 anni e 3 mesi. Negativa = mercato che teme la recessione,
    # ed è uno dei pochi segnali con una storia lunga alle spalle.
    try:
        d10 = (dati.get("tasso_10a") or {}).get("valore")
        d3m = (dati.get("tasso_3m") or {}).get("valore")
        dati["curva_tassi"] = round(d10 - d3m, 3) if (d10 is not None and d3m is not None) else None
    except Exception:
        dati["curva_tassi"] = None
    return dati


def contesto_settori(giorno: str = None) -> list:
    """Come stanno gli 11 settori: quanto si muovono e quanto vanno meglio o peggio dell'indice.
    È così che «il settore era in crisi» diventa un numero verificabile."""
    giorno = giorno or _arc_oggi()
    sp = _serie_mondo("^GSPC")
    fuori = []
    for nome, etf in sorted(_SETTORI_ETF.items()):
        s = _serie_mondo(etf)
        if not s:
            continue
        riga = {"giorno": giorno, "settore": nome, "etf": etf, "ora": _arc_ora()}
        riga.update(s)
        for periodo in ("var_5g", "var_1m", "var_3m"):
            mio, suo = s.get(periodo), sp.get(periodo)
            riga["forza_" + periodo] = (round(mio - suo, 2)
                                        if (mio is not None and suo is not None) else None)
        fuori.append(riga)
    return fuori


def ampiezza_mercato(righe) -> dict:
    """Quanti dei titoli guardati stanno salendo e quanti scendendo. Non esiste da nessuna parte nel
    sistema, ma si ricava a COSTO ZERO da quello che la scansione ha già in mano: è la differenza
    fra «è scesa lei» e «è scesa tutta la borsa», che è la domanda da cui dipende metà del giudizio
    su un'occasione."""
    vals = [r for r in (righe or []) if isinstance(r, dict)]
    if not vals:
        return {}
    def conta(campo):
        xs = [r.get(campo) for r in vals if r.get(campo) is not None]
        if not xs:
            return {}
        su = sum(1 for x in xs if x > 0)
        return {"quanti": len(xs), "in_salita": su, "in_salita_pct": round(100 * su / len(xs), 1),
                "mediana": round(float(np.median(xs)), 2)}
    rsi = [r.get("rsi") for r in vals if r.get("rsi") is not None]
    return {"a_5_giorni": conta("perf_5d"), "a_1_mese": conta("perf_1m"),
            "rsi_mediano": round(float(np.median(rsi)), 1) if rsi else None,
            "titoli_guardati": len(vals)}


# --- LE NOTIZIE -------------------------------------------------------------

_NOTIZIE_IN_ARCHIVIO = {}     # giorno -> insieme dei titoli che hanno gia le notizie


def _gia_ha_notizie(giorno: str, ticker: str) -> bool:
    """Se quel titolo ha già le notizie di quel giorno in archivio. Legge l'archivio UNA volta per
    giro e poi tiene il risultato in memoria: senza questo sarebbe una lettura per titolo."""
    if giorno not in _NOTIZIE_IN_ARCHIVIO:
        try:
            _NOTIZIE_IN_ARCHIVIO[giorno] = {
                str(n.get("ticker")).upper()
                for n in _arc_leggi_giorni(ARC_NOTIZIE, dal=giorno, al=giorno)
                if isinstance(n, dict) and n.get("ticker")}
        except Exception:
            _NOTIZIE_IN_ARCHIVIO[giorno] = set()
    # anche quelle appena messe in coda in questo giro contano come già fatte
    in_coda = {str(n.get("ticker")).upper() for n in _BUFFER_NOTIZIE
               if isinstance(n, dict) and n.get("giorno") == giorno}
    return ticker in (_NOTIZIE_IN_ARCHIVIO[giorno] | in_coda)


# I NOMI DELLE CARATTERISTICHE IN ITALIANO. Stanno qui e non nell'interfaccia perche' li usano piu
# schede: la tabella dell'apprendimento, il profilo di una singola occasione e i pezzi del giudizio.
# Servono a rispondere alla domanda per cui l'archivio esiste — «che aspetto hanno le occasioni che
# guadagnano» — e una tabella che risponde con «avg_dollar_vol» e «histcheap» non risponde.
NOMI_CARATTERISTICHE = {
    # com'era il titolo
    "price": "Prezzo", "rsi": "Forza del prezzo (RSI)", "dd_high": "Quanto è scesa dai massimi",
    "perf_5d": "Ultimi 5 giorni", "perf_1m": "Ultimo mese", "perf_1y": "Ultimo anno",
    "hist_z": "Rispetto alla sua media storica", "sortino": "Qualità della salita",
    "ulcer": "Quanto ha fatto soffrire", "maxdd": "La caduta peggiore",
    "sharpe": "Rendimento contro rischio", "atr": "Movimento tipico in valuta",
    "atr_pct": "Movimento tipico giornaliero", "rr": "Rischio contro rendimento",
    "rvol": "Scambi rispetto al solito", "avg_dollar_vol": "Quanto viene scambiata al giorno",
    "rebound_pot": "Rimbalzo possibile", "above_sma200": "Sopra la media a 200 giorni",
    "below_bb": "Sotto la banda bassa", "green_day": "Giornata in verde",
    "rsi_rising": "Forza in risalita", "back_in_bb": "Rientrata nelle bande",
    "reversal_confirmed": "Inversione confermata", "vertical_crash": "Crollo verticale",
    "target_price": "Bersaglio", "stop_price": "Prezzo di uscita",
    "bench_5d": "L'indice negli ultimi 5 giorni", "bench_1m": "L'indice nell'ultimo mese",
    "pe": "Prezzo sugli utili", "pb": "Prezzo sul patrimonio", "ps": "Prezzo sui ricavi",
    "fscore": "Solidità dei conti", "fscore_health": "Salute dei conti",
    "roic": "Redditività del capitale", "ev_ebit": "Valore sull'utile operativo",
    "fcf_yield": "Cassa generata sul prezzo", "gross_m": "Margine lordo",
    "interest_cov": "Copertura degli interessi", "div_cov": "Copertura del dividendo",
    "rev_cagr3": "Crescita dei ricavi (3 anni)", "eps_cagr3": "Crescita degli utili (3 anni)",
    "sector": "Settore", "industry": "Industria", "etf": "È un ETF",
    # i punteggi
    "prob_gain": "Probabilità di salita", "prob_loss": "Rischio di perdita",
    "exp_ret": "Rendimento atteso", "reliab": "Affidabilità del dato",
    "reliab_factor": "Quanto è affidabile il dato",
    # i pezzi del giudizio
    "discount": "Quanto è a sconto", "histcheap": "Sotto la sua media storica",
    "riskadj": "Qualità della salita", "ddpen": "Quanto ha fatto soffrire",
    "momentum": "Spinta recente", "prob": "Probabilità netta",
    "oversold": "Quanto è ipervenduta", "rebound": "Rimbalzo possibile",
    "trend": "Sopra la media a 200 giorni", "relstrength": "Forza contro l'indice",
    "quality": "Qualità dei conti", "valcheap": "Multipli bassi per il suo settore",
    "trappen": "Segnali di trappola",
}


def nome_caratteristica(k) -> str:
    """Il nome in italiano di una caratteristica, o la chiave se non e' ancora tradotta."""
    return NOMI_CARATTERISTICHE.get(str(k), str(k))


def testo_sicuro(t) -> str:
    """Rende innocuo un testo che arriva da internet, prima di mostrarlo nell'app.

    I titoli delle notizie sono scritti da altri e finiscono in st.markdown, che interpreta i
    metacaratteri: due simboli di dollaro attorno a un pezzo di frase diventano una formula e i
    prezzi SPARISCONO dalla pagina. Misurato sui dati veri: 34 campi su 338 (il 10%) contengono due
    o piu dollari, e altri contengono asterischi e parentesi quadre. Non e' un problema di sicurezza
    grave — e' che la notizia mostrata non e' piu quella salvata, e chi legge non lo sa."""
    x = str(t or "")
    for c in ("\\", "$", "*", "_", "[", "]", "`", "~"):
        x = x.replace(c, "\\" + c)
    return x


def registra_notizie(ticker: str, giorno: str = None, forza: bool = False) -> int:
    """Salva le notizie di un titolo COL RIASSUNTO, così che fra un anno si possa capire perché quel
    giorno il prezzo era quello. Va fatto il giorno stesso: una ricerca fatta dopo restituisce cose
    diverse e, soprattutto, restituisce anche quello che è successo DOPO — cioè bara.

    Il budget è la ragione per cui esiste il tetto: senza, sarebbero ~3.000 chiamate al giorno in
    raffiche. Il limite vero di Finnhub non è scritto nel codice, quindi non lo si indovina: si
    tiene un tetto proprio e prudente, e chi lo supera aspetta il giro dopo invece di ricevere
    silenzio (che è quello che accade oggi: superata la quota, le notizie diventano [] e nessuno lo
    viene a sapere)."""
    giorno = giorno or _arc_oggi()
    TK = str(ticker).upper()
    if (TK, giorno) in _NOTIZIE_CHIESTE:
        return 0
    # IL RICORDO DEVE DURARE PIU DEL PROCESSO. _NOTIZIE_CHIESTE vive solo dentro un giro: al giro
    # dopo il sistema ripartiva dai primi titoli della lista e ribruciava il budget su quelli che
    # avevano GIA le notizie, quindi la coda non le riceveva mai. Misurato sui dati veri del
    # 21/08/2026: 34 titoli con notizie su 100 visti, tutte richieste fra le 8 e le 9 del mattino —
    # una quarantina di giri successivi non ne hanno aggiunta nessuna. Chiedere all'archivio chi ce
    # le ha già costa una lettura per giro e fa arrivare il budget a chi non e ancora servito.
    if _gia_ha_notizie(giorno, TK):
        _NOTIZIE_CHIESTE.add((TK, giorno))
        return 0
    if not forza and _NOTIZIE_SPESE[0] >= _NOTIZIE_PER_GIRO:
        return 0
    _NOTIZIE_CHIESTE.add((TK, giorno))
    _NOTIZIE_SPESE[0] += 1
    try:
        news = get_news(TK, _NOTIZIE_PER_TITOLO) or []
    except Exception:
        news = []
    if not news:
        return 0
    voci = []
    for n in news[:_NOTIZIE_PER_TITOLO]:
        testo = (n.get("summary") or "").strip()
        voci.append({"titolo": (n.get("title") or "").strip(),
                     "riassunto": testo[:_NOTIZIE_MAX_RIASSUNTO],
                     "riassunto_tagliato": len(testo) > _NOTIZIE_MAX_RIASSUNTO,
                     "fonte": n.get("publisher"), "data": n.get("date"), "url": n.get("url")})
    try:
        etichetta, punteggio = news_sentiment(news)
    except Exception:
        etichetta, punteggio = None, None
    try:
        bandiere = news_red_flags(news)
    except Exception:
        bandiere = []
    riga = {"giorno": giorno, "ticker": TK, "ora": _arc_ora(), "quante": len(voci),
            "tono": etichetta, "tono_punteggio": punteggio, "bandiere_rosse": bandiere,
            "notizie": voci}
    # In coda, non su disco: venti titoli in un giro sarebbero venti letture-e-riscritture dello
    # stesso file, cioè quaranta chiamate all'API per niente. Si scrive una volta alla fine.
    _BUFFER_NOTIZIE.append(riga)
    return len(voci)


def notizie_del_giorno(ticker: str, giorno: str = None) -> dict:
    giorno = giorno or _arc_oggi()
    TK = str(ticker).upper()
    for nome in sorted(indice_archivio()):
        if not nome.startswith(ARC_NOTIZIE + "/") or os.path.basename(nome)[:10] != giorno:
            continue
        for r in (read_data_json(nome, None) or []):
            if r.get("ticker") == TK:
                return r
    return {}


# --- IL PROFILO DI UN'OCCASIONE --------------------------------------------

def _profilo_id(giorno, kind, ticker, momento) -> str:
    return f"{giorno}:{kind}:{str(ticker).upper()}:{momento or 'scartata'}"


def profilo_da_riga(r: dict, kind: str, momento: str = None, episodio: str = None,
                    motivo: str = None, dettaglio=None, conv=None, occasione=None,
                    fattori: dict = None, mondo: dict = None, origine: str = None,
                    giorno: str = None) -> dict:
    """Costruisce la riga di profilo da un record di opportunity_row. Tutte le caratteristiche che
    oggi il sistema calcola a ogni giro e poi butta finiscono qui, raggruppate in modo che aprendo
    il file si capisca cosa si sta guardando."""
    giorno = giorno or _arc_oggi()
    tk = str(r.get("ticker") or "").upper()
    titolo = {k: r.get(k) for k in _PROF_TITOLO if r.get(k) is not None}
    trappola = r.get("trap") or {}
    prof = {
        # NELL'IDENTIFICATIVO CI VA IL MOTIVO, non un generico «scartata». I doppioni si scartano
        # per identificativo: senza il motivo, di un titolo bocciato due volte nello stesso giorno
        # per ragioni DIVERSE sopravviveva solo la prima, e la distribuzione dei motivi — cioe' il
        # dato per cui le bocciature si registrano — risultava storta. Misurato: 36 titoli su 124
        # bocciature del 21/08 compaiono piu di una volta nello stesso giorno.
        "id": _profilo_id(giorno, kind, tk, momento or motivo),
        "giorno": giorno, "ora": _arc_ora(), "ticker": tk, "nome": r.get("name"),
        "kind": kind, "momento": momento, "episodio": episodio,
        "scartata": bool(motivo), "motivo": motivo, "motivo_dettaglio": dettaglio,
        "origine": origine,
        # IL COLLEGAMENTO ALLE NOTIZIE. Le notizie stanno in un archivio loro (pesano dieci volte
        # una riga di profilo e sono condivise da tutti i momenti dello stesso titolo nello stesso
        # giorno), ma il legame è scritto qui e non è un numero progressivo che si può disallineare:
        # è titolo + giorno, cioè due dati che la riga possiede già. apri_occasione() lo segue.
        "notizie_di": f"{giorno}:{tk}",
        "prezzo": r.get("price"),
        "titolo": titolo,
        "punteggi": {k: r.get(k) for k in _PROF_PUNTEGGI if r.get(k) is not None},
        "convenienza": conv, "occasione": occasione,
        "fattori": {k: (round(v, 4) if isinstance(v, float) else v)
                    for k, v in (fattori or {}).items() if v is not None},
        "trappola": {"etichetta": trappola.get("label"), "conclamata": trappola.get("strong"),
                     "segnali": trappola.get("signals")} if trappola else None,
        # DUE campi, non uno: «settore» e il nome esatto che la fonte ha dato (non si falsa un dato
        # alla fonte), «settore_gruppo» e il nome standard con cui si ritrova l'ETF di riferimento
        # negli archivi. Tenere solo il primo faceva fallire il collegamento in silenzio.
        "settore": r.get("sector"),
        "settore_gruppo": settore_canonico(r.get("sector")) or None,
        "mondo": mondo or {},
    }
    return prof


def mondo_minimo(mondo: dict = None, ampiezza: dict = None, settore_riga: dict = None) -> dict:
    """La copia essenziale del contesto dentro la riga di profilo: quattro numeri, perché una riga
    deve restare leggibile da sola senza dover aprire altri tre file. Il contesto COMPLETO sta nei
    suoi archivi, che è dove va guardato quando si vuole capire davvero."""
    m = mondo or {}
    out = {"paura": ((m.get("paura") or {}).get("valore")),
           "regime": ((m.get("regime") or {}).get("etichetta")),
           "sp500_1m": ((m.get("sp500") or {}).get("var_1m")),
           "curva_tassi": m.get("curva_tassi")}
    if ampiezza:
        out["titoli_in_salita_pct"] = (ampiezza.get("a_5_giorni") or {}).get("in_salita_pct")
    if settore_riga:
        out["settore_1m"] = settore_riga.get("var_1m")
        out["settore_forza_1m"] = settore_riga.get("forza_var_1m")
    return out


def accoda_profilo(prof: dict) -> None:
    """Mette una riga in coda. Si scrive UNA volta per giro (vedi scarica_profili): con ~135 scarti
    al giorno, salvare a ogni riga vorrebbe dire 135 letture-e-riscritture dello stesso file."""
    if prof:
        _BUFFER_PROFILI.append(prof)


def _scarica_coda(coda: list, prefisso: str, chiave) -> dict:
    """Svuota una coda sui file del giorno a cui ogni riga appartiene. Se il salvataggio non riesce
    le righe RESTANO in coda: un giro andato male non deve costare le sue righe."""
    if not coda:
        return {"scritte": 0, "in_coda": 0, "motivo": None}
    per_giorno = {}
    for p in coda:
        per_giorno.setdefault(p.get("giorno") or _arc_oggi(), []).append(p)
    scritte, problemi, rimaste = 0, [], []
    for giorno, righe in sorted(per_giorno.items()):
        esito = _arc_aggiungi(prefisso, righe, chiave=chiave, giorno=giorno)
        scritte += esito.get("scritte", 0)
        if not esito.get("salvate"):
            problemi.append(esito.get("motivo"))
            rimaste += righe
    del coda[:]
    coda.extend(rimaste)
    return {"scritte": scritte, "in_coda": len(rimaste),
            "motivo": ("; ".join(x for x in problemi if x) or None)}


def scarica_profili() -> dict:
    """Scrive in archivio tutto quello che è in coda — profili e notizie. Da chiamare una volta per
    giro, alla fine."""
    p = _scarica_coda(_BUFFER_PROFILI, ARC_PROFILI, lambda r: r.get("id"))
    n = _scarica_coda(_BUFFER_NOTIZIE, ARC_NOTIZIE,
                      lambda r: (r.get("giorno"), r.get("ticker")))
    motivi = [x for x in (p.get("motivo"), n.get("motivo")) if x]
    return {"scritte": p["scritte"], "notizie_scritte": n["scritte"],
            "in_coda": p["in_coda"] + n["in_coda"],
            "motivo": ("; ".join(motivi) or None)}


# --- COM'È ANDATA ----------------------------------------------------------

# Gli orizzonti su cui si misura l'esito. ATTENZIONE: nei registri vecchi convivono due unità di
# misura diverse — 5 e 21 giorni di BORSA nel registro della convenienza, 7 e 30 di CALENDARIO
# negli scenari. Mescolarle senza dirlo produce confronti falsi, quindi qui l'unità è scritta nel
# nome e nel campo `unita`.
ORIZZONTI_ESITO = (("7g", 7, "calendario"), ("30g", 30, "calendario"), ("365g", 365, "calendario"))


def _resa_e_percorso(ticker: str, dal: str, prezzo, giorni: int, storico=None) -> dict:
    """Com'è andata, e COME ci è arrivata. Il percorso conta quanto il traguardo: due occasioni che
    finiscono entrambe a +2% sono animali diversi se una è prima passata da +15% e l'altra da -12%.
    Senza il massimo e il minimo toccati, le regole di vendita non sono giudicabili — si misurerebbe
    il traguardo ignorando la corsa."""
    try:
        h = storico if storico is not None else get_history(ticker, "2y")
        if h is None or h.empty or prezzo in (None, 0):
            return {}
        c = h["Close"].dropna()
        idx = [str(x)[:10] for x in c.index]
        parti = [i for i, g in enumerate(idx) if g >= str(dal)[:10]]
        if not parti:
            return {}
        i0 = parti[0]
        # GUARDIA ANTI-FRAZIONAMENTO: dopo un raggruppamento di azioni lo storico è riscalato ma il
        # prezzo registrato no, e la resa risulta assurda (misurato +50.421% su un titolo). Le righe
        # fuori scala si MARCANO, non si cancellano: un dato sbagliato riconosciuto vale più di un
        # dato scomparso.
        p0 = float(c.iloc[i0])
        if abs(p0 / float(prezzo) - 1) > _SPLIT_TOLL:
            return {"dati_sospetti": True, "prezzo_storico": round(p0, 4)}
        fine = None
        limite = (datetime.date.fromisoformat(str(dal)[:10])
                  + datetime.timedelta(days=giorni)).isoformat()
        for i in range(i0, len(c)):
            if idx[i] <= limite:
                fine = i
            else:
                break
        if fine is None or fine <= i0:
            return {}
        # IL TITOLO QUOTA ANCORA FINO ALLA SCADENZA? Se ha smesso di quotare a metà finestra — un
        # delisting, un titolo sospeso — l'ultima chiusura disponibile è di settimane prima, e
        # attribuirla all'orizzonte intero significa dire «dopo 30 giorni ha reso questo» quando in
        # realtà il prezzo è fermo al giorno 6. Un esito falso è peggio di un esito mancante: qui la
        # riga si scrive comunque (il dato parziale è utile) ma DICHIARA fino a dove arriva.
        _ultimo = idx[fine]
        _giorni_reali = (datetime.date.fromisoformat(_ultimo)
                        - datetime.date.fromisoformat(str(dal)[:10])).days
        _incompleto = _ultimo < limite and _giorni_reali < giorni * 0.8
        tratto = c.iloc[i0:fine + 1].astype(float)
        pf = float(tratto.iloc[-1])
        pmax, pmin = float(tratto.max()), float(tratto.min())
        imax = int(tratto.values.argmax())
        imin = int(tratto.values.argmin())
        return {
            "resa": round((pf / float(prezzo) - 1) * 100, 2),
            "max_toccato": round((pmax / float(prezzo) - 1) * 100, 2),
            "min_toccato": round((pmin / float(prezzo) - 1) * 100, 2),
            "giorni_al_massimo": imax, "giorni_al_minimo": imin,
            "giorni_misurati": fine - i0, "prezzo_fine": round(pf, 4),
            "maturato_il": idx[fine],
            # quanto della finestra è stato davvero coperto, e se il titolo ha smesso di quotare
            "giorni_di_calendario_coperti": _giorni_reali,
            "finestra_incompleta": _incompleto,
            "ultima_quotazione": _ultimo,
        }
    except Exception:
        return {}


def risolvi_esiti(max_titoli: int = 60, recupero_giorni: int = 10) -> dict:
    """Calcola gli esiti maturati e li archivia come righe NUOVE nel giorno in cui maturano.
    Non riapre nessun file passato: è quello che rende impossibile perdere lo storico riscrivendolo.
    L'esito porta con sé la resa a scadenza, il massimo e il minimo toccati e in quanti giorni.

    LEGGE POCHISSIMO, di proposito. Gli esiti che maturano oggi appartengono a tre giornate precise
    — oggi meno 7, meno 30, meno 365 — quindi non c'è alcun bisogno di aprire tutto l'archivio: si
    aprono quelle. `recupero_giorni` allarga la finestra all'indietro perché il lavoro automatico
    salta dei giri (il 6 agosto non ha girato affatto): senza quel margine, un giorno saltato
    lascerebbe quelle occasioni senza esito per sempre."""
    oggi = _arc_oggi()
    oggi_d = datetime.date.fromisoformat(oggi)
    # le giornate di ACQUISTO che maturano adesso, per ciascun orizzonte
    interessanti = set()
    for _nome, gg, _u in ORIZZONTI_ESITO:
        for indietro in range(0, max(1, recupero_giorni) + 1):
            g = oggi_d - datetime.timedelta(days=gg + indietro)
            interessanti.add(g.isoformat())
    dal = min(interessanti)
    profili = [p for p in _arc_leggi_giorni(ARC_PROFILI, dal=dal, al=oggi)
               if isinstance(p, dict) and p.get("giorno") in interessanti]
    if not profili:
        return {"nuovi": 0, "in_attesa": 0, "titoli": 0}
    # gli esiti già scritti stanno nei giorni in cui sono maturati, cioè da poco: basta la finestra
    fatti = {(r.get("profilo"), r.get("orizzonte"))
             for r in _arc_leggi_giorni(
                 ARC_ESITI,
                 dal=(oggi_d - datetime.timedelta(days=max(1, recupero_giorni) + 3)).isoformat(),
                 al=oggi) if isinstance(r, dict)}
    da_fare = []
    for p in profili:
        giorno, prezzo = p.get("giorno"), p.get("prezzo")
        if not giorno or prezzo in (None, 0):
            continue
        for nome, gg, unita in ORIZZONTI_ESITO:
            if (p.get("id"), nome) in fatti:
                continue
            scade = (datetime.date.fromisoformat(giorno)
                     + datetime.timedelta(days=gg)).isoformat()
            if scade > oggi:
                continue
            da_fare.append((p, nome, gg, unita))
    per_titolo = {}
    for p, nome, gg, unita in da_fare:
        per_titolo.setdefault(p.get("ticker"), []).append((p, nome, gg, unita))
    nuove = []
    for i, (tk, lista) in enumerate(sorted(per_titolo.items())):
        if i >= max_titoli:
            break
        try:
            h = get_history(tk, "2y")
        except Exception:
            h = None
        for p, nome, gg, unita in lista:
            res = _resa_e_percorso(tk, p.get("giorno"), p.get("prezzo"), gg, storico=h)
            if not res:
                continue
            riga = {"giorno": oggi, "ora": _arc_ora(), "profilo": p.get("id"), "ticker": tk,
                    "kind": p.get("kind"), "momento": p.get("momento"),
                    "scartata": p.get("scartata"), "comprato_il": p.get("giorno"),
                    "prezzo_acquisto": p.get("prezzo"), "orizzonte": nome,
                    "giorni": gg, "unita": unita}
            riga.update(res)
            nuove.append(riga)
    esito = _arc_aggiungi(ARC_ESITI, nuove,
                          chiave=lambda r: (r.get("profilo"), r.get("orizzonte")))
    return {"nuovi": esito.get("scritte", 0), "in_attesa": len(da_fare) - len(nuove),
            "titoli": len(per_titolo), "motivo": esito.get("motivo")}


# --- COSA SE NE IMPARA ----------------------------------------------------

def _mediana(xs):
    xs = [float(x) for x in xs if x is not None]
    return round(float(np.median(xs)), 3) if xs else None


def sintesi_apprendimento(kind: str = None, orizzonte: str = "30g", momento: str = None,
                          solo_scartate: bool = None) -> dict:
    """Per ogni caratteristica: quanto valeva nelle occasioni che hanno guadagnato e quanto in
    quelle che hanno perso. Niente modello: una differenza fra due mediane, con il numero di casi
    accanto — perché è quello che dice se puoi crederci.

    Il campo `solidita` non è decorazione: con meno di 30 casi per lato qualunque differenza è
    compatibile col caso, e presentarla come scoperta è il modo più comune di sbagliare con i dati."""
    profili = {p.get("id"): p for p in _arc_leggi_giorni(ARC_PROFILI) if isinstance(p, dict)}
    esiti = [e for e in _arc_leggi_giorni(ARC_ESITI)
             if isinstance(e, dict) and e.get("orizzonte") == orizzonte
             and not e.get("dati_sospetti") and not e.get("finestra_incompleta")
             and e.get("resa") is not None]
    vinte, perse = [], []
    for e in esiti:
        p = profili.get(e.get("profilo"))
        if not p:
            continue
        if kind and p.get("kind") != kind:
            continue
        if momento and p.get("momento") != momento:
            continue
        if solo_scartate is True and not p.get("scartata"):
            continue
        if solo_scartate is False and p.get("scartata"):
            continue
        (vinte if e["resa"] > 0 else perse).append((p, e))
    caratteristiche = {}
    campi = [("titolo", k) for k in _PROF_TITOLO] + \
            [("punteggi", k) for k in _PROF_PUNTEGGI] + \
            [("fattori", k) for k in ("discount", "histcheap", "riskadj", "ddpen", "momentum",
                                      "prob", "oversold", "rebound", "trend", "relstrength",
                                      "quality", "valcheap", "trappen")]
    for gruppo, campo in campi:
        gv = [(p.get(gruppo) or {}).get(campo) for p, _ in vinte]
        gp = [(p.get(gruppo) or {}).get(campo) for p, _ in perse]
        gv = [x for x in gv if isinstance(x, (int, float)) and not isinstance(x, bool)]
        gp = [x for x in gp if isinstance(x, (int, float)) and not isinstance(x, bool)]
        if not gv or not gp:
            continue
        mv, mp = _mediana(gv), _mediana(gp)
        caratteristiche[campo] = {
            "gruppo": gruppo, "chi_guadagna": mv, "chi_perde": mp,
            "differenza": (round(mv - mp, 3) if (mv is not None and mp is not None) else None),
            "casi_guadagno": len(gv), "casi_perdita": len(gp),
            "solidita": ("da confermare" if min(len(gv), len(gp)) < 30 else
                         "indicativa" if min(len(gv), len(gp)) < 100 else "solida"),
        }
    ordinate = sorted(caratteristiche.items(),
                      key=lambda kv: abs(kv[1].get("differenza") or 0), reverse=True)
    return {"orizzonte": orizzonte, "kind": kind, "momento": momento,
            "quante_guadagnano": len(vinte), "quante_perdono": len(perse),
            "caratteristiche": dict(ordinate),
            "aggiornato": _arc_ora(),
            "avvertenza": ("Con meno di 30 casi per lato le differenze non sono distinguibili dal "
                           "caso: la colonna «solidità» dice a quali si può cominciare a credere.")}


def sintesi_pronta(kind: str = None, orizzonte: str = "30g") -> dict:
    """Le statistiche GIA CALCOLATE, dal file che il lavoro automatico tiene aggiornato.

    Serve all'app: sintesi_apprendimento rilegge l'intero archivio, e a un anno di distanza sarebbero
    centinaia di file scaricati a ogni clic su una scheda. Il lavoro automatico le ricalcola due
    volte al giorno; qui si legge il risultato. Se il file non c'e ancora — o non contiene la vista
    chiesta — si ricalcola una volta sola, cosi la scheda funziona comunque."""
    try:
        d = read_data_json(SINTESI_NAME, None) or {}
        v = ((d.get("viste") or {}).get(f"{kind}:{orizzonte}"))
        if v:
            return dict(v, calcolata_il=d.get("aggiornato"), da_file=True)
    except Exception:
        pass
    s = sintesi_apprendimento(kind=kind, orizzonte=orizzonte)
    s["da_file"] = False
    return s


def salva_sintesi(forza: bool = False, ogni_ore: int = 12) -> bool:
    """Ricalcola e salva le statistiche misurate. È il file piccolo che legge l'app: l'archivio
    grezzo sono centinaia di file, aprirli tutti a ogni caricamento di pagina non è sostenibile.

    Girando ogni mezz'ora questo conto rileggerebbe l'intero archivio 48 volte al giorno per
    ottenere quasi sempre lo stesso risultato: le mediane non cambiano perché sono arrivati due
    esiti. Si rifà due volte al giorno, e basta."""
    if not forza:
        try:
            vecchia = read_data_json(SINTESI_NAME, None) or {}
            q = str(vecchia.get("aggiornato") or "")
            if q:
                eta = datetime.datetime.now() - datetime.datetime.strptime(q, "%Y-%m-%d %H:%M")
                if eta.total_seconds() < ogni_ore * 3600:
                    return True     # ancora fresca: non c'è niente da rifare
        except Exception:
            pass
    fuori = {"aggiornato": _arc_ora(), "viste": {}}
    for kind in ("short", "long"):
        for oriz in ("7g", "30g", "365g"):
            s = sintesi_apprendimento(kind=kind, orizzonte=oriz)
            if s.get("quante_guadagnano") or s.get("quante_perdono"):
                fuori["viste"][f"{kind}:{oriz}"] = s
    return write_data_json(SINTESI_NAME, fuori)


def stato_archivio() -> dict:
    """A che punto è l'archivio: quanti file, quante righe, da quando. Serve perché «non si è perso
    niente» sia una cosa che si può VERIFICARE, non una che si deve sperare."""
    indice = indice_archivio()
    per_area = {}
    for nome, info in indice.items():
        if "/" not in nome or not isinstance(info, dict):
            continue                      # voci di servizio dell'indice (es. _creato)
        area = nome.rsplit("/", 1)[0]
        d = per_area.setdefault(area, {"file": 0, "righe": 0, "primo": None, "ultimo": None})
        d["file"] += 1
        d["righe"] += int((info or {}).get("righe") or 0)
        g = os.path.basename(nome)[:10]
        if len(g) == 10:
            d["primo"] = g if not d["primo"] else min(d["primo"], g)
            d["ultimo"] = g if not d["ultimo"] else max(d["ultimo"], g)
    return {"aree": per_area, "in_coda": len(_BUFFER_PROFILI),
            "notizie_in_coda": len(_BUFFER_NOTIZIE),
            "notizie_spese_in_questo_giro": _NOTIZIE_SPESE[0],
            "salvataggi_falliti": sorted(_SALVATAGGI_FALLITI)}


# --- IL CALENDARIO: COME SI SCRIVE E COME SI RILEGGE UNA GIORNATA ----------
# Ogni giornata è una cartella di file col nome del giorno. Scrivere i dati di oggi non può toccare
# nessun altro giorno, perché nessun altro giorno viene aperto. È la stessa cosa che si farebbe con
# un'agenda di carta: si scrive sulla pagina di oggi e le pagine di ieri restano dove sono.

_CONTESTO_FATTO = {}      # (giorno, kind) → contesto già preparato in questo processo


def _contesto_del_giorno(kind: str, righe: list, giorno: str = None) -> dict:
    """Prepara (e archivia, una volta al giorno) il contesto condiviso da tutte le occasioni di
    oggi: com'era il mondo, come stavano gli 11 settori, quanti titoli salivano. Costa 24 chiamate
    AL GIORNO in tutto, non per occasione: è la ragione per cui il contesto sta in archivi suoi e
    non copiato dentro ogni riga.

    La memoria per (giorno, tipo) non è un'ottimizzazione: senza, ogni singolo scarto rileggerebbe e
    riscriverebbe gli stessi due file del contesto, cioè centinaia di chiamate all'API per riscrivere
    le stesse righe."""
    giorno = giorno or _arc_oggi()
    _memo = (giorno, kind)
    if _memo in _CONTESTO_FATTO:
        return _CONTESTO_FATTO[_memo]
    # UN GIORNO PASSATO NON SI FOTOGRAFA OGGI. Da quando i momenti d'acquisto in ritardo ricevono la
    # data vera dell'evento (1-5 giorni prima, 64 casi su 82), questa funzione veniva chiamata con un
    # giorno passato — e contesto_mondo/contesto_settori leggono i mercati ADESSO, senza data. Il
    # risultato era la paura, gli indici e i settori di oggi scritti nel file di un giorno chiuso:
    # esattamente il difetto delle soglie costruite col futuro, sullo stesso percorso.
    # Per un giorno passato si LEGGE quello che era stato archiviato allora; se non c'e, il contesto
    # resta vuoto. Un contesto che manca si vede; un contesto sbagliato no.
    if giorno != _arc_oggi():
        try:
            _m = ([x for x in _arc_leggi_giorni(ARC_MONDO, dal=giorno, al=giorno)
                   if isinstance(x, dict)] or [{}])[0]
            _s = [x for x in _arc_leggi_giorni(ARC_SETTORI, dal=giorno, al=giorno)
                  if isinstance(x, dict)]
        except Exception:
            _m, _s = {}, []
        try:
            _o = origine_candidati(kind)
        except Exception:
            _o = {}
        ctx = {"giorno": giorno, "mondo": _m, "ampiezza": (_m.get("ampiezza_mercato") or {}),
               "origine": _o, "settori": {x.get("settore"): x for x in _s},
               "ricostruito_da_archivio": True, "contesto_mancante": not bool(_m)}
        _CONTESTO_FATTO[_memo] = ctx
        return ctx
    try:
        mondo = contesto_mondo(giorno)
    except Exception:
        mondo = {}
    try:
        settori = contesto_settori(giorno)
    except Exception:
        settori = []
    try:
        ampiezza = ampiezza_mercato(righe)
    except Exception:
        ampiezza = {}
    if mondo:
        m = dict(mondo)
        m["ampiezza_mercato"] = ampiezza
        _arc_aggiungi(ARC_MONDO, [m], chiave=lambda r: r.get("giorno"), giorno=giorno)
    if settori:
        _arc_aggiungi(ARC_SETTORI, settori,
                      chiave=lambda r: (r.get("giorno"), r.get("settore")), giorno=giorno)
    try:
        origine = origine_candidati(kind)
    except Exception:
        origine = {}
    ctx = {"giorno": giorno, "mondo": mondo, "ampiezza": ampiezza, "origine": origine,
           "settori": {s.get("settore"): s for s in settori}}
    _CONTESTO_FATTO[_memo] = ctx
    return ctx


def scarto_cancello_osservazione(kind: str, ticker: str, conv=None) -> bool:
    """Un'occasione che ha superato tutti i filtri tecnici ma NON la convenienza minima per entrare
    in osservazione. È una bocciatura diversa dalle altre — non ha un difetto, ha solo un giudizio
    troppo basso — ed è la più vicina al confine, quindi come contro-esempio è fra le più utili."""
    try:
        TK = str(ticker).upper()
        r = opportunity_row(TK, with_fundamentals=(kind == "long"))
        if not r:
            return False
        ctx = _contesto_del_giorno(kind, [r])
        prof = profilo_da_riga(
            r, kind, momento=None, motivo="convenienza_sotto_cancello",
            dettaglio=conv, conv=conv, mondo=_mondo_per_riga(r, ctx),
            origine=(ctx.get("origine") or {}).get(TK), giorno=ctx.get("giorno"))
        accoda_profilo(prof)
        return True
    except Exception:
        return False


def _prepara_contesto_scansione(kind: str, righe: list) -> dict:
    """Nome usato dalla scansione. Se qualcosa nel contesto non si riesce a prendere, il profilo si
    registra comunque: una riga senza il contesto vale molto più di una riga che non esiste."""
    try:
        return _contesto_del_giorno(kind, righe)
    except Exception:
        return {"giorno": _arc_oggi(), "mondo": {}, "ampiezza": {}, "origine": {}, "settori": {}}


def _mondo_per_riga(r: dict, ctx: dict) -> dict:
    ctx = ctx or {}
    # il nome del settore passa dalla tabella dei sinonimi, altrimenti il collegamento all'ETF
    # settoriale fallisce in silenzio ogni volta che la fonte usa un nome diverso dal solito
    gruppo = settore_canonico(r.get("sector"))
    sett = (ctx.get("settori") or {}).get(gruppo) if gruppo else None
    return mondo_minimo(ctx.get("mondo"), ctx.get("ampiezza"), sett)


def _accoda_scarto(r: dict, kind: str, motivo: str, dettaglio=None, conv=None,
                   punteggio=None, ctx: dict = None) -> None:
    """Mette in coda un'occasione BOCCIATA, col motivo preso nell'istante del rifiuto.
    Sono le righe più preziose dell'archivio: senza contro-esempi non si impara niente, e senza il
    motivo non si scopre mai che è il filtro a sbagliare invece del titolo."""
    try:
        ctx = ctx or {}
        # I PEZZI DEL GIUDIZIO ANCHE PER LE BOCCIATE. Senza, la tabella dell'apprendimento
        # confronterebbe quelle caratteristiche fra popolazioni diverse: presenti sulle comprate,
        # assenti sulle bocciate. Sono contro-esempi solo se hanno gli stessi campi.
        try:
            _fat = _factor_values(r, kind)
        except Exception as _e:
            _fat = None
            _log_silenzioso("fattori non calcolati per %s: %r" % (r.get("ticker"), _e))
        prof = profilo_da_riga(
            r, kind, momento=None, motivo=motivo, dettaglio=dettaglio, conv=conv,
            occasione=(int(round(punteggio)) if isinstance(punteggio, (int, float)) else None),
            fattori=_fat, mondo=_mondo_per_riga(r, ctx),
            origine=(ctx.get("origine") or {}).get(r.get("ticker")),
            giorno=ctx.get("giorno"))
        accoda_profilo(prof)
        # Le notizie costano chiamate, quindi si spendono dove servono: sugli scarti che avevano
        # convenienza da promozione. Sono il contro-esempio più informativo che esista — «il sistema
        # le riteneva buone e le ha bocciate un filtro tecnico» — e sono ~800 su 3.760 misurate.
        if conv is not None and conv >= _OBS_ENTRY_CONV:
            registra_notizie(r.get("ticker"), ctx.get("giorno"))
    except Exception:
        pass


def accoda_senza_profilo(kind: str, tickers, motivo: str, giorno: str = None) -> int:
    """Mette in coda i titoli di cui NON si può avere un profilo, col motivo. Sono i due punti
    ciechi del sistema: quelli con troppa poca storia (esclusi prima di calcolare qualsiasi cosa) e
    quelli oltre il tetto dell'universo (mai nemmeno aperti).

    Registrarli è quello che trasforma «non sappiamo cosa ci siamo perso» in «sappiamo esattamente
    quali nomi ci siamo perso, e sono questi»: fra qualche mese si potrà andare a vedere come sono
    andati quei titoli e sapere se il tetto ci costa qualcosa, invece di supporlo."""
    if motivo not in MOTIVI_SENZA_PROFILO:
        return 0
    giorno = giorno or _arc_oggi()
    n = 0
    for tk in dict.fromkeys([str(x).upper() for x in (tickers or []) if x]):
        accoda_profilo({
            "id": _profilo_id(giorno, kind, tk, motivo), "giorno": giorno, "ora": _arc_ora(),
            "ticker": tk, "nome": None, "kind": kind, "momento": None, "episodio": None,
            "scartata": True, "motivo": motivo, "motivo_dettaglio": None, "origine": None,
            "notizie_di": None, "prezzo": None, "titolo": {}, "punteggi": {},
            "convenienza": None, "occasione": None, "fattori": {}, "trappola": None,
            "settore": None, "mondo": {},
        })
        n += 1
    return n


def registra_profilo_occasione(kind: str, ticker: str, momento: str, episodio: str = None,
                               giorno: str = None, ritardo_ore: float = 0,
                               prezzo_acquisto: float = None) -> bool:
    """Registra il profilo COMPLETO di un'occasione in un momento d'acquisto. Chiamata dal diario,
    così ogni momento passa da qui e nessuno può sfuggire per dimenticanza in un chiamante.

    Costa poco: opportunity_row ha una cache di 15 minuti e nel giro automatico è già calda dalla
    scansione appena fatta, quindi tipicamente zero o una chiamata di rete. Tutto il resto — le ~50
    caratteristiche, i fattori, i punteggi — è calcolo locale gratuito."""
    try:
        TK = str(ticker).upper()
        giorno = giorno or _arc_oggi()
        r = opportunity_row(TK, with_fundamentals=True)
        if not r:
            return False
        if kind == "short":
            try:
                b = _benchmark_perf()
                r = dict(r)
                r["bench_5d"], r["bench_1m"] = b.get("perf_5d"), b.get("perf_1m")
            except Exception:
                pass
        ctx = _contesto_del_giorno(kind, [r], giorno)
        try:
            fattori = _factor_values(r, kind)
        except Exception:
            fattori = None
        try:
            # LA RIGA, non il ticker: _convenience_single vuole il record di opportunity_row e al
            # primo r.get() su una stringa solleva. L'except muto qui accanto ha nascosto il difetto
            # su TUTTE le righe dei momenti d'acquisto — 42 su 42 nei dati veri avevano il giudizio
            # vuoto, e nella scheda dell'archivio la colonna «Giudizio» era bianca su ogni riga.
            conv = _convenience_single(r, kind)
        except Exception as _e:
            conv = None
            _log_silenzioso("convenienza non calcolata per %s: %r" % (TK, _e))
        try:
            punteggio = _short_score(r) if kind == "short" else _long_score(r)
        except Exception:
            punteggio = None
        prof = profilo_da_riga(
            r, kind, momento=momento, episodio=episodio, conv=conv,
            occasione=(int(round(punteggio)) if isinstance(punteggio, (int, float))
                       and np.isfinite(punteggio) else None),
            fattori=fattori, mondo=_mondo_per_riga(r, ctx),
            origine=(ctx.get("origine") or {}).get(TK), giorno=giorno)
        # IL PREZZO D'ACQUISTO E QUELLO DEL DIARIO, non quello di adesso: e' l'unico prezzo a cui
        # l'occasione e' stata "comprata", e su quello si misurano tutti i rendimenti. Il prezzo di
        # adesso resta a verbale a parte, dentro le caratteristiche, dove e' un dato vero e utile.
        if prezzo_acquisto is not None:
            prof["prezzo"] = prezzo_acquisto
            prof["prezzo_al_momento_del_profilo"] = r.get("price")
        try:
            # anche le soglie si calcolano sul PREZZO D'ACQUISTO: un bersaglio misurato da un prezzo
            # diverso da quello pagato non e' il bersaglio di quell'acquisto
            s = soglie_ora(TK, (prezzo_acquisto if prezzo_acquisto is not None
                                else r.get("price")), kind, fino_a=str(giorno)[:10])
            prof["soglie"] = s.get("soglie")
            prof["stop_soglia"] = s.get("stop")
        except Exception:
            pass
        # a quale dei cinque scenari corrisponde questo momento: ricavato da SCENARI_ACQUISTO, mai
        # scritto a mano, così se gli scenari cambiano l'archivio resta coerente da solo
        prof["scenario"] = next((c for c, ev, _n, _a in SCENARI_ACQUISTO if ev == momento), None)
        # QUANTO TARDI e' stato preso questo profilo. Un profilo recuperato mezz'ora dopo l'evento
        # non e' la stessa cosa di uno preso nell'istante: i numeri sono di un altro momento. Va
        # scritto, non nascosto, cosi chi legge puo scartarlo se il ritardo e troppo grande.
        # sempre, anche se vale 0: «preso nell'istante» e' un'informazione, non un'assenza
        try:
            prof["profilo_in_ritardo_ore"] = round(float(ritardo_ore or 0), 1)
        except (TypeError, ValueError):
            prof["profilo_in_ritardo_ore"] = None
        accoda_profilo(prof)
        registra_notizie(TK, giorno, forza=True)   # un momento d'acquisto ha sempre diritto alle notizie
        return True
    except Exception:
        return False


def giornata(giorno: str) -> dict:
    """Tutto quello che il sistema ha visto e pensato in una singola giornata: le occasioni e gli
    scarti col loro profilo, com'era il mondo, come stavano i settori, che notizie girassero, e gli
    esiti maturati quel giorno. È la pagina del calendario."""
    def leggi(prefisso):
        fuori = []
        for nome in sorted(indice_archivio()):
            if nome.startswith(prefisso + "/") and os.path.basename(nome)[:10] == giorno:
                fuori += (read_data_json(nome, None) or [])
        return fuori

    profili = leggi(ARC_PROFILI)
    return {"giorno": giorno, "profili": profili,
            "occasioni": [p for p in profili if not p.get("scartata")],
            "scartate": [p for p in profili if p.get("scartata")],
            "mondo": (leggi(ARC_MONDO) or [{}])[0],
            "settori": leggi(ARC_SETTORI), "notizie": leggi(ARC_NOTIZIE),
            "esiti_maturati": leggi(ARC_ESITI)}


def giorni_archivio(prefisso: str = None) -> list:
    """I giorni presenti nell'archivio, dal più recente. È l'elenco delle pagine del calendario."""
    pre = prefisso or ARC_PROFILI
    giorni = set()
    for nome in indice_archivio():
        if nome.startswith(pre + "/"):
            g = os.path.basename(nome)[:10]
            if len(g) == 10 and g[4] == "-":
                giorni.add(g)
    return sorted(giorni, reverse=True)


def apri_occasione(profilo_id: str) -> dict:
    """Ricompone UNA occasione da tutti gli archivi: il suo profilo, le notizie di quel giorno per
    QUEL titolo, com'era il mondo, come stava il suo settore, e com'è andata.

    È qui che si vede perché tenere le notizie in un archivio separato non le scollega: il legame è
    (titolo, giorno), che è dentro l'identificativo del profilo stesso. Nulla è appeso a un numero
    progressivo che si può disallineare."""
    if not profilo_id or ":" not in profilo_id:
        return {}
    giorno = str(profilo_id).split(":")[0]
    g = giornata(giorno)
    prof = next((p for p in g["profili"] if p.get("id") == profilo_id), None)
    if prof is None:
        return {}
    tk = prof.get("ticker")
    return {
        "profilo": prof,
        "notizie": next((n for n in g["notizie"] if n.get("ticker") == tk), {}),
        "mondo": g["mondo"],
        "settore": next((s for s in g["settori"]
                         if s.get("settore") == (prof.get("settore_gruppo")
                                                 or settore_canonico(prof.get("settore")))), {}),
        "esiti": [e for e in _arc_leggi_giorni(ARC_ESITI) if e.get("profilo") == profilo_id],
    }


def ripara_indice() -> dict:
    """Riallinea l'indice ai file che esistono davvero. Serve nel caso in cui l'indice dica «questo
    file ha 80 righe» e il file ne abbia 50: quella discordanza blocca le scritture per non
    rischiare di cancellare, ed è giusto che le blocchi, ma deve esistere un modo di sbloccarla
    guardando i fatti invece di forzare. Non cancella niente: riscrive solo i conteggi."""
    indice = read_data_json(INDICE_NAME, None)
    if not isinstance(indice, dict):
        return {"riparate": 0, "motivo": "l'indice non si legge: non tocco niente"}
    cambi = []
    for nome in sorted(indice):
        if "/" not in nome or not isinstance(indice.get(nome), dict):
            continue
        righe = read_data_json(nome, None)
        if not isinstance(righe, list):
            continue        # non si legge: si lascia stare, non si azzera
        atteso = indice[nome].get("righe")
        if atteso != len(righe):
            cambi.append({"file": nome, "prima": atteso, "adesso": len(righe)})
            indice[nome] = {"righe": len(righe), "aggiornato": _arc_ora(),
                            "riparato": True}
    if cambi:
        _indice_scrivi(indice)
    return {"riparate": len(cambi), "dettagli": cambi}


def copertura_archivio(kind: str = None, giorni: int = 60) -> dict:
    """QUANTE occasioni finiscono davvero in archivio e quante no, e perché. Esiste perché
    «registriamo tutto» è una frase che va verificata, non ripetuta: qui si vedono i buchi
    dichiarati invece di scoprirli fra un anno.

    Il totale viene dall'elenco dell'archivio, che lo sa senza aprire niente; i dettagli si
    calcolano sugli ultimi `giorni` giorni. Serve perché aprire questa pagina non debba scaricare
    l'intero archivio: fra un anno sarebbero centinaia di file a ogni caricamento."""
    _dal = (datetime.date.today() - datetime.timedelta(days=max(1, giorni))).isoformat()
    # totale esatto e gratuito: i conteggi per file sono già nell'elenco
    totale_righe = sum(int((info or {}).get("righe") or 0)
                       for nome, info in indice_archivio().items()
                       if nome.startswith(ARC_PROFILI + "/") and isinstance(info, dict))
    profili = [p for p in _arc_leggi_giorni(ARC_PROFILI, dal=_dal)
               if isinstance(p, dict) and (not kind or p.get("kind") == kind)]
    per_motivo = {}
    for p in profili:
        if p.get("scartata"):
            per_motivo[p.get("motivo")] = per_motivo.get(p.get("motivo"), 0) + 1
    momenti = {}
    for p in profili:
        if not p.get("scartata"):
            momenti[p.get("momento")] = momenti.get(p.get("momento"), 0) + 1
    con_notizie = {(n.get("giorno"), n.get("ticker")) for n in _arc_leggi_giorni(ARC_NOTIZIE)}
    quante_con_notizie = sum(1 for p in profili
                             if (p.get("giorno"), p.get("ticker")) in con_notizie)
    return {
        "righe_totali": totale_righe,
        "righe_guardate": len(profili), "dettagli_dal": _dal,
        "occasioni_comprate": sum(1 for p in profili if not p.get("scartata")),
        "bocciate": sum(1 for p in profili if p.get("scartata")),
        "per_momento": momenti, "per_motivo_di_scarto": per_motivo,
        "con_notizie": quante_con_notizie,
        "giorni_coperti": len(giorni_archivio()),
        "senza_profilo": sum(1 for p in profili
                             if p.get("motivo") in MOTIVI_SENZA_PROFILO),
        # DUE POPOLAZIONI, CONTATE SEPARATAMENTE. Prima il numeratore girava su tutte le righe e il
        # denominatore solo sulle comprate: il riquadro diceva "22 su 22, 100%" mentre la copertura
        # vera fra le comprate era 8 su 22. Un controllo di copertura che mente in positivo e' peggio
        # di nessun controllo, perche' spegne proprio l'allarme che deve suonare.
        "con_contesto_settore": sum(1 for p in profili
                                    if not p.get("scartata")
                                    and (p.get("mondo") or {}).get("settore_1m") is not None),
        "bocciate_con_settore": sum(1 for p in profili
                                    if p.get("scartata")
                                    and (p.get("mondo") or {}).get("settore_1m") is not None),
        "settore_non_riconosciuto": sorted({
            str(p.get("settore")) for p in profili
            if p.get("settore") and not (p.get("settore_gruppo")
                                         or settore_canonico(p.get("settore")))}),
        "senza_settore": sum(1 for p in profili
                             if not p.get("scartata") and not p.get("settore")),
        "bocciate_senza_settore": sum(1 for p in profili
                                      if p.get("scartata") and not p.get("settore")),
        "non_registrate": [
            "I nomi oltre il tetto dell'universo (40 per il breve, 20 per il lungo) non vengono "
            "mai aperti, quindi di loro non esistono caratteristiche. Il loro NOME però è a "
            "verbale, con il motivo «mai guardata»: fra qualche mese si potrà controllare come "
            "sono andati e sapere se quel tetto ci costa occasioni.",
            "Lo stesso per i titoli con meno di 60 sedute di storico o col prezzo non "
            "disponibile: nome e motivo sì, caratteristiche no — vengono esclusi prima che si "
            "possa calcolarne una.",
            "Le notizie hanno un tetto di %d chiamate per giro: le hanno tutti i momenti "
            "d'acquisto e le bocciature con convenienza da promozione, non ogni candidato. "
            "Il limite vero della fonte non è scritto nel codice, quindi il tetto è nostro e "
            "prudente." % _NOTIZIE_PER_GIRO,
            "L'archivio si scrive solo durante il lavoro automatico, non quando si sfoglia "
            "l'app: il lavoro gira ogni mezz'ora sullo stesso mercato, quindi non sfugge nulla.",
        ],
    }


# --- GLI SCATTI DEL MONITORAGGIO --------------------------------------------
# IL PROBLEMA, misurato: tracking.json era a 1,89 MB con 6.651 scatti su 23 giorni. Oltre 1 MB
# l'API dei contenuti di GitHub non restituisce più il contenuto del file, e allora la protezione
# anti-cancellazione si spegne IN SILENZIO — non c'è errore, non c'è messaggio: semplicemente da
# quel momento chiunque può riscriverci sopra qualunque cosa. Quel file conteneva i prezzi
# d'ingresso di 78 titoli seguiti, cioè roba irrecuperabile.
#
# LA CURA: gli scatti vecchi vanno in file giornalieri d'archivio e il file vivo torna piccolo. Non
# si perde niente — al contrario, da adesso gli scatti si tengono PER SEMPRE, mentre prima venivano
# buttati dopo 22 giorni. Il file vivo tiene gli ultimi giorni, e chi vuole la storia completa la
# chiede a storia_scatti(), che rimette insieme archivio e vivo.
ARC_SCATTI = "archivio/scatti"
_SCATTI_VIVI_GG = 3          # giorni di scatti che restano nel file vivo
_SCATTI_TETTO_BYTE = 600_000  # oltre questo il file vivo si accorcia da solo, fin dove serve
_SCATTI_GIORNI_PER_GIRO = 10  # quanti giorni archiviare al massimo per giro, per non martellare l'API
# QUANTI SCATTI RESTANO SEMPRE, per ogni titolo, anche se più vecchi della finestra. Non è una
# rifinitura: un titolo che smette di ricevere dati — cioè un possibile delisting, il caso in cui
# l'allarme serve davvero — non avrebbe scatti recenti per definizione, e resterebbe con la lista
# vuota. Chi controlla se un titolo è fermo si ferma alla prima riga: «se non ci sono scatti, non
# dico niente». Quindi l'allarme si spegnerebbe esattamente sui titoli che deve sorvegliare.
_SCATTI_MINIMO = 3


def _peso(obj) -> int:
    try:
        return len(json.dumps(obj, ensure_ascii=False, indent=0).encode("utf-8"))
    except Exception:
        return 0


def archivia_scatti(giorni_vivi: int = None, tetto_byte: int = None,
                    max_giorni: int = None) -> dict:
    """Sposta gli scatti vecchi del monitoraggio in file giornalieri e rimpicciolisce il file vivo.

    L'ordine è quello che conta: si scrive l'archivio, si VERIFICA che sia arrivato, e solo dopo si
    toglie qualcosa dal file vivo. Se l'archivio non riesce, il file vivo non viene toccato: resta
    grosso, che è un problema, ma nessuno scatto sparisce — e un problema che resta è sempre meglio
    di un dato che non c'è più.

    Ritorna quanti scatti ha spostato, quanti giorni ha coperto e quanto pesa ora il file vivo."""
    giorni_vivi = _SCATTI_VIVI_GG if giorni_vivi is None else giorni_vivi
    tetto_byte = _SCATTI_TETTO_BYTE if tetto_byte is None else tetto_byte
    max_giorni = _SCATTI_GIORNI_PER_GIRO if max_giorni is None else max_giorni

    tracked = load_tracking()
    if not isinstance(tracked, dict) or not tracked:
        return {"spostati": 0, "giorni": 0, "peso_prima": 0, "peso_dopo": 0,
                "motivo": "non riesco a leggere il monitoraggio: non tocco niente"}
    peso_prima = _peso(tracked)
    spostati_tot, giorni_fatti, problemi = 0, [], []

    while True:
        taglio = (datetime.date.today() - datetime.timedelta(days=max(1, giorni_vivi))).isoformat()
        # 1. raccogli gli scatti da spostare, raggruppati per il GIORNO IN CUI SONO AVVENUTI: così
        #    l'archivio diventa un calendario di com'erano i titoli seguiti, giorno per giorno.
        per_giorno = {}
        scelti = {}      # {ticker: set(date esatte scelte)} — la corrispondenza deve essere ESATTA
        for tk, e in tracked.items():
            if not isinstance(e, dict):
                continue
            TK = str(tk).upper()
            _tutti = sorted((e.get("snapshots") or []), key=lambda s: str(s.get("date") or ""))
            _intoccabili = {id(s) for s in _tutti[-_SCATTI_MINIMO:]}   # gli ultimi restano sempre
            for s in _tutti:
                g = str(s.get("date") or "")[:10]
                if not g or g >= taglio or id(s) in _intoccabili:
                    continue
                riga = {"giorno": g, "ticker": TK, "kind": e.get("kind"), "nome": e.get("name")}
                riga.update({k: v for k, v in s.items() if k != "name"})
                per_giorno.setdefault(g, []).append(riga)
                scelti.setdefault(TK, set()).add(str(s.get("date")))
        if not per_giorno:
            break
        # 2. scrivi (e verifica) un giorno alla volta, dal più vecchio
        salvati = set()
        for g in sorted(per_giorno)[:max(1, max_giorni)]:
            esito = _arc_aggiungi(ARC_SCATTI, per_giorno[g],
                                  chiave=lambda r: (r.get("ticker"), r.get("date")), giorno=g)
            if esito.get("salvate"):
                salvati.add(g)
                giorni_fatti.append(g)
            else:
                problemi.append(f"{g}: {esito.get('motivo')}")
        if not salvati:
            break
        # 3. SOLO ADESSO togli dal file vivo quelli che sono davvero in archivio
        spostati = 0
        for tk, e in tracked.items():
            if not isinstance(e, dict):
                continue
            _scelte = scelti.get(str(tk).upper()) or set()
            tenuti = []
            for s in (e.get("snapshots") or []):
                d = str(s.get("date") or "")
                # Si toglie SOLO quello che è stato scelto E il cui giorno è arrivato in archivio.
                # Non basta «è vecchio e quel giorno è salvato»: gli ultimi scatti di ogni titolo
                # non vengono mai archiviati, e un altro titolo può averne uno lo stesso giorno —
                # quindi quella scorciatoia li cancellerebbe senza che siano da nessuna parte.
                if d in _scelte and d[:10] in salvati:
                    spostati += 1
                else:
                    tenuti.append(s)
            e["snapshots"] = tenuti
        spostati_tot += spostati
        # 4. ancora troppo grosso? si stringe la finestra e si ripassa. Il tetto non è un vezzo: è
        #    quello che tiene ACCESA la protezione anti-cancellazione di questo file.
        if _peso(tracked) <= tetto_byte or giorni_vivi <= 1:
            break
        giorni_vivi -= 1

    if not spostati_tot:
        return {"spostati": 0, "giorni": 0, "peso_prima": peso_prima, "peso_dopo": peso_prima,
                "motivo": ("; ".join(problemi) or None)}
    if not save_tracking(tracked, force=True):   # riduzione dichiarata, non un effetto collaterale
        return {"spostati": 0, "giorni": len(set(giorni_fatti)), "peso_prima": peso_prima,
                "peso_dopo": peso_prima,
                "motivo": "gli scatti sono in archivio ma il file vivo non si è salvato: "
                          "nessuno scatto è perso, si riprova al prossimo giro"}
    return {"spostati": spostati_tot, "giorni": len(set(giorni_fatti)),
            "peso_prima": peso_prima, "peso_dopo": _peso(tracked),
            "giorni_vivi": giorni_vivi, "motivo": ("; ".join(problemi) or None)}


def storia_scatti(ticker: str, dal: str = None, al: str = None) -> list:
    """La storia COMPLETA degli scatti di un titolo: archivio più file vivo, in ordine di data.
    Da usare dove serve la storia lunga — i grafici del monitoraggio e la ricerca di un valore a una
    data precisa. Il file vivo da solo tiene pochi giorni, ma l'archivio non butta più niente:
    quindi da adesso questa storia si allunga invece di accorciarsi come faceva prima."""
    TK = str(ticker).upper()
    fuori = {}
    for r in _arc_leggi_giorni(ARC_SCATTI, dal=dal, al=al):
        if isinstance(r, dict) and r.get("ticker") == TK and r.get("date"):
            fuori[str(r["date"])] = {k: v for k, v in r.items()
                                     if k not in ("giorno", "ticker", "kind", "nome")}
    e = (load_tracking() or {}).get(TK) or {}
    for s in (e.get("snapshots") or []):
        if s.get("date"):
            d = str(s["date"])
            if (dal and d[:10] < dal) or (al and d[:10] > al):
                continue
            fuori[d] = s          # il vivo vince: è la copia più aggiornata
    return [fuori[k] for k in sorted(fuori)]


def scatti_del_giorno(giorno: str) -> list:
    """Com'erano tutti i titoli seguiti in un giorno preciso. È la pagina del calendario del
    monitoraggio, e serve a rispondere a «com'era la situazione quel giorno» senza doverla
    ricostruire titolo per titolo."""
    fuori = []
    for nome in sorted(indice_archivio()):
        if nome.startswith(ARC_SCATTI + "/") and os.path.basename(nome)[:10] == giorno:
            fuori += (read_data_json(nome, None) or [])
    return fuori


def scenari_calendario_diario(kind: str = "short", granularita: str = "settimana",
                              min_pg: int = 0, max_pl: int = 100, min_conv: int = 0,
                              importo: float = 30.0, fee: float = 1.0) -> dict:
    """IL CALENDARIO, ma preso dal DIARIO invece che dal vecchio registro degli scenari.

    Perché rifatto: il calendario vecchio leggeva un registro che non usiamo più per imparare, e
    ragionava sui quattro momenti d'acquisto di prima. Gli scenari ora sono cinque e stanno nel
    diario, quindi due viste sugli stessi dati davano strutture diverse — cioè il modo più sicuro
    per trovarsi con due numeri che non tornano e non sapere a quale credere.

    A che serve: la scheda di riepilogo mette tutto insieme e risponde a «quale momento d'acquisto
    rende di più». Non risponde a «sta migliorando o peggiorando?», che è un'altra domanda: una
    media buona può essere costruita in una settimana fortunata. Qui ogni riga è un periodo.

    I periodi sono quelli dell'ACQUISTO, non della vendita: è la data che il diario conserva con
    certezza, e raggruppare per periodo d'ingresso è anche l'unico modo corretto di confrontare
    periodi diversi. La resa di un gruppo matura nei giorni successivi.

    Le caselle hanno la stessa forma di prima — "scenario|vendita" — così l'interfaccia del
    calendario resta quella e non ci sono due modi di leggere la stessa cosa."""
    sd = scenari_diario(kind, min_pg, max_pl, min_conv, importo, fee)
    nomi = {sc["chiave"]: sc["nome"] for sc in sd["scenari"]}
    gruppi = {}
    for sc in sd["scenari"]:
        for vend in sd.get("vendite") or ():
            for p in ((sc.get("casi") or {}).get(vend) or []):
                g = str(p.get("data") or p.get("date") or "")[:10]
                if not g or p.get("ret") is None:
                    continue
                try:
                    chiave, etichetta, primo, ultimo = _periodo_di(g, granularita)
                except Exception:
                    continue
                gr = gruppi.setdefault(chiave, {
                    "chiave": chiave, "etichetta": etichetta, "dal": primo.isoformat(),
                    "al": ultimo.isoformat(), "casi": {}, "episodi": set()})
                gr["casi"].setdefault(f"{sc['chiave']}|{vend}", []).append(p)
                gr["episodi"].add(p.get("episodio") or p.get("ticker"))

    periodi = []
    for chiave in sorted(gruppi, reverse=True):          # dal più recente
        gr = gruppi[chiave]
        celle = {}
        for k, punti in gr["casi"].items():
            rese = sorted(float(p["ret"]) for p in punti if p.get("ret") is not None)
            if not rese:
                continue
            n = len(rese)
            med = rese[n // 2] if n % 2 else (rese[n // 2 - 1] + rese[n // 2]) / 2
            # I netti si calcolano CASO PER CASO e poi si fa la media: «il netto della resa tipica»
            # e «la media dei netti» sono numeri diversi, perché la commissione è fissa e la tassa
            # colpisce solo i guadagni. Quello utile è il secondo, ed è lo stesso che mostra la
            # scheda di riepilogo — così le due viste non si contraddicono sugli stessi dati.
            netti = [x for x in (net_eur(p["ret"], importo, fee) for p in punti) if x is not None]
            celle[k] = {
                "n": n, "med": round(med, 2), "avg": round(sum(rese) / n, 2),
                "hit": round(100 * sum(1 for x in rese if x > 0) / n),
                "best": round(max(rese), 2), "worst": round(min(rese), 2),
                "netto_medio": (round(sum(netti) / len(netti), 2) if netti else None),
                "netto_totale": round(sum(netti), 2),
                "in_utile": sum(1 for x in netti if x > 0),
            }
        periodi.append({
            "chiave": chiave, "etichetta": gr["etichetta"], "dal": gr["dal"], "al": gr["al"],
            "n_occasioni": len(gr["episodi"]),
            "titoli": sorted({str(p.get("ticker")) for punti in gr["casi"].values() for p in punti}),
            "celle": celle,
            "casi": {k: sorted(v, key=lambda p: str(p.get("data") or ""))
                     for k, v in gr["casi"].items()},
        })
    return {"granularita": granularita, "kind": kind, "importo": importo, "fee": fee,
            "pareggio_pct": round(pareggio_pct(importo, fee), 2),
            "n_senza_dato": sum(sc.get("n_senza_dato") or 0 for sc in sd["scenari"]),
            "nomi_scenari": nomi, "vendite": sd.get("vendite") or (),
            "periodi": periodi, "n_periodi": len(periodi)}


def ripara_settori(giorni: int = 3) -> dict:
    """Riattacca il contesto del settore alle righe di profilo che ne sono rimaste prive.

    Serve perché il collegamento fra il nome del settore e il suo ETF di riferimento si è allargato
    dopo che le righe erano già scritte: il 21/08/2026 il sistema riconosceva 22 nomi su 40, ora 38,
    e senza questa passata quelle righe resterebbero senza il confronto col settore per sempre.
    Vale anche per il futuro: ogni volta che si aggiunge un sinonimo, le righe recenti si riparano.

    NON inventa niente: il nome del settore era già a verbale nella riga, e i numeri del settore
    erano già a verbale nell'archivio dei settori DI QUEL GIORNO. Qui si ricollegano due dati veri.
    Gira dentro il lavoro automatico, che è l'unico che scrive: nessuna corsa fra due processi.
    Non tocca i giorni più vecchi di `giorni`, dove i settori potrebbero non essere stati fotografati."""
    oggi = datetime.date.today()
    dal = (oggi - datetime.timedelta(days=max(0, giorni))).isoformat()
    riparate, toccati = 0, []
    for nome in sorted(indice_archivio()):
        if not nome.startswith(ARC_PROFILI + "/"):
            continue
        g = os.path.basename(nome)[:10]
        if len(g) != 10 or g < dal:
            continue
        righe = read_data_json(nome, None)
        if not isinstance(righe, list) or not righe:
            continue        # non si legge o è vuoto: non si tocca, mai
        # i numeri dei settori di QUEL giorno, non di oggi
        sett = {s.get("settore"): s for s in _arc_leggi_giorni(ARC_SETTORI, dal=g, al=g)
                if isinstance(s, dict)}
        if not sett:
            continue
        cambi = 0
        for r in righe:
            if not isinstance(r, dict) or not r.get("settore"):
                continue
            gruppo = r.get("settore_gruppo") or settore_canonico(r.get("settore"))
            if not gruppo:
                continue
            if not r.get("settore_gruppo"):
                r["settore_gruppo"] = gruppo
                cambi += 1
            m = r.get("mondo")
            if isinstance(m, dict) and m.get("settore_1m") is None and sett.get(gruppo):
                s = sett[gruppo]
                m["settore_1m"] = s.get("var_1m")
                m["settore_forza_1m"] = s.get("forza_var_1m")
                cambi += 1
        if not cambi:
            continue
        # stesso numero di righe e solo campi AGGIUNTI: le due guardie lo accettano senza force
        if write_data_json(nome, righe) and nome not in _SALVATAGGI_FALLITI:
            riparate += cambi
            toccati.append(nome)
    return {"riparate": riparate, "file": toccati}


def riconcilia_profili(giorni: int = 2) -> dict:
    """Recupera i momenti d'acquisto che sono nel diario ma non hanno un profilo in archivio.

    PERCHE SERVE. registra_evento scrive subito l'evento nel diario, poi mette il profilo in coda;
    la coda si scrive alla fine del giro. Se il giro muore in mezzo — il servizio che lo esegue puo
    ucciderlo — l'evento resta a verbale e il profilo no. E al giro dopo registra_evento vede che
    l'evento c'e gia e non riprova: quel momento d'acquisto resterebbe senza caratteristiche PER
    SEMPRE, cioe inutile all'apprendimento, senza che nessuno lo sappia.

    Questa passata confronta i due elenchi e ricrea quello che manca. E ripetibile senza danno:
    l'archivio scarta i doppioni per identificativo, quindi puo girare a ogni giro.
    Sul profilo recuperato scrive di quante ore e in ritardo: un dato preso dopo non va confuso con
    uno preso nell'istante giusto."""
    oggi = datetime.date.today()
    dal = (oggi - datetime.timedelta(days=max(0, giorni))).isoformat()
    acquisti = eventi_acquisto()
    # gli identificativi dei profili gia in archivio nella finestra, piu quelli ancora in coda
    presenti = {p.get("id") for p in _arc_leggi_giorni(ARC_PROFILI, dal=dal) if isinstance(p, dict)}
    presenti |= {p.get("id") for p in _BUFFER_PROFILI if isinstance(p, dict)}
    recuperati, non_riusciti = [], []
    for r in load_registro_completo(DIARIO_NAME, load_diario()):
        if r.get("evento") not in acquisti:
            continue
        g = str(r.get("data") or r.get("scritto_il") or "")[:10]
        if len(g) != 10 or g < dal:
            continue
        tk, kind = str(r.get("ticker") or "").upper(), r.get("kind")
        if not tk or not kind:
            continue
        if _profilo_id(g, kind, tk, r.get("evento")) in presenti:
            continue
        # quante ore sono passate fra il momento dell'evento e adesso
        ore = 0.0
        try:
            q = str(r.get("data") or "")[:16].replace("T", " ")
            ore = max(0.0, (datetime.datetime.strptime(_now_iso()[:16], "%Y-%m-%d %H:%M")
                            - datetime.datetime.strptime(q, "%Y-%m-%d %H:%M")).total_seconds() / 3600)
        except Exception:
            ore = 0.0
        if registra_profilo_occasione(kind, tk, r.get("evento"), episodio=r.get("episodio"),
                                      giorno=g, ritardo_ore=ore):
            recuperati.append(f"{tk}:{r.get('evento')}")
        else:
            # non si e riusciti nemmeno adesso: si mette a verbale il BUCO, invece di tacerlo
            accoda_senza_profilo(kind, [tk], "profilo_non_ricostruibile", g)
            non_riusciti.append(f"{tk}:{r.get('evento')}")
    return {"recuperati": len(recuperati), "quali": recuperati[:20],
            "non_riusciti": len(non_riusciti)}


def ripara_soglie_contaminate(max_righe: int = 120) -> dict:
    """Ricalcola le soglie delle righe del diario che le avevano costruite con dati del FUTURO.

    Il difetto: soglie_ora leggeva lo storico fino a oggi mentre il prezzo era quello dell'evento, e
    il lavoro automatico mette a verbale gli eventi anche giorni dopo (salta dei giri: misurato, 64
    momenti su 82 sono stati scritti con 1-5 giorni di ritardo). Risultato: 57 righe su 82 avevano
    bersagli costruiti su barre successive all'acquisto — e «meta_caduta», che e' il punto a meta fra
    il prezzo e il massimo delle ultime 60 sedute, risultava raggiunto per costruzione ogni volta che
    quel massimo cadeva dopo l'acquisto.

    Perche ricalcolare e non solo scartare: il dato d'ingresso — lo storico dei prezzi fino alla data
    dell'acquisto — e' oggettivo e disponibile, quindi il valore corretto si CALCOLA, non si indovina.
    Non e' un riempimento a posteriori: e' la correzione di un conto sbagliato.
    Le soglie vecchie restano scritte in `soglie_contaminate`, cosi nulla si perde e la correzione
    resta verificabile. Ripetibile senza danno: chi e' gia stato corretto porta il marchio."""
    righe = load_diario()
    if not righe:
        return {"corrette": 0, "in_attesa": 0}
    acquisti = eventi_acquisto()
    corrette, restano = 0, 0
    for r in righe:
        if r.get("evento") not in acquisti or r.get("soglie_ricalcolate_il"):
            continue
        d_ev, d_scr = str(r.get("data") or "")[:10], str(r.get("scritto_il") or "")[:10]
        if not d_ev or not d_scr or d_scr <= d_ev:
            continue          # scritta nello stesso giorno: le soglie erano già quelle giuste
        if not (r.get("soglie") or {}):
            continue
        if corrette >= max_righe:
            restano += 1
            continue
        nuove = soglie_ora(r.get("ticker"), r.get("prezzo"), r.get("kind"), fino_a=d_ev)
        if not isinstance(nuove, dict):
            continue
        r["soglie_contaminate"] = r.get("soglie")      # non si butta: resta verificabile
        r["soglie"] = nuove.get("soglie")
        r["stop"] = nuove.get("stop")
        r["atr"] = nuove.get("atr")
        r["soglie_ricalcolate_il"] = _now_iso()
        r["soglie_ritardo_giorni"] = (datetime.date.fromisoformat(d_scr)
                                      - datetime.date.fromisoformat(d_ev)).days
        # l'esito calcolato sul bersaglio sbagliato non vale piu: si rifara al prossimo giro
        if isinstance(r.get("res"), dict):
            r["res"].pop("soglia", None)
        r.pop("res_soglia", None)
        corrette += 1
    if corrette and not salva_registro(DIARIO_NAME, righe, _DIARIO_MAX, giorni_protetti=400):
        return {"corrette": 0, "in_attesa": corrette + restano,
                "motivo": "il diario non si e salvato: nessuna correzione applicata"}
    return {"corrette": corrette, "in_attesa": restano}


def ripara_prezzi_profili(giorni: int = 7) -> dict:
    """Riallinea il prezzo dei profili in archivio a quello del diario, dov'erano diversi.

    Il diario e' la fonte del prezzo d'acquisto: e' l'unico prezzo a cui l'occasione e' stata
    «comprata», e su quello si misurano tutti i rendimenti. L'archivio, per gli eventi in ritardo,
    aveva registrato il prezzo del giorno in cui il profilo veniva costruito — misurato: 4 profili su
    22 con scarti fino al +2,93%. Due verita per lo stesso acquisto significa che scenari e archivio
    misurano rendimenti diversi, quindi una delle due e' sbagliata: e' quella dell'archivio.
    Il prezzo di allora non si butta: finisce in `prezzo_al_momento_del_profilo`, dov'e' un dato vero."""
    oggi = datetime.date.today()
    dal = (oggi - datetime.timedelta(days=max(0, giorni))).isoformat()
    # il prezzo giusto, per (ticker, momento, giorno) dal diario
    veri = {}
    for r in load_registro_completo(DIARIO_NAME, load_diario()):
        if r.get("evento") in eventi_acquisto() and r.get("prezzo"):
            veri[(str(r.get("ticker")).upper(), r.get("evento"),
                  str(r.get("data") or "")[:10])] = r["prezzo"]
    riallineati, file_toccati = 0, []
    for nome in sorted(indice_archivio()):
        if not nome.startswith(ARC_PROFILI + "/"):
            continue
        g = os.path.basename(nome)[:10]
        if len(g) != 10 or g < dal:
            continue
        prof = read_data_json(nome, None)
        if not isinstance(prof, list) or not prof:
            continue          # non si legge: non si tocca
        cambi = 0
        for p in prof:
            if not isinstance(p, dict) or p.get("scartata") or not p.get("momento"):
                continue
            giusto = veri.get((str(p.get("ticker")).upper(), p.get("momento"),
                               str(p.get("giorno") or "")[:10]))
            if giusto is None or p.get("prezzo") is None:
                continue
            if abs(float(p["prezzo"]) - float(giusto)) <= 0.005:
                continue
            if p.get("prezzo_al_momento_del_profilo") is None:
                p["prezzo_al_momento_del_profilo"] = p["prezzo"]
            p["prezzo"] = giusto
            p["prezzo_riallineato_il"] = _arc_ora()
            cambi += 1
        if cambi and write_data_json(nome, prof) and nome not in _SALVATAGGI_FALLITI:
            riallineati += cambi
            file_toccati.append(nome)
    return {"riallineati": riallineati, "file": file_toccati}
