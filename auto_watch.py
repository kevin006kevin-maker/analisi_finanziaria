"""
auto_watch.py — motore autonomo delle occasioni.

Pensato per girare su GitHub Actions ogni ~15 minuti (anche a PC spento):
1. scansiona le occasioni di mercato (breve e lungo periodo);
2. registra l'evoluzione della convenienza di ciascuna (1 osservazione/giorno);
3. promuove al monitoraggio quelle in salita da 3 giorni consecutivi.

I dati precedenti vengono letti dal branch remoto (raw URL) e quelli aggiornati
salvati sia su file locale sia DIRETTAMENTE sul branch dei dati via API GitHub
(come fa l'app). L'app legge da lì, così funziona ovunque, anche da telefono.

Chiavi/config da variabili d'ambiente:
  FMP_API_KEY, FINNHUB_API_KEY  → dati di mercato
  DATA_REPO = "utente/repo"     → branch remoto da cui leggere/scrivere i dati
  DATA_BRANCH = "auto-data"     → branch dei dati (default auto-data)
  GITHUB_TOKEN                  → token (contents:write) per salvare i dati via API.
NB: la persistenza la fa lo SCRIPT via API (non più il git-push del workflow): così le
    promozioni vengono salvate subito e non si ripetono a ogni giro (niente notifiche doppie).
"""

import os
import sys
import html
import datetime

import finance_utils as fu


def log(msg):
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}Z] {msg}", flush=True)


def notify_promotions(tickers):
    """Notifica quando una o più occasioni vengono INSERITE nel Monitoraggio (promozione automatica)."""
    tr = fu.load_tracking()
    righe = ["🆕 <b>Nuove occasioni nel Monitoraggio</b>", ""]
    for tk in tickers:
        e = tr.get(tk, {})
        nm = html.escape(str(e.get("name") or tk))
        term = "breve termine" if e.get("kind") == "short" else "lungo termine"
        snaps = e.get("snapshots", [])
        price = snaps[-1].get("price") if snaps else None
        extra = f" · prezzo {price:,.2f}" if price else ""
        righe.append(f"📌 <b>{html.escape(str(tk))}</b> — {nm} ({term}){extra}")
    righe += ["", "Inserite in automatico dopo la fase di osservazione. Apri l'app → Monitoraggio.",
              "(Strumento informativo, non è un consiglio.)"]
    ok = fu.send_telegram("\n".join(righe))
    log("Notifica inserimento inviata." if ok
        else "Notifica inserimento NON inviata (Telegram non configurato o errore).")


def notify_monitoring(items):
    """Prima notifica per le occasioni che confermano l'andamento positivo nel monitoraggio
    (breve: dopo 3 giorni positivi · lungo: dopo 7 giorni positivi)."""
    righe = ["📈 <b>Occasioni confermate</b>",
             "(andamento positivo dopo la fase di monitoraggio)", ""]
    for it in items:
        tk = html.escape(str(it.get("ticker")))
        nm = html.escape(str(it.get("name") or tk))
        term = "breve termine" if it.get("kind") == "short" else "lungo termine"
        righe.append(f"🔔 <b>{tk}</b> — {nm}")
        righe.append(f"   {term} · +{it.get('ret', 0):.1f}% in {it.get('days', 0)} giorni di monitoraggio")
    righe += ["", "Possibile opportunità di investimento — apri l'app → Monitoraggio.",
              "(Strumento informativo, non è un consiglio.)"]
    ok = fu.send_telegram("\n".join(righe))
    log("Notifica opportunità inviata." if ok
        else "Notifica opportunità NON inviata (Telegram non configurato o errore).")


def notify_exit(items):
    """Notifica quando la TESI di un'occasione monitorata è esaurita (avviso di uscita, NON un ordine)."""
    righe = ["🚪 <b>Tesi esaurita — valuta l'uscita</b>", ""]
    for it in items:
        tk = html.escape(str(it.get("ticker")))
        nm = html.escape(str(it.get("name") or tk))
        righe.append(f"🔔 <b>{tk}</b> — {nm}")
        for motivo in it.get("reasons", []):
            righe.append("• " + html.escape(str(motivo)))
        righe.append("")
    righe.append("Apri l'app → Monitoraggio. (Strumento informativo, non è un consiglio di vendita.)")
    ok = fu.send_telegram("\n".join(righe))
    log("Notifica uscita inviata." if ok
        else "Notifica uscita NON inviata (Telegram non configurato o errore).")


