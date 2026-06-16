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

st.set_page_config(page_title="Analisi Finanziaria", page_icon="📈", layout="wide")


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
        if hmac.compare_digest(str(st.session_state.get("pwd_in", "")), str(pwd)):
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

# ---------------------------------------------------------------------------
# STILE GIUDIZI
# ---------------------------------------------------------------------------
COLORS = {"positivo": "#1a7f37", "negativo": "#cf222e", "neutro": "#9a6700", None: "#57606a"}
ICONS = {"positivo": "🟢", "negativo": "🔴", "neutro": "🟡", None: "⚪"}


def badge(label, value, judgement, help_text=""):
    color = COLORS.get(judgement, "#57606a")
    icon = ICONS.get(judgement, "⚪")
    info_icon = ""
    if help_text:
        safe = help_text.replace('"', "&quot;")
        info_icon = (
            f" <span title=\"{safe}\" "
            f"style='cursor:help;color:#0969da;font-size:0.85em'>&#9432;</span>"
        )
    st.markdown(
        f"<div style='padding:6px 0;border-bottom:1px solid #eee;'>"
        f"{icon} <b>{label}</b>{info_icon}: "
        f"<span style='color:{color};font-weight:600'>{value}</span></div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------------------------
st.sidebar.title("📈 Analisi Finanziaria")

# --- Sezione principale ---
section = st.sidebar.radio(
    "Sezione", ["📊 Analisi di un titolo", "💎 Occasioni di mercato", "📰 Attualità"],
    help="«Analisi di un titolo» studia una singola azienda/ETF. «Occasioni» scansiona il mercato per cali interessanti. "
         "«Attualità» raccoglie le notizie recenti divise per azienda/ETF.",
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

st.sidebar.markdown("---")
st.sidebar.markdown(
    "**Esempi di ticker**\n\n"
    "- USA: `AAPL`, `MSFT`, `NVDA`\n"
    "- Milano: `ENI.MI`, `ISP.MI`, `STLAM.MI`\n"
    "- Indici: `^GSPC` (S&P500), `^FTSEMIB.MI`\n"
    "- ETF: `VWCE.DE`, `CSSPX.MI`"
)
st.sidebar.markdown("---")
st.sidebar.caption(
    "⚠️ Strumento di analisi a scopo informativo. **Non è consulenza finanziaria.** "
    "I dati gratuiti possono avere ritardo o essere incompleti."
)

# ===========================================================================
# SEZIONE: OCCASIONI DI MERCATO (pagina a sé, indipendente dal titolo)
# ===========================================================================
if section.startswith("💎"):
    st.title("💎 Occasioni di mercato")
    st.warning("⚠️ **Non sono previsioni né consigli.** Sono titoli/ETF in calo che mostrano segnali tipici "
               "da potenziale rimbalzo o sconto. Un calo può anche **continuare** ('coltello che cade'): "
               "usa questi spunti solo come punto di partenza per approfondire.")
    st.caption("Parto dalle classifiche di mercato (USA). Puoi aggiungere ticker tuoi (anche .MI / ETF europei) "
               "e includere la watchlist, così copre qualsiasi titolo.")

    extra_raw = st.text_area("Ticker extra da includere (separati da virgola, opzionale)",
                             value="", height=68, key="opp_extra")
    extra = [t.strip().upper() for t in extra_raw.replace(";", ",").split(",") if t.strip()]
    inc_wl = st.checkbox("Includi la mia watchlist", value=bool(watchlist), key="opp_wl")

    bcol, rcol = st.columns([1, 1])
    if bcol.button("🔎 Cerca occasioni", type="primary", key="opp_scan"):
        st.session_state["opp_done"] = True
    refresh_choice = rcol.selectbox(
        "🔄 Aggiornamento automatico", ["Disattivato", "Ogni 15 minuti", "Ogni 30 minuti"],
        index=1, key="opp_refresh_int",
        help="Riesegue la scansione da solo, in autonomia. I dati si rinnovano davvero ~ogni 15 minuti "
             "(le occasioni si basano su indicatori giornalieri e le API hanno limiti).")

    if st.session_state.get("opp_done"):
        if refresh_choice != "Disattivato":
            st_autorefresh(interval=(900000 if "15" in refresh_choice else 1800000), key="opp_auto")
            st.caption(f"🔄 Aggiornamento automatico **attivo** ({refresh_choice.lower()}) · "
                       f"ultimo aggiornamento: {datetime.datetime.now().strftime('%H:%M')}")
        def render_opps(kind, header, help_txt, cols_cfg):
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
                        "- **Trend di fondo**: se il prezzo è sopra la media a 200 giorni il rimbalzo è più probabile; "
                        "se è «debole», molto più rischioso.\n"
                        "- **💎 Segnale**: quanto è forte il setup (più alto = più ipervenduto con trend sano).\n\n"
                        "⚠️ **Rischio:** un titolo che rimbalza dopo un calo è una *scommessa di breve*. "
                        "Cali fortissimi possono continuare (il «coltello che cade»). Spunto da approfondire, non un segnale di acquisto."
                    )
                else:
                    st.markdown(
                        "**Cosa cerchiamo:** aziende con **buoni fondamentali** (o ETF diversificati) **scese parecchio dai massimi**: "
                        "l'idea è comprare qualità «in saldo» e tenere per **anni**.\n\n"
                        "- **💎 Valore**: combina la **qualità dei conti** (punteggio fondamentale) e lo **sconto** dai massimi.\n"
                        "- **% dal max**: lo sconto rispetto al massimo dell'ultimo anno.\n"
                        "- **Perché**: i motivi sintetici (qualità + sconto + andamento).\n\n"
                        "⚠️ **Rischio:** uno sconto **non garantisce** la risalita. Chiediti sempre *perché* il titolo è sceso: "
                        "difficoltà temporanea (possibile occasione) o problema strutturale (trappola di valore)?"
                    )
            with st.spinner("Analizzo i candidati…"):
                base = fu.opportunity_candidates(kind)
                universe = list(dict.fromkeys(base + extra + (watchlist if inc_wl else [])))
                df = fu.scan_opportunities(universe, kind)
            if df.empty:
                st.info("Nessuna occasione che soddisfi i criteri in questo momento.")
                return
            st.dataframe(df, use_container_width=True,
                         height=min(60 + 38 * len(df), 460), column_config=cols_cfg)

            orizz = "~1 anno" if kind == "long" else "~1 mese"
            st.caption(f"📈 **Prob. salita** e 📉 **Rischio perdita** sono **stime statistiche** dai rendimenti storici "
                       f"(orizzonte {orizz}), **non previsioni**: indicano l'ordine di grandezza del rischio/rendimento.")

            st.markdown("##### 🔍 Approfondimenti — notizie recenti e perché")
            for tk, row in df.head(6).iterrows():
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
                    news = fu.get_news(tk, 3)
                    if news:
                        st.markdown("**Notizie recenti** (per capire cosa sta succedendo):")
                        for n in news:
                            title = fu.translate_text(n["title"]) if translate_news else n["title"]
                            link = f"[{title}]({n['url']})" if n["url"] else title
                            meta = f"  ·  _{n['date']}_" if n["date"] else ""
                            st.markdown(f"- {link}{meta}")
                            brief = fu.summarize_text(n["summary"], 1)
                            if brief:
                                if translate_news:
                                    brief = fu.translate_text(brief)
                                st.caption(brief)
                    else:
                        st.caption("Nessuna notizia recente trovata per questo titolo.")
            return

        short_cfg = {
            "Nome": st.column_config.TextColumn("Azienda", width="medium"),
            "Prezzo": st.column_config.NumberColumn("Prezzo", format="%.2f"),
            "RSI": st.column_config.NumberColumn("RSI", format="%.0f",
                help="Sotto 30-35 = ipervenduto (possibile rimbalzo)."),
            "% dal max": st.column_config.NumberColumn("% dal max", format="%.0f%%",
                help="Quanto è sceso dal massimo di 52 settimane."),
            "Perf 1 mese": st.column_config.NumberColumn("1 mese", format="%.0f%%"),
            "Occasione": st.column_config.ProgressColumn("💎 Segnale", min_value=0, max_value=100, format="%.0f",
                help="Forza del setup da rimbalzo: più alto = più ipervenduto ma con trend ancora sano."),
            "Prob. salita": st.column_config.NumberColumn("📈 Prob. salita", format="%.0f%%",
                help="Stima statistica (dai rendimenti storici, ~1 mese) della probabilità che il prezzo salga. NON è una previsione."),
            "Guadagno atteso": st.column_config.NumberColumn("🎯 Guadagno atteso", format="%+.1f%%",
                help="Stima del rendimento atteso (mediano) sull'orizzonte ~1 mese. Indicativo, non una previsione."),
            "Rischio perdita": st.column_config.NumberColumn("📉 Rischio perdita", format="%.0f%%",
                help="Stima statistica della probabilità di perdere oltre il 15% (~1 mese). NON è una previsione."),
            "Affidabilità": st.column_config.TextColumn("📊 Affidabilità",
                help="Quanto è solida la stima: dipende da volatilità e lunghezza dello storico. 🟢 Alta · 🟡 Media · 🔴 Bassa (molto volatile)."),
            "Perché": st.column_config.TextColumn("Perché", width="large"),
        }
        long_cfg = {
            "Nome": st.column_config.TextColumn("Azienda", width="medium"),
            "Prezzo": st.column_config.NumberColumn("Prezzo", format="%.2f"),
            "% dal max": st.column_config.NumberColumn("% dal max", format="%.0f%%",
                help="Sconto rispetto al massimo di 52 settimane."),
            "Perf 1 anno": st.column_config.NumberColumn("1 anno", format="%.0f%%"),
            "Occasione": st.column_config.ProgressColumn("💎 Valore", min_value=0, max_value=100, format="%.0f",
                help="Combina qualità dei fondamentali e sconto dai massimi."),
            "Prob. salita": st.column_config.NumberColumn("📈 Prob. salita", format="%.0f%%",
                help="Stima statistica (dai rendimenti storici, ~1 anno) della probabilità che il prezzo salga. NON è una previsione."),
            "Guadagno atteso": st.column_config.NumberColumn("🎯 Guadagno atteso", format="%+.1f%%",
                help="Stima del rendimento atteso (mediano) sull'orizzonte ~1 anno. Indicativo, non una previsione."),
            "Rischio perdita": st.column_config.NumberColumn("📉 Rischio perdita", format="%.0f%%",
                help="Stima statistica della probabilità di perdere oltre il 15% (~1 anno). NON è una previsione."),
            "Affidabilità": st.column_config.TextColumn("📊 Affidabilità",
                help="Quanto è solida la stima: dipende da volatilità e lunghezza dello storico. 🟢 Alta · 🟡 Media · 🔴 Bassa (molto volatile)."),
            "Perché": st.column_config.TextColumn("Perché", width="large"),
        }

        render_opps("short", "⚡ Breve periodo — rimbalzo tecnico",
                    "Titoli **ipervenduti** (RSI basso, spesso sotto la banda di Bollinger) ma con trend di fondo "
                    "ancora sano: storicamente più inclini a un rimbalzo. Orizzonte: settimane.", short_cfg)
        st.markdown("---")
        render_opps("long", "🏛️ Lungo periodo — qualità in saldo",
                    "Aziende con **buoni fondamentali** (o ETF diversificati) scese parecchio **dai massimi**: "
                    "possibile occasione di valore. Orizzonte: anni.", long_cfg)
        st.caption("👀 **Come leggere:** la barra 💎 indica la forza del segnale; la colonna **Perché** ne spiega il motivo. "
                   "Ordinate dal segnale più forte. Per approfondire un titolo, passa a «📊 Analisi di un titolo» e cercalo.")
    else:
        st.info("Premi **🔎 Cerca occasioni** per analizzare il mercato (può richiedere qualche secondo).")
    st.stop()

# ===========================================================================
# SEZIONE: ATTUALITÀ — notizie recenti divise per azienda/ETF
# ===========================================================================
if section.startswith("📰"):
    st.title("📰 Attualità — notizie dei mercati")
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
        news = fu.get_news(src, count=50 if day else n)
        if day:
            target = day.isoformat()
            news = [x for x in news if x["date"] == target][:20]
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
            st.markdown("<hr style='margin:4px 0;border:none;border-top:1px solid #eee'>", unsafe_allow_html=True)

    labels = ["🌍 Mercato generale"] + focus
    news_tabs = st.tabs(labels)
    with news_tabs[0]:
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
    st.title("📈 Analisi Finanziaria")
    st.markdown(
        "Benvenuto! Questo strumento ti aiuta a **capire un'azienda, un ETF o un indice** "
        "e a valutarne la convenienza, con spiegazioni a parole semplici.\n\n"
        "**Come iniziare:** cerca un nome nella barra a sinistra (es. *Apple*, *Eni*), "
        "oppure scegli uno dei suggerimenti qui sotto. "
        "Se è la prima volta, lascia attiva la modalità **🟢 Principiante**."
    )

    def suggestion_grid(title, items):
        st.markdown(f"#### {title}")
        cols = st.columns(len(items))
        for col, (sym, label) in zip(cols, items):
            if col.button(label, key=f"sugg_{sym}", use_container_width=True):
                st.session_state["ticker"] = sym
                st.rerun()

    suggestion_grid("🏢 Azioni famose", [
        ("AAPL", "🍎 Apple"), ("MSFT", "🪟 Microsoft"),
        ("NVDA", "🎮 Nvidia"), ("ENI.MI", "⛽ Eni"), ("ISP.MI", "🏦 Intesa SP"),
    ])
    suggestion_grid("🧺 ETF popolari", [
        ("VWCE.DE", "🌍 Vanguard All-World"), ("CSSPX.MI", "🇺🇸 S&P 500"),
        ("SWDA.MI", "🌐 MSCI World"), ("EIMI.MI", "🌏 Mercati Emergenti"),
    ])
    suggestion_grid("📊 Indici di mercato", [
        ("^GSPC", "🇺🇸 S&P 500"), ("^FTSEMIB.MI", "🇮🇹 FTSE MIB"),
        ("^IXIC", "💻 Nasdaq"), ("^STOXX50E", "🇪🇺 Euro Stoxx 50"),
    ])
    st.markdown("---")
    st.caption("⚠️ Strumento a scopo informativo. **Non è consulenza finanziaria.**")
    st.stop()

with st.spinner(f"Scarico i dati di {ticker}…"):
    hist = fu.get_history(ticker, period=period)
    info = fu.get_info(ticker)

if hist.empty:
    st.error(
        f"Nessun dato trovato per **{ticker}**. "
        "Controlla il simbolo (per Milano aggiungi `.MI`, per gli indici usa `^`)."
    )
    st.stop()

hist = fu.add_indicators(hist)
name = info.get("longName") or info.get("shortName") or ticker
currency = info.get("currency", "")
fund = fu.is_fund(info)
fdata = fu.get_fund_data(ticker) if fund else None

# ---------------------------------------------------------------------------
# INTESTAZIONE
# ---------------------------------------------------------------------------
st.title(f"{name}")
st.caption(f"Ticker: **{ticker}**  ·  {info.get('exchange', '')}  ·  Valuta: {currency}")

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
        st.plotly_chart(gauge, use_container_width=True)
    else:
        st.markdown(f"<div style='font-size:2.4em;text-align:center'>{verdict['emoji']}</div>",
                    unsafe_allow_html=True)
with vcol2:
    st.markdown(
        f"<div style='padding:14px 16px;border-radius:10px;background:{verdict['color']}14;"
        f"border-left:6px solid {verdict['color']}'>"
        f"<div style='font-size:1.25em;font-weight:700;color:{verdict['color']}'>"
        f"{verdict['emoji']} {verdict['label']}</div>"
        f"<div style='margin-top:6px;color:#444'>{verdict['line']}</div></div>",
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
     "⚖️ Confronto / Screener", "🌐 Mercati & Notizie"]
)

