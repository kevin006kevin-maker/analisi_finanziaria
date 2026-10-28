"""Il lato server dell'app «Occasioni» sul telefono.

Il telefono non calcola niente e non scrive mai direttamente nei dati. Qui si fanno due cose:
  1. i RIEPILOGHI che il telefono legge, già calcolati con le stesse funzioni dell'app sul PC
     (telefono.json, telefono_mercato.json, telefono_risultati.json, telefono_attualita.json e,
     a richiesta, analisi/<TITOLO>.json). Sono file di stato: si riscrivono, non sono storia;
  2. le RICHIESTE che il telefono lascia in `richieste/` sul ramo dati (segui, smetti, soglia,
     nota, analizza). Si applicano con le funzioni del motore, quindi con le sue protezioni, e
     ognuna finisce a verbale in archivio/richieste prima di togliere il file della richiesta.
Lo usano auto_watch.py (giro completo) e il lavoro piccolo «Richieste dal telefono».
"""
import base64
import datetime
import json
import math
import os
import re

import finance_utils as fu

TELEFONO_MERCATO = "telefono_mercato.json"
TELEFONO_RISULTATI = "telefono_risultati.json"
TELEFONO_ATTUALITA = "telefono_attualita.json"
ANALISI_DIR = "analisi"
RICHIESTE_DIR = "richieste"
RICHIESTE_ESITI = "richieste_esiti.json"     # gli ultimi esiti, perché il telefono tolga «in attesa»
_RICHIESTE_ESITI_MAX = 200                   # la storia completa sta in archivio/richieste
ARC_RICHIESTE = "archivio/richieste"
_ATTUALITA_OGNI_ORE = 3                      # le notizie non servono a ogni giro
_MERCATO_MAX = 60                            # titoli per tipo nella scheda Mercato
_IMPORTO, _COMMISSIONE = 30.0, 1.0           # come nell'app (decisione dell'utente del 7/10)
_NETTO = 2.0                                 # netto desiderato di partenza nell'app, per la soglia