def notify_my_target(items):
    """Notifica quando un'occasione seguita raggiunge la SOGLIA PERSONALE impostata dall'utente
    (il prezzo che copre commissioni + guadagno netto desiderato)."""
    righe = ["🎯 <b>Soglia personale raggiunta</b>", ""]
    for it in items:
        tk = html.escape(str(it.get("ticker")))
        nm = html.escape(str(it.get("name") or tk))
        righe.append(f"🔔 <b>{tk}</b> — {nm}")
        righe.append(f"• prezzo <b>{it.get('price'):,.2f}</b> ≥ la tua soglia <b>{it.get('target'):,.2f}</b>")
        righe.append("• commissioni e guadagno netto desiderato coperti: valuta l'incasso")
        righe.append("")
    righe.append("Apri l'app → Monitoraggio. (Strumento informativo, non è un consiglio di vendita.)")
    ok = fu.send_telegram("\n".join(righe))
    log("Notifica soglia personale inviata." if ok
        else "Notifica soglia personale NON inviata (Telegram non configurato o errore).")


def notify_profit(items):
    """Notifica quando un'occasione seguita ha già dato quello che doveva dare: bersaglio raggiunto,
    soglia personale raggiunta, oppure guadagno che si sta sgonfiando dal massimo. È l'unico avviso
    sul lato GUADAGNO: prima il sistema sapeva segnalare solo le perdite."""
    righe = ["💰 <b>Da valutare per l'incasso</b>", ""]
    for it in items:
        tk = html.escape(str(it.get("ticker")))
        nm = html.escape(str(it.get("name") or tk))
        righe.append(f"🔔 <b>{tk}</b> — {nm}")
        righe.append("• " + html.escape(str(it.get("motivo"))))
        if it.get("max") is not None and it.get("giu_dal_max") is not None:
            righe.append(f"• guadagno ora <b>{it.get('gain'):+.1f}%</b> · massimo toccato "
                         f"{it.get('max'):,.2f} ({it.get('giu_dal_max'):+.1f}% da lì)")
        righe.append("")
    righe.append("Apri l'app → Monitoraggio → «Da incassare». "
                 "(Strumento informativo, non è un consiglio di vendita.)")
    ok = fu.send_telegram("\n".join(righe))
    log("Notifica incasso inviata." if ok
        else "Notifica incasso NON inviata (Telegram non configurato o errore).")


def notify_sales(fired):
    """Notifica Telegram quando conviene valutare la vendita di un titolo del portafoglio."""
    righe = ["💰 <b>Consiglio di vendita</b>", ""]
    for f in fired:
        p, adv = f["position"], f["advice"]
        tk = html.escape(str(p.get("ticker")))
        gp = f" — guadagno {adv['gain_pct']:+.1f}%" if adv.get("gain_pct") is not None else ""
        righe.append(f"🔔 <b>{tk}</b>{gp}")
        for motivo in adv.get("reasons", []):
            righe.append("• " + html.escape(motivo))
        righe.append("")
    righe.append("Apri l'app → 💰 Portafoglio per i dettagli. (Non è un consiglio di investimento.)")
    ok = fu.send_telegram("\n".join(righe))
    log("Notifica di vendita inviata." if ok
        else "Notifica di vendita NON inviata (Telegram non configurato o errore).")


