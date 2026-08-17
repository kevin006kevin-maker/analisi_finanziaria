"""
NOTA (lug 2026): questo strumento NON è più nell'app. Il guadagno in euro per ogni scenario si
legge ora direttamente nella tabella «Scenari», che si aggiorna da sola cambiando l'importo.
Lo script resta utilizzabile dal terminale (`python strategy_sim.py`) per analisi occasionali.

strategy_sim.py — "Quanto avrei guadagnato": rigioca le promozioni REALI del Monitoraggio
(comprese quelle poi RIMOSSE, grazie alle lapidi di exit_history.json → niente survivorship bias)
simulando l'acquisto alla promozione con un importo fisso e confrontando tre regole di uscita:

  hold    — compro e tengo fino a oggi (o fino alla rimozione, per le posizioni chiuse)
  target  — vendo la prima volta che il prezzo tocca il bersaglio registrato all'ingresso (SMA50);
            se non lo tocca mai, sto ancora tenendo (= hold)
  allarme — esco quando il sistema rimuove la posizione (prezzo dell'ultimo scatto); le posizioni
            ancora aperte sono come hold

Il netto in EUR usa la stessa formula del Portafoglio: netto = G − commissioni − 26%·max(G−commissioni, 0),
dove G = importo·resa%/100. Le percentuali sono nella valuta del titolo applicate al nominale in EUR:
l'oscillazione del CAMBIO è ignorata (dichiarato in UI; trascurabile rispetto alle commissioni sugli
importi piccoli e sugli orizzonti di giorni/settimane di questo strumento).

Usabile da CLI (`python strategy_sim.py`) o importato dall'app (`run_strategy_replay(...)`).
"""
import pandas as pd

import finance_utils as fu

STRATEGY_LABELS = {
    "hold": "Compro e tengo",
    "target": "Vendo al bersaglio (SMA50)",
    "allarme": "Esco quando il sistema rimuove",
}


def _net_eur(gross_pct, importo, fee, tax):
    """Netto in EUR di una posizione: come portfolio_view (tassa solo sull'utile post-commissioni)."""
    if gross_pct is None:
        return None
    g = importo * float(gross_pct) / 100.0
    return round(g - fee - tax * max(g - fee, 0.0), 2)


def _series_for(tk, entry, added):
    """Serie (data, prezzo) dall'ingresso a oggi: barre giornaliere (chiusure) + gli scatti
    dell'app più recenti dell'ultima barra (coprono le ultime ore/il weekend). Può essere vuota
    (titolo delistato): il chiamante ripiega sui soli scatti."""
    rows = []
    try:
        h = fu.get_history(tk, period="6mo")
        closes = h["Close"].dropna()
        try:
            closes.index = closes.index.tz_localize(None)
        except (TypeError, AttributeError):
            pass   # indice già senza fuso orario
        start = pd.Timestamp(str(added)[:10])
        closes = closes[closes.index >= start]
        rows = [(d, float(v)) for d, v in closes.items()]
    except Exception:
        rows = []
    last_bar = rows[-1][0] if rows else pd.Timestamp("1900-01-01")
    for s in entry.get("snapshots", []) or []:
        p = s.get("price")
        if not p:
            continue
        try:
            d = pd.Timestamp(str(s.get("date"))[:10])
        except Exception:
            continue
        if d > last_bar:
            rows.append((d, float(p)))
    rows.sort(key=lambda x: x[0])
    return rows


def _positions():
    """Posizioni da rigiocare: le APERTE da tracking.json (ingresso = 1° scatto con prezzo) e le
    CHIUSE dalle lapidi di exit_history.json (rimozioni automatiche e manuali)."""
    out = []
    for tk, e in fu.load_tracking().items():
        snaps = [s for s in e.get("snapshots", []) if s.get("price")]
        if not snaps:
            continue
        out.append({"ticker": tk, "kind": e.get("kind", "short"), "open": True,
                    "added": e.get("added") or str(snaps[0].get("date"))[:10],
                    "p_in": float(snaps[0]["price"]),
                    "target": snaps[0].get("target"),
                    "p_last": float(snaps[-1]["price"]),
                    "entry": e, "removed": None, "reason": None})
    # storico completo (archivio + vivo): includo TUTTE le rimozioni, anche quelle vecchie
    for r in fu.load_registro_completo(fu.EXIT_HISTORY_NAME, fu.load_exit_history()):
        if not r.get("first_price"):
            continue
        out.append({"ticker": r.get("ticker"), "kind": r.get("kind", "short"), "open": False,
                    "added": r.get("added"), "p_in": float(r["first_price"]),
                    "target": r.get("first_target"),
                    "p_last": float(r.get("last_price") or r["first_price"]),
                    "entry": {"snapshots": []}, "removed": r.get("removed"),
                    "reason": r.get("reason")})
    out.sort(key=lambda p: str(p.get("added") or ""), reverse=True)   # prima le più recenti
    return out