def _r(x, dec=1):
    """Un numero arrotondato, o None se non è un numero vero (NaN compreso)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else round(v, dec)


def _testo(x, n=400):
    s = "" if x is None else str(x)
    return s if len(s) <= n else s[: n - 1] + "…"


def _scrivi(nome, obj) -> bool:
    return bool(fu.write_data_json(nome, obj)) and nome not in fu._SALVATAGGI_FALLITI


# ---------------------------------------------------------------------------
# 1. RIEPILOGHI
# ---------------------------------------------------------------------------

def riepilogo_base() -> dict:
    """telefono.json: osservazione e monitoraggio (dal motore), più In anticipo, Portafoglio, gli
    esiti delle ultime richieste e i dati che servono alle azioni (nota, soglia)."""
    rt = fu.riepilogo_telefono()
    tracked = fu.load_tracking()
    for m in rt["monitoraggio"]:
        e = tracked.get(m["t"]) or {}
        m["nota"] = _testo(e.get("note"), 300)
        m["mia_soglia"] = _r(e.get("my_target_price"), 4)
        # la soglia che l'app sul PC propone di partenza: 30 €, 1 € a ordine, 2 € netti desiderati
        lv = fu.personal_levels(m.get("prezzo"), _IMPORTO, _COMMISSIONE, _NETTO) if m.get("prezzo") else None
        m["soglia_suggerita"] = _r((lv or {}).get("target"), 4)
    # In anticipo: le «più solide», come nell'app (spunta accesa di partenza), senza quelle già corse
    watch = fu.load_opp_watch()
    anticipo = []
    for s in fu.solid_presignals():
        w = watch.get(f"{s.get('kind')}:{s.get('ticker')}") or {}
        if fu.gia_corsa(w, s):
            continue
        anticipo.append({"t": s.get("ticker"), "nome": s.get("name") or "", "tipo": s.get("kind"),
                         "conv": _r(s.get("last_conv"), 0), "dconv": _r(s.get("dconv"), 0),
                         "giorni": s.get("days", 0), "rend": _r(s.get("ret")),
                         "salita": _r(s.get("prob_gain"), 0), "perdita": _r(s.get("prob_loss"), 0),
                         "affid": s.get("reliab") or ""})
    rt["anticipo"] = anticipo
    # Portafoglio: solo le posizioni salvate (il telefono lo nasconde se è vuoto)
    rt["portafoglio"] = [{"t": p.get("ticker"), "quante": _r(p.get("qty"), 4),
                          "prezzo_acquisto": _r(p.get("buy_price"), 4), "data": p.get("date"),
                          "importo": _r(p.get("amount_eur") or p.get("amount"), 2),
                          "orizzonte": p.get("horizon") or ""} for p in (fu.load_portfolio() or [])]
    esiti = fu.read_data_json(RICHIESTE_ESITI, [])
    rt["richieste"] = [{k: e.get(k) for k in ("id", "esito", "messaggio", "quando", "azione", "ticker")}
                       for e in (esiti if isinstance(esiti, list) else [])[-50:]]
    rt["giro"] = fu._now_iso()
    return rt


def scrivi_riepilogo_base() -> dict:
    rt = riepilogo_base()
    ok = _scrivi(fu.TELEFONO_NAME, rt)
    return {"osservazione": len(rt["osservazione"]), "monitoraggio": len(rt["monitoraggio"]),
            "anticipo": len(rt["anticipo"]), "salvato": ok}


def riepilogo_mercato(scansioni: dict) -> dict:
    """telefono_mercato.json: la scansione dell'ultimo giro, i migliori per convenienza.
    `scansioni` = {"short": DataFrame, "long": DataFrame} come le produce scan_opportunities."""
    tracked = fu.load_tracking()
    watch = fu.load_opp_watch()
    out = {"aggiornato": fu._now_iso()}
    for kind in ("short", "long"):
        df = scansioni.get(kind)
        righe = []
        if df is not None and not df.empty:
            perf = "Perf 1 mese" if kind == "short" else "Perf 1 anno"
            for tk, rr in df.head(_MERCATO_MAX).iterrows():
                stato = ("seguita" if tk in tracked else
                         "in osservazione" if f"{kind}:{tk}" in watch else "")
                righe.append({"t": tk, "nome": _testo(rr.get("Nome"), 60), "conv": _r(rr.get("Convenienza"), 0),
                              "prezzo": _r(rr.get("Prezzo"), 4), "dal_max": _r(rr.get("% dal max")),
                              "perf": _r(rr.get(perf)), "salita": _r(rr.get("Prob. salita"), 0),
                              "perdita": _r(rr.get("Rischio perdita"), 0),
                              "affid": str(rr.get("Affidabilità") or ""),
                              "settore": str(rr.get("Settore") or "") if kind == "long" else "",
                              "perche": _testo(rr.get("Perché"), 220), "stato": stato})
        out[kind] = righe
    return out


def _celle(celle: dict) -> dict:
    return {v: {"n": c.get("n", 0), "med": _r(c.get("med"), 2), "hit": _r(c.get("hit"), 0),
                "netto": _r(c.get("netto_medio"), 2)} for v, c in (celle or {}).items()}


def riepilogo_risultati() -> dict:
    """telefono_risultati.json: Metodi, Scenari, Archivio e Diario in forma di riepilogo.
    I dettagli (calendari, distribuzioni, singola occasione) restano nell'app sul PC."""
    out = {"aggiornato": fu._now_iso(), "metodi": {}, "scenari": {}, "archivio": {}, "diario": {}}
    nomi = {m["chiave"]: m for m in fu.metodi_info()}
    for kind in ("short", "long"):
        # METODI: le due tabelle (tutti i giorni e prova vera) e il verdetto di ognuno
        try:
            conti = fu.conti_metodi(kind)
            tab = {}
            for periodo in ("prova", "tutto"):
                tab[periodo] = [{"chiave": r["chiave"], "nome": r["nome"], "riferimento": bool(r.get("riferimento")),
                                 "scelte": r.get("scelte", 0),
                                 "vendite": {v: {"n": s.get("n", 0), "med": _r(s.get("med"), 2),
                                                 "hit": _r(s.get("hit"), 0), "eccesso": _r(s.get("eccesso"), 2)}
                                             for v, s in (r.get("vendite") or {}).items()}}
                                for r in fu.riepilogo_metodi(conti, _IMPORTO, _COMMISSIONE, periodo)]
            verdetti = {}
            for k, m in nomi.items():
                if m.get("riferimento"):
                    continue
                v = fu.verdetto_metodo(conti, k)
                verdetti[k] = {"stato": v.get("stato"), "testo": _testo(v.get("testo"), 300)}
            out["metodi"][kind] = {"vendite": list(fu.METODI_VENDITE[kind]), "tabelle": tab,
                                   "verdetti": verdetti, "aggiornato": conti.get("aggiornato"),
                                   "decide": dict(fu._METODI_DECIDE)}
        except Exception as e:
            out["metodi"][kind] = {"errore": type(e).__name__}
        # SCENARI: i cinque momenti d'acquisto con le tre regole di vendita, senza filtri
        try:
            sc = fu.scenari_diario(kind, importo=_IMPORTO, fee=_COMMISSIONE)
            imb = fu.imbuto_occasioni(kind)
            out["scenari"][kind] = {
                "vendite": list(sc.get("vendite") or []),
                "etichette": {v: fu.SCENARIO_ETICHETTE.get(v, v) for v in (sc.get("vendite") or [])},
                "momenti": [{"chiave": s.get("chiave"), "nome": s.get("nome"), "quante": s.get("n_passano", 0),
                             "celle": _celle(s.get("celle"))} for s in sc.get("scenari", [])],
                "imbuto": [{"nome": t.get("nome"), "quante": t.get("quante"), "passa": _r(t.get("passa_pct"), 0)}
                           for t in (imb.get("tappe") or [])]}
        except Exception as e:
            out["scenari"][kind] = {"errore": type(e).__name__}
        # ARCHIVIO: cosa se ne impara, a 30 giorni, le prime caratteristiche della classifica
        try:
            sp = fu.sintesi_pronta(kind, "30g")
            car = []
            for campo, c in list((sp.get("caratteristiche") or {}).items())[:8]:
                car.append({"nome": fu.nome_caratteristica(campo), "gruppo": c.get("gruppo"),
                            "guadagna": c.get("chi_guadagna"), "perde": c.get("chi_perde"),
                            "concordi": _r(c.get("giornate_concordi_pct"), 0),
                            "conferma": c.get("conferma"), "solidita": c.get("solidita")})
            out["archivio"][kind] = {"chiuse": sp.get("chiuse"), "aperte": sp.get("aperte"),
                                     "giornate": sp.get("giornate_totali"),
                                     "caratteristiche": car, "avvertenza": _testo(sp.get("avvertenza"), 400),
                                     "calcolata_il": sp.get("calcolata_il") or sp.get("aggiornato")}
        except Exception as e:
            out["archivio"][kind] = {"errore": type(e).__name__}
    try:
        st = fu.stato_archivio()
        out["archivio"]["righe"] = {a: v.get("righe") for a, v in (st.get("aree") or {}).items()}
    except Exception:
        pass
    # DIARIO: i numeri e gli ultimi eventi
    try:
        out["diario"]["riepilogo"] = fu.diario_riepilogo()
        ev = [r for r in fu.load_diario() if isinstance(r, dict)]
        ev.sort(key=lambda r: str(r.get("scritto_il") or r.get("data") or ""))
        out["diario"]["ultimi"] = [{"t": r.get("ticker"), "tipo": r.get("kind"), "evento": r.get("evento"),
                                    "data": r.get("data"), "prezzo": _r(r.get("prezzo"), 4),
                                    "conv": _r(r.get("conv"), 0)} for r in ev[-40:]][::-1]
    except Exception as e:
        out["diario"] = {"errore": type(e).__name__}
    return out


