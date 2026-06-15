"""
Funzioni di supporto per l'app di analisi finanziaria.
Download dati (yfinance) + calcolo indicatori tecnici e fondamentali.
Nessuna dipendenza da TA-Lib: gli indicatori sono calcolati con pandas/numpy.
"""

import os
import json

import numpy as np
import pandas as pd
import yfinance as yf
import streamlit as st


# ---------------------------------------------------------------------------
# DOWNLOAD DATI
# ---------------------------------------------------------------------------

@st.cache_data(ttl=900, show_spinner=False)
def get_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """Scarica lo storico prezzi. Cache 15 min (dati gratuiti ~15 min di ritardo)."""
    t = yf.Ticker(ticker)
    df = t.history(period=period, interval=interval, auto_adjust=False)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.dropna(how="all")
    return df


@st.cache_data(ttl=900, show_spinner=False)
def get_info(ticker: str) -> dict:
    """Scarica i metadati / fondamentali dell'azienda."""
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        info = {}
    return info


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
    try:
        res = yf.Search(query, max_results=max_results)
        out = []
        for q in res.quotes:
            sym = q.get("symbol")
            if not sym:
                continue
            nome = q.get("shortname") or q.get("longname") or ""
            tipo = q.get("quoteType", "")
            borsa = q.get("exchDisp") or q.get("exchange", "")
            out.append((sym, nome, tipo, borsa))
        return out
    except Exception:
        return []


