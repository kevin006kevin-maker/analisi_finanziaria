"""Prova sull'archivio dei metodi di selezione documentati (versioni calcolabili coi nostri dati).
Tutto in-sample su ~48 giorni: serve a scegliere quali meritano di diventare metodi in ombra."""
import collections, datetime, json, logging, os, statistics as st, sys, warnings
warnings.filterwarnings("ignore"); logging.disable(logging.WARNING)
APP = r"C:\Users\kevin.munaretti\Documents\programma\finanza\analisi_finanziaria"
os.chdir(APP); sys.path.insert(0, APP)
CACHE = r"C:\Users\kevin.munaretti\Documents\programma\finanza\analisi_finanziaria\strumenti_verifica\archivio_cache_0610.json"

if not os.path.exists(CACHE):
    import finance_utils as fu
    prof = {p.get("id"): p for p in fu._arc_leggi_giorni(fu.ARC_PROFILI) if isinstance(p, dict)}
    esiti = [e for e in fu._arc_leggi_giorni(fu.ARC_ESITI) if isinstance(e, dict) and e.get("resa") is not None
             and not e.get("dati_sospetti") and not e.get("finestra_incompleta")]
    json.dump({"prof": prof, "esiti": esiti}, open(CACHE, "w"))
C = json.load(open(CACHE))
prof, esiti = C["prof"], C["esiti"]
E = collections.defaultdict(dict)
for e in esiti:
    if e.get("orizzonte") in ("7g", "30g"):
        E[e.get("profilo")][e.get("orizzonte")] = e["resa"]
print("profili", len(prof), "| esiti 7g/30g", sum(len(v) for v in E.values()))

GIUDIZIO = {"punteggio_basso", "sconto_insufficiente", "convenienza_sotto_cancello", "rischio_rendimento",
            "troppi_dello_stesso_settore"}


def t(p, k):
    v = (p.get("titolo") or {}).get(k)
    if isinstance(v, bool):
        return v
    return float(v) if isinstance(v, (int, float)) else None


def med(xs):
    return st.median(xs) if xs else None


def mom121(p):
    a, b = t(p, "perf_1y"), t(p, "perf_1m")
    if a is None or b is None or b <= -99:
        return None
    return ((1 + a / 100) / (1 + b / 100) - 1) * 100