def run_strategy_replay(importo: float = 30.0, fee: float = 1.0,
                        tax: float = fu.CAPITAL_GAINS_TAX, max_positions: int = 40) -> dict:
    """Rigioca le posizioni reali del Monitoraggio con le tre regole di uscita. Ritorna un dict
    con totali e spaccato breve/lungo per strategia + le posizioni saltate (dati mancanti)."""
    pos = _positions()
    skipped = [p["ticker"] for p in pos[max_positions:]]
    pos = pos[:max_positions]

    results = {name: [] for name in STRATEGY_LABELS}
    rows = []
    for p in pos:
        tk, p_in = p["ticker"], p["p_in"]
        if not p_in or p_in <= 0:
            skipped.append(tk)
            continue
        # Serie fino a OGGI anche per le rimosse (se ancora quotate): così "hold" misura davvero
        # "avessi tenuto", distinto da "allarme" (= esco al prezzo di rimozione della lapide).
        serie = _series_for(tk, p["entry"], p["added"])
        # Guardia anti-split: se il prezzo d'ingresso registrato è lontanissimo dalla prima
        # chiusura disponibile (raggruppamenti/split non rettificati negli scatti) i rendimenti
        # sarebbero fantasiosi → la posizione si salta e si dichiara tra le escluse.
        if serie and abs(serie[0][1] / p_in - 1) > 0.25:
            skipped.append(tk)
            continue
        p_now = serie[-1][1] if serie else p["p_last"]

        # hold: tengo fino a oggi (per le delistate senza dati: ultimo prezzo noto)
        ret_hold = (p_now / p_in - 1) * 100

        # target: prima volta che una chiusura/scatto tocca il bersaglio d'ingresso
        tgt = p["target"]
        ret_target = ret_hold
        if tgt:
            hit = next((v for _d, v in serie if v >= float(tgt)), None)
            if hit is None and not p["open"] and p["p_last"] >= float(tgt):
                hit = p["p_last"]
            if hit is not None:
                ret_target = (float(tgt) / p_in - 1) * 100

        # allarme: le chiuse escono al prezzo di rimozione (lapide); le aperte sono come hold
        ret_alarm = ((p["p_last"] / p_in - 1) * 100) if not p["open"] else ret_hold

        per_strategy = {"hold": ret_hold, "target": ret_target, "allarme": ret_alarm}
        for name, r in per_strategy.items():
            results[name].append({"ticker": tk, "kind": p["kind"], "ret": r,
                                  "net": _net_eur(r, importo, fee, tax)})
        rows.append({"ticker": tk, "kind": p["kind"], "aperta": p["open"],
                     "ingresso": p["added"], "p_in": round(p_in, 4),
                     "ret_hold": round(ret_hold, 2), "ret_target": round(ret_target, 2),
                     "uscita": p.get("reason") or ("aperta" if p["open"] else "rimossa")})

    def _agg(items):
        n = len(items)
        if not n:
            return {"n": 0}
        tot = round(sum(x["net"] for x in items if x["net"] is not None), 2)
        return {"n": n, "tot_net_eur": tot, "avg_net_eur": round(tot / n, 2),
                "avg_ret": round(sum(x["ret"] for x in items) / n, 2),
                "hit": round(100 * sum(1 for x in items if (x["net"] or 0) > 0) / n),
                "capitale": round(n * (importo + fee), 2)}

    strategies = {}
    for name, items in results.items():
        strategies[name] = _agg(items)
        strategies[name]["by_kind"] = {k: _agg([x for x in items if x["kind"] == k])
                                       for k in ("short", "long")}
        strategies[name]["label"] = STRATEGY_LABELS[name]

    return {"n_positions": len(rows),
            "n_open": sum(1 for r in rows if r["aperta"]),
            "n_closed": sum(1 for r in rows if not r["aperta"]),
            "importo": importo, "fee": fee, "tax": tax,
            "strategies": strategies, "rows": rows, "skipped": skipped,
            "note_fx": "Oscillazione del cambio ignorata: percentuali native del titolo su nominale in EUR."}


if __name__ == "__main__":
    import json
    print(json.dumps(run_strategy_replay(), indent=1, ensure_ascii=False, default=str))