def _notizie(ticker, n):
    out = []
    for a in fu.get_news(ticker, n) or []:
        titolo = fu.translate_text(a.get("title") or "")
        breve = fu.summarize_text(a.get("summary") or "", 2)
        out.append({"titolo": _testo(titolo, 200), "breve": _testo(fu.translate_text(breve) if breve else "", 400),
                    "fonte": a.get("publisher") or "", "data": a.get("date") or "", "url": a.get("url") or ""})
    return out


def riepilogo_attualita() -> dict:
    """telefono_attualita.json: notizie del mercato e classifiche del giorno."""
    out = {"aggiornato": fu._now_iso(), "notizie": [], "classifiche": {}}
    try:
        out["notizie"] = _notizie("^GSPC", 10)
    except Exception:
        pass
    for nome in ("day_gainers", "day_losers", "most_actives"):
        try:
            df = fu.get_screen(nome, 12)
            out["classifiche"][nome] = [] if df is None or df.empty else [
                {"t": str(r.get("Ticker")), "nome": _testo(r.get("Nome"), 50), "prezzo": _r(r.get("Prezzo"), 4),
                 "var": _r(r.get("Var %"), 2)} for _, r in df.head(12).iterrows()]
        except Exception:
            out["classifiche"][nome] = []
    return out


