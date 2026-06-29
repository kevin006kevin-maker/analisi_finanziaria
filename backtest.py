"""
backtest.py — Backtest WALK-FORWARD del ramo prezzo/tecnico delle "Occasioni" (breve, rimbalzo da
ipervenduto). Per ogni titolo, su ogni giorno ricostruisce il setup usando SOLO i dati fino a quel
giorno (nessun look-ahead) e misura la resa forward NETTA (tassa 26%) a `horizon` giorni di Borsa,
o prima se il prezzo tocca lo stop (prezzo − 2·ATR) o il bersaglio (media 50 giorni).

Limiti dichiarati (onestà): NON include i fondamentali point-in-time (non ricostruibili da fonti
gratuite), quindi valida il ramo tecnico/prezzo, non quello "qualità in saldo" del lungo. È
walk-forward per costruzione (ogni ingresso usa solo il passato, la resa si realizza dopo).

Usabile da CLI (`python backtest.py`) o importato dall'app (`run_backtest(...)`).
"""
import numpy as np

import finance_utils as fu


def _net(ret_pct):
    return fu.net_return_pct(ret_pct)


def _bench_forward(symbol: str, horizon: int) -> float:
    """Resa forward MEDIA del benchmark (compra-e-tieni) su `horizon` giorni, campionata su 2 anni.
    Riferimento onesto: l'occasione batte il semplice 'compra l'indice e aspetta'?"""
    try:
        c = fu.get_history(symbol, period="2y")["Close"].dropna().values
    except Exception:
        return None
    if len(c) < horizon + 30:
        return None
    rr = [(c[i + horizon] / c[i] - 1) * 100 for i in range(0, len(c) - horizon, max(1, horizon // 2))
          if c[i] > 0]
    return round(float(np.mean(rr)), 2) if rr else None


def _band(score: float) -> str:
    if score >= 70:
        return "🟢 forte (≥70)"
    if score >= 50:
        return "🟡 media (50–69)"
    return "🔴 debole (<50)"


def run_backtest(tickers=None, horizon: int = 21, benchmark: str = "^GSPC", max_tickers: int = 30) -> dict:
    """Esegue il backtest e ritorna statistiche aggregate + per fascia di forza del segnale.
    horizon = giorni di Borsa di mantenimento massimo. Ritorna {} se non ci sono dati."""
    universe = list(dict.fromkeys(tickers or fu._FALLBACK_UNIVERSE))[:max_tickers]
    trades = []
    for tk in universe:
        try:
            h = fu.get_history(tk, period="2y")
        except Exception:
            h = None
        if h is None or h.empty or len(h) < 260:
            continue
        h = fu.add_indicators(h)
        closes = h["Close"].values.astype(float)
        rsi = h["RSI"].values.astype(float) if "RSI" in h else np.full(len(h), np.nan)
        sma50 = h["SMA50"].values.astype(float) if "SMA50" in h else np.full(len(h), np.nan)
        sma200 = h["SMA200"].values.astype(float) if "SMA200" in h else np.full(len(h), np.nan)
        bb_low = h["BB_low"].values.astype(float) if "BB_low" in h else np.full(len(h), np.nan)
        atr_ser = fu.atr(h, 14).values.astype(float)
        n = len(h)
        i = 205
        while i < n - 1:
            price = closes[i]
            r = rsi[i]
            if np.isnan(price) or price <= 0 or np.isnan(r) or r > 45:
                i += 1
                continue
            hi52 = np.nanmax(closes[max(0, i - 252):i + 1])
            dd = (price / hi52 - 1) * 100 if hi52 else 0.0
            if dd > -8:                               # dev'essere un calo reale
                i += 1
                continue
            below_bb = (not np.isnan(bb_low[i])) and price <= bb_low[i]
            above_sma200 = (not np.isnan(sma200[i])) and price > sma200[i]
            score = max(0.0, min(50.0, 12.0 + (45.0 - r) * 1.9))   # stessa rampa RSI dell'app
            score += 12 if below_bb else 0
            score += 13 if above_sma200 else 0
            score += min(max(-dd, 0) / 60 * 25, 25)
            if score < 35:                            # stessa soglia minima dell'app
                i += 1
                continue
            atrv = atr_ser[i] if not np.isnan(atr_ser[i]) else price * 0.02
            stop = price - 2.0 * atrv
            target = sma50[i] if not np.isnan(sma50[i]) else price * 1.05
            exit_ret = None
            end = min(i + 1 + horizon, n)
            for j in range(i + 1, end):               # uscita anticipata su stop/bersaglio
                pj = closes[j]
                if np.isnan(pj):
                    continue
                if pj <= stop:
                    exit_ret = (stop / price - 1) * 100
                    break
                if target > price and pj >= target:
                    exit_ret = (target / price - 1) * 100
                    break
            if exit_ret is None:
                pe = closes[min(i + horizon, n - 1)]
                exit_ret = (pe / price - 1) * 100 if not np.isnan(pe) else 0.0
            trades.append({"ticker": tk, "score": float(score), "ret": float(exit_ret),
                           "net": float(_net(exit_ret))})
            i += horizon                              # niente trade sovrapposti sullo stesso titolo

    if not trades:
        return {"n_trades": 0}

    rets = np.array([t["ret"] for t in trades])
    nets = np.array([t["net"] for t in trades])
    bands = {}
    for t in trades:
        b = _band(t["score"])
        bands.setdefault(b, []).append(t)
    by_band = []
    for b in ("🟢 forte (≥70)", "🟡 media (50–69)", "🔴 debole (<50)"):
        grp = bands.get(b, [])
        if grp:
            gr = np.array([x["net"] for x in grp])
            by_band.append({"banda": b, "n": len(grp),
                            "avg_net": round(float(gr.mean()), 2),
                            "hit": round(100 * float((gr > 0).mean()))})
    return {
        "n_trades": len(trades),
        "universe": len(universe),
        "horizon": horizon,
        "hit_rate": round(100 * float((rets > 0).mean())),
        "avg_ret": round(float(rets.mean()), 2),
        "avg_net": round(float(nets.mean()), 2),
        "median_net": round(float(np.median(nets)), 2),
        "bench_avg": _bench_forward(benchmark, horizon),
        "by_band": by_band,
    }


if __name__ == "__main__":
    res = run_backtest()
    if not res.get("n_trades"):
        print("Nessun trade: dati insufficienti.")
    else:
        print(f"Backtest occasioni (breve, orizzonte {res['horizon']} gg di Borsa) "
              f"su {res['universe']} titoli — {res['n_trades']} trade simulati")
        print(f"  Hit-rate: {res['hit_rate']}%  ·  resa media NETTA: {res['avg_net']:+.2f}%  "
              f"(mediana {res['median_net']:+.2f}%)")
        print(f"  Benchmark (compra-e-tieni {res['horizon']} gg): {res['bench_avg']:+.2f}% medio")
        print("  Per fascia di forza del segnale:")
        for b in res["by_band"]:
            print(f"    {b['banda']}: n={b['n']}  resa netta media {b['avg_net']:+.2f}%  in positivo {b['hit']}%")