# ============================ PANORAMICA ===================================
with tab_over:
    st.subheader("Andamento del prezzo")

    # Selettore del periodo, direttamente sul grafico
    CHART_PERIODS = {"1 settimana": "5d", "1 mese": "1mo", "6 mesi": "6mo",
                     "1 anno": "1y", "5 anni": "5y", "Tutto": "max"}
    cp_label = st.radio("Periodo del grafico", list(CHART_PERIODS.keys()),
                        index=3, horizontal=True, key="chart_period")
    hist_c = fu.add_indicators(fu.get_history(ticker, period=CHART_PERIODS[cp_label]))

    st.caption("👀 Ogni candela è una giornata: **verde** se ha chiuso in rialzo, **rossa** se in calo. "
               "Le linee sono le medie a 50 e 200 giorni (compaiono sui periodi più lunghi): "
               "quando il prezzo sta **sopra** di esse il trend è positivo.")
    if hist_c.empty:
        st.info("Nessun dato per il periodo scelto.")
    else:
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=hist_c.index, open=hist_c["Open"], high=hist_c["High"],
            low=hist_c["Low"], close=hist_c["Close"], name="Prezzo",
        ))
        if hist_c["SMA50"].notna().any():
            fig.add_trace(go.Scatter(x=hist_c.index, y=hist_c["SMA50"], name="SMA 50", line=dict(width=1)))
        if hist_c["SMA200"].notna().any():
            fig.add_trace(go.Scatter(x=hist_c.index, y=hist_c["SMA200"], name="SMA 200", line=dict(width=1)))
        fig.update_layout(height=480, xaxis_rangeslider_visible=False, margin=dict(t=10, b=10),
                          legend=dict(orientation="h"))
        st.plotly_chart(fig, use_container_width=True)
        perf_c = (hist_c["Close"].iloc[-1] / hist_c["Close"].iloc[0] - 1) * 100
        st.caption(f"Variazione nel periodo «{cp_label}»: **{perf_c:+.1f}%**")

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
            st.plotly_chart(figa, use_container_width=True)
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
            st.plotly_chart(figs, use_container_width=True)
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
            for label, value, judgement in rows:
                badge(label, value, judgement, fu.help_for(label))
            st.write("")

    # Sintesi conteggio segnali (sempre su tutti i blocchi)
    all_rows = [r for rows in blocks.values() for r in rows]
    pos = sum(1 for _, _, j in all_rows if j == "positivo")
    neg = sum(1 for _, _, j in all_rows if j == "negativo")
    neu = sum(1 for _, _, j in all_rows if j == "neutro")
    st.markdown("---")
    st.markdown(
        f"**Bilancio dei segnali fondamentali:** "
        f"🟢 {pos} favorevoli · 🟡 {neu} neutri · 🔴 {neg} sfavorevoli"
    )
    if pos + neg + neu == 0:
        st.warning("Dati fondamentali non disponibili per questo strumento.")

    with st.expander("📖 Glossario — cosa significano questi indicatori"):
        for label, _, _ in all_rows:
            txt = fu.help_for(label)
            if txt:
                st.markdown(f"**{label}** — {txt}")