def _ore_da(quando) -> float:
    try:
        t = datetime.datetime.strptime(str(quando)[:16], "%Y-%m-%d %H:%M")
        ora = datetime.datetime.strptime(fu._now_iso()[:16], "%Y-%m-%d %H:%M")
        return (ora - t).total_seconds() / 3600
    except Exception:
        return 1e9


def scrivi_riepiloghi_completi(scansioni: dict) -> dict:
    """Tutti i riepiloghi, a fine giro del lavoro automatico. Ognuno per conto suo: se uno non riesce
    gli altri si scrivono lo stesso."""
    esito = {}
    for nome, fare in ((TELEFONO_MERCATO, lambda: riepilogo_mercato(scansioni)),
                       (TELEFONO_RISULTATI, riepilogo_risultati)):
        try:
            esito[nome] = _scrivi(nome, fare())
        except Exception as e:
            esito[nome] = f"errore {type(e).__name__}"
    try:
        vecchio = fu.read_data_json(TELEFONO_ATTUALITA, {}) or {}
        if _ore_da(vecchio.get("aggiornato")) >= _ATTUALITA_OGNI_ORE:
            esito[TELEFONO_ATTUALITA] = _scrivi(TELEFONO_ATTUALITA, riepilogo_attualita())
        else:
            esito[TELEFONO_ATTUALITA] = "ancora fresco"
    except Exception as e:
        esito[TELEFONO_ATTUALITA] = f"errore {type(e).__name__}"
    return esito


# ---------------------------------------------------------------------------
# 2. ANALISI DI UN TITOLO, A RICHIESTA
# ---------------------------------------------------------------------------

def nome_analisi(ticker: str) -> str:
    sicuro = re.sub(r"[^A-Za-z0-9._^=-]", "_", str(ticker).upper())
    return f"{ANALISI_DIR}/{sicuro}.json"


