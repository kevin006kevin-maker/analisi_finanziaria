"""
auto_watch.py — motore autonomo delle occasioni.

Pensato per girare su GitHub Actions ogni ~15 minuti (anche a PC spento):
1. scansiona le occasioni di mercato (breve e lungo periodo);
2. registra l'evoluzione della convenienza di ciascuna (1 osservazione/giorno);
3. promuove al monitoraggio quelle in salita da 3 giorni consecutivi.

I dati precedenti vengono letti dal branch remoto (raw URL) e quelli aggiornati
salvati su file locali (opp_watch.json, tracking.json), che il workflow pubblica
poi sul branch dei dati. L'app legge da lì, così funziona ovunque, anche da telefono.

Chiavi/config da variabili d'ambiente:
  FMP_API_KEY, FINNHUB_API_KEY  → dati di mercato
  DATA_REPO = "utente/repo"     → per leggere i dati precedenti dal branch remoto
  DATA_BRANCH = "auto-data"     → branch dei dati (default auto-data)
NB: NON impostare GITHUB_TOKEN per questo script: la pubblicazione la fa il workflow
    con git push (così non si scrive due volte).
"""

import os
import sys
import html
import datetime

import finance_utils as fu


def log(msg):
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}Z] {msg}", flush=True)


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
        righe.append(f"   {term} · convenienza +{it.get('dconv', 0):.0f} in {it.get('days', 0)} giorni di monitoraggio")
    righe += ["", "Possibile opportunità di investimento — apri l'app → Monitoraggio.",
              "(Strumento informativo, non è un consiglio.)"]
    ok = fu.send_telegram("\n".join(righe))
    log("Notifica opportunità inviata." if ok
        else "Notifica opportunità NON inviata (Telegram non configurato o errore).")


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
            candidates = fu.opportunity_candidates(kind)
            df = fu.scan_opportunities(candidates, kind)
            n = 0 if df is None or df.empty else len(df)
            total += n
            fu.record_observations(df, kind)
            log(f"{kind}: {n} occasioni scansionate e registrate.")
        except Exception as e:
            log(f"{kind}: errore durante la scansione: {e!r}")

    # FASE 1 — promozione (silenziosa): occasioni con osservazione positiva (breve 3g / lungo 7g)
    try:
        promoted = fu.auto_promote_opportunities()
        log(f"PROMOSSE al Monitoraggio (osservazione positiva): {', '.join(promoted)}"
            if promoted else "Nessuna nuova promozione in questo giro.")
    except Exception as e:
        log(f"Errore durante la promozione automatica: {e!r}")

    # FASE 2 — monitoraggio: rimuove le perdenti oltre la finestra (breve 5g / lungo 10g) e
    # invia la prima notifica per quelle confermate positive (breve 3g / lungo 7g).
    try:
        to_notify, removed = fu.manage_monitoring()
        if removed:
            log(f"Rimosse dal monitoraggio (in perdita oltre la finestra): {', '.join(removed)}")
        if to_notify:
            log(f"Notifica opportunità confermate: {', '.join(x['ticker'] for x in to_notify)}")
            notify_monitoring(to_notify)
        else:
            log("Nessuna nuova notifica di opportunità.")
    except Exception as e:
        log(f"Errore gestione monitoraggio: {e!r}")

    # Aggiorna la "scheda voti": rendimento reale delle promozioni (ora / 7g / 30g)
    try:
        recs = fu.update_track_record()
        log(f"Scheda voti aggiornata: {len(recs)} promozioni registrate.")
    except Exception as e:
        log(f"Errore aggiornamento scheda voti: {e!r}")

    # Diagnostica: quante occasioni sono 'in osservazione' (vicine alla promozione)
    try:
        status = [s for s in fu.observation_status() if s["run"] >= 2]
        if status:
            log("In osservazione (giorni in salita): "
                + ", ".join(f"{s['ticker']}={s['run']}" for s in status[:15]))
    except Exception:
        pass

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

    # Garantisce che i file esistano in locale per la pubblicazione del workflow
    # (se un giro non produce novità, ripubblica lo stato corrente senza perdere lo storico).
    fu.save_opp_watch(fu.load_opp_watch())
    fu.save_tracking(fu.load_tracking())
    fu.save_track_record(fu.load_track_record())
    fu.save_portfolio(fu.load_portfolio())          # preserva il portafoglio (lo gestisce l'app)
    fu.save_sell_alerts(fu.load_sell_alerts())      # stato avvisi di vendita (deduplica)

    log(f"Fatto. Totale occasioni viste: {total}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