def main():
    if not (fu._fmp_key() or fu._finnhub_key()):
        log("ATTENZIONE: nessuna chiave API (FMP/Finnhub) impostata. I dati potrebbero essere assenti.")

    # Persistenza: i dati si salvano sul branch via API GitHub. Senza repo+token NON si salva nulla
    # (le promozioni verrebbero notificate ma non memorizzate → notifiche duplicate). Lo segnaliamo.
    if not os.environ.get("TEST_NOTIFICA") == "true":
        repo_ok, token_ok = bool(fu._data_repo()), bool(fu._github_token())
        log(f"Persistenza cloud → repo: {'SI' if repo_ok else 'NO'} · token: {'SI' if token_ok else 'NO'}"
            + ("" if (repo_ok and token_ok) else "  ⚠️ DATI NON SALVATI: controlla DATA_REPO/GITHUB_TOKEN nel workflow."))

    # Percorso di prova: avvio manuale con "test_notifica" → manda solo un messaggio di verifica
    if os.environ.get("TEST_NOTIFICA") == "true":
        tok, cid = fu._telegram_cfg()
        log(f"Diagnostica notifiche → token impostato: {'SI' if tok else 'NO'} · "
            f"chat_id impostato: {'SI' if cid else 'NO'}"
            + (f" (chat_id di {len(str(cid))} cifre)" if cid else ""))
        ok, dettaglio = fu.send_telegram_verbose(
            "✅ Notifica di prova dal sistema Occasioni.\n"
            "Se leggi questo messaggio, le notifiche funzionano correttamente!")
        log(f"Risposta Telegram: {dettaglio}")
        log("Test notifica: " + ("inviata ✓" if ok else "NON inviata"))
        return 0

    total = 0
    for kind in ("short", "long"):
        try:
            # Universo COMPLETO della sezione Occasioni (standard + EU/ETF + extra/watchlist
            # dell'utente, dalla config salvata dall'app): osserva TUTTE le occasioni della sezione.
            universe = fu.opportunity_universe(kind)
            df = fu.scan_opportunities(universe, kind)
            n = 0 if df is None or df.empty else len(df)
            total += n
            fu.record_observations(df, kind)
            # Sticky: per i titoli già in osservazione (finestra aperta) non più tra le occasioni di
            # oggi, registra comunque il prezzo → i giorni avanzano e la promozione resta possibile.
            try:
                fu.record_sticky_observations(kind, df)
            except Exception as e:
                log(f"{kind}: errore record_sticky: {e!r}")
            # Calibrazione: registra la P(salita) di ogni occasione (1/giorno) per il backtest
            if df is not None and not df.empty:
                horizon = 21 if kind == "short" else 252
                for tk_f, rr in df.iterrows():
                    try:
                        fu.log_forecast(tk_f, horizon, rr.get("Prob. salita"), rr.get("Prezzo"))
                    except Exception:
                        pass
            log(f"{kind}: {n} occasioni scansionate e registrate.")
        except Exception as e:
            log(f"{kind}: errore durante la scansione: {e!r}")

    # FASE 1 — promozione: occasioni con osservazione positiva (breve 3g / lungo 7g) → notifica inserimento
    try:
        promoted = fu.auto_promote_opportunities()
        if promoted:
            log(f"PROMOSSE al Monitoraggio (osservazione positiva): {', '.join(promoted)}")
            notify_promotions(promoted)
        else:
            log("Nessuna nuova promozione in questo giro.")
    except Exception as e:
        log(f"Errore durante la promozione automatica: {e!r}")

    # PREZZI FRESCHI PRIMA DI DECIDERE. Questo passaggio stava DOPO le decisioni di uscita, quindi
    # ogni rimozione veniva decisa sul prezzo del giro precedente (mezz'ora prima) e il ritardo si
    # sommava ai giorni di conferma: è la ragione per cui un titolo è uscito il 10,6% sotto il
    # proprio stop invece che sul livello. Ora si aggiorna prima e si decide dopo.
    try:
        tracked = fu.auto_snapshot_tracked()
        log(f"Monitoraggio: snapshot aggiornati ({len(tracked)} titoli seguiti).")
    except Exception as e:
        log(f"Errore snapshot monitoraggio: {e!r}")

    # POI: congela/verifica i PREZZI D'INGRESSO delle occasioni seguite. Deve stare prima della FASE 2
    # perché avvisi, rimozioni e notifiche misurano il rendimento dall'ingresso: se quel prezzo viene
    # dedotto dagli scatti (che si conservano poche settimane) il sistema "vede" perdite che non
    # esistono e finisce per rimuovere posizioni sane.
    try:
        anc = fu.ancora_ingressi()
        if anc.get("ancorati") or anc.get("riancorati") or anc.get("ignoti"):
            log(f"Prezzi d'ingresso: {anc['ancorati']} congelati, {anc['riancorati']} riallineati "
                f"(frazionamenti), {anc['ignoti']} non ricavabili, {anc['saltati']} già a posto.")
        else:
            log(f"Prezzi d'ingresso: già tutti a posto ({anc.get('saltati', 0)} verificati).")
    except Exception as e:
        log(f"Errore ancoraggio prezzi d'ingresso: {e!r}")

    # FASE 2 — monitoraggio: rimozione autonoma PRUDENTE (solo se il deterioramento persiste alcuni
    # giorni di Borsa, non al primo calo) + crollo/delisting (>90%) subito. Prima notifica per le confermate.
    try:
        to_notify, removed = fu.manage_monitoring()
        if removed:
            log(f"Rimosse per crollo/delisting (>90%): {', '.join(removed)}")  # rimozione silenziosa (nessuna notifica)
        if to_notify:
            log(f"Notifica opportunità confermate: {', '.join(x['ticker'] for x in to_notify)}")
            notify_monitoring(to_notify)
        else:
            log("Nessuna nuova notifica di opportunità.")
    except Exception as e:
        log(f"Errore gestione monitoraggio: {e!r}")

    # FASE 2b — avvisi di USCITA: tesi esaurita (ipercomprato / bersaglio / fondamentali peggiorati)
    try:
        exits = fu.monitoring_exit_alerts()
        if exits:
            log(f"Avvisi di uscita: {', '.join(x['ticker'] for x in exits)}")
            notify_exit(exits)
        else:
            log("Nessun nuovo avviso di uscita.")
    except Exception as e:
        log(f"Errore avvisi di uscita: {e!r}")

    # FASE 2d — PRESA DI PROFITTO: le occasioni che hanno già dato quello che dovevano dare
    # (bersaglio raggiunto, o guadagno che si sta sgonfiando dal massimo). È l'unica porta d'uscita
    # sul lato GUADAGNO: prima esistevano solo quattro modi di dire "sta perdendo".
    try:
        incassi = fu.aggiorna_presa_profitto()
        if incassi:
            log(f"Da valutare per l'incasso: {', '.join(x['ticker'] for x in incassi)}")
            notify_profit(incassi)
        else:
            log("Nessuna occasione da incassare in questo giro.")
    except Exception as e:
        log(f"Errore presa di profitto: {e!r}")

    # FASE 2c — Soglie PERSONALI: avvisa quando il prezzo copre commissioni + netto desiderato.
    # DOPO gli snapshot, così valuta il prezzo di OGGI e non quello del giro precedente.
    try:
        hits = fu.my_target_alerts()
        if hits:
            log(f"Soglie personali raggiunte: {', '.join(h['ticker'] for h in hits)}")
            notify_my_target(hits)
        else:
            log("Nessuna soglia personale raggiunta.")
    except Exception as e:
        log(f"Errore soglie personali: {e!r}")

    # Aggiorna la "scheda voti": rendimento reale delle promozioni (ora / 7g / 30g)
    try:
        recs = fu.update_track_record()
        log(f"Scheda voti aggiornata: {len(recs)} promozioni registrate.")
    except Exception as e:
        log(f"Errore aggiornamento scheda voti: {e!r}")

    # Calibrazione: risolve le previsioni mature (prezzo a scadenza vs prezzo iniziale)
    try:
        nres = fu.resolve_forecasts()
        log(f"Calibrazione: {nres} previsioni risolte.")
    except Exception as e:
        log(f"Errore calibrazione previsioni: {e!r}")

    # Scenari acquisto/vendita: risolve le combinazioni mature (7g / 30g / bersaglio)
    try:
        nsc = fu.resolve_scenarios()
        log(f"Scenari acquisto/vendita: {nsc} celle risolte.")
    except Exception as e:
        log(f"Errore scenari acquisto/vendita: {e!r}")

    # Pre-segnale: registra le "più solide" di oggi e ne verifica l'esito quando maturo,
    # così anche l'affidabilità del pre-segnale viene misurata nel tempo.
    try:
        nuovi_pre = fu.record_presignals()
        npre = fu.resolve_presignals()
        log(f"Pre-segnale: {len(nuovi_pre)} nuovi registrati · {npre} esiti verificati.")
    except Exception as e:
        log(f"Errore registro pre-segnale: {e!r}")

    # Loop di feedback: risolve la resa forward del log convenienza e ri-stima i pesi (se ci sono dati)
    try:
        nrc = fu.resolve_convenience_log()
        learned = fu.update_conv_weights()
        log(f"Pesi convenienza: {nrc} rese risolte · appresi per: "
            + (", ".join(sorted(learned.keys())) if learned else "nessuno (dati ancora insufficienti)"))
    except Exception as e:
        log(f"Errore loop di feedback pesi: {e!r}")

    # Diagnostica: quante occasioni sono 'in osservazione' con convenienza in salita
    try:
        status = [s for s in fu.observation_status() if s.get("run", 0) >= 2]
        if status:
            log("In osservazione (giorni di convenienza in salita): "
                + ", ".join(f"{s['ticker']}={s.get('run', 0)}g(dconv{s.get('dconv', 0):+.0f})" for s in status[:15]))
    except Exception as e:
        log(f"Errore diagnostica osservazione: {e!r}")

    # Consulente di vendita: avvisa quando conviene incassare un titolo del portafoglio
    try:
        fired = fu.evaluate_portfolio_sales()
        if fired:
            log(f"Avvisi di vendita: {', '.join(f['position'].get('ticker', '?') for f in fired)}")
            notify_sales(fired)
        else:
            log("Nessun nuovo avviso di vendita.")
    except Exception as e:
        log(f"Errore consulente di vendita: {e!r}")

    # NIENTE ri-salvataggi "di sicurezza" alla fine del giro.
    # Servivano al vecchio sistema di pubblicazione con `git push` (che richiedeva i file presenti
    # in locale). Da quando la persistenza avviene via API GitHub dentro write_data_json, ogni
    # funzione salva già da sé quando i dati cambiano davvero: quelle righe erano inutili e
    # PERICOLOSE. Il 16/08/2026 hanno azzerato scenario_log (26 KB → 2 byte) ed exit_history
    # (4,7 KB → 2 byte): erano nella forma `write(load())` e, quando la lettura dal branch
    # falliva, `load()` restituiva [] (valore di ripiego) e la scrittura lo salvava sopra lo
    # storico. Si sono svuotati esattamente i due registri che quel giro non aveva scritto in
    # locale (presignal_log, scritto durante il giro, si è salvato). Ora write_data_json ha
    # comunque una protezione anti-cancellazione come seconda rete di sicurezza.

    log(f"Fatto. Totale occasioni viste: {total}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