def analisi_titolo(ticker: str) -> dict:
    """La scheda di un titolo per il telefono: le stesse funzioni delle schede Panoramica,
    Fondamentale, Tecnica e Notizie dell'app sul PC, sul periodo di 1 anno."""
    tk = str(ticker).strip().upper()
    hist = fu.get_history(tk, period="1y")
    if hist is None or hist.empty:
        return {"t": tk, "aggiornato": fu._now_iso(), "errore": "nessun dato di prezzo per questo titolo"}
    hist = fu.add_indicators(hist)
    info = fu.get_info(tk, merge=True) or {}
    fondo = bool(fu.is_fund(info) or fu.is_known_etf(tk))
    fdata = fu.get_fund_data(tk, info) if fondo else None
    close = hist["Close"].dropna()
    prezzo = float(close.iloc[-1])

    def perf(giorni):
        return _r((prezzo / float(close.iloc[-giorni - 1]) - 1) * 100) if len(close) > giorni else None

    # il grafico: un punto ogni 2 giorni di Borsa basta per un anno su un telefono
    passo = max(1, len(close) // 130)
    serie = [[str(i.date()) if hasattr(i, "date") else str(i)[:10], _r(v, 4)] for i, v in close.iloc[::passo].items()]
    if serie and serie[-1][0] != str(close.index[-1])[:10]:
        serie.append([str(close.index[-1])[:10], _r(prezzo, 4)])
    medie = {}
    for col in ("SMA50", "SMA200"):
        if col in hist:
            s = hist[col].iloc[::passo]
            medie[col] = [_r(v, 4) for v in s.values]
    verd = fu.overall_verdict(info, hist, fund=fondo, fdata=fdata) or {}
    try:
        commento = (fu.fund_commentary(tk, fdata, info, hist, "1 anno") if fondo
                    else fu.generate_commentary(tk, info, hist, "1 anno"))
    except Exception:
        commento = ""
    out = {"t": tk, "aggiornato": fu._now_iso(), "nome": info.get("longName") or info.get("shortName") or tk,
           "valuta": info.get("currency") or "", "etf": fondo, "prezzo": _r(prezzo, 4),
           "perf": {"1 mese": perf(21), "6 mesi": perf(126), "1 anno": perf(len(close) - 1)},
           "serie": serie, "medie": medie,
           "giudizio": {"voto": _r(verd.get("score"), 0), "emoji": verd.get("emoji"), "etichetta": verd.get("label"),
                        "riga": _testo(verd.get("line"), 300)},
           "commento": _testo(commento, 2500),
           "panoramica": {k: str(v) for k, v in (fu.overview_metrics(info, hist) or {}).items()}}
    if fondo and fdata:
        out["etf_dati"] = {"costo": fdata.get("expense_ratio"), "patrimonio": fdata.get("total_assets"),
                           "categoria": fdata.get("category"), "famiglia": fdata.get("family"),
                           "principali": [[h[0], h[1], _r((h[2] or 0) * 100, 2)] for h in (fdata.get("top_holdings") or [])[:10]],
                           "settori": {k: _r((v or 0) * 100, 1) for k, v in (fdata.get("sector_weightings") or {}).items()}}
    else:
        out["fondamentale"] = {blocco: [[v[0], v[1], v[2] if len(v) > 2 else None] for v in voci]
                               for blocco, voci in (fu.fundamental_blocks(info) or {}).items()}
    ts = fu.technical_summary(hist) or {}
    out["tecnica"] = {"sintesi": {"emoji": ts.get("emoji"), "etichetta": ts.get("label"), "riga": _testo(ts.get("line"), 300)},
                      "segnali": [[s[0], s[1], s[2] if len(s) > 2 else None] for s in (fu.technical_signals(hist) or [])],
                      "rsi": _r(hist["RSI"].iloc[-1], 1) if "RSI" in hist else None}
    try:
        out["notizie"] = _notizie(tk, 8)
    except Exception:
        out["notizie"] = []
    return out


# ---------------------------------------------------------------------------
# 3. RICHIESTE DAL TELEFONO
# ---------------------------------------------------------------------------

def _gh():
    repo, token, branch = fu._data_repo(), fu._github_token(), fu._data_branch()
    if not (repo and token):
        return None
    return repo, branch, {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def richieste_in_attesa() -> list:
    """Le richieste lasciate dal telefono: [(percorso, sha, richiesta)], in ordine di arrivo.
    Lista vuota se non ce ne sono o se il ramo non risponde: si riprova al giro dopo."""
    g = _gh()
    if not g:
        return []
    repo, branch, h = g
    import requests
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}/contents/{RICHIESTE_DIR}?ref={branch}",
                         headers=h, timeout=15)
    except Exception:
        return []
    if r.status_code != 200:
        return []            # 404 = cartella non ancora creata: niente da fare
    out = []
    for f in sorted(r.json() or [], key=lambda x: x.get("name", "")):
        if f.get("type") != "file" or not str(f.get("name", "")).endswith(".json"):
            continue
        try:
            c = requests.get(f"https://api.github.com/repos/{repo}/contents/{f['path']}?ref={branch}",
                             headers=h, timeout=15)
            if c.status_code != 200:
                continue
            j = c.json()
            req = json.loads(base64.b64decode("".join(j.get("content", "").split())).decode("utf-8"))
            if isinstance(req, dict):
                out.append((f["path"], j.get("sha") or f.get("sha"), req))
        except Exception:
            continue
    return out


def _togli_richiesta(percorso: str, sha: str) -> bool:
    """Toglie il file di una richiesta GIÀ messa a verbale in archivio/richieste (è uno
    spostamento, non una cancellazione: il contenuto resta nell'archivio)."""
    g = _gh()
    if not (g and sha):
        return False
    repo, branch, h = g
    import requests
    try:
        r = requests.delete(f"https://api.github.com/repos/{repo}/contents/{percorso}", headers=h, timeout=15,
                            json={"message": f"richiesta applicata {os.path.basename(percorso)}",
                                  "sha": sha, "branch": branch})
        return r.status_code == 200
    except Exception:
        return False


def _ticker(req) -> str:
    return str(req.get("ticker") or "").strip().upper()