@st.cache_data(ttl=600, show_spinner=False)
def get_screen(name: str, count: int = 15) -> pd.DataFrame:
    """Classifica predefinita (es. 'day_gainers', 'day_losers', 'most_actives')."""
    try:
        res = yf.screen(name, count=count)
        quotes = res.get("quotes", []) if isinstance(res, dict) else []
    except Exception:
        quotes = []
    rows = []
    for q in quotes:
        rows.append({
            "Ticker": q.get("symbol", ""),
            "Nome": (q.get("shortName") or q.get("longName") or "")[:34],
            "Prezzo": q.get("regularMarketPrice"),
            "Var %": q.get("regularMarketChangePercent"),
            "Volume": q.get("regularMarketVolume"),
            "Cap.": q.get("marketCap"),
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=600, show_spinner=False)
def get_news(ticker: str, count: int = 8) -> list:
    """Notizie recenti legate a un ticker. Ritorna lista di dict normalizzati."""
    try:
        raw = yf.Ticker(ticker).news or []
    except Exception:
        raw = []
    out = []
    for item in raw[:count]:
        c = item.get("content", item) if isinstance(item, dict) else {}
        provider = c.get("provider") or {}
        click = c.get("clickThroughUrl") or c.get("canonicalUrl") or {}
        out.append({
            "title": c.get("title", "(senza titolo)"),
            "summary": c.get("summary") or c.get("description") or "",
            "publisher": provider.get("displayName", "") if isinstance(provider, dict) else "",
            "url": click.get("url", "") if isinstance(click, dict) else "",
            "date": (c.get("pubDate") or c.get("displayTime") or "")[:10],
        })
    return out


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
    """Prezzo e variazione del giorno per la watchlist (leggero)."""
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
def opportunity_row(ticker: str) -> dict:
    info = get_info(ticker)
    h = get_history(ticker, period="1y")
    if h.empty or len(h) < 60:
        return None
    h = add_indicators(h)
    last = h.iloc[-1]
    price = float(last["Close"])
    rsi = float(last["RSI"]) if not np.isnan(last.get("RSI", np.nan)) else None
    hi = info.get("fiftyTwoWeekHigh") or float(h["Close"].max())
    dd_high = (price / hi - 1) * 100 if hi else None          # % sotto il massimo 52s (negativo)
    perf_1m = (price / float(h["Close"].iloc[-21]) - 1) * 100 if len(h) > 21 else None
    perf_1y = (price / float(h["Close"].iloc[0]) - 1) * 100
    bb_low = last.get("BB_low", np.nan)
    below_bb = bool(price <= bb_low) if not np.isnan(bb_low) else False
    sma200 = last.get("SMA200", np.nan)
    above_sma200 = bool(price > sma200) if not np.isnan(sma200) else None
    etf = is_fund(info)
    fscore = _fundamental_score(info) if not etf else None
    name = (info.get("shortName") or info.get("longName") or ticker)[:34]
    return dict(ticker=ticker.upper(), name=name, price=price, rsi=rsi, dd_high=dd_high,
                perf_1m=perf_1m, perf_1y=perf_1y, below_bb=below_bb, above_sma200=above_sma200,
                etf=etf, fscore=fscore)


def _short_score(r):
    if r["rsi"] is None:
        return None
    rsi = r["rsi"]
    if rsi <= 25:
        base = 60
    elif rsi <= 30:
        base = 50
    elif rsi <= 35:
        base = 40
    elif rsi <= 40:
        base = 28
    elif rsi <= 45:
        base = 16
    else:
        base = 0
    if r["below_bb"]:
        base += 20
    if r["above_sma200"]:
        base += 20                           # trend di fondo intatto = rimbalzo più probabile
    return min(base, 100)


def _short_reasons(r):
    bits = []
    if r["rsi"] is not None:
        bits.append(f"RSI {r['rsi']:.0f}" + (" (ipervenduto)" if r["rsi"] <= 35 else ""))
    if r["dd_high"] is not None:
        bits.append(f"{r['dd_high']:.0f}% dal massimo")
    if r["below_bb"]:
        bits.append("sotto banda Bollinger")
    bits.append("trend di fondo positivo" if r["above_sma200"] else "trend di fondo debole")
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
        bits.append("ETF diversificato")
    elif r["fscore"] is not None:
        bits.append(f"fondamentali {r['fscore']:.0f}/100")
    if r["dd_high"] is not None:
        bits.append(f"{r['dd_high']:.0f}% sotto il massimo 52s")
    if r["perf_1y"] is not None:
        bits.append(f"1 anno {r['perf_1y']:+.0f}%")
    return " · ".join(bits)


@st.cache_data(ttl=900, show_spinner=False)
def opportunity_candidates(kind: str) -> list:
    """Universo di partenza dalle classifiche di mercato (yfinance)."""
    screens = (["day_losers", "most_actives", "small_cap_gainers"] if kind == "short"
               else ["undervalued_large_caps", "undervalued_growth_stocks", "day_losers"])
    names = []
    for s in screens:
        df = get_screen(s, 12)
        if not df.empty:
            names += [x for x in df["Ticker"].tolist() if x]
    return list(dict.fromkeys(names))[:30]   # cap per tenere la scansione sotto i ~30s


def scan_opportunities(tickers: list, kind: str) -> pd.DataFrame:
    rows = []
    for t in dict.fromkeys([x for x in tickers if x]):
        try:
            r = opportunity_row(t)
        except Exception:
            r = None
        if not r:
            continue
        if kind == "short":
            sc = _short_score(r)
            if sc is None or sc < 35:          # setup da ipervenduto / zona bassa
                continue
            if (r["dd_high"] or 0) > -8:        # dev'essere un calo reale, non un titolo ai massimi
                continue
            rows.append({"Ticker": r["ticker"], "Nome": r["name"], "Prezzo": r["price"],
                         "RSI": r["rsi"], "% dal max": r["dd_high"], "Perf 1 mese": r["perf_1m"],
                         "Occasione": round(sc), "Perché": _short_reasons(r)})
        else:
            sc = _long_score(r)
            if sc is None or sc < 50:
                continue
            if (r["dd_high"] or 0) > -12:       # richiede uno sconto significativo dai massimi
                continue
            rows.append({"Ticker": r["ticker"], "Nome": r["name"], "Prezzo": r["price"],
                         "% dal max": r["dd_high"], "Perf 1 anno": r["perf_1y"],
                         "Occasione": round(sc), "Perché": _long_reasons(r)})
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Occasione", ascending=False).set_index("Ticker")
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
