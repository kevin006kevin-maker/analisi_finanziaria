"""
Analisi Finanziaria — app Streamlit
Analisi fondamentale, tecnica e confronto/screener di azioni, ETF e indici.

Avvio:  streamlit run app.py --server.port 8507

NOTA: strumento di analisi e supporto decisionale, NON consulenza finanziaria.
I dati (yfinance) sono gratuiti e possono avere ritardo (~15 min) o essere incompleti.
"""

import os
import hmac
import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from streamlit_autorefresh import st_autorefresh

import finance_utils as fu

st.set_page_config(page_title="Analisi Finanziaria", page_icon="📈", layout="wide",
                   initial_sidebar_state="expanded")

# --- Stile: aspetto sobrio e professionale (tipografia Inter, palette scura raffinata) ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"], .stApp, button, input, textarea, select {
    font-family: 'Inter', -apple-system, "Segoe UI", system-ui, sans-serif;
}
.stApp { background: #13151a; color: #e8eaed; }

/* Nasconde solo gli elementi superflui SENZA toccare la barra in alto di Streamlit,
   così resta SEMPRE il pulsante nativo per aprire/chiudere il menu laterale (anche da telefono). */
[data-testid="stDecoration"] { display: none; }
footer { visibility: hidden; }
.block-container { padding-top: 2.2rem; max-width: 1250px; }

/* Sidebar */
section[data-testid="stSidebar"] {
    background: #101216;
    border-right: 1px solid rgba(255,255,255,0.06);
}
section[data-testid="stSidebar"] .stRadio [role="radiogroup"] { gap: 2px; }

/* Tipografia titoli: sobria, non gridata */
h1 { font-weight: 700; font-size: 1.85rem; letter-spacing: -0.022em; }
h2 { font-weight: 600; letter-spacing: -0.012em; margin-top: 0.4rem; }
h3 { font-weight: 600; letter-spacing: -0.01em; color: #f2f4f7; }
h4, h5, h6 { font-weight: 600; color: #cdd3db; }

/* Metriche come schede eleganti */
[data-testid="stMetric"] {
    background: linear-gradient(180deg, #1b1e25, #16181d);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 14px;
    padding: 14px 18px;
}
[data-testid="stMetricLabel"] { opacity: 0.72; font-weight: 500; }
[data-testid="stMetricValue"] { font-weight: 700; letter-spacing: -0.01em; }

/* Contenitori, expander, tabelle */
div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 16px; }
[data-testid="stExpander"] {
    border-radius: 12px;
    border: 1px solid rgba(255,255,255,0.07);
    background: #15171c;
}
[data-testid="stExpander"] summary { font-weight: 500; }
[data-testid="stExpander"] summary:hover { color: #6ea8fe; }
[data-testid="stDataFrame"] {
    border-radius: 12px; overflow: hidden;
    border: 1px solid rgba(255,255,255,0.06);
}

/* Bottoni raffinati */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
    border-radius: 9px;
    border: 1px solid rgba(255,255,255,0.12);
    background: #1b1e24;
    font-weight: 500;
    transition: all .15s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover {
    border-color: #6ea8fe; color: #cfe0ff; background: #1f2530;
}
.stButton > button[kind="primary"], .stFormSubmitButton > button {
    background: #2f6fed; border-color: #2f6fed; color: #fff;
}
.stButton > button[kind="primary"]:hover { background: #2a63d4; border-color: #2a63d4; color: #fff; }

/* Tab e link */
.stTabs [data-baseweb="tab-list"] { gap: 2px; border-bottom: 1px solid rgba(255,255,255,0.07); }
.stTabs [data-baseweb="tab"] { font-weight: 500; }
a, a:visited { color: #6ea8fe; text-decoration: none; }
a:hover { text-decoration: underline; }

/* Didascalie un filo più tenui */
[data-testid="stCaptionContainer"] { opacity: 0.82; }

/* Intestazione di pagina (banner) */
.page-header {
    padding: 20px 24px; margin: 0 0 20px 0; border-radius: 16px;
    background: linear-gradient(135deg, #1d2330 0%, #15181e 70%);
    border: 1px solid rgba(255,255,255,0.07);
    box-shadow: 0 6px 22px rgba(0,0,0,0.25);
}
.page-header .ph-title { font-size: 1.7rem; font-weight: 700; letter-spacing: -0.02em; color: #f3f5f8; }
.page-header .ph-sub { margin-top: 6px; color: #9aa4b2; font-size: 0.95rem; line-height: 1.4; }
.page-header .ph-accent { display:inline-block; width:34px; height:3px; border-radius:3px;
    background: linear-gradient(90deg,#3b82f6,#22d3ee); margin-bottom:12px; }

/* Testata di marca nella sidebar */
.app-brand { padding: 6px 2px 14px; }
.app-brand .ab-name { font-size: 1.15rem; font-weight: 700; letter-spacing: -0.01em; color: #f3f5f8; }
.app-brand .ab-name span { color: #3b82f6; }
.app-brand .ab-tag { font-size: 0.78rem; color: #8b94a3; margin-top: 2px; }

/* Schermata iniziale (hero) */
.hero {
    padding: 30px 28px; border-radius: 18px; margin-bottom: 22px;
    background: radial-gradient(1200px 240px at 0% 0%, rgba(59,130,246,0.16), transparent 60%), #16191f;
    border: 1px solid rgba(255,255,255,0.07);
}
.hero h2 { margin: 0; font-size: 1.7rem; font-weight: 750; color: #f3f5f8; }
.hero p { margin: 10px 0 0; color: #aab3c0; max-width: 680px; line-height: 1.5; }

/* ---- Adattamento per telefono (schermi stretti) ---- */
@media (max-width: 640px) {
    .block-container { padding-top: 1.3rem; padding-left: 0.8rem; padding-right: 0.8rem; }
    /* Le colonne si impilano in verticale invece di restare strette affiancate */
    [data-testid="stHorizontalBlock"] { flex-direction: column !important; gap: 0.5rem !important; }
    [data-testid="stHorizontalBlock"] > div,
    [data-testid="stColumn"], [data-testid="column"] {
        width: 100% !important; flex: 1 1 100% !important; min-width: 0 !important;
    }
    /* Intestazioni e titoli più contenuti */
    .page-header { padding: 15px 16px; }
    .page-header .ph-title { font-size: 1.35rem; }
    .hero { padding: 22px 18px; }
    .hero h2 { font-size: 1.4rem; }
    .hero p { font-size: 0.92rem; }
    h1 { font-size: 1.45rem; }
    h2 { font-size: 1.25rem; }
    [data-testid="stMetric"] { padding: 10px 13px; }
    [data-testid="stMetricValue"] { font-size: 1.4rem; }
}
</style>
""", unsafe_allow_html=True)


def page_header(title: str, subtitle: str = ""):
    """Intestazione di pagina con banner (sostituisce il semplice st.title)."""
    safe = str(title).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    sub = f"<div class='ph-sub'>{subtitle}</div>" if subtitle else ""
    st.markdown(
        f"<div class='page-header'><div class='ph-accent'></div>"
        f"<div class='ph-title'>{safe}</div>{sub}</div>",
        unsafe_allow_html=True,
    )


def show_chart(fig, use_container_width=True, config=None, key=None, **kw):
    """Grafico ottimizzato per il telefono: niente zoom fastidioso al tocco; toccando un punto
    della linea compare il valore con una linea-guida verticale. Dove il browser mobile lo
    consente, il valore segue anche il trascinamento del dito.
    Assegna una chiave univoca a ogni grafico per evitare collisioni di ID (es. stesso titolo
    nelle occasioni di breve e di lungo)."""
    try:
        fig.update_layout(dragmode=False, hovermode="x unified", hoverdistance=120, spikedistance=1000)
        fig.update_xaxes(fixedrange=True, showspikes=True, spikemode="across",
                         spikethickness=1, spikedash="dot", spikecolor="rgba(255,255,255,0.5)")
        fig.update_yaxes(fixedrange=True)
    except Exception:
        pass
    cfg = {"displayModeBar": False, "scrollZoom": False, "doubleClick": False}
    if config:
        cfg.update(config)
    if key is None:
        _n = st.session_state.get("_chart_seq", 0) + 1
        st.session_state["_chart_seq"] = _n
        key = f"_chart_{_n}"
    st.plotly_chart(fig, use_container_width=use_container_width, config=cfg, key=key, **kw)


def chart_history(ticker, period):
    """Storico per i grafici (intraday sui periodi brevi). Robusto alla finestra push→reboot di
    Streamlit Cloud: se il modulo in cache è ancora vecchio (senza get_chart_history) ripiega su
    get_history (giornaliero) invece di far crashare l'app."""
    fn = getattr(fu, "get_chart_history", None)
    if fn is not None:
        return fn(ticker, period)
    df = fu.get_history(ticker, period)
    try:
        df.attrs["intraday"] = False
    except Exception:
        pass
    return df


def _now_rome():
    """Ora locale italiana (il server cloud gira in UTC)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("Europe/Rome"))
    except Exception:
        return datetime.datetime.utcnow() + datetime.timedelta(hours=2)


# ---------------------------------------------------------------------------
# PROTEZIONE CON PASSWORD
# La password si imposta in .streamlit/secrets.toml (locale) o nei "Secrets" di
# Streamlit Cloud, come:  app_password = "la-tua-password"
# Se nessuna password è configurata, l'accesso è libero (utile in sviluppo).
# ---------------------------------------------------------------------------
def check_password():
    try:
        pwd = st.secrets["app_password"]
    except Exception:
        pwd = os.environ.get("APP_PASSWORD", "")
    if not pwd:
        return  # nessuna password impostata → accesso libero
    if st.session_state.get("auth_ok"):
        return

    def _verify():
        # .strip() su entrambi i lati: evita il classico "password giusta rifiutata" per uno
        # spazio o un a-capo in coda (nel secret o in un incolla dal telefono).
        typed = str(st.session_state.get("pwd_in", "")).strip()
        if hmac.compare_digest(typed, str(pwd).strip()):
            st.session_state["auth_ok"] = True
            st.session_state.pop("pwd_in", None)
        else:
            st.session_state["auth_ok"] = False

    st.markdown("## 🔒 Analisi Finanziaria")
    st.caption("Inserisci la password per accedere.")
    st.text_input("Password", type="password", key="pwd_in", on_change=_verify)
    if st.session_state.get("auth_ok") is False:
        st.error("Password errata, riprova.")
    st.stop()


check_password()

# Azzera a ogni esecuzione il contatore delle chiavi dei grafici (vedi show_chart):
# garantisce ID univoci e stabili per ogni grafico nella stessa pagina.
st.session_state["_chart_seq"] = 0

# ---------------------------------------------------------------------------
# STILE GIUDIZI
# ---------------------------------------------------------------------------
COLORS = {"positivo": "#1a7f37", "negativo": "#cf222e", "neutro": "#9a6700", None: "#8b949e"}
ICONS = {"positivo": "🟢", "negativo": "🔴", "neutro": "🟡", None: "⚪"}


def badge(label, value, judgement, help_text="", reason=""):
    color = COLORS.get(judgement, "#8b949e")
    icon = ICONS.get(judgement, "⚪")
    info_icon = ""
    if help_text:
        safe = help_text.replace('"', "&quot;")
        info_icon = (
            f" <span title=\"{safe}\" "
            f"style='cursor:help;color:#0969da;font-size:0.85em'>&#9432;</span>"
        )
    reason_html = ""
    if reason:
        reason_html = (
            f"<div style='font-size:0.82em;color:#a9b1ba;margin-left:1.5em;margin-top:1px'>"
            f"↳ {reason}</div>"
        )
    st.markdown(
        f"<div style='padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.12);'>"
        f"{icon} <b>{label}</b>{info_icon}: "
        f"<span style='color:{color};font-weight:600'>{value}</span>"
        f"{reason_html}</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------------------------
st.sidebar.markdown(
    "<div class='app-brand'><div class='ab-name'>Analisi<span>·</span>Finanziaria</div>"
    "<div class='ab-tag'>Analisi titoli · occasioni · portafoglio</div></div>",
    unsafe_allow_html=True,
)

# Cambio sezione programmatico (es. bottone "📊 Analizza" dal Monitoraggio):
# va impostato PRIMA che il widget radio venga creato, altrimenti Streamlit
# vieta di modificare la chiave del widget già istanziato.
if "_goto_section" in st.session_state:
    st.session_state["section_radio"] = st.session_state.pop("_goto_section")

# --- Sezione principale ---
section = st.sidebar.radio(
    "Sezione", ["Analisi di un titolo", "Occasioni di mercato",
                "In osservazione", "Monitoraggio", "Portafoglio", "Attualità"], key="section_radio",
    help="«Analisi di un titolo» studia una singola azienda/ETF. «Occasioni» scansiona il mercato per cali interessanti. "
         "«In osservazione» mostra le occasioni che il sistema sta seguendo verso un'eventuale promozione. "
         "«Monitoraggio» segue nel tempo le occasioni che hai scelto. «Portafoglio» registra i tuoi acquisti veri e mostra il guadagno/perdita. "
         "«Attualità» raccoglie le classifiche di mercato (rialzi/ribassi/più scambiati) e le notizie recenti divise per azienda/ETF.",
)
st.sidebar.markdown("---")

# --- Livello di dettaglio ---
livello = st.sidebar.radio(
    "Modalità", ["🟢 Principiante", "🔵 Esperto"], horizontal=True, index=1,
    help="Principiante mostra solo l'essenziale spiegato a parole. Esperto aggiunge tutti gli indicatori avanzati.",
)
expert = livello.endswith("Esperto")

st.sidebar.caption("Cerca un'azienda per **nome** oppure inserisci il simbolo.")

# --- Ricerca per nome (con suggerimenti) ---
query = st.sidebar.text_input("🔎 Cerca", placeholder="es. Apple, Eni, S&P 500, Tesla")
if query and len(query.strip()) >= 2:
    results = fu.search_symbols(query)
    if results:
        labels = [f"{s} — {n}  ·  {b or t}" for s, n, t, b in results]
        idx = st.sidebar.selectbox(
            "Risultati della ricerca", range(len(labels)),
            format_func=lambda i: labels[i],
        )
        if st.sidebar.button("✅ Analizza questo", use_container_width=True):
            st.session_state["ticker"] = results[idx][0]
    else:
        st.sidebar.caption("Nessun risultato — prova un altro termine.")

ticker = st.sidebar.text_input(
    "Ticker da analizzare",
    value=st.session_state.get("ticker", ""),
    help="Es: AAPL, MSFT, ENI.MI, ISP.MI, ^GSPC, VWCE.DE",
).strip().upper()
st.session_state["ticker"] = ticker

PERIOD_OPTIONS = {
    "1 mese": "1mo", "3 mesi": "3mo", "6 mesi": "6mo",
    "1 anno": "1y", "2 anni": "2y", "5 anni": "5y", "Massimo": "max",
}
period_label = st.sidebar.selectbox("Periodo storico", list(PERIOD_OPTIONS.keys()), index=3)
period = PERIOD_OPTIONS[period_label]

translate_news = st.sidebar.checkbox("🇮🇹 Traduci testi in italiano (notizie e descrizioni)", value=True)

# --- Watchlist (preferiti) ---
st.sidebar.markdown("---")
st.sidebar.markdown("### ⭐ La mia watchlist")
watchlist = fu.load_watchlist()

wc1, wc2 = st.sidebar.columns(2)
if wc1.button("➕ Aggiungi", use_container_width=True, help=f"Aggiungi {ticker} ai preferiti"):
    if ticker and ticker not in watchlist:
        watchlist.append(ticker)
        fu.save_watchlist(watchlist)
        st.rerun()
if wc2.button("➖ Rimuovi", use_container_width=True, help=f"Togli {ticker} dai preferiti"):
    if ticker in watchlist:
        watchlist.remove(ticker)
        fu.save_watchlist(watchlist)
        st.rerun()

if watchlist:
    for w in watchlist:
        q = fu.quick_quote(w)
        chg = q.get("change_pct")
        price = q.get("price")
        arrow = "▲" if (chg or 0) >= 0 else "▼"
        col = "#1a7f37" if (chg or 0) >= 0 else "#cf222e"
        price_txt = f"{price:,.2f}" if price is not None else "n/d"
        chg_txt = f"{arrow} {chg:+.2f}%" if chg is not None else ""
        bcol, icol = st.sidebar.columns([3, 2])
        if bcol.button(w, key=f"wl_{w}", use_container_width=True):
            st.session_state["ticker"] = w
            st.rerun()
        icol.markdown(
            f"<div style='text-align:right;padding-top:6px'>{price_txt}<br>"
            f"<span style='color:{col};font-size:0.85em'>{chg_txt}</span></div>",
            unsafe_allow_html=True,
        )
else:
    st.sidebar.caption("Vuota. Premi ➕ per salvare il titolo che stai analizzando.")

# --- Monitoraggio occasioni (conteggio) ---
tracked = fu.load_tracking()
if tracked:
    st.sidebar.caption(f"📌 Stai monitorando **{len(tracked)}** occasion{'e' if len(tracked)==1 else 'i'} "
                       "(vedi la sezione «Monitoraggio»).")

st.sidebar.markdown("---")
st.sidebar.caption(
    "⚠️ Strumento di analisi a scopo informativo. **Non è consulenza finanziaria.** "
    "I dati gratuiti possono avere ritardo o essere incompleti."
)

# ---------------------------------------------------------------------------
# NAVIGAZIONE "INDIETRO" INTERNA
# Il tasto indietro del telefono uscirebbe dall'app; questo pulsante riporta in
# modo affidabile alla schermata precedente (sezione + titolo) dentro l'app.
# ---------------------------------------------------------------------------
_cur_view = (section, ticker)
if st.session_state.pop("_nav_back", False):
    st.session_state["_nav_current"] = _cur_view            # arrivo da "Indietro": non impilare
else:
    _prev = st.session_state.get("_nav_current")
    if _prev is not None and _prev != _cur_view:
        _stack = st.session_state.setdefault("_nav_stack", [])
        if not _stack or _stack[-1] != _prev:
            _stack.append(_prev)
        del _stack[:-30]                                     # conserva solo le ultime 30 schermate
    st.session_state["_nav_current"] = _cur_view

if st.session_state.get("_nav_stack"):
    _bcol, _ = st.columns([1, 4])
    if _bcol.button("← Indietro", use_container_width=True, key="nav_back_btn",
                    help="Torna alla schermata precedente. Usa questo invece del tasto «indietro» del telefono."):
        _dest_section, _dest_ticker = st.session_state["_nav_stack"].pop()
        st.session_state["_goto_section"] = _dest_section
        st.session_state["ticker"] = _dest_ticker
        st.session_state["_nav_back"] = True
        st.rerun()

# ===========================================================================
# SEZIONE: OCCASIONI DI MERCATO (pagina a sé, indipendente dal titolo)
# ===========================================================================
if section.startswith("Occasioni"):
    page_header("Occasioni di mercato",
                "Titoli ed ETF in calo con segnali tipici da rimbalzo o sconto — spunti da approfondire, non consigli.")
    st.caption("Parto dalle classifiche di mercato (USA). Puoi aggiungere ticker tuoi (anche .MI / ETF europei) "
               "e includere la watchlist, così copre qualsiasi titolo.")

    extra_raw = st.text_area("Ticker extra da includere (separati da virgola, opzionale)",
                             value="", height=68, key="opp_extra")
    extra = [t.strip().upper() for t in extra_raw.replace(";", ",").split(",") if t.strip()]
    ic1, ic2, ic3 = st.columns(3)
    inc_wl = ic1.checkbox("Includi la mia watchlist", value=bool(watchlist), key="opp_wl")
    inc_eu = ic2.checkbox("Includi Borsa Italiana / Europa", value=True, key="opp_eu",
                          help="Aggiunge alla ricerca i principali titoli di Milano e d'Europa (le classifiche "
                               "automatiche gratuite coprono solo gli USA).")
    inc_etf = ic3.checkbox("Includi ETF", value=True, key="opp_etf",
                           help="Aggiunge alla ricerca i principali ETF (USA e UCITS europei): "
                                "anche un ETF può essere un'occasione quando scende parecchio.")

    # Salva la config (ticker extra + watchlist + preferenze EU/ETF) sul data-layer: così il
    # SISTEMA AUTONOMO osserva lo STESSO universo che vedi qui, non solo quello standard.
    fu.save_opp_config(extra + (watchlist if inc_wl else []), inc_eu, inc_etf)

    refresh_choice = st.selectbox(
        "🔄 Aggiornamento automatico", ["Disattivato", "Ogni 15 minuti", "Ogni 30 minuti"],
        index=1, key="opp_refresh_int",
        help="Le occasioni vengono cercate da sole. Con l'aggiornamento attivo si riscansionano in autonomia "
             "(i dati si rinnovano davvero ~ogni 15 minuti: indicatori giornalieri + limiti delle API).")

    # Le occasioni vengono cercate in automatico all'apertura della sezione (nessun pulsante)
    if True:
        if refresh_choice != "Disattivato":
            st_autorefresh(interval=(900000 if "15" in refresh_choice else 1800000), key="opp_auto")
            st.caption(f"🔄 Aggiornamento automatico **attivo** ({refresh_choice.lower()}) · "
                       f"ultimo aggiornamento: {_now_rome().strftime('%H:%M')}")

        cloud = fu.cloud_mode()
        if cloud:
            st.caption("🤖 **Sistema autonomo attivo sul server**: le occasioni vengono aggiornate ogni ~15 minuti "
                       "anche a PC spento, e le migliori (in salita da 3 giorni) finiscono da sole nel «Monitoraggio». "
                       "Qui vedi sempre l'ultimo aggiornamento del server.")
            auto_promote_on = True
        else:
            auto_promote_on = st.checkbox(
                "🤖 Salva da solo le occasioni che migliorano per 3 giorni di fila", value=True,
                key="auto_promote",
                help="A ogni aggiornamento il sistema registra l'evoluzione di tutte le occasioni. Quando la convenienza "
                     "di un titolo sale per 3 giorni consecutivi, lo aggiunge da solo al «Monitoraggio». "
                     "Nota (modalità locale): il controllo avviene mentre questa pagina è aperta; i 3 giorni si contano "
                     "sui giorni in cui apri l'app. Per renderlo automatico anche a PC spento vedi README_AUTONOMIA.md.")

        with st.expander("🎛️ Filtri", expanded=False):
            fco1, fco2, fco3 = st.columns(3)
            f_min_conv = fco1.slider("Convenienza minima", 0, 100, 0, key="f_conv")
            f_rel = fco2.radio("Affidabilità", ["Tutte", "Almeno 🟡 Media", "Solo 🟢 Alta"], key="f_rel")
            f_max_loss = fco3.slider("Rischio di perdita massimo (%)", 0, 100, 100, key="f_loss")

        with st.expander("📐 Dimensionamento posizione (rischio fisso)", expanded=False):
            st.caption("Per ogni occasione di breve calcola **quante azioni** comprare rischiando una quota fissa "
                       "del capitale, dato lo **stop = prezzo − 2×ATR**. Regola d'oro: non rischiare più dell'1-2% "
                       "del capitale per singola operazione.")
            psc1, psc2 = st.columns(2)
            pos_capital = psc1.number_input("Capitale da impiegare (€)", min_value=0.0, value=10000.0,
                                            step=500.0, key="pos_capital")
            pos_risk = psc2.slider("Rischio per operazione (%)", 0.25, 5.0, 1.0, 0.25, key="pos_risk")

        # Regime di volatilità: moltiplicatore globale del breve (il rimbalzo si rompe nei crash)
        regime = fu.volatility_regime()
        rg_factor, rg_label, rg_vix = regime["factor"], regime["label"], regime["vix"]
        rgvix = f" · VIX ~{rg_vix:.0f}" if rg_vix is not None else ""
        if rg_factor >= 1.0:
            st.success(f"🌡️ **Regime di volatilità: {rg_label}**{rgvix} — condizioni normali per i rimbalzi da ipervenduto.")
        elif rg_factor >= 0.75:
            st.info(f"🌡️ **Regime di volatilità: {rg_label}**{rgvix} — i punteggi di breve sono **ridotti** "
                    f"(×{rg_factor:.2f}): nei mercati nervosi il rimbalzo è meno affidabile.")
        else:
            st.error(f"🌡️ **Regime di volatilità: {rg_label}**{rgvix} — punteggi di breve **fortemente ridotti** "
                     f"(×{rg_factor:.2f}): in un crash il mean-reversion (rimbalzo) tende a rompersi. Prudenza.")

        mkt_1m = fu.market_perf_1m()

        # --- Scansione unica (poi riusata da shortlist, sistema autonomo e tabelle) ---
        def _scan(kind):
            base = fu.opportunity_candidates(kind, include_eu=inc_eu, include_etf=inc_etf)
            # + sticky watch: ri-scansiona i titoli già in osservazione con finestra aperta,
            # così non spariscono dopo un giorno e possono maturare verso il Monitoraggio.
            universe = list(dict.fromkeys(base + extra + (watchlist if inc_wl else [])
                                          + fu.sticky_watch_tickers(kind)))
            return fu.scan_opportunities(universe, kind)

        with st.spinner("Analizzo il mercato…"):
            full_short, full_long = _scan("short"), _scan("long")

        # --- 🤖 Sistema autonomo: registra l'evoluzione e promuove chi migliora da 3 giorni ---
        # In modalità cloud è il job su GitHub Actions a registrare/promuovere (anche a PC spento);
        # l'app si limita a LEGGERE i risultati. In locale puro, lo fa l'app a ogni refresh.
        promoted = []
        if auto_promote_on and not cloud:
            fu.record_observations(full_short, "short")
            fu.record_observations(full_long, "long")
            # Sticky: per i titoli già in osservazione (finestra aperta) NON tra le occasioni di oggi,
            # registra comunque il prezzo → i giorni avanzano e la promozione resta possibile.
            fu.record_sticky_observations("short", full_short)
            fu.record_sticky_observations("long", full_long)
            # Calibrazione (locale): registra la P(salita) di ogni occasione per il backtest
            for _df, _h in ((full_short, 21), (full_long, 252)):
                if _df is not None and not _df.empty:
                    for _tk, _rr in _df.iterrows():
                        fu.log_forecast(_tk, _h, _rr.get("Prob. salita"), _rr.get("Prezzo"))
            promoted = fu.auto_promote_opportunities()
            fu.manage_monitoring()      # rimozioni delle perdenti + (eventuali) prime notifiche
        if promoted:
            st.success("🤖 **Aggiunte da sole al Monitoraggio** (prezzo in ripresa dopo la fase di osservazione): "
                       + ", ".join(f"**{t}**" for t in promoted) + ". Le trovi nella sezione «Monitoraggio».")

        # (Le occasioni «in osservazione» hanno ora una sezione dedicata nel menu: «In osservazione».)

        # --- 🏆 Le migliori da seguire (shortlist automatica) ---
        def _best_picks(df, n=3):
            if df is None or df.empty:
                return df
            d = df[df["Affidabilità"].isin(["🟢 Alta", "🟡 Media"])]   # scarta le stime poco affidabili
            return d.sort_values("Convenienza", ascending=False).head(n)

        with st.container(border=True):
            st.markdown("### Le migliori da seguire")
            st.caption("Selezione automatica delle occasioni con la **convenienza più alta** e affidabilità almeno 🟡 media, "
                       "di breve e di lungo periodo. È il punto di partenza più sensato: seguile qualche giorno nel "
                       "**📌 Monitoraggio** e compra quelle il cui segnale si **rafforza** (non quelle che continuano a scendere).")
            best_s, best_l = _best_picks(full_short), _best_picks(full_long)
            picks, rows_view = [], []
            for kind_b, label_b, dfb_src in [("short", "⚡ Breve", best_s), ("long", "🏛️ Lungo", best_l)]:
                if dfb_src is None or dfb_src.empty:
                    continue
                for tk, r in dfb_src.iterrows():
                    picks.append((tk, kind_b))
                    rows_view.append({"Tipo": label_b, "Ticker": tk, "Azienda": r["Nome"],
                                      "Conv.": int(r["Convenienza"]), "Prob. salita": r.get("Prob. salita"),
                                      "Rischio": r.get("Rischio perdita"), "Affid.": r["Affidabilità"]})
            if not rows_view:
                st.info("Al momento nessuna occasione con affidabilità almeno media. Guarda comunque le tabelle qui sotto.")
            else:
                dfb = pd.DataFrame(rows_view).set_index("Ticker")
                st.dataframe(dfb, use_container_width=True, column_config={
                    "Conv.": st.column_config.ProgressColumn("🏅 Convenienza", min_value=0, max_value=100, format="%d",
                        help="Più alto = prospettive migliori (fonde prob. salita, guadagno atteso, rischio e affidabilità)."),
                    "Prob. salita": st.column_config.NumberColumn("📈 Prob. salita", format="%.0f%%"),
                    "Rischio": st.column_config.NumberColumn("📉 Rischio perdita", format="%.0f%%"),
                    "Affid.": st.column_config.TextColumn("📊 Affidabilità"),
                })
                already = fu.load_tracking()
                new_picks = [(tk, k) for tk, k in picks if tk not in already]
                bcol1, bcol2 = st.columns([1, 2])
                if new_picks:
                    if bcol1.button(f"📌 Segui tutte ({len(new_picks)})", use_container_width=True, type="primary",
                                    key="follow_best"):
                        fu.track_many(new_picks)   # un'unica scrittura: le salva tutte (anche sul cloud)
                        st.success(f"📌 Aggiunte {len(new_picks)} occasioni al Monitoraggio.")
                        st.rerun()
                    bcol2.caption("Le aggiunge tutte alla sezione «Monitoraggio» con lo scatto di oggi. "
                                  "Potrai sempre toglierne qualcuna lì.")
                else:
                    bcol1.caption("✅ Le stai già seguendo tutte (vedi «Monitoraggio»).")
        st.markdown("---")

        def render_opps(df_full, kind, header, help_txt, cols_cfg):
            st.markdown(f"### {header}")
            st.caption(help_txt)
            with st.expander("ℹ️ Come leggere queste occasioni (e i rischi)"):
                if kind == "short":
                    st.markdown(
                        "**Cosa cerchiamo:** titoli **scesi molto** e tecnicamente **«ipervenduti»**. "
                        "Storicamente, dopo cali eccessivi e improvvisi, il prezzo tende a **rimbalzare** nel breve (settimane).\n\n"
                        "- **RSI** (0-100): misura la «foga» di vendita. Sotto 30 = ipervenduto, possibile rimbalzo.\n"
                        "- **% dal max**: quanto è sceso dal massimo dell'ultimo anno.\n"
                        "- **Banda di Bollinger**: se il prezzo la sfora verso il basso, è a un estremo.\n"
                        "- **🔄 Conferma d'inversione**: non segnaliamo un rimbalzo finché il titolo **non ha girato** "
                        "(chiusura verde, RSI in risalita o rientro dentro le bande). È il rimedio diretto al «coltello che cade».\n"
                        "- **🔊 RVOL** (volume relativo): un giorno verde con volume sopra la media segnala "
                        "**capitolazione + ripartenza** credibile.\n"
                        "- **⚖️ R:R** (rischio/rendimento): bersaglio (media 50gg) vs **stop = prezzo − 2×ATR**. "
                        "Mostriamo solo setup con R:R **≥ 1,5** (scartiamo le scommesse asimmetriche).\n"
                        "- **🌡️ Regime di volatilità**: nei mercati turbolenti (VIX alto) i punteggi del breve sono ridotti, "
                        "perché il rimbalzo da ipervenduto si rompe nei crash.\n"
                        "- **Trend di fondo**: se il prezzo è sopra la media a 200 giorni il rimbalzo è più probabile.\n"
                        "- **💎 Segnale**: forza del setup (ipervenduto + trend sano + inversione confermata + volume).\n\n"
                        "⚠️ **Rischio:** un titolo che rimbalza dopo un calo è una *scommessa di breve*. "
                        "Cali fortissimi possono continuare (il «coltello che cade»). Spunto da approfondire, non un segnale di acquisto."
                    )
                else:
                    st.markdown(
                        "**Cosa cerchiamo:** aziende con **buoni fondamentali** (o ETF diversificati) **scese parecchio dai massimi**: "
                        "l'idea è comprare qualità «in saldo» e tenere per **anni**.\n\n"
                        "- **🧭 Qualità (trend) — anti-trappola di valore**: incrociamo il calo di prezzo col **trend dei conti**. "
                        "Prezzo giù + ricavi/utili/margini stabili = vera occasione; prezzo giù + conti in calo = **trappola**. È la protezione n°1.\n"
                        "- **💎 Valore**: qualità del business a **pilastri pesati** (Qualità 35% / Solidità 25% / Valutazione 25% / Crescita 15%) "
                        "— non più un conteggio di pallini dove il P/S pesava quanto la redditività — combinata con lo sconto dai massimi.\n"
                        "- **Radar qualità** (nel dettaglio): Valore / Qualità / Salute / Crescita / Dividendo, 0-100.\n"
                        "- **Metriche serie** (nel dettaglio): **ROIC** vs costo del capitale, **EV/EBITDA**, **FCF yield**, "
                        "**copertura del dividendo col flusso di cassa**, indice di salute (Piotroski semplificato), **Altman Z** (industriali USA).\n"
                        "- **Settore**: limitiamo le occasioni a poche per settore (niente liste tutte-banche).\n\n"
                        "⚠️ **Rischio:** uno sconto **non garantisce** la risalita. Chiediti sempre *perché* il titolo è sceso: "
                        "difficoltà temporanea (possibile occasione) o problema strutturale (trappola di valore)?"
                    )
            if df_full is None or df_full.empty:
                st.info("Nessuna occasione che soddisfi i criteri in questo momento.")
                return
            df = df_full.copy()
            # Filtri scelti dall'utente
            df = df[df["Convenienza"] >= f_min_conv]
            if f_rel == "Solo 🟢 Alta":
                df = df[df["Affidabilità"] == "🟢 Alta"]
            elif f_rel == "Almeno 🟡 Media":
                df = df[df["Affidabilità"].isin(["🟢 Alta", "🟡 Media"])]
            df = df[df["Rischio perdita"].isna() | (df["Rischio perdita"] <= f_max_loss)]
            if df.empty:
                st.info("Nessuna occasione con i filtri scelti. Allarga i criteri nei 🎛️ Filtri.")
                return
            orizz = "~1 anno" if kind == "long" else "~1 mese"

            def _block(df_sub, subtitle=None):
                if subtitle:
                    st.markdown(f"**{subtitle}**")
                if df_sub.empty:
                    st.caption("Nessun titolo in questa fascia con i filtri scelti.")
                    return
                st.dataframe(df_sub, use_container_width=True,
                             height=min(60 + 38 * len(df_sub), 460), column_config=cols_cfg)
                st.caption(f"📈 **Prob. salita** e 📉 **Rischio perdita** sono **stime statistiche** dai rendimenti "
                           f"storici (orizzonte {orizz}), **non previsioni**.")
                st.markdown("###### Approfondimenti — notizie recenti e perché")
                for tk, row in df_sub.head(5).iterrows():
                    pg, pl = row.get("Prob. salita"), row.get("Rischio perdita")
                    with st.expander(f"{tk} — {row['Nome']}   ·   💎 {int(row['Occasione'])}"):
                        st.markdown(f"**Perché è un'occasione:** {row['Perché']}")
                        bits = []
                        if pg is not None and not pd.isna(pg):
                            bits.append(f"📈 probabilità di salita **~{pg:.0f}%**")
                        eg = row.get("Guadagno atteso")
                        if eg is not None and not pd.isna(eg):
                            bits.append(f"🎯 guadagno atteso **{eg:+.1f}%**")
                        if pl is not None and not pd.isna(pl):
                            bits.append(f"📉 rischio di perdita oltre il 15% **~{pl:.0f}%**")
                        rel = row.get("Affidabilità")
                        if bits:
                            line = f"**Stima statistica ({orizz}):** " + " · ".join(bits)
                            if rel and not pd.isna(rel):
                                line += f"  \nAffidabilità della stima: **{rel}**"
                            line += "  \n_Stima dai dati storici, non una previsione._"
                            st.markdown(line)
                        det = fu.opportunity_row(tk, with_fundamentals=(kind == "long"))
                        if det:
                            price = det.get("price")
                            tgt, stp = det.get("target_price"), det.get("stop_price")
                            cper = {"1 giorno": "1d", "1 settimana": "5d", "1 mese": "1mo",
                                    "1 anno": "1y", "Tutto": "max"}
                            csel = st.radio("Periodo del grafico", list(cper.keys()), index=3,
                                            horizontal=True, key=f"oppchart_{kind}_{tk}")
                            # giorno → intraday ~15 min · settimana → intraday ~1 ora · altri → 1/giorno
                            hc = chart_history(tk, cper[csel])
                            if not hc.empty:
                                sfig = go.Figure()
                                sfig.add_trace(go.Scatter(x=hc.index, y=hc["Close"], mode="lines",
                                                          line=dict(color="#0969da", width=2), name="Prezzo"))
                                if tgt:
                                    sfig.add_hline(y=tgt, line=dict(color="#1a7f37", dash="dash", width=1),
                                                   annotation_text="🎯 bersaglio (media 50gg)", annotation_position="top left")
                                if stp:
                                    sfig.add_hline(y=stp, line=dict(color="#cf222e", dash="dash", width=1),
                                                   annotation_text="🛑 stop", annotation_position="bottom left")
                                sfig.update_layout(height=230, margin=dict(t=10, b=10, l=10, r=10),
                                                   showlegend=False, yaxis_title=None, xaxis_title=None)
                                show_chart(sfig, use_container_width=True)
                                _id = bool(hc.attrs.get("intraday"))
                                _gran = "~15 min" if cper[csel] == "1d" else "~1 ora"
                                st.caption(f"📅 Ultimo dato: {hc.index[-1].strftime('%d/%m/%Y %H:%M' if _id else '%d/%m/%Y')}"
                                           + (f" · prezzo intraday {_gran}" if _id else " · chiusura giornaliera"))
                            lvl = []
                            if tgt and price:
                                lvl.append(f"🎯 Bersaglio: **{tgt:,.2f}** ({(tgt/price-1)*100:+.0f}%)")
                            if stp and price:
                                lvl.append(f"🛑 Stop: **{stp:,.2f}** ({(stp/price-1)*100:+.0f}%)")
                            rr_v = det.get("rr")
                            if rr_v is not None:
                                lvl.append(f"⚖️ R:R **{rr_v:.1f}**")
                            atrp = det.get("atr_pct")
                            if atrp is not None:
                                lvl.append(f"📐 ATR **{atrp:.1f}%**")
                            rvol_v = det.get("rvol")
                            if rvol_v is not None:
                                lvl.append(f"🔊 RVOL **{rvol_v:.1f}×**")
                            if lvl:
                                st.markdown(" · ".join(lvl))
                            st.caption("👀 **Come leggere:** la linea blu è il prezzo degli ultimi ~3 mesi. "
                                       "La linea **verde** è la media a 50 giorni (il *bersaglio* di un rimbalzo): "
                                       "se il prezzo le sta **sotto**, c'è spazio per risalire. La **rossa** è lo stop "
                                       "(**prezzo − 2×ATR**, tarato sulla volatilità del titolo): sotto di esso l'idea di "
                                       "rimbalzo salta. Livelli indicativi, non consigli.")
                            # --- Dimensionamento a rischio fisso (solo breve, con stop ATR) ---
                            if kind == "short" and stp and price:
                                ps = fu.position_size(pos_capital, pos_risk, price, stp)
                                if ps:
                                    st.markdown(
                                        f"📐 **Quanto comprare** (rischio {pos_risk:.2f}% di € {pos_capital:,.0f}): "
                                        f"**{ps['qty']:.2f}** azioni ≈ **€ {ps['value']:,.0f}** investiti · "
                                        f"perdita massima allo stop ≈ **€ {ps['risk_eur']:,.0f}** "
                                        f"({ps['stop_pct']:+.1f}% dal prezzo).")
                                    st.caption("Calcolo a rischio fisso: qty = capitale × rischio% / (prezzo − stop). "
                                               "Così ogni operazione mette a rischio la **stessa** cifra, qualunque sia la volatilità.")
                                # First-passage: P(il prezzo tocca lo stop lungo il percorso, ~1 mese)
                                if stp and price and price > stp:
                                    hp = fu.get_history(tk, period="1y")
                                    fp = fu.forecast_paths(hp, 21, stop_pct=(stp / price - 1))
                                    if fp and fp.get("p_touch_stop") is not None:
                                        _net = fu.net_return_pct(fp.get("expectancy"))
                                        st.caption(f"🎲 **Probabilità di toccare lo stop entro ~1 mese: ~{fp['p_touch_stop']}%** "
                                                   f"· P(salita) ~{fp['p_up']}% (intervallo {fp['p_up_lo']}–{fp['p_up_hi']}%) "
                                                   f"· rendimento atteso ~{fp['expectancy']:+.1f}% (netto ~{_net:+.1f}%) "
                                                   f"· ventaglio a 1 mese: da {fp['ret_p10']:+.0f}% (sfortuna) "
                                                   f"a {fp['ret_p90']:+.0f}% (fortuna), mediana {fp['ret_p50']:+.0f}%. "
                                                   "Stima da block bootstrap dei rendimenti reali (code grasse), non una previsione.")
                            s1m = det.get("perf_1m")
                            if mkt_1m is not None and s1m is not None:
                                if abs(s1m - mkt_1m) <= 1:
                                    conf = "in linea col mercato"
                                elif s1m < mkt_1m:
                                    conf = "**peggio del mercato** (calo più specifico del titolo)"
                                else:
                                    conf = "**meglio del mercato**"
                                st.caption(f"📊 Ultimo mese: {tk} {s1m:+.0f}% · mercato S&P 500 {mkt_1m:+.0f}% → {conf}.")
                            # --- Qualità in saldo: anti-trappola, radar, metriche serie (solo lungo) ---
                            if kind == "long":
                                trap = det.get("trap")
                                if trap:
                                    msg = f"**Anti-trappola di valore:** {trap['label']}"
                                    if trap.get("reasons"):
                                        msg += " — " + ", ".join(trap["reasons"])
                                    v = trap.get("verdict")
                                    (st.success if v == "occasione" else
                                     st.error if v == "trappola" else st.warning)(msg)
                                    st.caption("Incrocia il **calo di prezzo** col **trend dei fondamentali**: prezzo giù + "
                                               "conti stabili = occasione; prezzo giù + conti in calo = trappola. "
                                               "È la protezione più importante: uno sconto da solo non basta.")
                                radar = det.get("radar") or {}
                                rvals = [(k, radar.get(k)) for k in
                                         ["Valore", "Qualità", "Salute", "Crescita", "Dividendo"]
                                         if radar.get(k) is not None]
                                if len(rvals) >= 3:
                                    cats = [k for k, _ in rvals] + [rvals[0][0]]
                                    vals = [val for _, val in rvals] + [rvals[0][1]]
                                    rfig = go.Figure()
                                    rfig.add_trace(go.Scatterpolar(r=vals, theta=cats, fill="toself",
                                                                   line=dict(color="#3b82f6"), name="Qualità"))
                                    rfig.update_layout(height=300, margin=dict(t=30, b=30, l=40, r=40),
                                                       polar=dict(radialaxis=dict(range=[0, 100])),
                                                       showlegend=False)
                                    show_chart(rfig, use_container_width=True)
                                    st.caption("👀 **Radar qualità** (0-100, più ampio = meglio): "
                                               "Valore = a buon prezzo · Qualità = redditività/ROIC · "
                                               "Salute = solidità finanziaria · Crescita = ricavi/utili · "
                                               "Dividendo = rendimento sostenibile.")
                                # Metriche serie dai bilanci ufficiali SEC (USA, on-demand; stessa
                                # companyfacts in cache → una sola chiamata di rete per Altman/EV-EBIT/Piotroski)
                                is_fin = fu._is_financial_sector(det.get("sector"))
                                ev_ebit_real = fu.ev_ebit_from_sec(tk) if not is_fin else None
                                piotroski = fu.piotroski_from_sec(tk) if not is_fin else None
                                mbits = []
                                if det.get("roic") is not None:
                                    mbits.append(f"**ROIC** {det['roic'] * 100:.0f}% (vs costo capitale ~9%)")
                                if ev_ebit_real is not None:
                                    mbits.append(f"**EV/EBIT** {ev_ebit_real:.1f} (SEC)")
                                elif det.get("ev_ebit") is not None:
                                    mbits.append(f"**EV/EBITDA** {det['ev_ebit']:.1f}")
                                if det.get("fcf_yield") is not None:
                                    mbits.append(f"**FCF yield** {det['fcf_yield']:.1f}%")
                                if det.get("gross_m") is not None:
                                    mbits.append(f"**Margine lordo** {det['gross_m'] * 100:.0f}%")
                                if det.get("interest_cov") is not None:
                                    mbits.append(f"**Copertura interessi** {det['interest_cov']:.1f}×")
                                if piotroski is not None:
                                    mbits.append(f"**Piotroski F-Score** {piotroski['score']}/{piotroski['max']} (SEC)")
                                elif det.get("fscore_health") is not None:
                                    mbits.append(f"**Salute (Piotroski sempl.)** {det['fscore_health']:.0f}/9")
                                if det.get("div_cov") is not None:
                                    mbits.append(f"**Dividendo coperto dal FCF** {det['div_cov']:.1f}×")
                                if det.get("rev_cagr3") is not None:
                                    mbits.append(f"**Ricavi 3 anni** {det['rev_cagr3'] * 100:+.0f}%/anno")
                                if det.get("eps_cagr3") is not None:
                                    mbits.append(f"**Utili 3 anni** {det['eps_cagr3'] * 100:+.0f}%/anno")
                                if mbits:
                                    st.markdown("**Metriche di qualità**  \n" + " · ".join(mbits))
                                if piotroski is not None:
                                    with st.expander(f"📋 Piotroski F-Score {piotroski['score']}/{piotroski['max']} — "
                                                     "i 9 test (dai bilanci SEC)"):
                                        for label, ok in piotroski["details"]:
                                            st.markdown(f"- {'✅' if ok else '❌'} {label}")
                                        st.caption("F-Score validato da Piotroski (2000): ≥7 = bilancio solido · "
                                                   "≤3 = debole. Calcolato dai bilanci ufficiali anno-su-anno.")
                                if not is_fin:
                                    az = fu.altman_z_from_sec(tk)
                                    if az:
                                        st.markdown(f"**Altman Z-Score:** {az['z']} → {az['zone']} ({az['note']}) "
                                                    "  \n_Rischio di dissesto; modello per le industriali, dai bilanci SEC (USA)._")
                                # DCF inversa + rendimento atteso dai fondamentali (no fair value a numero singolo)
                                _fi = {"trailingPE": det.get("pe"), "epsGrowth3Y": det.get("eps_cagr3"),
                                       "revenueGrowth": det.get("rev_cagr3")}
                                rdcf = fu.reverse_dcf_growth(_fi)
                                fdr = fu.fundamental_drift(_fi)
                                fvbits = []
                                if rdcf is not None:
                                    fvbits.append(f"📐 **DCF inversa:** al prezzo attuale il mercato sconta una crescita "
                                                  f"perpetua implicita di **~{rdcf:+.1f}%/anno** (Gordon, r=9%). "
                                                  f"Confrontala con la crescita che ritieni realistica.")
                                if fdr is not None:
                                    fvbits.append(f"🧮 **Rendimento atteso dai fondamentali** (earnings yield + crescita): "
                                                  f"~**{fdr * 100:.0f}%/anno** — un'ancora ragionata, non una previsione.")
                                if fvbits:
                                    st.markdown("  \n".join(fvbits))
                                st.caption("ℹ️ Niente «valore equo» a numero singolo (falsa precisione): qui contano i multipli "
                                           "rispetto a settore e storia, la qualità a pilastri, la copertura del dividendo col "
                                           "flusso di cassa e la **crescita implicita** (DCF inversa).")
                        # --- Segui questa occasione nel tempo ---
                        is_tracked = tk in tracked
                        tlabel = ("✅ Già in monitoraggio — registra lo scatto di oggi"
                                  if is_tracked else "📌 Segui nel tempo")
                        if st.button(tlabel, key=f"track_{kind}_{tk}", use_container_width=True,
                                     help="Salva questa occasione per osservarne l'evoluzione nei prossimi giorni "
                                          "(sezione «Monitoraggio»)."):
                            snap = {
                                "name": row["Nome"], "price": row["Prezzo"], "rsi": row.get("RSI"),
                                "dd_high": row["% dal max"], "occasione": int(row["Occasione"]),
                                "convenienza": int(row["Convenienza"]),
                                "prob_gain": row.get("Prob. salita"), "prob_loss": row.get("Rischio perdita"),
                                "exp_ret": row.get("Guadagno atteso"), "gain": row.get("Guadagno atteso"),
                                "reliab": row.get("Affidabilità"),
                                "target": (det or {}).get("target_price"),
                                "stop": (det or {}).get("stop_price"),
                            }
                            fu.track_opportunity(tk, kind, snapshot=snap)
                            st.success(f"📌 {tk} aggiunto al monitoraggio. Lo trovi nella sezione «Monitoraggio».")
                            st.rerun()
                        news = fu.get_news(tk, 4)
                        if news:
                            # Flag DIFENSIVO (non un bonus): frode/causa/indagine fresca su un
                            # titolo già ipervenduto è un problema reale, non un saldo.
                            flags = fu.news_red_flags(news)
                            if flags:
                                st.error("⚠️ **Allarme difensivo:** nelle notizie compaiono termini di tipo "
                                         f"legale/contabile ({', '.join(flags)}). Su un titolo già ipervenduto questo è "
                                         "spesso il **motivo del calo**, non un'occasione: il prezzo può continuare a "
                                         "scendere. Approfondisci la causa prima di considerarlo.")
                            sent_label, _ = fu.news_sentiment(news)
                            st.markdown(f"**Notizie recenti** · tono indicativo: {sent_label} "
                                        "_(spunto di contesto, non un segnale di acquisto)_")
                            for n in news[:3]:
                                title = fu.translate_text(n["title"]) if translate_news else n["title"]
                                link = f"[{title}]({n['url']})" if n["url"] else title
                                meta = f"  ·  _{n['date']}_" if n["date"] else ""
                                st.markdown(f"- {link}{meta}")
                        else:
                            st.caption("Nessuna notizia recente trovata per questo titolo.")

            if kind == "short":
                soglia = 10
                _block(df[df["Prezzo"] < soglia],
                       f"💰 Titoli economici (sotto i {soglia}$) — più speculativi")
                st.markdown("---")
                _block(df[df["Prezzo"] >= soglia],
                       f"🏢 Titoli a prezzo più alto (da {soglia}$ in su)")
            else:
                _block(df)
            return

        short_cfg = {
            "Nome": st.column_config.TextColumn("Azienda", width="medium"),
            "Convenienza": st.column_config.ProgressColumn("🏅 Convenienza", min_value=0, max_value=100, format="%d",
                help="Punteggio RELATIVO alle occasioni di QUESTO scan (z-score): confronta il titolo con gli altri trovati ORA, non è un voto assoluto. Combina sconto/qualità, rischio, momentum e probabilità. La tabella è ordinata da qui (più alto = più conveniente dei pari)."),
            "Prezzo": st.column_config.NumberColumn("Prezzo", format="%.2f"),
            "RSI": st.column_config.NumberColumn("RSI", format="%.0f",
                help="Sotto 30-35 = ipervenduto (possibile rimbalzo)."),
            "% dal max": st.column_config.NumberColumn("% dal max", format="%.0f%%",
                help="Quanto è sceso dal massimo di 52 settimane."),
            "Perf 1 mese": st.column_config.NumberColumn("1 mese", format="%.0f%%"),
            "Occasione": st.column_config.ProgressColumn("💎 Segnale", min_value=0, max_value=100, format="%.0f",
                help="Forza del setup da rimbalzo: più alto = più ipervenduto, con trend sano, inversione confermata e volume. Ridotto dal regime di volatilità."),
            "Conferma": st.column_config.TextColumn("🔄 Conferma",
                help="Stato dell'inversione: ✅ confermata (giorno verde + RSI in risalita o rientro in Bollinger) · 🟢 1° verde · ⏳ ancora in calo · ⚠️ in caduta verticale. Non si segnala un rimbalzo finché non ha girato."),
            "RVOL": st.column_config.NumberColumn("🔊 RVOL", format="%.1f×",
                help="Volume di oggi rispetto alla media di 20 sedute. Sopra 1,2-1,5× su un giorno verde = capitolazione + ripartenza credibile."),
            "R:R": st.column_config.NumberColumn("⚖️ R:R", format="%.1f",
                help="Rapporto Rischio/Rendimento: (bersaglio − prezzo) / (prezzo − stop ATR). Mostrati solo i setup con R:R ≥ 1,5."),
            "Prob. salita": st.column_config.NumberColumn("📈 Prob. salita", format="%.0f%%",
                help="Stima statistica (dai rendimenti storici, ~1 mese) della probabilità che il prezzo salga. NON è una previsione."),
            "Guadagno atteso": st.column_config.NumberColumn("🎯 Potenziale rimbalzo", format="%+.1f%%",
                help="Quanto salirebbe il titolo se tornasse alla sua media a 50 giorni (bersaglio tipico di un rimbalzo). Indicativo."),
            "Guadagno netto": st.column_config.NumberColumn("💶 Netto", format="%+.1f%%",
                help="Guadagno atteso al NETTO della tassa italiana 26% sulle plusvalenze (le perdite non sono tassate). Le commissioni sono importi fissi e contano nel Portafoglio."),
            "Rischio perdita": st.column_config.NumberColumn("📉 Rischio perdita", format="%.0f%%",
                help="Stima statistica della probabilità di perdere oltre il 15% (~1 mese). NON è una previsione."),
            "Affidabilità": st.column_config.TextColumn("📊 Affidabilità",
                help="Quanto è solida la stima: dipende da volatilità e lunghezza dello storico. 🟢 Alta · 🟡 Media · 🔴 Bassa (molto volatile)."),
            "Perché": st.column_config.TextColumn("Perché", width="large"),
        }
        long_cfg = {
            "Nome": st.column_config.TextColumn("Azienda", width="medium"),
            "Settore": st.column_config.TextColumn("Settore", width="small",
                help="Settore di appartenenza. Le occasioni sono limitate a poche per settore, così la lista non è tutta-banche o tutta-stesso-settore."),
            "Qualità trend": st.column_config.TextColumn("🧭 Qualità (trend)",
                help="Anti-trappola di valore: ✅ conti che tengono (ricavi/utili/margini stabili o in crescita) · ⚠️ trend incerto · 🛑 fondamentali in peggioramento (possibile trappola di valore). È la protezione più importante: uno sconto NON basta."),
            "Convenienza": st.column_config.ProgressColumn("🏅 Convenienza", min_value=0, max_value=100, format="%d",
                help="Punteggio RELATIVO alle occasioni di QUESTO scan (z-score): confronta il titolo con gli altri trovati ORA, non è un voto assoluto. Combina sconto/qualità, rischio, momentum e probabilità. La tabella è ordinata da qui (più alto = più conveniente dei pari)."),
            "Prezzo": st.column_config.NumberColumn("Prezzo", format="%.2f"),
            "% dal max": st.column_config.NumberColumn("% dal max", format="%.0f%%",
                help="Sconto rispetto al massimo di 52 settimane."),
            "Perf 1 anno": st.column_config.NumberColumn("1 anno", format="%.0f%%"),
            "Occasione": st.column_config.ProgressColumn("💎 Valore", min_value=0, max_value=100, format="%.0f",
                help="Qualità del business (pilastri pesati: Qualità 35% / Solidità 25% / Valutazione 25% / Crescita 15%) combinata con lo sconto dai massimi, e declassata se i fondamentali peggiorano."),
            "Prob. salita": st.column_config.NumberColumn("📈 Prob. salita", format="%.0f%%",
                help="Stima statistica (dai rendimenti storici, ~1 anno) della probabilità che il prezzo salga. NON è una previsione."),
            "Guadagno atteso": st.column_config.NumberColumn("🎯 Guadagno atteso", format="%+.1f%%",
                help="Stima del rendimento atteso (mediano) sull'orizzonte ~1 anno. Indicativo, non una previsione."),
            "Guadagno netto": st.column_config.NumberColumn("💶 Netto", format="%+.1f%%",
                help="Guadagno atteso al NETTO della tassa italiana 26% sulle plusvalenze. Indicativo."),
            "Rischio perdita": st.column_config.NumberColumn("📉 Rischio perdita", format="%.0f%%",
                help="Stima statistica della probabilità di perdere oltre il 15% (~1 anno). NON è una previsione."),
            "Affidabilità": st.column_config.TextColumn("📊 Affidabilità",
                help="Quanto è solida la stima: dipende da volatilità e lunghezza dello storico. 🟢 Alta · 🟡 Media · 🔴 Bassa (molto volatile)."),
            "Perché": st.column_config.TextColumn("Perché", width="large"),
        }

        render_opps(full_short, "short", "⚡ Breve periodo — rimbalzo tecnico",
                    "Titoli **ipervenduti** (RSI basso, spesso sotto la banda di Bollinger) ma con trend di fondo "
                    "ancora sano: storicamente più inclini a un rimbalzo. Orizzonte: settimane.", short_cfg)
        st.markdown("---")
        render_opps(full_long, "long", "🏛️ Lungo periodo — qualità in saldo",
                    "Aziende con **buoni fondamentali** (o ETF diversificati) scese parecchio **dai massimi**: "
                    "possibile occasione di valore. Orizzonte: anni.", long_cfg)
        st.caption("👀 **Come leggere:** la barra 🏅 è la convenienza complessiva (la tabella è ordinata da lì). "
                   "Per i dettagli (grafico, livelli, notizie) apri l'approfondimento di un titolo.")
    st.stop()

# ===========================================================================
# SEZIONE: IN OSSERVAZIONE — occasioni che il sistema segue verso la promozione
# ===========================================================================
if section.startswith("In osservazione"):
    page_header("In osservazione",
                "Le occasioni che il sistema sta seguendo verso un'eventuale promozione nel Monitoraggio.")
    st.caption("Qui vedi le occasioni **prima** che entrino nel Monitoraggio: è il posto per coglierle in "
               "anticipo. Tutte quelle trovate in «Occasioni di mercato» vengono osservate per una finestra "
               "(**breve: 3 giorni di Borsa**, **lungo: 7**). Al termine passano nel «Monitoraggio» **solo se "
               "la tesi regge**: prezzo risalito ≥2%, convenienza ancora alta (≥55) e non in calo e — sul lungo "
               "— fondamentali non peggiorati. Guarda **Rendimento** (quanto è già salita), **Tendenza** (se il "
               "segnale si rafforza) e **Mancano** (giorni alla valutazione): se una sta già salendo bene puoi "
               "seguirla a mano dalle «Occasioni» senza aspettare la promozione. Ordinate per giorni mancanti.")
    if fu.cloud_mode():
        st.caption("🤖 Aggiornate dal sistema autonomo sul server (~ogni 15 min, anche a PC spento).")

    _status = fu.observation_status()
    _tracked_now = fu.load_tracking()
    obs_all = [s for s in _status if s.get("ticker") not in _tracked_now]
    _obs_key = lambda s: (s.get("remaining", 0), -(s.get("ret") or 0.0))
    obs_short = sorted([s for s in obs_all if s.get("kind") == "short"], key=_obs_key)
    obs_long = sorted([s for s in obs_all if s.get("kind") != "short"], key=_obs_key)
    _obs_cols = {
        "Azienda": st.column_config.TextColumn("Azienda", width="medium"),
        "Giorni osservata": st.column_config.NumberColumn("📅 Giorni", format="%d",
            help="Giorni da cui il sistema osserva questa occasione."),
        "Rendimento": st.column_config.NumberColumn("📈 Rendimento", format="%+.1f%%",
            help="Variazione del PREZZO dal primo giorno di osservazione. Negativo = sta ancora scendendo "
                 "(non verrà promossa finché non torna positivo)."),
        "Convenienza": st.column_config.ProgressColumn("🏅 Convenienza (saldo)", min_value=0, max_value=100, format="%d",
            help="Convenienza relativa alle occasioni dello scan (più alta = più a sconto/interessante dei pari). Ultima nota durante l'osservazione."),
        "Tendenza": st.column_config.TextColumn("🧭 Tendenza",
            help="Andamento della convenienza sui giorni osservati (mediana giornaliera, così un calo di mezza "
                 "giornata non conta): Δ punti dal 1° giorno e giorni consecutivi di salita tollerante."),
        "Mancano": st.column_config.NumberColumn("⏳ Mancano (gg)", format="%d",
            help="Giorni al termine della finestra (breve 3 / lungo 7); a 0 viene valutata per la promozione."),
    }

    def _trend_label(s):
        d = s.get("dconv", 0) or 0
        run = s.get("run", 0) or 0
        icon = "📈" if d >= 6 else "📉" if d <= -6 else "➡️"
        return f"{icon} {d:+.0f} ({run}g)"

    def _obs_table(items):
        if not items:
            st.caption("Nessuna occasione in osservazione in questa categoria.")
            return
        df_obs = pd.DataFrame([{
            "Ticker": s.get("ticker"), "Azienda": s.get("name", ""),
            "Giorni osservata": s.get("days", 0), "Rendimento": s.get("ret", 0.0),
            "Convenienza": s.get("last_conv"), "Tendenza": _trend_label(s),
            "Mancano": s.get("remaining", 0),
        } for s in items]).set_index("Ticker")
        st.dataframe(df_obs, use_container_width=True,
                     height=min(60 + 36 * len(items), 600), column_config=_obs_cols)

    if not obs_all:
        st.info("Nessuna occasione in osservazione al momento. Apri «Occasioni di mercato» per popolarla, "
                "oppure attendi il prossimo aggiornamento del sistema autonomo.")
    else:
        st.markdown(f"### ⚡ Breve termine — {len(obs_short)} in osservazione")
        _obs_table(obs_short)
        st.markdown(f"### 🏛️ Lungo termine — {len(obs_long)} in osservazione")
        _obs_table(obs_long)
    st.stop()

# ===========================================================================
# SEZIONE: MONITORAGGIO — segui le occasioni nel tempo
# ===========================================================================
if section.startswith("Monitoraggio"):
    page_header("Monitoraggio delle occasioni",
                "Segui nel tempo le occasioni scelte e decidi con calma quando comprare.")
    st.caption("Qui osservi nel tempo le occasioni che hai scelto di seguire (dalla sezione «Occasioni di mercato»). "
               "Ogni giorno che apri l'app viene registrato uno «scatto» dei valori: così vedi se il segnale si "
               "rafforza o si indebolisce **prima** di decidere se comprare.")
    st.caption("Strumento per seguire un'idea per più giorni con calma; non è un consiglio di acquisto. "
               "La storia si costruisce in avanti: un punto per ogni giorno in cui apri l'app.")

    # --- 📊 Scheda voti del sistema (track record delle promozioni automatiche) ---
    if not fu.cloud_mode():
        fu.update_track_record()        # in locale aggiorna i rendimenti reali (sul cloud lo fa il job)
    rstats = fu.track_record_stats()
    if rstats["total"]:
        with st.expander(f"📊 Scheda voti del sistema — {rstats['total']} promozioni automatiche finora",
                         expanded=False):
            st.caption("Quanto hanno **reso davvero** le occasioni promosse dal sistema: una misura onesta dell'efficacia. "
                       "Non è una garanzia sul futuro, ma ti dice quanto fidarti dei segnali.")
            rc1, rc2, rc3 = st.columns(3)
            for col, key, label in [(rc1, "now", "Ad oggi"), (rc2, "d7", "Dopo 7 giorni"),
                                    (rc3, "d30", "Dopo 30 giorni")]:
                s = rstats[key]
                with col:
                    if s:
                        st.metric(f"{label} — rendimento medio", f"{s['avg']:+.1f}%")
                        st.caption(f"🎯 In positivo **{s['hit']}%** ({s['n']} casi) · "
                                   f"migliore {s['best']:+.1f}% · peggiore {s['worst']:+.1f}%")
                    else:
                        st.metric(f"{label} — rendimento medio", "—")
                        st.caption("Servono più giorni di dati.")

            # --- Calibrazione: la convenienza alta rende più della bassa? ---
            cal = fu.track_record_calibration()
            st.markdown("###### La convenienza funziona? Resa reale per fascia")
            band_rows = [{
                "Fascia": fa["banda"], "Promozioni": fa["count"],
                "Resa 7g": (fa["d7"]["avg"] if fa["d7"] else None),
                "Resa 30g": (fa["d30"]["avg"] if fa["d30"] else None),
                "In positivo 30g": (fa["d30"]["hit"] if fa["d30"] else None),
            } for fa in cal["fasce"]]
            st.dataframe(pd.DataFrame(band_rows).set_index("Fascia"), use_container_width=True, column_config={
                "Promozioni": st.column_config.NumberColumn("Promozioni", format="%d"),
                "Resa 7g": st.column_config.NumberColumn("Resa media 7g", format="%+.1f%%"),
                "Resa 30g": st.column_config.NumberColumn("Resa media 30g", format="%+.1f%%"),
                "In positivo 30g": st.column_config.NumberColumn("In positivo 30g", format="%d%%"),
            })
            if cal["ok"] is True:
                st.success(cal["verdetto"])
            elif cal["ok"] is False:
                st.info(cal["verdetto"])
            else:
                st.caption("ℹ️ " + cal["verdetto"])

            recs = fu.load_track_record()
            if recs:
                dfr = pd.DataFrame([{
                    "Ticker": r.get("ticker"), "Tipo": "⚡ Breve" if r.get("kind") == "short" else "🏛️ Lungo",
                    "Promossa il": r.get("date"), "Conv. iniziale": r.get("conv"),
                    "Oggi": r.get("ret_now"), "Dopo 7g": r.get("ret_7d"), "Dopo 30g": r.get("ret_30d"),
                } for r in reversed(recs)]).set_index("Ticker")
                st.dataframe(dfr, use_container_width=True, column_config={
                    "Conv. iniziale": st.column_config.NumberColumn("Conv. iniziale", format="%d"),
                    "Oggi": st.column_config.NumberColumn("Oggi", format="%+.1f%%",
                        help="Rendimento dal prezzo di promozione a oggi."),
                    "Dopo 7g": st.column_config.NumberColumn("Dopo 7g", format="%+.1f%%"),
                    "Dopo 30g": st.column_config.NumberColumn("Dopo 30g", format="%+.1f%%"),
                })
            st.caption("Le occasioni promosse vengono registrate col prezzo di partenza; il rendimento a 7 e 30 giorni "
                       "si fissa al raggiungimento di quei traguardi. Stima sui dati reali, non una promessa.")
        st.markdown("---")

    # --- 🎯 Calibrazione delle probabilità (Brier score) ---
    if not fu.cloud_mode():
        fu.resolve_forecasts()          # in locale risolve le previsioni mature (sul cloud lo fa il job)
    crep = fu.calibration_report()
    if crep is not None:
        with st.expander(f"🎯 Quanto sono oneste le probabilità (calibrazione) — "
                         f"{crep['n_resolved']} previsioni verificate", expanded=False):
            st.caption("Degli eventi a cui diamo **~70%**, quanti si avverano davvero? Questa scheda confronta la "
                       "**probabilità di salita predetta** con quella **realizzata**. Non serve a indovinare il prezzo, "
                       "ma a misurare se le nostre percentuali sono affidabili. Si popola nel tempo.")
            if crep["n_resolved"] == 0:
                st.info(f"Nessuna previsione ancora verificata (servono ~1 mese per il breve, ~1 anno per il lungo). "
                        f"Registrate finora: {crep['n_total']}. Torna più avanti.")
            else:
                if crep["brier"] is not None:
                    bs = crep["brier"]
                    tone = st.success if bs <= 0.20 else st.warning if bs <= 0.25 else st.error
                    tone(f"**Brier score: {bs:.3f}** (più basso = meglio; 0,25 = come tirare a caso, "
                         "<0,20 = previsioni utili).")
                if crep["buckets"]:
                    st.dataframe(pd.DataFrame(crep["buckets"]).set_index("range"),
                                 use_container_width=True, column_config={
                        "n": st.column_config.NumberColumn("Casi", format="%d"),
                        "predetto": st.column_config.NumberColumn("Prob. predetta", format="%d%%"),
                        "realizzato": st.column_config.NumberColumn("Salite reali", format="%d%%",
                            help="Se 'predetta' e 'realizzato' sono vicine, le probabilità sono ben calibrate."),
                    })
        st.markdown("---")

    # --- 🧪 Validazione del sistema (backtest tecnico + verifica ML) — su richiesta, pesanti ---
    with st.expander("🧪 Validazione del sistema (backtest + verifica ML)", expanded=False):
        st.caption("Mette alla prova il sistema sui DATI STORICI (non sui soldi veri). Il **backtest** "
                   "ricostruisce le regole delle occasioni giorno per giorno usando solo i dati "
                   "disponibili fino a quel momento (walk-forward, niente 'senno di poi') e simula gli "
                   "acquisti, mostrando: quanti finiscono in positivo (**hit-rate**), il **guadagno medio "
                   "NETTO** (tassa 26%), il confronto col semplice **compra-e-tieni l'indice**, e la resa "
                   "per **fascia di convenienza** (verifica se la convenienza alta rende davvero di più). "
                   "La **verifica ML** controlla se un modello di machine learning batte i metodi semplici "
                   "(di norma no: i mercati sono ~imprevedibili). Sono pesanti → si avviano col pulsante. "
                   "Limite onesto: valida solo il ramo TECNICO/prezzo del breve (i fondamentali storici "
                   "non sono ricostruibili da fonti gratuite).")
        bcol1, bcol2 = st.columns(2)
        if bcol1.button("▶️ Backtest occasioni (breve)", key="run_backtest", use_container_width=True):
            with st.spinner("Backtest walk-forward in corso… (~1-2 min)"):
                try:
                    import backtest as _bt
                    st.session_state["_bt_res"] = _bt.run_backtest(horizon=21, max_tickers=25)
                except Exception as e:
                    st.session_state["_bt_res"] = {"errore": str(e)}
        if bcol2.button("▶️ Verifica ML vs metodi semplici", key="run_mlverify", use_container_width=True):
            with st.spinner("Verifica ML in corso… (~1-2 min, richiede scikit-learn)"):
                try:
                    import ml_verify as _mlv
                    st.session_state["_ml_res"] = _mlv.run_ml_verify()
                except Exception as e:
                    st.session_state["_ml_res"] = {"errore": str(e)}
        _btr = st.session_state.get("_bt_res")
        if _btr:
            if _btr.get("errore"):
                st.error("Backtest non riuscito: " + _btr["errore"])
            elif not _btr.get("n_trades"):
                st.info("Nessun trade simulato (dati insufficienti).")
            else:
                vb1, vb2, vb3 = st.columns(3)
                vb1.metric("Trade simulati", _btr["n_trades"])
                vb2.metric("In positivo", f"{_btr['hit_rate']}%")
                vb3.metric("Resa netta media", f"{_btr['avg_net']:+.2f}%")
                _bench = _btr.get("bench_avg")
                st.caption(f"Orizzonte {_btr['horizon']} gg di Borsa · mediana netta {_btr['median_net']:+.2f}%"
                           + (f" · compra-e-tieni indice {_bench:+.2f}%" if _bench is not None else ""))
                if _btr.get("by_band"):
                    st.dataframe(pd.DataFrame(_btr["by_band"]).set_index("banda"), use_container_width=True,
                                 column_config={
                                     "n": st.column_config.NumberColumn("Trade", format="%d"),
                                     "avg_net": st.column_config.NumberColumn("Resa netta media", format="%+.2f%%"),
                                     "hit": st.column_config.NumberColumn("In positivo", format="%d%%")})
                st.caption("Walk-forward: ogni ingresso usa solo i dati fino a quel giorno. Stima storica, non una promessa.")
        _mlr = st.session_state.get("_ml_res")
        if _mlr:
            if _mlr.get("errore"):
                st.error("Verifica ML non riuscita (scikit-learn installato?): " + _mlr["errore"])
            elif not _mlr.get("count"):
                st.info("Dati insufficienti per la verifica ML.")
            else:
                st.caption(f"Errore medio (MAE, più basso = meglio): ML {_mlr['ml_mae']}% · drift {_mlr['drift_mae']}% · "
                           f"naive {_mlr['naive_mae']}% — ML batte il naive in {_mlr['ml_beats_naive']}/{_mlr['count']} titoli.")
                (st.success if _mlr["verdict"].startswith("✅") else st.info)(_mlr["verdict"])
    st.markdown("---")

    tracked = fu.load_tracking()
    if not tracked:
        st.info("Non stai ancora monitorando nessuna occasione.\n\n"
                "Vai su **💎 Occasioni di mercato**, apri l'approfondimento di un titolo interessante e premi "
                "**📌 Segui nel tempo**. Tornerà qui, e da domani vedrai come si evolve.")
        st.stop()

    with st.spinner("Aggiorno gli scatti di oggi…"):
        tracked = fu.auto_snapshot_tracked()

    cc1, cc2 = st.columns([1, 3])
    if cc1.button("🔄 Aggiorna ora", use_container_width=True,
                  help="Forza un nuovo scatto dei valori di oggi per tutti i titoli seguiti."):
        fu.get_history.clear()          # dati freschi
        fu.opportunity_row.clear()
        for tk in list(tracked):
            snap = fu.opportunity_snapshot(tk, tracked[tk].get("kind", "short"))
            if snap:
                fu.track_opportunity(tk, tracked[tk].get("kind", "short"), snapshot=snap)
        st.rerun()
    cc2.caption(f"Ultimo accesso: **{_now_rome().strftime('%d/%m %H:%M')}** · "
                f"i dati gratuiti si rinnovano ~ogni 15 minuti.")

    def render_tracked(tk, entry):
        snaps = entry.get("snapshots", [])
        last = snaps[-1] if snaps else {}
        first = snaps[0] if snaps else {}
        nm = entry.get("name") or last.get("name") or tk
        kind = entry.get("kind", "short")
        kind_badge = "⚡ Breve" if kind == "short" else "🏛️ Lungo"
        try:
            d0 = datetime.date.fromisoformat(entry.get("added", ""))
            giorni = fu._trading_days_between(entry.get("added", ""), fu._today_iso(), tk)
        except Exception:
            giorni = len(snaps) - 1
        trend = fu.tracking_trend(snaps)

        with st.container(border=True):
            tc1, tc2 = st.columns([4, 1])
            auto_tag = " 🤖" if entry.get("auto") else ""
            tc1.markdown(f"### {nm}  ·  `{tk}`{auto_tag}")
            origine = "aggiunta automatica" if entry.get("auto") else "aggiunta manuale"
            tc1.caption(f"{kind_badge} · {origine} · seguito da **{max(giorni,0)}** giorn{'o' if giorni==1 else 'i'} di Borsa "
                        f"(dal {entry.get('added','?')}) · {len(snaps)} scatt{'o' if len(snaps)==1 else 'i'}")
            if tc2.button("🗑️ Smetti", key=f"untrack_{tk}", use_container_width=True):
                fu.untrack_opportunity(tk)
                st.rerun()

            # Verdetto di tendenza
            if trend:
                arrow_p = (f" · prezzo {trend['dprice']:+.1f}%" if trend["dprice"] is not None else "")
                st.markdown(
                    f"<div style='padding:8px 12px;border-radius:8px;background:{trend['color']}14;"
                    f"border-left:5px solid {trend['color']};margin-bottom:8px'>"
                    f"<b style='color:{trend['color']}'>{trend['emoji']} {trend['label']}</b> — "
                    f"convenienza {trend['dconv']:+.0f} punti{arrow_p} da quando lo segui.</div>",
                    unsafe_allow_html=True)
            else:
                st.caption("📅 Servono almeno **2 giorni** di scatti per valutare la tendenza. Riapri l'app domani.")

            # Avviso (il sistema NON rimuove più da solo, tranne i crolli >90%: qui segnala e basta)
            if entry.get("warn"):
                st.markdown(
                    f"<div style='padding:6px 10px;border-radius:8px;background:#cf222e14;"
                    f"border-left:5px solid #cf222e;margin-bottom:8px'>⚠️ <b>Attenzione:</b> "
                    f"{entry['warn']}.</div>", unsafe_allow_html=True)

            # Metriche attuali con variazione dal primo scatto
            def _delta(curr, prev):
                if curr is None or prev is None:
                    return None
                return curr - prev
            m1, m2, m3, m4 = st.columns(4)
            price = last.get("price")
            dprice = None
            if price and first.get("price"):
                dprice = (price / first["price"] - 1) * 100
            m1.metric("Prezzo", f"{price:,.2f}" if price else "n/d",
                      f"{dprice:+.1f}%" if dprice is not None else None)
            conv = last.get("convenienza")
            dc = _delta(conv, first.get("convenienza"))
            m2.metric("🏅 Convenienza", f"{conv:.0f}/100" if conv is not None else "n/d",
                      f"{dc:+.0f}" if dc is not None else None)
            pg = last.get("prob_gain")
            m3.metric("📈 Prob. salita", f"{pg:.0f}%" if pg is not None else "n/d")
            pl = last.get("prob_loss")
            m4.metric("📉 Rischio perdita", f"{pl:.0f}%" if pl is not None else "n/d")

            rsi = last.get("rsi")
            dd = last.get("dd_high")
            rel = last.get("reliab")
            extra = []
            if rsi is not None:
                extra.append(f"RSI **{rsi:.0f}**")
            if dd is not None:
                extra.append(f"**{dd:.0f}%** dal massimo")
            if rel:
                extra.append(f"affidabilità {rel}")
            if extra:
                st.caption(" · ".join(extra))

            # Guadagno atteso comprando ORA e arrivando al bersaglio (INFO sul potenziale, non un'uscita).
            # L'importo è inseribile: il guadagno in € si ricalcola sull'importo scelto.
            tgt_now = last.get("target")
            if tgt_now and price and tgt_now > price:
                pot = (tgt_now / price - 1) * 100
                pot_net = fu.net_return_pct(pot) or 0.0
                cimp, _sp = st.columns([1, 2])
                amt = cimp.number_input("💶 Importo da investire (€)", min_value=0, value=1000, step=100,
                                        key=f"amt_{tk}",
                                        help="Quanto investiresti ORA su questo titolo: il guadagno atteso qui sotto si aggiorna.")
                eur_net = round(amt * pot_net / 100)
                st.markdown(f"🎯 Al bersaglio (**{tgt_now:,.2f}**): **+{pot:.1f}%** → guadagno atteso "
                            f"≈ **€{eur_net:,}** netti (tassa 26%) su €{amt:,.0f} investiti. *Indicativo, non una previsione.*")
            elif tgt_now and price and tgt_now <= price:
                st.caption(f"🎯 Bersaglio del rimbalzo (media 50gg ≈ {tgt_now:,.2f}) **già raggiunto/superato**: "
                           f"il prezzo ({price:,.2f}) è salito oltre l'obiettivo, quindi non c'è un guadagno atteso "
                           f"«fino al bersaglio» da mostrare (occasione promossa dopo un forte rialzo).")

            # Grafico: prezzo reale + convenienza accumulata (asse destro) + livelli.
            # Periodo selezionabile: dai giorni di monitoraggio fino al massimo storico.
            TPER = {"Giorni": "track", "1 settimana": "5d", "1 mese": "1mo",
                    "6 mesi": "6mo", "1 anno": "1y", "Max": "max"}
            tsel = st.radio("Periodo del grafico", list(TPER.keys()), index=0,
                            horizontal=True, key=f"trackper_{tk}",
                            help="«Giorni» mostra solo da quando hai iniziato a seguire il titolo; gli altri allargano lo storico del prezzo.")
            sel = TPER[tsel]
            fig = go.Figure()
            x_min = None
            last_dt = None
            price_note = ""
            if sel == "track":
                # «Giorni» = da quando segui il titolo: prezzo E convenienza dai NOSTRI snapshot
                # (registrati ~ogni ora con il prezzo live), così condividono la stessa griglia
                # temporale e la linea del prezzo non è un punto isolato del daily.
                try:
                    start = pd.to_datetime(entry.get("added")) if entry.get("added") else None
                except Exception:
                    start = None
                pp = [(pd.to_datetime(s["date"]), s["price"]) for s in snaps
                      if s.get("price") is not None
                      and (start is None or pd.to_datetime(s["date"]) >= start)]
                if pp:
                    fig.add_trace(go.Scatter(x=[d for d, _ in pp], y=[v for _, v in pp], name="Prezzo",
                                             mode="lines+markers", line=dict(color="#0969da", width=2)))
                    x_min, last_dt = pp[0][0], pp[-1][0]
                    price_note = " (snapshot del monitoraggio, ~1/ora)"
                has_price = bool(pp)
            else:
                # periodi più ampi: storico di mercato (settimana → intraday ~1 ora; altri → daily)
                hc = chart_history(tk, sel)
                if not hc.empty and getattr(hc.index, "tz", None) is not None:
                    hc = hc.copy()
                    hc.index = hc.index.tz_localize(None)
                if not hc.empty:
                    fig.add_trace(go.Scatter(x=hc.index, y=hc["Close"], name="Prezzo",
                                             line=dict(color="#0969da", width=2)))
                    x_min, last_dt = hc.index.min(), hc.index[-1]
                    price_note = " (intraday ~1 ora)" if hc.attrs.get("intraday") else " (chiusura giornaliera)"
                has_price = not hc.empty
            # punti di convenienza: solo quelli dentro la finestra mostrata
            cs = [(pd.to_datetime(s["date"]), s["convenienza"]) for s in snaps
                  if s.get("convenienza") is not None
                  and (x_min is None or pd.to_datetime(s["date"]) >= x_min)]
            if cs:
                fig.add_trace(go.Scatter(
                    x=[d for d, _ in cs], y=[v for _, v in cs],
                    name="Convenienza", yaxis="y2", mode="lines+markers",
                    line=dict(color="#8250df", width=2), marker=dict(size=8)))
            tgt, stp = last.get("target"), last.get("stop")
            if tgt:
                fig.add_hline(y=tgt, line=dict(color="#1a7f37", dash="dash", width=1),
                              annotation_text="🎯 bersaglio", annotation_position="top left")
            if stp:
                fig.add_hline(y=stp, line=dict(color="#cf222e", dash="dash", width=1),
                              annotation_text="🛑 stop", annotation_position="bottom left")
            fig.update_layout(
                height=300, margin=dict(t=10, b=10, l=10, r=10),
                legend=dict(orientation="h"), hovermode="x unified",
                yaxis=dict(title="Prezzo"),
                yaxis2=dict(title="Convenienza", overlaying="y", side="right",
                            range=[0, 100], showgrid=False))
            if not has_price and not cs:
                st.caption("Ancora nessun dato per il periodo scelto: la storia si costruisce man mano "
                           "(un punto circa ogni ora mentre la borsa è aperta).")
            else:
                show_chart(fig, use_container_width=True)
                if last_dt is not None:
                    st.caption(f"📅 Ultimo prezzo: {last_dt.strftime('%d/%m/%Y %H:%M')}{price_note}")
            st.caption("👀 **Linea blu** = prezzo del titolo nel periodo scelto qui sopra. **Linea viola** = la convenienza "
                       "registrata mentre il sistema osserva il titolo (sale = il segnale migliora). "
                       "Verde = bersaglio, rossa = stop.")

            # Nota personale + scorciatoia all'analisi
            nc1, nc2 = st.columns([4, 1])
            note = nc1.text_input("📝 Nota personale", value=entry.get("note", ""),
                                  key=f"note_{tk}", placeholder="es. aspetto RSI sotto 30 / attendo trimestrale")
            if note != entry.get("note", ""):
                fu.set_tracking_note(tk, note)
            if nc2.button("📊 Analizza", key=f"goto_{tk}", use_container_width=True):
                st.session_state["ticker"] = tk
                st.session_state["_goto_section"] = "Analisi di un titolo"
                st.rerun()

    # Ordine: prima le occasioni presenti da PIÙ TEMPO (added crescente → si segue l'evoluzione),
    # poi per AFFIDABILITÀ (🟢 Alta prima di 🟡 Media prima di 🔴 Bassa).
    def _mon_sort_key(item):
        tk, e = item
        snaps = e.get("snapshots") or []
        rel = (snaps[-1].get("reliab") if snaps else "") or ""
        rel_rank = 0 if "Alta" in rel else (1 if "Media" in rel else 2)
        return (str(e.get("added") or "9999-99-99"), rel_rank, tk)

    # Il sistema NON rimuove più da solo: calcola dal vivo (senza chiamate di rete) quali AVREBBE
    # tolto e le raccoglie in "Candidate all'uscita"; le altre restano nelle liste normali.
    for _tk, _e in tracked.items():
        _w = fu.monitoring_warn(_e)
        if _w:
            _e["warn"] = _w
        else:
            _e.pop("warn", None)
    exit_items = sorted([(tk, e) for tk, e in tracked.items() if e.get("warn")], key=_mon_sort_key)
    healthy = [(tk, e) for tk, e in tracked.items() if not e.get("warn")]
    short_items = sorted([(tk, e) for tk, e in healthy if e.get("kind") == "short"], key=_mon_sort_key)
    long_items = sorted([(tk, e) for tk, e in healthy if e.get("kind") != "short"], key=_mon_sort_key)

    # --- 🚪 Candidate all'uscita: SEMPRE visibile (con stato "nessuna" quando è tutto in salute) ---
    st.markdown(f"## 🚪 Candidate all'uscita — {len(exit_items)}")
    if exit_items:
        st.caption("Occasioni che stanno **smettendo di esserlo** (sotto lo stop, in perdita da troppo, "
                   "o dati fermi/possibile delisting). Il sistema le rimuove **da solo SOLO se restano "
                   "così per alcuni giorni** (conferma, non al primo calo: ~4 breve / ~10 lungo giorni di "
                   "Borsa); se recuperano, restano. Qui le vedi in anticipo → 🗑️ puoi toglierle subito. "
                   "(I crolli oltre il 90% vengono rimossi subito.)")
        for tk, e in exit_items:
            snaps = e.get("snapshots", [])
            last = snaps[-1] if snaps else {}
            first = snaps[0] if snaps else {}
            nm = e.get("name") or last.get("name") or tk
            kb = "⚡ Breve" if e.get("kind") == "short" else "🏛️ Lungo"
            pr, ba = last.get("price"), first.get("price")
            ret = (pr / ba - 1) * 100 if (pr and ba) else None
            try:
                gg = fu._trading_days_between(e.get("added", ""), fu._today_iso(), tk)
            except Exception:
                gg = len(snaps) - 1
            with st.container(border=True):
                xa, xb = st.columns([4, 1])
                xa.markdown(f"**{nm}**  ·  `{tk}`  ·  {kb}  ·  seguito da {max(gg, 0)} giorni di Borsa")
                xa.markdown(
                    f"<div style='padding:6px 10px;border-radius:8px;background:#cf222e14;"
                    f"border-left:5px solid #cf222e'>⚠️ <b>{e.get('warn')}</b>"
                    + (f" · rendimento <b>{ret:+.1f}%</b> da quando lo segui" if ret is not None else "")
                    + "</div>", unsafe_allow_html=True)
                if xb.button("🗑️ Smetti", key=f"exit_untrack_{tk}", use_container_width=True):
                    fu.untrack_opportunity(tk)
                    st.rerun()
                if xb.button("📊 Analizza", key=f"exit_goto_{tk}", use_container_width=True):
                    st.session_state["ticker"] = tk
                    st.session_state["_goto_section"] = "Analisi di un titolo"
                    st.rerun()
    else:
        st.caption("✅ Nessuna al momento: tutte le occasioni monitorate sono in salute. Una comparirà "
                   "qui appena inizia a indebolirsi (sotto lo stop, in perdita da troppo o con dati fermi).")
    st.markdown("---")

    if short_items:
        st.markdown("## Breve periodo (rimbalzo)")
        for tk, e in short_items:
            render_tracked(tk, e)
    if long_items:
        st.markdown("## Lungo periodo (qualità in saldo)")
        for tk, e in long_items:
            render_tracked(tk, e)
    st.stop()

# ===========================================================================
# SEZIONE: PORTAFOGLIO — acquisti reali con guadagno/perdita
# ===========================================================================
if section.startswith("Portafoglio"):
    page_header("Il mio portafoglio",
                "I tuoi acquisti reali: guadagno/perdita in tempo reale e consigli su quando vendere.")
    st.caption("Registra gli acquisti che hai fatto davvero (titolo, quantità, prezzo) e vedi in tempo reale "
               "il guadagno/perdita. Puoi impostare un **bersaglio** e uno **stop**: l'app ti avvisa quando vengono toccati.")
    st.caption("Strumento di monitoraggio personale, non collegato a nessun conto o broker: "
               "i dati li inserisci tu a mano.")

    with st.expander("➕ Aggiungi un acquisto", expanded=not fu.load_portfolio()):
        st.caption("Inserisci **quanti soldi** hai investito: il sistema ricava da solo prezzo attuale e quantità, "
                   "e registra **data e ora**. 👉 Inseriscilo **subito dopo l'acquisto**, così il prezzo coincide col tuo.")
        with st.form("add_pos", clear_on_submit=True):
            pf1, pf2, pf3 = st.columns([2, 2, 2])
            p_tk = pf1.text_input("Titolo / marchio (ticker)", placeholder="es. AAPL, ENI.MI").strip().upper()
            p_amt = pf2.number_input("Soldi investiti (€)", min_value=0.0, step=50.0, value=0.0, format="%.2f",
                                     help="Quanti EURO hai messo su questo titolo. Per i titoli in dollari/altra "
                                          "valuta la quantità di azioni viene calcolata convertendo l'importo al cambio.")
            p_hor = pf3.radio("Orizzonte", ["⚡ Breve termine", "🏛️ Lungo termine"], index=1,
                              help="«Breve» = scommessa di rimbalzo (incassare presto). «Lungo» = investimento da tenere; "
                                   "il consulente di vendita è più paziente.")
            pf4, pf5, pf6 = st.columns(3)
            p_tgt = pf4.number_input("Vendi a +% (opzionale)", min_value=0.0, step=1.0, value=0.0, format="%.0f",
                                     help="Bersaglio di guadagno: es. 20 = avvisami a +20%.")
            p_stp = pf5.number_input("Stop a −% (opzionale)", min_value=0.0, step=1.0, value=0.0, format="%.0f",
                                     help="Limite di perdita: es. 10 = avvisami a −10%.")
            p_note = pf6.text_input("Nota (opzionale)", placeholder="es. rimbalzo, dividendo")
            submitted = st.form_submit_button("➕ Aggiungi al portafoglio", use_container_width=True)
            if submitted:
                if p_tk and p_amt > 0:
                    pos = fu.add_position_by_amount(
                        p_tk, p_amt, target_pct=(p_tgt or None), stop_pct=(p_stp or None),
                        note=p_note, horizon=("breve" if p_hor.endswith("Breve termine") else "lungo"))
                    if pos:
                        st.success(f"Aggiunto: **{p_amt:,.2f}** di **{p_tk}** a {pos['buy_price']:.2f} "
                                   f"(≈ {pos['qty']:.4f} quote) il {pos['datetime']}.")
                        st.rerun()
                    else:
                        st.error(f"Non riesco a recuperare il prezzo attuale di **{p_tk}**. "
                                 "Controlla il ticker (Milano: aggiungi `.MI`) e riprova tra poco.")
                else:
                    st.error("Inserisci almeno **titolo** e **soldi investiti** (maggiore di zero).")

    pf_fee = st.number_input("Commissioni per operazione (€)", min_value=0.0, value=1.0, step=0.5, key="pf_fee",
                             help="Costo di compravendita sottratto dal guadagno netto, oltre alla tassa del 26% "
                                  "sulla plusvalenza. Imposta quello del tuo broker.")
    with st.spinner("Calcolo il valore attuale…"):
        rows, totals = fu.portfolio_view(fee=pf_fee)

    if not rows:
        st.info("Portafoglio vuoto. Aggiungi il tuo primo acquisto qui sopra.")
        st.stop()

    # --- Totali (convertiti in EUR, valuta base) — lordo e NETTO (tassa 26% + commissioni) ---
    mt1, mt2, mt3, mt4 = st.columns(4)
    mt1.metric("Investito (€)", f"{totals['cost']:,.2f}")
    mt2.metric("Valore attuale (€)", f"{totals['value']:,.2f}")
    d_gross = f"{totals['pnl_pct']:+.1f}%" if totals.get("pnl_pct") is not None else None
    mt3.metric("G/P lordo (€)", f"{totals['pnl']:+,.2f}", d_gross)
    d_net = f"{totals['net_pnl_pct']:+.1f}%" if totals.get("net_pnl_pct") is not None else None
    mt4.metric("G/P netto (€)", f"{totals['net_pnl']:+,.2f}", d_net,
               help="Quanto ti resterebbe vendendo ora: dopo la tassa del 26% sulla plusvalenza e le commissioni.")
    st.caption(f"💰 **Netto** = lordo − **€ {totals['tax']:,.2f}** di tassa (26% sulla plusvalenza, solo se in utile) "
               f"− **€ {totals['fee_total']:,.2f}** di commissioni → vendendo ora incasseresti **€ {totals['net_value']:,.2f}**. "
               "Stima: la tassa è calcolata per singola posizione (non compensa le minusvalenze).")
    ccys = totals.get("currencies", [])
    if len(ccys) > 1:
        st.caption("💱 Totali convertiti in **EUR** (valuta base) — posizioni in: "
                   + ", ".join(ccys) + ". Cambi aggiornati ~1 volta l'ora. "
                   "I valori per riga restano nella valuta del titolo (vedi colonna «Valuta»).")
    else:
        st.caption(f"Totali in **EUR**. Tutte le posizioni sono in {ccys[0] if ccys else 'EUR'}.")
    if not totals.get("complete", True):
        st.caption("ℹ️ Alcune posizioni sono escluse dal totale: manca il prezzo aggiornato o il "
                   "tasso di cambio (per Londra `.L` i prezzi sono spesso in pence — verifica a mano).")

    # --- Avvisi target/stop ---
    alerts = [r for r in rows if r["status"]]
    for r in alerts:
        if "target" in r["status"]:
            st.success(f"🎯 **{r['ticker']}** ha raggiunto il bersaglio ({r['target']:.2f}) — prezzo {r['price']:.2f}. Valuta se vendere.")
        else:
            st.error(f"🛑 **{r['ticker']}** ha toccato lo stop ({r['stop']:.2f}) — prezzo {r['price']:.2f}. Valuta se uscire.")

    # --- Tabella posizioni ---
    dfp = pd.DataFrame([{
        "Ticker": r["ticker"], "Orizz.": "⚡" if r["horizon"] == "breve" else "🏛️",
        "Valuta": r.get("ccy", ""),
        "Investito": r["amount"], "Quando": r["datetime"], "Prezzo acq.": r["buy_price"],
        "Q.tà": r["qty"], "Prezzo ora": r["price"], "Valore": r["value"],
        "G/P": r["pnl"], "G/P %": r["pnl_pct"],
        "Tassa 26%": r.get("tax_eur"), "G/P netto": r.get("net_eur"), "Netto %": r.get("net_pct"),
        "Stato": r["status"] or "—",
    } for r in rows]).set_index("Ticker")
    st.dataframe(dfp, use_container_width=True, column_config={
        "Orizz.": st.column_config.TextColumn("Orizz.", help="⚡ breve termine · 🏛️ lungo termine"),
        "Valuta": st.column_config.TextColumn("Valuta", help="Valuta di quotazione del titolo. Tassa e netto sono in EUR."),
        "Investito": st.column_config.NumberColumn("Investito (nativo)", format="%.2f"),
        "Quando": st.column_config.TextColumn("Acquisto (data e ora)"),
        "Prezzo acq.": st.column_config.NumberColumn("Prezzo acq.", format="%.2f"),
        "Q.tà": st.column_config.NumberColumn("Q.tà", format="%.4f"),
        "Prezzo ora": st.column_config.NumberColumn("Prezzo ora", format="%.2f"),
        "Valore": st.column_config.NumberColumn("Valore", format="%.2f"),
        "G/P": st.column_config.NumberColumn("G/P lordo", format="%+.2f"),
        "G/P %": st.column_config.NumberColumn("G/P % lordo", format="%+.1f%%"),
        "Tassa 26%": st.column_config.NumberColumn("Tassa 26% (€)", format="%.2f",
            help="26% sulla plusvalenza (solo se in utile), in EUR."),
        "G/P netto": st.column_config.NumberColumn("G/P netto (€)", format="%+.2f",
            help="Guadagno dopo tassa del 26% e commissioni — quanto incassi vendendo ora."),
        "Netto %": st.column_config.NumberColumn("Netto %", format="%+.1f%%"),
    })

    # --- 🔔 Consigli di vendita ---
    st.markdown("### Consigli di vendita")
    st.caption("Per ogni titolo il sistema valuta **se conviene incassare ora**, in base a bersaglio, stop, "
               "trailing stop (calo dal massimo toccato), ipercomprato e trend. **Non prevede il futuro** e non "
               "garantisce il massimo guadagno: è un aiuto a non farsi scappare un buon momento e a tagliare le perdite.")
    if fu.cloud_mode():
        st.caption("📲 Quando un titolo passa a «🔔 Valuta la vendita», ricevi anche una **notifica Telegram** (il sistema "
                   "controlla ogni ~15 minuti, anche a PC spento).")
    with st.spinner("Valuto i titoli…"):
        positions = fu.load_portfolio()
        advices = [(p, fu.sell_advice(p)) for p in positions]
    order = {"sell": 0, "watch": 1, "hold": 2}
    for p, adv in sorted(advices, key=lambda x: order.get(x[1]["verdict"], 3)):
        colore = {"sell": "#cf222e", "watch": "#9a6700", "hold": "#1a7f37"}[adv["verdict"]]
        gp = f"{adv['gain_pct']:+.1f}%" if adv["gain_pct"] is not None else "n/d"
        hor = "⚡ breve" if str(p.get("horizon", "lungo")).startswith("breve") else "🏛️ lungo"
        st.markdown(
            f"<div style='padding:8px 12px;border-radius:8px;background:{colore}14;"
            f"border-left:5px solid {colore};margin-bottom:6px'>"
            f"<b style='color:{colore}'>{adv['emoji']} {p.get('ticker')} — {adv['label']}</b> "
            f"<span style='color:#a9b1ba'>· {hor} · guadagno attuale {gp}</span></div>",
            unsafe_allow_html=True)
        for motivo in adv["reasons"]:
            st.markdown(f"<div style='margin-left:14px;color:#c9d1d9;font-size:0.9em'>↳ {motivo}</div>",
                        unsafe_allow_html=True)
    st.caption("⚠️ Spunti automatici, non consigli di investimento. La decisione finale è sempre tua.")

    # --- Rimozione posizioni ---
    st.markdown("###### Gestisci le posizioni")
    for r in rows:
        rc1, rc2 = st.columns([5, 1])
        gp = f"{r['pnl']:+,.2f} ({r['pnl_pct']:+.1f}%)" if r["pnl_pct"] is not None else "n/d"
        rc1.markdown(f"**{r['ticker']}** · {r['amount']:,.2f} investiti il {r['datetime']} "
                     f"(≈ {r['qty']:.4f} quote a {r['buy_price']:.2f}) · G/P: {gp}")
        if rc2.button("🗑️ Togli", key=f"rmpos_{r['index']}", use_container_width=True):
            fu.remove_position(r["index"])
            st.rerun()
    st.stop()

# ===========================================================================
# SEZIONE: ATTUALITÀ — notizie recenti divise per azienda/ETF
# ===========================================================================
if section.startswith("Attualità"):
    page_header("Attualità",
                "Le notizie più recenti dei mercati, divise per azienda ed ETF.")
    st.caption("Le notizie più recenti, divise per azienda/ETF. Una scheda per ciascun titolo più una per il mercato generale. "
               "Aggiungi i titoli che vuoi seguire; la traduzione in italiano segue l'interruttore nella barra laterale.")

    default_focus = watchlist if watchlist else ["AAPL", "MSFT", "NVDA"]
    foc_raw = st.text_input("Aziende/ETF da seguire (ticker separati da virgola)",
                            value=", ".join(default_focus), key="news_focus")
    focus = [t.strip().upper() for t in foc_raw.replace(";", ",").split(",") if t.strip()][:15]

    # --- Filtro per giorno ---
    fc1, fc2 = st.columns([1, 2])
    filtra_giorno = fc1.checkbox("📅 Filtra per giorno", value=False,
                                 help="Mostra solo le notizie pubblicate in una data specifica.")
    giorno = None
    if filtra_giorno:
        giorno = fc2.date_input("Giorno", value=datetime.date.today(),
                                max_value=datetime.date.today(), key="news_day")
        st.caption("ℹ️ Le fonti gratuite forniscono solo le notizie degli **ultimi giorni**: "
                   "date più lontane nel tempo potrebbero non avere risultati.")

    def render_news(src, header, n=8, day=None):
        st.markdown(f"#### {header}")
        news = fu.get_news(src, count=20 if day else n,
                           day=day.isoformat() if day else None)
        if not news:
            st.caption("Nessuna notizia per il giorno scelto." if day
                       else "Nessuna notizia disponibile per questo titolo.")
            return
        for it in news:
            title = it["title"]
            brief = fu.summarize_text(it["summary"], max_sentences=2)
            if translate_news:
                title = fu.translate_text(title)
                brief = fu.translate_text(brief)
            meta = " · ".join([x for x in (it["publisher"], it["date"]) if x])
            if it["url"]:
                st.markdown(f"**[{title}]({it['url']})**")
            else:
                st.markdown(f"**{title}**")
            if meta:
                st.caption(meta)
            if brief:
                st.markdown(f"📝 **In breve:** {brief}")
            else:
                st.caption("Riassunto non disponibile — apri l'articolo per i dettagli.")
            st.markdown("<hr style='margin:4px 0;border:none;border-top:1px solid rgba(255,255,255,0.12)'>", unsafe_allow_html=True)

    labels = ["🌍 Mercato generale"] + focus
    news_tabs = st.tabs(labels)
    with news_tabs[0]:
        st.markdown("#### Le aziende del momento")
        st.caption(
            "Classifiche aggiornate del mercato USA: chi sale, chi scende e chi viene più scambiato oggi. "
            "Clicca un ticker e incollalo nella ricerca per analizzarlo in dettaglio."
        )

        def show_screen(name, vmin_color):
            df = fu.get_screen(name, count=12)
            if df.empty:
                st.info("Classifica non disponibile al momento.")
                return
            df = df.set_index("Ticker")
            fmt = {"Prezzo": "{:,.2f}", "Var %": "{:+.2f}%", "Volume": "{:,.0f}", "Cap.": "{:,.0f}"}
            sty = df.style.format(fmt, na_rep="n/d")
            try:
                sty = sty.background_gradient(subset=["Var %"], cmap="RdYlGn", vmin=-vmin_color, vmax=vmin_color)
            except Exception:
                pass
            st.dataframe(sty, use_container_width=True)

        g1, g2, g3 = st.tabs(["🚀 In crescita oggi", "📉 In perdita oggi", "🔥 Più scambiati"])
        with g1:
            st.markdown("**Maggiori rialzi della giornata** (day gainers)")
            show_screen("day_gainers", 15)
        with g2:
            st.markdown("**Maggiori ribassi della giornata** (day losers)")
            show_screen("day_losers", 15)
        with g3:
            st.markdown("**Titoli più scambiati** per volume (most actives)")
            st.caption("Sono i titoli con il **maggior numero di scambi** oggi (volume più alto): tanti compratori "
                       "e venditori, quindi molto **movimento e attenzione** del momento — spesso per una notizia. "
                       "«Più scambiato» **non** vuol dire buono o cattivo: indica solo che oggi se ne parla e si muove molto.")
            show_screen("most_actives", 8)

        st.markdown("---")
        render_news("^GSPC", "S&P 500 — notizie generali di mercato", 10, day=giorno)
    for i, t in enumerate(focus, start=1):
        with news_tabs[i]:
            info_t = fu.get_info(t)
            nm = info_t.get("shortName") or info_t.get("longName") or t
            render_news(t, f"{nm} ({t})", 8, day=giorno)
    st.stop()

# ---------------------------------------------------------------------------
# CARICAMENTO DATI
# ---------------------------------------------------------------------------
if not ticker:
    st.markdown(
        "<div class='hero'><h2>Analisi Finanziaria</h2>"
        "<p>Capisci un'azienda, un ETF o un indice e valutane la convenienza, con spiegazioni in parole "
        "semplici. Cerca un nome nella barra a sinistra, oppure parti da uno dei suggerimenti qui sotto.</p></div>",
        unsafe_allow_html=True,
    )

    def suggestion_grid(title, items):
        st.markdown(f"#### {title}")
        cols = st.columns(len(items))
        for col, (sym, label) in zip(cols, items):
            if col.button(label, key=f"sugg_{sym}", use_container_width=True):
                st.session_state["ticker"] = sym
                st.rerun()

    suggestion_grid("Azioni famose", [
        ("AAPL", "Apple"), ("MSFT", "Microsoft"),
        ("NVDA", "Nvidia"), ("ENI.MI", "Eni"), ("ISP.MI", "Intesa Sanpaolo"),
    ])
    suggestion_grid("ETF popolari", [
        ("VWCE.DE", "Vanguard All-World"), ("CSSPX.MI", "S&P 500"),
        ("SWDA.MI", "MSCI World"), ("EIMI.MI", "Mercati Emergenti"),
    ])
    suggestion_grid("Indici di mercato", [
        ("^GSPC", "S&P 500"), ("^FTSEMIB.MI", "FTSE MIB"),
        ("^IXIC", "Nasdaq"), ("^STOXX50E", "Euro Stoxx 50"),
    ])
    st.markdown("---")
    st.caption("⚠️ Strumento a scopo informativo. **Non è consulenza finanziaria.**")
    st.stop()

with st.spinner(f"Scarico i dati di {ticker}…"):
    hist = fu.get_history(ticker, period=period)
    info = fu.get_info(ticker, merge=True)   # combina tutte le fonti → meno campi «n/d»

if hist.empty:
    st.error(
        f"Nessun dato trovato per **{ticker}**. "
        "Controlla il simbolo (per Milano aggiungi `.MI`, per gli indici usa `^`)."
    )
    st.stop()

hist = fu.add_indicators(hist)
name = info.get("longName") or info.get("shortName") or ticker
currency = info.get("currency", "")
fund = fu.is_fund(info) or fu.is_known_etf(ticker)
fdata = fu.get_fund_data(ticker, info) if fund else None

# ---------------------------------------------------------------------------
# INTESTAZIONE
# ---------------------------------------------------------------------------
_exch = info.get("exchange", "") or ""
page_header(name, f"<b>{ticker}</b>"
            + (f" · {_exch}" if _exch else "")
            + (f" · Valuta: {currency}" if currency else ""))

last_close = hist["Close"].iloc[-1]
prev_close = hist["Close"].iloc[-2] if len(hist) > 1 else last_close
delta = last_close - prev_close
delta_pct = (delta / prev_close * 100) if prev_close else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Ultimo prezzo", f"{last_close:,.2f} {currency}", f"{delta:+,.2f} ({delta_pct:+.2f}%)",
          help="Ultima quotazione disponibile e variazione rispetto alla chiusura precedente.")
perf = (hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100
c2.metric(f"Performance ({period_label})", f"{perf:+.2f}%",
          help="Variazione percentuale del prezzo sull'intero periodo selezionato.")
c3.metric("Volatilità annua", f"{fu.annualized_volatility(hist['Close']) * 100:.1f}%",
          help=fu.help_for("Volatilità annua"))
if fund:
    aum = info.get("totalAssets") or (fdata or {}).get("total_assets")
    c4.metric("Patrimonio (AUM)", fu._fmt_big(aum), help=fu.help_for("Patrimonio (AUM)"))
else:
    c4.metric("Capitalizzazione", fu._fmt_big(info.get("marketCap")),
              help=fu.help_for("Capitalizzazione"))

# --- Trasparenza dati: fonte dei fondamentali, data ultimo prezzo, stato FMP ---
st.caption(fu.data_status_line(info, hist)
           + "  ·  _i dati gratuiti possono avere ritardo (chiusura del giorno) o ripiegare su altre fonti._")

# --- Semaforo / verdetto sintetico ---
verdict = fu.overall_verdict(info, hist, fund, fdata)
vcol1, vcol2 = st.columns([1, 2.4])
with vcol1:
    if verdict["score"] is not None:
        gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=verdict["score"],
            number={"suffix": "/100", "font": {"size": 26}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1},
                "bar": {"color": verdict["color"]},
                "steps": [
                    {"range": [0, 40], "color": "#ffe3e0"},
                    {"range": [40, 66], "color": "#fff3cd"},
                    {"range": [66, 100], "color": "#d8f5e0"},
                ],
            },
        ))
        gauge.update_layout(height=180, margin=dict(t=10, b=10, l=20, r=20))
        show_chart(gauge, use_container_width=True)
    else:
        st.markdown(f"<div style='font-size:2.4em;text-align:center'>{verdict['emoji']}</div>",
                    unsafe_allow_html=True)
with vcol2:
    st.markdown(
        f"<div style='padding:14px 16px;border-radius:10px;background:{verdict['color']}14;"
        f"border-left:6px solid {verdict['color']}'>"
        f"<div style='font-size:1.25em;font-weight:700;color:{verdict['color']}'>"
        f"{verdict['emoji']} {verdict['label']}</div>"
        f"<div style='margin-top:6px;color:#c9d1d9'>{verdict['line']}</div></div>",
        unsafe_allow_html=True,
    )
    st.caption("Verdetto sintetico calcolato dai segnali analizzati. **Non è un consiglio di investimento.**")

# --- Sintesi automatica in linguaggio naturale ---
with st.expander("🧠 Sintesi automatica — leggi il titolo a parole", expanded=True):
    if fund:
        st.markdown(fu.fund_commentary(ticker, fdata, info, hist, period_label))
    else:
        st.markdown(fu.generate_commentary(ticker, info, hist, period_label))
    st.caption(
        "Commento generato automaticamente dai dati (regole quantitative, nessun consiglio di acquisto). "
        "Verifica sempre con altre fonti prima di investire."
    )

# ---------------------------------------------------------------------------
# TAB
# ---------------------------------------------------------------------------
fund_tab_label = "🧺 Composizione ETF" if fund else "💰 Analisi Fondamentale"
tab_over, tab_fund, tab_tech, tab_sim, tab_cmp, tab_news = st.tabs(
    ["📊 Panoramica", fund_tab_label, "📈 Analisi Tecnica", "💶 Simulatore",
     "⚖️ Confronto / Screener", "📰 Notizie"]
)

# ============================ PANORAMICA ===================================
with tab_over:
    st.subheader("Andamento del prezzo")

    # Selettore del periodo, direttamente sul grafico
    CHART_PERIODS = {"1 giorno": "1d", "1 settimana": "5d", "1 mese": "1mo", "6 mesi": "6mo",
                     "1 anno": "1y", "5 anni": "5y", "Tutto": "max"}
    cp_label = st.radio("Periodo del grafico", list(CHART_PERIODS.keys()),
                        index=4, horizontal=True, key="chart_period")
    # Periodi brevi (giorno/settimana) → prezzo intraday ~15 min; periodi lunghi → un valore al giorno
    hist_c = chart_history(ticker, CHART_PERIODS[cp_label])
    _intraday_c = bool(hist_c.attrs.get("intraday"))

    st.caption("👀 La linea mostra l'andamento del prezzo nel periodo scelto: **verde** se in rialzo, "
               "**rossa** se in calo. Cambia periodo qui sopra. "
               + ("Nei periodi brevi il prezzo è **intraday** (giorno ~15 min · settimana ~1 ora); "
                  "negli altri è un valore al giorno (chiusura). I dati esistono solo nelle ore di "
                  "apertura della borsa: a mercato chiuso non ci sono scambi." if _intraday_c
                  else "In questo periodo è un valore al giorno (chiusura)."))
    if hist_c.empty:
        st.info("Nessun dato per il periodo scelto.")
    else:
        closes = hist_c["Close"]
        up = closes.iloc[-1] >= closes.iloc[0]
        line_color = "#1a7f37" if up else "#cf222e"
        fill_color = "rgba(26,127,55,0.12)" if up else "rgba(207,34,46,0.12)"
        ymin, ymax = float(closes.min()), float(closes.max())
        pad = (ymax - ymin) * 0.12 or (ymax * 0.02) or 1.0
        _htfmt = "%d %b %H:%M" if _intraday_c else "%d %b %Y"
        fig = go.Figure(go.Scatter(
            x=hist_c.index, y=closes, mode="lines",
            line=dict(color=line_color, width=2), fill="tozeroy", fillcolor=fill_color,
            hovertemplate="%{x|" + _htfmt + "} · %{y:.2f} " + str(currency) + "<extra></extra>",
        ))
        fig.update_layout(
            height=420, margin=dict(t=10, b=10, l=10, r=10),
            xaxis_rangeslider_visible=False, hovermode="x unified", showlegend=False,
            plot_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(range=[ymin - pad, ymax + pad], showgrid=True, gridcolor="rgba(128,128,128,0.15)"),
            xaxis=dict(showgrid=False),
        )
        show_chart(fig, use_container_width=True)
        perf_c = (closes.iloc[-1] / closes.iloc[0] - 1) * 100
        _last_lbl = hist_c.index[-1].strftime("%d/%m/%Y %H:%M" if _intraday_c else "%d/%m/%Y")
        st.caption(f"Variazione nel periodo «{cp_label}»: **{perf_c:+.1f}%** · 📅 ultimo dato: {_last_lbl}")

    colA, colB = st.columns([1, 1])
    with colA:
        st.subheader("Scheda azienda")
        for k, v in fu.overview_metrics(info, hist).items():
            st.markdown(f"**{k}:** {v}")
    with colB:
        st.subheader("Descrizione")
        summary = info.get("longBusinessSummary")
        if summary:
            if translate_news:
                summary = fu.translate_text(summary)
            st.write(summary)
        else:
            st.write("Descrizione non disponibile per questo strumento.")

# ======================== ANALISI FONDAMENTALE =============================
with tab_fund:
  if fund:
    # ---------------- VISTA ETF / FONDO ----------------
    st.subheader("Composizione e caratteristiche dell'ETF")
    st.caption("Per un fondo contano costi, diversificazione, asset e settori — non i bilanci di una singola azienda.")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Categoria", fdata.get("category") or "n/d")
    m2.metric("Gestore", (fdata.get("family") or "n/d"))
    ter = fdata.get("expense_ratio")
    m3.metric("TER (costo annuo)", f"{ter*100:.2f}%" if ter else "n/d", help=fu.help_for("TER (costo annuo)"))
    m4.metric("Patrimonio (AUM)", fu._fmt_big(fdata.get("total_assets")), help=fu.help_for("Patrimonio (AUM)"))

    if ter and fdata.get("expense_ratio_source") == "tabella interna":
        st.caption("ℹ️ TER da tabella interna (yfinance non lo fornisce per questo ETF UCITS): valore indicativo, "
                   "verificalo sul KID dell'emittente.")
    elif not ter:
        st.caption("ℹ️ TER non disponibile: cercalo sul sito dell'emittente — è il fattore di costo più importante.")

    if not expert:
        st.info("👀 **Cosa guardare:** un ETF è un paniere di tanti titoli. Conta che i **costi (TER)** siano bassi, "
                "che sia **diversificato** (nessun titolo troppo grande) e ampio come patrimonio.")

    colL, colR = st.columns(2)

    # Asset allocation (torta)
    with colL:
        st.markdown("#### Asset allocation")
        st.caption("👀 Come sono divisi i soldi del fondo tra azioni, obbligazioni e liquidità: definisce rischio e rendimento attesi.")
        ac = fdata.get("asset_classes") or {}
        if ac:
            labels = [fu.ASSET_IT.get(k, k) for k in ac]
            vals = [v * 100 for v in ac.values()]
            figa = go.Figure(go.Pie(labels=labels, values=vals, hole=0.45, sort=True))
            figa.update_traces(textinfo="label+percent")
            figa.update_layout(height=320, margin=dict(t=10, b=10), showlegend=False)
            show_chart(figa, use_container_width=True)
        else:
            st.caption("Dati di composizione non disponibili.")

    # Settori (barre)
    with colR:
        st.markdown("#### Esposizione settoriale")
        st.caption("👀 A quali settori dell'economia sei più esposto. Le barre più lunghe = settori dove il fondo investe di più.")
        sw = fdata.get("sector_weightings") or {}
        if sw:
            items = sorted(sw.items(), key=lambda kv: kv[1])
            figs = go.Figure(go.Bar(
                x=[v * 100 for _, v in items],
                y=[fu.SECTOR_IT.get(k, k) for k, _ in items],
                orientation="h", marker_color="#0969da",
            ))
            figs.update_layout(height=320, margin=dict(t=10, b=10), xaxis_title="%")
            show_chart(figs, use_container_width=True)
        else:
            st.caption("Ripartizione settoriale non disponibile.")

    # Top holdings
    st.markdown("#### Principali titoli in portafoglio")
    st.caption("👀 Le aziende più presenti nel fondo. Se i primi 10 pesano poco (<25%) il fondo è ben diversificato.")
    th = fdata.get("top_holdings") or []
    if th:
        df_th = pd.DataFrame(
            [(s, n, p * 100) for s, n, p in th],
            columns=["Ticker", "Nome", "Peso %"],
        ).set_index("Ticker")
        conc = df_th["Peso %"].sum()
        st.dataframe(
            df_th.style.format({"Peso %": "{:.2f}%"})
            .background_gradient(subset=["Peso %"], cmap="Blues"),
            use_container_width=True,
        )
        st.caption(f"I primi {len(df_th)} titoli pesano circa il {conc:.1f}% del fondo "
                   f"({'concentrazione elevata' if conc > 50 else 'buona diversificazione'}).")

        # --- Andamento dei titoli che compongono l'ETF (un grafico per titolo) ---
        st.markdown("#### Andamento dei titoli che lo compongono")
        st.caption("👀 Un grafico per ciascun titolo principale del fondo, ognuno con la propria scala, "
                   "con la performance nel periodo scelto.")
        HPER = {"1 mese": "1mo", "6 mesi": "6mo", "1 anno": "1y", "Tutto": "max"}
        hsel = st.radio("Periodo", list(HPER.keys()), index=2, horizontal=True, key="etf_holdings_period")
        with st.spinner("Scarico l'andamento dei titoli…"):
            hdata = []
            for s, n, p in th[:10]:
                if not s:
                    continue
                hh = fu.get_history(s, period=HPER[hsel])
                if hh.empty:
                    continue
                cc = hh["Close"].dropna()
                if cc.empty or float(cc.iloc[0]) == 0:
                    continue
                perf = (float(cc.iloc[-1]) / float(cc.iloc[0]) - 1) * 100
                hdata.append((s, n, p, cc, perf))
        if hdata:
            hcols = st.columns(2)
            for i, (s, n, p, cc, perf) in enumerate(hdata):
                with hcols[i % 2]:
                    col = "#1a7f37" if perf >= 0 else "#cf222e"
                    nm = (n or "")[:26].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    st.markdown(
                        f"<b>{s}</b> <span style='color:#8b94a3;font-size:0.85em'>{nm}</span><br>"
                        f"<span style='color:#8b94a3;font-size:0.85em'>peso {p*100:.1f}%</span> · "
                        f"<span style='color:{col};font-weight:600'>{perf:+.1f}%</span>",
                        unsafe_allow_html=True)
                    fg = go.Figure(go.Scatter(x=cc.index, y=cc, mode="lines",
                                              line=dict(color=col, width=1.8)))
                    fg.update_layout(height=170, margin=dict(t=6, b=6, l=6, r=6), showlegend=False,
                                     yaxis_title=None, xaxis_title=None,
                                     plot_bgcolor="rgba(0,0,0,0)")
                    show_chart(fg)
            st.caption("Performance dal primo giorno del periodo. Per l'analisi dettagliata di un titolo, "
                       "cercane il ticker nella barra a sinistra.")
        else:
            st.caption("Andamento dei titoli non disponibile al momento (dati non recuperabili).")
    else:
        st.caption("Elenco titoli non disponibile.")

    # Descrizione
    desc = fdata.get("description") or info.get("longBusinessSummary") or ""
    if desc:
        if translate_news:
            desc = fu.translate_text(desc)
        st.markdown("#### Descrizione")
        st.write(desc)

    with st.expander("📖 Glossario — capire un ETF"):
        for key in ["ETF", "TER (costo annuo)", "Patrimonio (AUM)", "Asset allocation",
                    "Diversificazione", "Top holdings", "Settori"]:
            st.markdown(f"**{key}** — {fu.GLOSSARY.get(key, '')}")

  else:
    # ---------------- VISTA AZIENDA ----------------
    st.subheader("Analisi fondamentale")
    st.caption(
        "Misura la qualità e il valore dell'azienda dai suoi bilanci. "
        "🟢 favorevole · 🟡 neutro · 🔴 sfavorevole (soglie indicative generali)."
    )

    blocks = fu.fundamental_blocks(info)
    if not expert:
        st.info("👀 **Cosa guardare:** se prevalgono i 🟢, l'azienda è solida e a un prezzo ragionevole. "
                "I 🔴 sono i punti deboli. Attiva la modalità *Esperto* per vedere tutti gli indicatori.")
        keep = ["Valutazione (è caro o conveniente?)", "Redditività (quanto guadagna bene?)"]
        view_blocks = {k: v for k, v in blocks.items() if k in keep}
    else:
        view_blocks = blocks

    cols = st.columns(2)
    for i, (block_name, rows) in enumerate(view_blocks.items()):
        with cols[i % 2]:
            st.markdown(f"#### {block_name}")
            for row in rows:
                label, value, judgement = row[0], row[1], row[2]
                reason = row[3] if len(row) > 3 else ""
                badge(label, value, judgement, fu.help_for(label), reason)
            st.write("")

    # Sintesi conteggio segnali (sempre su tutti i blocchi)
    all_rows = [r for rows in blocks.values() for r in rows]
    pos = sum(1 for r in all_rows if r[2] == "positivo")
    neg = sum(1 for r in all_rows if r[2] == "negativo")
    neu = sum(1 for r in all_rows if r[2] == "neutro")
    st.markdown("---")
    st.markdown(
        f"**Bilancio dei segnali fondamentali:** "
        f"🟢 {pos} favorevoli · 🟡 {neu} neutri · 🔴 {neg} sfavorevoli"
    )
    if pos + neg + neu == 0:
        st.info("Dati fondamentali non disponibili per questo strumento.")

    # (Rimosso il confronto con i bilanci SEC: metteva a confronto dati TTM con dati annuali,
    # quindi mostrava sempre valori "differiti" e talvolta numeri incoerenti. I valori mostrati
    # restano quelli delle fonti indicate nell'indicatore «📡 dati» in cima alla pagina.)

    with st.expander("📖 Glossario — cosa significano questi indicatori"):
        for label, *_ in all_rows:
            txt = fu.help_for(label)
            if txt:
                st.markdown(f"**{label}** — {txt}")

# =========================== ANALISI TECNICA ===============================
with tab_tech:
    st.subheader("Analisi tecnica")
    st.caption("Studia l'andamento di prezzo e volumi per valutare trend e momentum (utile per il timing).")

    # Selettore di periodo (come nella Panoramica)
    CHART_PERIODS_T = {"1 settimana": "5d", "1 mese": "1mo", "6 mesi": "6mo",
                       "1 anno": "1y", "5 anni": "5y", "Tutto": "max"}
    cpt_label = st.radio("Periodo del grafico", list(CHART_PERIODS_T.keys()),
                         index=3, horizontal=True, key="tech_period")
    hist_t = fu.add_indicators(fu.get_history(ticker, period=CHART_PERIODS_T[cpt_label]))

    if hist_t.empty:
        st.info("Nessun dato per il periodo scelto.")
    elif not expert:
        # Modalità Principiante: solo prezzo + medie mobili, con spiegazione
        st.info("👀 **Cosa guardare:** la linea blu è il prezzo. Quando sta **sopra** la media a 50 giorni "
                "(verde) il trend è positivo, quando sta **sotto** è negativo.")
        figp = go.Figure()
        figp.add_trace(go.Scatter(x=hist_t.index, y=hist_t["Close"], name="Prezzo", line=dict(color="#0969da")))
        if hist_t["SMA50"].notna().any():
            figp.add_trace(go.Scatter(x=hist_t.index, y=hist_t["SMA50"], name="Media 50 giorni", line=dict(color="#1a7f37", width=1.4)))
        if hist_t["SMA200"].notna().any():
            figp.add_trace(go.Scatter(x=hist_t.index, y=hist_t["SMA200"], name="Media 200 giorni", line=dict(color="#d29922", width=1.4)))
        figp.update_layout(height=420, margin=dict(t=10, b=10), legend=dict(orientation="h"))
        show_chart(figp, use_container_width=True)
        st.caption("Su periodi brevi (1 settimana/1 mese) le medie mobili possono non comparire: servono più dati.")
    else:
        # Modalità Esperto: prezzo + Bollinger + RSI + MACD
        figp = make_subplots(
            rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04,
            row_heights=[0.55, 0.22, 0.23],
            subplot_titles=("Prezzo + Medie mobili + Bande di Bollinger", "RSI (14)", "MACD"),
        )
        figp.add_trace(go.Scatter(x=hist_t.index, y=hist_t["Close"], name="Prezzo", line=dict(color="#0969da")), row=1, col=1)
        figp.add_trace(go.Scatter(x=hist_t.index, y=hist_t["SMA20"], name="SMA 20", line=dict(width=1)), row=1, col=1)
        figp.add_trace(go.Scatter(x=hist_t.index, y=hist_t["SMA50"], name="SMA 50", line=dict(width=1)), row=1, col=1)
        figp.add_trace(go.Scatter(x=hist_t.index, y=hist_t["BB_up"], name="Bollinger sup", line=dict(width=0.5, dash="dot", color="gray")), row=1, col=1)
        figp.add_trace(go.Scatter(x=hist_t.index, y=hist_t["BB_low"], name="Bollinger inf", line=dict(width=0.5, dash="dot", color="gray"), fill="tonexty", fillcolor="rgba(150,150,150,0.08)"), row=1, col=1)
        figp.add_trace(go.Scatter(x=hist_t.index, y=hist_t["RSI"], name="RSI", line=dict(color="#8250df")), row=2, col=1)
        figp.add_hline(y=70, line=dict(color="red", width=0.7, dash="dash"), row=2, col=1)
        figp.add_hline(y=30, line=dict(color="green", width=0.7, dash="dash"), row=2, col=1)
        figp.add_trace(go.Bar(x=hist_t.index, y=hist_t["MACD_hist"], name="Istogramma", marker_color="#bbb"), row=3, col=1)
        figp.add_trace(go.Scatter(x=hist_t.index, y=hist_t["MACD"], name="MACD", line=dict(color="#0969da")), row=3, col=1)
        figp.add_trace(go.Scatter(x=hist_t.index, y=hist_t["MACD_signal"], name="Signal", line=dict(color="#cf222e")), row=3, col=1)
        figp.update_layout(height=720, margin=dict(t=30, b=10), legend=dict(orientation="h"))
        show_chart(figp, use_container_width=True)
        st.markdown(
            "**Cosa mostra ogni grafico (in parole semplici):**\n\n"
            "- **📈 Prezzo + medie + Bollinger** *(grafico in alto)*: la linea blu è il **prezzo**; le medie mobili "
            "(20 e 50 giorni) indicano la **direzione del trend**; le due linee grigie tratteggiate (bande di "
            "Bollinger) sono la fascia «normale» — quando il prezzo le **tocca o le sfora** è a un estremo "
            "(insolitamente alto o basso).\n"
            "- **📊 RSI** *(grafico centrale, 0-100)*: misura la **foga** di acquisti/vendite. **Sopra 70** = "
            "ipercomprato (caro, può correggere); **sotto 30** = ipervenduto (sceso molto, può rimbalzare); "
            "in mezzo = neutro.\n"
            "- **📉 MACD** *(grafico in basso)*: misura lo **slancio** (momentum). Quando la **linea blu supera la "
            "rossa** lo slancio diventa positivo (possibile rialzo); quando le scende sotto, negativo. "
            "Le barre grigie mostrano quanto è forte lo slancio."
        )

    st.markdown("#### Segnali tecnici attuali")
    tsum = fu.technical_summary(hist)
    if tsum:
        st.markdown(
            f"<div style='padding:10px 14px;border-radius:10px;background:{tsum['color']}14;"
            f"border-left:6px solid {tsum['color']};margin-bottom:6px'>"
            f"<span style='font-size:1.15em;font-weight:700;color:{tsum['color']}'>"
            f"{tsum['emoji']} {tsum['label']}</span></div>",
            unsafe_allow_html=True,
        )
        st.markdown("👉 " + tsum["line"])
        st.caption("Sintesi dei singoli segnali qui sotto. Indicazione tecnica, **non un consiglio**.")

    signals = fu.technical_signals(hist)
    if signals:
        st.write("")
        scols = st.columns(2)
        for i, (label, value, judgement) in enumerate(signals):
            with scols[i % 2]:
                badge(label, value, judgement, fu.help_for(label))
    else:
        st.info("Storico insufficiente per calcolare i segnali (servono più dati).")

    with st.expander("📖 Glossario — gli strumenti dell'analisi tecnica"):
        for key in ["SMA", "EMA", "Bande di Bollinger", "RSI (14)", "MACD",
                    "Golden cross", "Death cross", "Volatilità annua"]:
            st.markdown(f"**{key}** — {fu.GLOSSARY.get(key, '')}")

# ============================= SIMULATORE ==================================
with tab_sim:
    st.subheader("Simulatore: quanto avresti guadagnato?")
    st.caption("Scopri quanto varrebbe oggi un investimento fatto in passato, confrontato col mercato.")

    hsim = fu.get_history(ticker, period="max")
    if hsim.empty or len(hsim) < 2:
        st.info("Storico insufficiente per la simulazione.")
    else:
        dmin = hsim.index[0].date()
        dmax = hsim.index[-1].date()
        default_start = max(dmin, dmax - datetime.timedelta(days=365 * 5))

        ic1, ic2, ic3 = st.columns(3)
        amount = ic1.number_input("Importo investito (€)", min_value=10.0, value=1000.0, step=100.0)
        start = ic2.date_input("Data dell'investimento", value=default_start,
                               min_value=dmin, max_value=dmax)
        bench_choice = ic3.selectbox(
            "Confronta con", ["Automatico", "S&P 500", "FTSE MIB", "Nasdaq", "Nessuno"],
            help="Il benchmark è il mercato di riferimento: serve a capire se l'investimento ha fatto meglio o peggio della media.",
        )
        bench_map = {"Automatico": fu.default_benchmark(ticker), "S&P 500": "^GSPC",
                     "FTSE MIB": "^FTSEMIB.MI", "Nasdaq": "^IXIC", "Nessuno": None}
        benchmark = bench_map[bench_choice]

        res = fu.simulate_investment(ticker, amount, start, benchmark)
        if not res:
            st.info("Nessun dato disponibile per la data scelta. Prova una data più recente.")
        else:
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Valore oggi", f"{res['final']:,.0f} {currency}")
            r2.metric("Guadagno/Perdita", f"{res['gain']:+,.0f} {currency}", f"{res['gain_pct']:+.1f}%")
            r3.metric("Rendimento annuo medio", f"{res['cagr']:+.1f}%",
                      help="CAGR: il tasso di crescita annuo composto equivalente nel periodo.")
            r4.metric("Quote acquistate", f"{res['shares']:,.2f}")

            figv = go.Figure()
            figv.add_trace(go.Scatter(x=res["df"].index, y=res["df"]["Titolo"],
                                      name=ticker, line=dict(color="#0969da", width=2), fill="tozeroy",
                                      fillcolor="rgba(9,105,218,0.08)"))
            if "Benchmark" in res["df"]:
                figv.add_trace(go.Scatter(x=res["df"].index, y=res["df"]["Benchmark"],
                                          name=f"Benchmark ({benchmark})", line=dict(color="#9a6700", dash="dot")))
            figv.add_hline(y=amount, line=dict(color="gray", width=1, dash="dash"),
                           annotation_text="Capitale iniziale")
            figv.update_layout(height=420, margin=dict(t=10, b=10), legend=dict(orientation="h"),
                               yaxis_title=f"Valore ({currency})")
            show_chart(figv, use_container_width=True)

            # Sintesi a parole + confronto col mercato
            verb = "guadagnato" if res["gain"] >= 0 else "perso"
            msg = (f"Investendo **{amount:,.0f} {currency}** in **{name}** il {start.strftime('%d/%m/%Y')}, "
                   f"oggi avresti **{res['final']:,.0f} {currency}**: hai {verb} "
                   f"**{abs(res['gain']):,.0f} {currency}** ({res['gain_pct']:+.1f}%) "
                   f"in {res['years']:.1f} anni.")
            if res.get("bench_final") is not None:
                diff = res["final"] - res["bench_final"]
                if diff >= 0:
                    msg += (f" Lo stesso importo sul mercato di riferimento varrebbe "
                            f"{res['bench_final']:,.0f} {currency}: hai fatto **meglio del mercato** "
                            f"di {diff:,.0f} {currency}.")
                else:
                    msg += (f" Lo stesso importo sul mercato di riferimento varrebbe "
                            f"{res['bench_final']:,.0f} {currency}: hai fatto **peggio del mercato** "
                            f"di {abs(diff):,.0f} {currency}.")
            st.success(msg)
            st.caption("👀 **Cosa guardare:** l'area blu è il valore del tuo investimento nel tempo; "
                       "la linea tratteggiata è il capitale di partenza. Sopra = sei in guadagno. "
                       "Rendimenti passati non garantiscono rendimenti futuri.")

    # ---------------- PROIEZIONE FUTURA (scenari ipotetici) ----------------
    st.markdown("---")
    st.markdown("### 🔮 Proiezione futura — scenari ipotetici")
    st.caption("Scenari ipotetici costruiti dai dati storici del titolo: danno un'idea degli ordini di grandezza, "
               "non sono una previsione del prezzo.")

    base_hist = hsim if not hsim.empty else hist
    ann_ret_hist, vol_hist = fu.hist_return_vol(base_hist)
    # Volatilità EWMA (più reattiva: cattura il volatility clustering) — usata per la fascia
    try:
        _lr = np.log(base_hist["Close"] / base_hist["Close"].shift(1)).dropna().values
        ewma_v = fu.ewma_vol(_lr)
    except Exception:
        ewma_v = None
    if ann_ret_hist is None:
        st.info("Storico insufficiente per una proiezione.")
    else:
        vol_used = ewma_v if ewma_v else vol_hist
        default_ret = float(np.clip(ann_ret_hist * 100, -15.0, 25.0))
        # Rendimento atteso "automatico": per le azioni dai fondamentali (earnings yield + crescita),
        # per ETF/indici dallo storico. Clampato per prudenza.
        _fdr = fu.fundamental_drift(info) if not fund else None
        auto_ret = float(np.clip((_fdr * 100) if _fdr is not None else default_ret, -15.0, 25.0))
        auto_src = "fondamentali (earnings yield + crescita)" if _fdr is not None else "storico"
        pc1, pc2, pc3, pc4 = st.columns(4)
        f_initial = pc1.number_input("Capitale iniziale (€)", min_value=0.0, value=1000.0, step=100.0, key="proj_init")
        f_monthly = pc2.number_input("Versamento mensile (€)", min_value=0.0, value=0.0, step=50.0, key="proj_month",
                                     help="PAC: quanto aggiungi ogni mese. Lascia 0 per un investimento una tantum.")
        f_years = pc3.slider("Orizzonte (anni)", 1, 30, 10, key="proj_years")
        with pc4:
            auto_on = st.checkbox("🤖 Rendimento automatico", value=True, key="proj_auto",
                                  help="Stima da sola il rendimento annuo atteso: dai fondamentali per le azioni, "
                                       "dallo storico per ETF/indici. Togli la spunta per impostarlo a mano.")
            if auto_on:
                f_ret = auto_ret
                st.metric("Rendimento annuo atteso", f"{f_ret:.1f}%")
                st.caption(f"calcolato da: {auto_src}")
            else:
                f_ret = st.slider("Rendimento annuo atteso (%)", -10.0, 30.0, round(default_ret, 1), 0.5,
                                  key="proj_ret",
                                  help=f"Storico annuo: {ann_ret_hist*100:.1f}%. Decide solo il *centro* del ventaglio, non la sua forma.")

        method_label = st.radio(
            "Modello di incertezza", ["Bootstrap reale (consigliato)", "t-Student (code grasse)", "Normale (gaussiana)"],
            horizontal=True, key="proj_method",
            help="Come viene disegnata la FORMA dell'incertezza (non la direzione). Il **bootstrap dei rendimenti reali** "
                 "ricampiona la storia vera del titolo → cattura code grasse e periodi turbolenti, dando probabilità più "
                 "oneste. La normale sottostima gli estremi.")
        method = {"Bootstrap reale (consigliato)": "bootstrap", "t-Student (code grasse)": "tstudent",
                  "Normale (gaussiana)": "normale"}[method_label]
        with st.expander("ℹ️ Cosa sono i modelli di incertezza?"):
            st.markdown(
                "Tutti e tre partono dallo **stesso rendimento atteso** (il centro del ventaglio): cambia solo "
                "**come disegnano l'incertezza** attorno, cioè quanto considerano probabili gli scenari estremi.\n\n"
                "- **Bootstrap reale (consigliato):** ricampiona a caso pezzi della **storia vera** del titolo. "
                "Riproduce code grasse e periodi turbolenti come sono successi davvero → probabilità più oneste, "
                "soprattutto sul rischio di forti perdite.\n"
                "- **t-Student (code grasse):** una campana con le **code più spesse** della normale → dà più peso "
                "agli estremi (crolli e balzi), ma senza usare la storia specifica del titolo.\n"
                "- **Normale (gaussiana):** la classica campana. Semplice, ma **sottostima gli eventi estremi** "
                "(nella realtà i crolli capitano più spesso) → la fascia può sembrare troppo stretta.")
        mlr = fu.monthly_logrets(base_hist)
        if method == "bootstrap" and mlr is None:
            st.caption("ℹ️ Storico mensile insufficiente per il bootstrap: uso il modello normale.")

        proj = fu.project_future(f_initial, f_monthly, f_years, f_ret / 100.0, vol_used,
                                 method=method, month_logrets=mlr)
        tot = proj["total_invested"]
        # Scenari coerenti col ventaglio Monte Carlo: prudente=10°, base=mediana, ottimistico=90°
        end_pru, end_base, end_opt = proj["p10"][-1], proj["p50"][-1], proj["p90"][-1]

        q1, q2, q3, q4 = st.columns(4)
        q1.metric("💶 Totale versato", f"{tot:,.0f} {currency}")
        q2.metric("🟡 Scenario base (mediana)", f"{end_base:,.0f} {currency}",
                  f"{(end_base/tot-1)*100:+.0f}%" if tot else None)
        q3.metric("🔴 Prudente (10%)", f"{end_pru:,.0f} {currency}",
                  f"{(end_pru/tot-1)*100:+.0f}%" if tot else None)
        q4.metric("🟢 Ottimistico (10%)", f"{end_opt:,.0f} {currency}",
                  f"{(end_opt/tot-1)*100:+.0f}%" if tot else None)

        pb = proj.get("p_below_invested")
        if pb is not None:
            tone = st.success if pb <= 20 else st.warning if pb <= 40 else st.error
            tone(f"📉 **Probabilità di finire SOTTO il totale versato a {f_years} anni: ~{pb}%** "
                 f"_(modello: {proj['method_label']})_. Più alta = più rischio di chiudere in perdita.")

        x = proj["x_years"]
        figf = go.Figure()
        figf.add_trace(go.Scatter(x=x, y=proj["p90"], name="Ottimistico (90°)",
                                  line=dict(color="#1a7f37", dash="dot", width=1)))
        figf.add_trace(go.Scatter(x=x, y=proj["p10"], name="Fascia probabile (80% degli scenari)", fill="tonexty",
                                  fillcolor="rgba(9,105,218,0.10)", line=dict(color="#cf222e", dash="dot", width=1)))
        figf.add_trace(go.Scatter(x=x, y=proj["p50"], name="Andamento mediano", line=dict(color="#0969da", width=2.5)))
        figf.add_trace(go.Scatter(x=x, y=proj["invested"], name="Totale versato", line=dict(color="gray", dash="dash")))
        figf.update_layout(height=440, margin=dict(t=10, b=10), legend=dict(orientation="h"),
                           xaxis_title="Anni da oggi", yaxis_title=f"Valore ({currency})")
        show_chart(figf, use_container_width=True)
        st.caption("👀 **Cosa guardare:** la linea blu è l'andamento **mediano** simulato; la **fascia azzurra** "
                   "racchiude l'80% degli scenari possibili (tra il bordo rosso = prudente e quello verde = ottimistico). "
                   "La linea grigia è quanto hai versato in totale: dove la fascia ci sta sopra, sei in guadagno. "
                   "**Più la fascia è ampia, maggiore è l'incertezza** (titoli volatili = fascia larga).")

# ========================= CONFRONTO / SCREENER ============================
with tab_cmp:
    st.subheader("Confronto tra titoli (Screener)")
    st.caption(
        "Confronta più aziende sulle metriche chiave e ottieni un **punteggio sintetico (0-100)** "
        "che premia valutazioni convenienti, buona redditività e basso debito."
    )

    default_list = f"{ticker}, MSFT, GOOGL"
    raw = st.text_area("Ticker da confrontare (separati da virgola)", value=default_list, height=70)
    tickers = [t.strip().upper() for t in raw.replace(";", ",").split(",") if t.strip()]

    if st.button("Confronta", type="primary") and tickers:
        with st.spinner("Scarico e confronto i dati…"):
            rows = []
            errors = []
            for t in tickers[:15]:  # limite di sicurezza
                try:
                    rows.append(fu.screener_row(t))
                except Exception as e:
                    errors.append(f"{t}: {e}")
        if errors:
            st.caption("Alcuni ticker non sono stati caricati: " + " · ".join(errors))
        if rows:
            df_cmp = pd.DataFrame(rows).set_index("Ticker")
            df_cmp = df_cmp.sort_values("Punteggio", ascending=False, na_position="last")

            # Tabella display: percentuali in numero ×100
            disp = df_cmp.copy()
            for c in ["ROE", "Margine", "Div%", "Cresc.ricavi", "Perf.1A", "Volatilità"]:
                disp[c] = disp[c] * 100
            # Medaglie nella colonna Ticker (bloccata a sinistra → la classifica resta sempre visibile)
            _medals = {0: "🥇", 1: "🥈", 2: "🥉"}
            disp.index = [f"{_medals.get(i, '')} {t}".strip() for i, t in enumerate(disp.index)]

            # Legenda sempre visibile delle colonne
            with st.expander("📖 Cosa significano le colonne (leggimi)", expanded=True):
                st.markdown(
                    "- **Azienda** — nome del titolo.\n"
                    "- **⭐ Punteggio (0-100)** — voto sintetico complessivo: più alto e più verde = meglio. "
                    "Premia prezzo conveniente, buona redditività e basso debito.\n"
                    "- **Prezzo** — ultima quotazione.\n"
                    "- **P/E** (prezzo/utili) — quante volte gli utili annui paghi il titolo. **Più basso = più conveniente.**\n"
                    "- **P/B** (prezzo/patrimonio) — prezzo rispetto al valore di libro. Sotto 1 = paghi meno del patrimonio.\n"
                    "- **ROE** — rendimento del capitale proprio. **Più alto = azienda più redditizia** (>15% è buono).\n"
                    "- **Margine netto** — quanta parte dei ricavi diventa utile. Più alto = meglio.\n"
                    "- **Debito/Equity** — quanto debito ha rispetto al capitale. **Più basso = meno rischio.**\n"
                    "- **Dividendo** — quanto rende in cedole all'anno (in %).\n"
                    "- **Crescita ricavi** — di quanto sono cresciuti i ricavi nell'ultimo anno.\n"
                    "- **Performance 1 anno** — variazione del prezzo negli ultimi 12 mesi.\n"
                    "- **Volatilità** — quanto oscilla il prezzo in un anno. **Più alta = più rischio.**"
                )

            show_all = st.checkbox(
                "Mostra tutte le metriche", value=False,
                help="Disattivata mostra solo le colonne essenziali (entrano nello schermo). Attivala per vedere anche P/B, margine, debito, crescita, volatilità.",
            )
            essential = ["Nome", "Punteggio", "Prezzo", "P/E", "ROE", "Div%", "Perf.1A"]
            full = ["Nome", "Punteggio", "Prezzo", "P/E", "P/B", "ROE", "Margine",
                    "Deb/Eq", "Div%", "Cresc.ricavi", "Perf.1A", "Volatilità"]
            col_order = full if show_all else essential

            st.caption("👀 Ordinate dal **punteggio più alto** (barra verde) al più basso. "
                       "Passa il mouse sull'intestazione per un promemoria.")
            st.dataframe(
                disp,
                use_container_width=True,
                column_order=col_order,
                height=min(60 + 38 * len(disp), 460),
                column_config={
                    "Ticker": st.column_config.TextColumn("Ticker", width="small"),
                    "Nome": st.column_config.TextColumn("Azienda", width="large"),
                    "Punteggio": st.column_config.ProgressColumn(
                        "⭐ Punteggio", min_value=0, max_value=100, format="%.0f",
                        help=fu.help_for("Punteggio sintetico")),
                    "Prezzo": st.column_config.NumberColumn("Prezzo", format="%.2f"),
                    "P/E": st.column_config.NumberColumn("P/E", format="%.1f",
                        help="Prezzo/Utili: quante volte gli utili paghi il titolo. Più basso = più conveniente."),
                    "P/B": st.column_config.NumberColumn("P/B", format="%.2f",
                        help="Prezzo/Patrimonio. Sotto 1 = paghi meno del valore di libro."),
                    "ROE": st.column_config.NumberColumn("ROE", format="%.1f%%",
                        help="Rendimento del capitale proprio. Più alto = più redditizia."),
                    "Margine": st.column_config.NumberColumn("Margine netto", format="%.1f%%",
                        help="Percentuale di ricavi che resta come utile."),
                    "Deb/Eq": st.column_config.NumberColumn("Debito/Equity", format="%.0f",
                        help="Debito rispetto al capitale proprio. Più basso = meno rischio."),
                    "Div%": st.column_config.NumberColumn("Dividendo", format="%.2f%%",
                        help="Rendimento da dividendo annuo."),
                    "Cresc.ricavi": st.column_config.NumberColumn("Crescita ricavi", format="%.1f%%",
                        help="Crescita dei ricavi sull'anno."),
                    "Perf.1A": st.column_config.NumberColumn("Performance 1 anno", format="%.1f%%",
                        help="Variazione del prezzo negli ultimi 12 mesi."),
                    "Volatilità": st.column_config.NumberColumn("Volatilità", format="%.1f%%",
                        help="Oscillazione annua del prezzo. Più alta = più rischio."),
                },
            )
            podio = []
            for med, t in zip(["🥇", "🥈", "🥉"], df_cmp.index[:3]):
                nm = df_cmp.loc[t, "Nome"]
                sc = df_cmp.loc[t, "Punteggio"]
                podio.append(f"{med} **{t}** ({nm}) — {sc:.0f}/100" if pd.notna(sc) else f"{med} **{t}** ({nm})")
            st.success("🏆 **Classifica per punteggio sintetico:**  \n" + "  \n".join(podio)
                       + "  \n\n_Sintesi quantitativa indicativa, non un consiglio di acquisto._")

            # Grafico performance normalizzata
            st.markdown("#### Andamento a confronto (base 100)")
            st.caption("👀 **Cosa guardare:** tutti partono da 100. La linea che sale di più ha reso di più "
                       "nel periodo (a parità di punto di partenza).")
            figc = go.Figure()
            for t in df_cmp.index:
                h = fu.get_history(t, period=period)
                if not h.empty:
                    norm = h["Close"] / h["Close"].iloc[0] * 100
                    figc.add_trace(go.Scatter(x=h.index, y=norm, name=t))
            figc.update_layout(height=420, margin=dict(t=10, b=10), yaxis_title="Base 100", legend=dict(orientation="h"))
            show_chart(figc, use_container_width=True)

# =============================== NOTIZIE ===================================
with tab_news:
    st.subheader(f"📰 Notizie su {name}")
    st.caption(
        "Le notizie più recenti che riguardano questo titolo. "
        "Le classifiche di mercato (chi sale, chi scende, i più scambiati) e le notizie generali "
        "le trovi nella sezione **📰 Attualità** (barra laterale a sinistra)."
    )

    nfc1, nfc2 = st.columns([1, 2])
    filtra_g = nfc1.checkbox("📅 Filtra per giorno", value=False, key="ticker_news_filter")
    giorno_t = None
    if filtra_g:
        giorno_t = nfc2.date_input("Giorno", value=datetime.date.today(),
                                   max_value=datetime.date.today(), key="ticker_news_day")
        st.caption("ℹ️ Le fonti gratuite coprono solo gli **ultimi giorni**: date più lontane potrebbero non avere risultati.")

    def show_news(source_ticker):
        news = fu.get_news(source_ticker, count=20 if giorno_t else 10,
                           day=giorno_t.isoformat() if giorno_t else None)
        if not news:
            st.caption("Nessuna notizia per il giorno scelto." if giorno_t
                       else "Nessuna notizia disponibile per questo titolo.")
            return
        for n in news:
            title = n["title"]
            brief = fu.summarize_text(n["summary"], max_sentences=2)
            if translate_news:
                title = fu.translate_text(title)
                brief = fu.translate_text(brief)
            url = n["url"]
            meta = " · ".join([x for x in (n["publisher"], n["date"]) if x])
            if url:
                st.markdown(f"**[{title}]({url})**")
            else:
                st.markdown(f"**{title}**")
            if meta:
                st.caption(meta)
            if brief:
                st.markdown(f"📝 **In breve:** {brief}")
            else:
                st.caption("Riassunto non disponibile — apri l'articolo per i dettagli.")
            st.markdown("<hr style='margin:4px 0;border:none;border-top:1px solid rgba(255,255,255,0.12)'>", unsafe_allow_html=True)

    show_news(ticker)

st.markdown("---")
st.caption(
    "Dati: Yahoo Finance via yfinance · App a scopo informativo/didattico. "
    "Le decisioni di investimento comportano rischi: nessuna parte di questa app costituisce consulenza finanziaria."
)