def applica_una(req: dict):
    """Applica una richiesta con le funzioni del motore. Ritorna (fatto, messaggio)."""
    azione, tk = str(req.get("azione") or ""), _ticker(req)
    if not tk or not re.fullmatch(r"[A-Z0-9._^=-]{1,20}", tk):
        return False, "titolo non valido"
    tracked = fu.load_tracking()
    if azione == "segui":
        kind = "long" if req.get("kind") == "long" else "short"
        if tk in tracked:
            return True, f"{tk} era già nel Monitoraggio"
        fu.track_opportunity(tk, kind, note="📱 Aggiunta dal telefono il " + fu._today_iso())
        return (tk in fu.load_tracking()), f"{tk} aggiunta al Monitoraggio"
    if azione == "smetti":
        if tk not in tracked:
            return True, f"{tk} non era più nel Monitoraggio"
        fu.untrack_opportunity(tk)
        return (tk not in fu.load_tracking()), f"{tk} tolta dal Monitoraggio (resta nello storico delle uscite)"
    if azione == "soglia":
        if tk not in tracked:
            return False, f"{tk} non è nel Monitoraggio: la soglia non si può salvare"
        prezzo = req.get("prezzo")
        prezzo = _r(prezzo, 4) if prezzo not in (None, "") else None
        if prezzo is not None and prezzo <= 0:
            return False, "la soglia deve essere un prezzo maggiore di zero"
        fu.set_my_target(tk, prezzo)
        return True, (f"soglia di {tk} salvata a {prezzo:,.2f}" if prezzo else f"soglia di {tk} tolta")
    if azione == "nota":
        if tk not in tracked:
            return False, f"{tk} non è nel Monitoraggio: la nota non si può salvare"
        fu.set_tracking_note(tk, _testo(req.get("testo"), 1000))
        return True, f"nota di {tk} salvata"
    if azione == "analizza":
        a = analisi_titolo(tk)
        ok = _scrivi(nome_analisi(tk), a)
        if a.get("errore"):
            return False, f"{tk}: {a['errore']}"
        return ok, (f"analisi di {tk} pronta" if ok else f"analisi di {tk} calcolata ma non salvata")
    return False, f"azione sconosciuta: {azione}"


def applica_richieste(log=print) -> list:
    """Applica tutte le richieste in attesa. Ogni esito va prima in archivio/richieste (storia) e
    in richieste_esiti.json (per il telefono); solo dopo si toglie il file della richiesta. Una
    richiesta già applicata (il suo id è fra gli esiti) non si riapplica: si toglie e basta."""
    attesa = richieste_in_attesa()
    if not attesa:
        return []
    # Se la lettura degli esiti fallisse, il peggio è riapplicare una richiesta già fatta: tutte le
    # azioni danno lo stesso risultato se ripetute, e la storia vera sta in archivio/richieste.
    esiti = fu.read_data_json(RICHIESTE_ESITI, [])
    esiti = esiti if isinstance(esiti, list) else []
    fatti = {e.get("id") for e in esiti if isinstance(e, dict)}
    nuovi, da_togliere, gia_fatte = [], [], []
    for percorso, sha, req in attesa:
        rid = str(req.get("id") or os.path.basename(percorso)[:-5])
        if rid in fatti:
            gia_fatte.append((percorso, sha))       # già a verbale in un giro precedente
            continue
        try:
            ok, msg = applica_una(req)
        except Exception as e:
            ok, msg = False, f"non riuscita ({type(e).__name__})"
        log(f"Richiesta dal telefono {rid}: {req.get('azione')} {_ticker(req)} → {msg}")
        nuovi.append({"id": rid, "date": fu._today_iso(), "quando": fu._now_iso(),
                      "azione": req.get("azione"), "ticker": _ticker(req),
                      "esito": "fatto" if ok else "non fatto", "messaggio": msg,
                      "richiesta": {k: req.get(k) for k in ("quando", "azione", "ticker", "kind", "prezzo", "testo")}})
        da_togliere.append((percorso, sha))
    if nuovi:
        # PRIMA il verbale in archivio, POI gli esiti, e solo alla fine si tolgono i file. Se il
        # verbale non si salva non si scrive nemmeno l'esito: al giro dopo la richiesta si
        # riapplica (tutte le azioni danno lo stesso risultato se ripetute) e niente va perso.
        arc = fu._arc_aggiungi(ARC_RICHIESTE, nuovi, chiave=lambda r: r.get("id"))
        if not arc.get("salvate"):
            log(f"Richieste: verbale in archivio non salvato ({arc.get('motivo')}): restano in attesa")
            da_togliere = []
        elif not _scrivi(RICHIESTE_ESITI, (esiti + nuovi)[-_RICHIESTE_ESITI_MAX:]):
            log("Richieste: esiti non salvati: restano in attesa")
            da_togliere = []
    da_togliere += gia_fatte
    tolte = sum(1 for p, s in da_togliere if _togli_richiesta(p, s))
    if da_togliere:
        log(f"Richieste: {tolte} file su {len(da_togliere)} spostati nell'archivio")
    return nuovi