# =========================== ANALISI TECNICA ===============================
with tab_tech:
    st.subheader("Analisi tecnica")
    st.caption("Studia l'andamento di prezzo e volumi per valutare trend e momentum (utile per il timing).")

    if not expert:
        # Modalità Principiante: solo prezzo + medie mobili, con spiegazione
        st.info("👀 **Cosa guardare:** la linea blu è il prezzo. Quando sta **sopra** la media a 50 giorni "
                "(verde) il trend è positivo, quando sta **sotto** è negativo.")
        figp = go.Figure()
        figp.add_trace(go.Scatter(x=hist.index, y=hist["Close"], name="Prezzo", line=dict(color="#0969da")))
        figp.add_trace(go.Scatter(x=hist.index, y=hist["SMA50"], name="Media 50 giorni", line=dict(color="#1a7f37", width=1.4)))
        figp.add_trace(go.Scatter(x=hist.index, y=hist["SMA200"], name="Media 200 giorni", line=dict(color="#d29922", width=1.4)))
        figp.update_layout(height=420, margin=dict(t=10, b=10), legend=dict(orientation="h"))
        st.plotly_chart(figp, use_container_width=True)
    else:
        # Modalità Esperto: prezzo + Bollinger + RSI + MACD
        figp = make_subplots(
            rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04,
            row_heights=[0.55, 0.22, 0.23],
            subplot_titles=("Prezzo + Medie mobili + Bande di Bollinger", "RSI (14)", "MACD"),
        )
        figp.add_trace(go.Scatter(x=hist.index, y=hist["Close"], name="Prezzo", line=dict(color="#0969da")), row=1, col=1)
        figp.add_trace(go.Scatter(x=hist.index, y=hist["SMA20"], name="SMA 20", line=dict(width=1)), row=1, col=1)
        figp.add_trace(go.Scatter(x=hist.index, y=hist["SMA50"], name="SMA 50", line=dict(width=1)), row=1, col=1)
        figp.add_trace(go.Scatter(x=hist.index, y=hist["BB_up"], name="Bollinger sup", line=dict(width=0.5, dash="dot", color="gray")), row=1, col=1)
        figp.add_trace(go.Scatter(x=hist.index, y=hist["BB_low"], name="Bollinger inf", line=dict(width=0.5, dash="dot", color="gray"), fill="tonexty", fillcolor="rgba(150,150,150,0.08)"), row=1, col=1)
        figp.add_trace(go.Scatter(x=hist.index, y=hist["RSI"], name="RSI", line=dict(color="#8250df")), row=2, col=1)
        figp.add_hline(y=70, line=dict(color="red", width=0.7, dash="dash"), row=2, col=1)
        figp.add_hline(y=30, line=dict(color="green", width=0.7, dash="dash"), row=2, col=1)
        figp.add_trace(go.Bar(x=hist.index, y=hist["MACD_hist"], name="Istogramma", marker_color="#bbb"), row=3, col=1)
        figp.add_trace(go.Scatter(x=hist.index, y=hist["MACD"], name="MACD", line=dict(color="#0969da")), row=3, col=1)
        figp.add_trace(go.Scatter(x=hist.index, y=hist["MACD_signal"], name="Signal", line=dict(color="#cf222e")), row=3, col=1)
        figp.update_layout(height=720, margin=dict(t=30, b=10), legend=dict(orientation="h"))
        st.plotly_chart(figp, use_container_width=True)
        st.caption(
            "👀 **Come leggere i tre riquadri:** "
            "**1) Prezzo** con medie mobili e bande di Bollinger (il prezzo che tocca la banda esterna è un estremo). "
            "**2) RSI**: sopra 70 = ipercomprato (caro), sotto 30 = ipervenduto (occasione). "
            "**3) MACD**: quando la linea blu supera quella rossa il momentum è positivo, viceversa negativo."
        )

    st.markdown("#### Segnali tecnici attuali")
    signals = fu.technical_signals(hist)
    if signals:
        scols = st.columns(2)
        for i, (label, value, judgement) in enumerate(signals):
            with scols[i % 2]:
                badge(label, value, judgement, fu.help_for(label))
        pos = sum(1 for _, _, j in signals if j == "positivo")
        neg = sum(1 for _, _, j in signals if j == "negativo")
        st.markdown("---")
        st.markdown(f"**Bilancio tecnico:** 🟢 {pos} rialzisti · 🔴 {neg} ribassisti")
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
            st.warning("Nessun dato disponibile per la data scelta. Prova una data più recente.")
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
            st.plotly_chart(figv, use_container_width=True)

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
    st.warning("⚠️ **Questa NON è una previsione.** Sono scenari ipotetici costruiti dal rendimento e dalla "
               "volatilità **storici** del titolo. Il futuro può essere molto diverso: servono solo a dare "
               "un'idea degli ordini di grandezza, non a indovinare il prezzo.")

    base_hist = hsim if not hsim.empty else hist
    ann_ret_hist, vol_hist = fu.hist_return_vol(base_hist)
    if ann_ret_hist is None:
        st.info("Storico insufficiente per una proiezione.")
    else:
        default_ret = float(np.clip(ann_ret_hist * 100, -15.0, 25.0))
        pc1, pc2, pc3, pc4 = st.columns(4)
        f_initial = pc1.number_input("Capitale iniziale (€)", min_value=0.0, value=1000.0, step=100.0, key="proj_init")
        f_monthly = pc2.number_input("Versamento mensile (€)", min_value=0.0, value=0.0, step=50.0, key="proj_month",
                                     help="PAC: quanto aggiungi ogni mese. Lascia 0 per un investimento una tantum.")
        f_years = pc3.slider("Orizzonte (anni)", 1, 30, 10, key="proj_years")
        f_ret = pc4.slider("Rendimento annuo atteso (%)", -10.0, 30.0, round(default_ret, 1), 0.5, key="proj_ret",
                           help=f"Default = rendimento storico annuo ({ann_ret_hist*100:.1f}%), limitato per prudenza. "
                                "Spostalo per testare le tue ipotesi.")

        proj = fu.project_future(f_initial, f_monthly, f_years, f_ret / 100.0, vol_hist)
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
        st.plotly_chart(figf, use_container_width=True)
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
            st.warning("Alcuni ticker non sono stati caricati: " + " · ".join(errors))
        if rows:
            df_cmp = pd.DataFrame(rows).set_index("Ticker")
            df_cmp = df_cmp.sort_values("Punteggio", ascending=False, na_position="last")

            # Tabella display: percentuali in numero ×100
            disp = df_cmp.copy()
            for c in ["ROE", "Margine", "Div%", "Cresc.ricavi", "Perf.1A", "Volatilità"]:
                disp[c] = disp[c] * 100

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
                "Mostra tutte le metriche", value=expert,
                help="Disattivata mostra solo le colonne essenziali; attivala per vedere P/B, margine, debito, crescita, volatilità.",
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
            best = df_cmp.index[0]
            best_name = df_cmp.loc[best, "Nome"]
            st.success(
                f"🏆 Punteggio sintetico più alto: **{best} — {best_name}** "
                f"({df_cmp.loc[best, 'Punteggio']:.0f}/100). "
                "Il punteggio è una sintesi quantitativa indicativa, non un consiglio di acquisto."
            )

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
            st.plotly_chart(figc, use_container_width=True)

# ========================= MERCATI & NOTIZIE ==============================
with tab_news:
    st.subheader("Le aziende del momento")
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
        show_screen("most_actives", 8)

    st.markdown("---")
    st.subheader("📰 Notizie")
    col_n1, col_n2 = st.columns(2)

    def show_news(source_ticker, header):
        st.markdown(f"#### {header}")
        news = fu.get_news(source_ticker, count=6)
        if not news:
            st.caption("Nessuna notizia disponibile.")
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
            st.markdown("<hr style='margin:4px 0;border:none;border-top:1px solid #eee'>", unsafe_allow_html=True)

    with col_n1:
        show_news(ticker, f"Su {ticker}")
    with col_n2:
        show_news("^GSPC", "Mercato generale (S&P 500)")

st.markdown("---")
st.caption(
    "Dati: Yahoo Finance via yfinance · App a scopo informativo/didattico. "
    "Le decisioni di investimento comportano rischi: nessuna parte di questa app costituisce consulenza finanziaria."
)