for KIND in ("short", "long"):
    base = [p for p in prof.values() if p.get("kind") == KIND and p.get("prezzo")
            and ((not p.get("scartata") and p.get("momento")) or (p.get("scartata") and p.get("motivo") in GIUDIZIO))]
    per_g = collections.defaultdict(list)
    for p in base:
        per_g[str(p.get("giorno"))[:10]].append(p)
    giorni = sorted(per_g)
    meta = giorni[len(giorni) // 2]
    print("\n" + "=" * 100)
    print("TIPO %s | universo guardato %d righe in %d giornate | taglio meta %s" % (KIND, len(base), len(giorni), meta))
    cov = lambda k: round(100 * sum(1 for p in base if t(p, k) is not None) / len(base))
    print("copertura: dd_high %d%%  perf_1y %d%%  above_sma200 %d%%  rebound_pot %d%%  atr_pct %d%%  fscore %d%%  roic %d%%  gross_m %d%%  avg_dollar_vol %d%%" % (
        cov("dd_high"), cov("perf_1y"), cov("above_sma200"), cov("rebound_pot"), cov("atr_pct"), cov("fscore"), cov("roic"), cov("gross_m"), cov("avg_dollar_vol")))

    # soglie di classifica PER GIORNATA (le classifiche relative si fanno fra i titoli guardati quel giorno)
    rank = {}
    for g, ps in per_g.items():
        for chiave, f, alto in (("mom", mom121, True), ("vol", lambda p: t(p, "atr_pct"), False)):
            vals = sorted(v for v in (f(p) for p in ps) if v is not None)
            if len(vals) < 10:
                continue
            q = vals[int(len(vals) * 0.7)] if alto else vals[int(len(vals) * 0.3)]
            rank[(g, chiave)] = q

    def top_mom(p):
        q, v = rank.get((p["giorno"], "mom")), mom121(p)
        return q is not None and v is not None and v >= q

    def low_vol(p):
        q, v = rank.get((p["giorno"], "vol")), t(p, "atr_pct")
        return q is not None and v is not None and v <= q

    def liquido(p, prezzo=10, vol=5e6):
        return (t(p, "price") or 0) >= prezzo and (t(p, "avg_dollar_vol") or 0) >= vol

    def qualita(p):
        f, r, gm = t(p, "fscore"), t(p, "roic"), t(p, "gross_m")
        return (f is not None and f >= 7) or (r is not None and gm is not None and r >= 12 and gm >= 35)

    METODI = [
        ("Vivo: quello che il sistema compra", lambda p: not p.get("scartata")),
        ("Universo: tutto quello che guarda", lambda p: True),
        ("Vicino ai massimi dell'anno (entro 10%)", lambda p: (t(p, "dd_high") or -999) >= -10 and liquido(p)),
        ("Forza relativa 12-1: il 30% migliore del giorno", lambda p: top_mom(p) and liquido(p)),
        ("Trend template semplificato (Minervini)", lambda p: t(p, "above_sma200") is True and (t(p, "rebound_pot") or 1) <= 0
                                                             and (t(p, "dd_high") or -999) >= -25 and (t(p, "perf_1y") or -1) > 0 and liquido(p)),
        ("Bassa volatilità: il 30% più calmo del giorno", lambda p: low_vol(p) and liquido(p)),
        ("Qualità dei conti", lambda p: qualita(p) and liquido(p)),
        ("Qualità + forza relativa", lambda p: qualita(p) and top_mom(p) and liquido(p)),
        ("Rimbalzo solo su titoli grandi e liquidi", lambda p: (t(p, "rsi") or 100) <= 35 and liquido(p, 10, 5e7)),
        ("Ombra 1: solo in trend positivo", lambda p: not p.get("scartata") and t(p, "above_sma200") is True),
        ("Ombra 2: regole nuove", lambda p: t(p, "above_sma200") is True and (t(p, "perf_1y") if t(p, "perf_1y") is not None else -999) >= -10
                                            and liquido(p) and not p.get("trappola")),
    ]

    def scegli(f):
        ultimo, out = {}, []
        for g in giorni:
            for p in sorted(per_g[g], key=lambda p: str(p.get("ora") or "")):
                if not f(p):
                    continue
                tk = str(p.get("ticker")).upper()
                d = datetime.date.fromisoformat(g)
                if tk in ultimo and (d - ultimo[tk]).days < 30:
                    continue
                ultimo[tk] = d
                out.append(p)
        return out

    # riferimento di giornata: mediana dell'universo guardato (dedup come sopra) per orizzonte
    univ = scegli(lambda p: True)
    rif = {}
    for oriz in ("7g", "30g"):
        bg = collections.defaultdict(list)
        for p in univ:
            if oriz in E.get(p["id"], {}):
                bg[p["giorno"]].append(E[p["id"]][oriz])
        rif[oriz] = {g: med(xs) for g, xs in bg.items() if len(xs) >= 5}
    vivo = scegli(lambda p: not p.get("scartata"))

    print("\n%-48s %6s | %-42s | %-42s" % ("metodo", "scelte", "7 giorni: mediana / vince / vs universo / meta1 meta2", "30 giorni: mediana / vince / vs universo / meta1 meta2"))
    for nome, f in METODI:
        sc = scegli(f)
        celle = []
        for oriz in ("7g", "30g"):
            xs = [(p["giorno"], E[p["id"]][oriz]) for p in sc if oriz in E.get(p["id"], {}) and p["giorno"] in rif[oriz]]
            if len(xs) < 8:
                celle.append("%-42s" % ("pochi casi (%d)" % len(xs)))
                continue
            r = [x for _, x in xs]
            ex = [x - rif[oriz][g] for g, x in xs]
            m1 = med([x - rif[oriz][g] for g, x in xs if g < meta])
            m2 = med([x - rif[oriz][g] for g, x in xs if g >= meta])
            celle.append("n%4d %+6.2f%% %3d%% %+6.2f | %s %s" % (
                len(r), med(r), round(100 * sum(1 for x in r if x > 0) / len(r)), med(ex),
                ("%+6.2f" % m1) if m1 is not None else "   ---", ("%+6.2f" % m2) if m2 is not None else "   ---"))
        print("%-48s %6d | %s | %s" % (nome[:48], len(sc), celle[0], celle[1]))
    print("  «vs universo» = resa meno la mediana di tutto il guardato nello STESSO giorno (toglie l'effetto mercato).")
    print("  «meta1 meta2» = lo stesso scarto nella prima e nella seconda meta dei giorni: se cambia segno, non e' stabile.")
