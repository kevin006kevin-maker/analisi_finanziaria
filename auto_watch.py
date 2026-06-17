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
import datetime

import finance_utils as fu


def log(msg):
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}Z] {msg}", flush=True)


def main():
    if not (fu._fmp_key() or fu._finnhub_key()):
        log("ATTENZIONE: nessuna chiave API (FMP/Finnhub) impostata. I dati potrebbero essere assenti.")

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

    try:
        promoted = fu.auto_promote_opportunities(min_days=3)
        if promoted:
            log(f"PROMOSSE automaticamente al monitoraggio (in salita da ≥3 giorni): {', '.join(promoted)}")
        else:
            log("Nessuna nuova promozione in questo giro.")
    except Exception as e:
        log(f"Errore durante la promozione automatica: {e!r}")

    # Diagnostica: quante occasioni sono 'in osservazione' (vicine alla promozione)
    try:
        status = [s for s in fu.observation_status() if s["run"] >= 2]
        if status:
            log("In osservazione (giorni in salita): "
                + ", ".join(f"{s['ticker']}={s['run']}" for s in status[:15]))
    except Exception:
        pass

    # Garantisce che entrambi i file esistano in locale per la pubblicazione del workflow
    # (se un giro non produce novità, ripubblica lo stato corrente senza perdere lo storico).
    fu.save_opp_watch(fu.load_opp_watch())
    fu.save_tracking(fu.load_tracking())

    log(f"Fatto. Totale occasioni viste: {total}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
