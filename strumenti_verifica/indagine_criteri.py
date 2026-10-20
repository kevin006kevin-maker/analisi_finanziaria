"""Indagine sui criteri del sistema attuale: filtro per filtro, chi viene fermato e chi passa, e com'e'
andata agli uni e agli altri NEGLI STESSI GIORNI. Solo lettura dell'archivio."""
import collections, json, statistics as st, sys

import os
_CACHE = r"C:\Users\kevin.munaretti\Documents\programma\finanza\analisi_finanziaria\strumenti_verifica\archivio_cache_0610.json"
if not os.path.exists(_CACHE):   # la cache dell'archivio si ricrea se manca (circa un minuto)
    sys.path.insert(0, r"C:\Users\kevin.munaretti\Documents\programma\finanza\analisi_finanziaria")
    import finance_utils as _fu
    json.dump({"prof": {p.get("id"): p for p in _fu._arc_leggi_giorni(_fu.ARC_PROFILI) if isinstance(p, dict)},
               "esiti": [e for e in _fu._arc_leggi_giorni(_fu.ARC_ESITI) if isinstance(e, dict) and e.get("resa") is not None
                         and not e.get("dati_sospetti") and not e.get("finestra_incompleta")]}, open(_CACHE, "w"))
C = json.load(open(_CACHE))
prof, esiti = C["prof"], C["esiti"]
E = collections.defaultdict(dict)
for e in esiti:
    if e.get("orizzonte") in ("7g", "30g"):
        E[e["profilo"]][e["orizzonte"]] = float(e["resa"])

ORDINE = {"short": ["prezzo_basso", "poco_scambiato", "punteggio_basso", "sconto_insufficiente",
                    "rischio_rendimento", "cade_piu_del_mercato", "TENUTE"],
          "long": ["prezzo_basso", "poco_scambiato", "trappola_di_valore", "punteggio_basso",
                   "sconto_insufficiente", "troppi_dello_stesso_settore", "TENUTE"]}
NOME = {"prezzo_basso": "prezzo minimo", "poco_scambiato": "scambi minimi", "punteggio_basso": "punteggio minimo",
        "sconto_insufficiente": "sconto minimo dai massimi", "rischio_rendimento": "rischio/rendimento minimo",
        "cade_piu_del_mercato": "cade più del mercato", "trappola_di_valore": "trappola di valore",
        "troppi_dello_stesso_settore": "tetto per settore", "TENUTE": "tenute"}


def med(xs):
    return st.median(xs) if xs else None


def num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def t(p, k):
    return (p.get("titolo") or {}).get(k)


def tappa(p):
    if p.get("scartata"):
        m = p.get("motivo")
        if m == "convenienza_sotto_cancello":
            return "TENUTE"
        return m
    return "TENUTE" if p.get("momento") == "ingresso_osservazione" else None


def score_breve(p):
    """Il punteggio di breve ricostruito dagli ingredienti registrati (regime di mercato calmo = 1)."""
    rsi = t(p, "rsi")
    if not num(rsi):
        return None
    b = max(0.0, min(50.0, 12.0 + (45.0 - rsi) * 1.9))
    if t(p, "below_bb"): b += 12
    if t(p, "above_sma200"): b += 13
    dd = t(p, "dd_high")
    if num(dd): b += min(max(-dd, 0) / 60 * 25, 25)
    if t(p, "reversal_confirmed"): b += 14
    elif t(p, "green_day") is False: b -= 18
    rv = t(p, "rvol")
    if num(rv) and t(p, "green_day"):
        b += 10 if rv >= 1.5 else (5 if rv >= 1.2 else 0)
    if t(p, "vertical_crash"): b -= 22
    return max(0.0, min(b, 100.0))


# una decisione per titolo e giorno: la prima della giornata
scan = {}
for p in sorted(prof.values(), key=lambda p: str(p.get("ora") or "")):
    tp = tappa(p)
    if tp is None or p.get("kind") not in ORDINE:
        continue
    k = (p["kind"], p["giorno"], str(p["ticker"]).upper())
    if k not in scan:
        scan[k] = (tp, p)


def confronto(fermati, passati, oriz):
    """Stessi giorni: mediana di chi passa contro mediana di chi e' fermato, giorno per giorno."""
    fb = [(p["giorno"], E[p["id"]][oriz]) for p in fermati if oriz in E.get(p["id"], {})]
    pb = [(p["giorno"], E[p["id"]][oriz]) for p in passati if oriz in E.get(p["id"], {})]
    pg = collections.defaultdict(lambda: ([], []))
    for g, x in fb: pg[g][0].append(x)
    for g, x in pb: pg[g][1].append(x)
    coppie = [(med(a), med(b)) for a, b in pg.values() if a and b]
    vinti = sum(1 for a, b in coppie if b > a)
    diff = med([b - a for a, b in coppie])
    return {"nf": len(fb), "np": len(pb), "mf": med([x for _, x in fb]), "mp": med([x for _, x in pb]),
            "hf": (round(100 * sum(1 for _, x in fb if x > 0) / len(fb)) if fb else None),
            "hp": (round(100 * sum(1 for _, x in pb if x > 0) / len(pb)) if pb else None),
            "gg": len(coppie), "vinti": vinti, "diff": diff}


def giudizio(c):
    if not c["gg"] or c["gg"] < 5:
        return "pochi giorni"
    q = c["vinti"] / c["gg"]
    if q >= 0.65 and (c["diff"] or 0) > 0:
        return "UTILE: chi passa va meglio"
    if q <= 0.35 and (c["diff"] or 0) < 0:
        return "CONTROPRODUCENTE: chi è fermato va meglio"
    return "non distingue"


def riga_c(c):
    f = lambda v: ("%+6.2f%%" % v) if v is not None else "   —   "
    return ("fermati n%5d %s %3s%% | passati n%5d %s %3s%% | giorni %2d, passati meglio in %2d (diff tipica %s)" % (
        c["nf"], f(c["mf"]), c["hf"] if c["hf"] is not None else "—", c["np"], f(c["mp"]),
        c["hp"] if c["hp"] is not None else "—", c["gg"], c["vinti"], f(c["diff"])))


def fasce(popolazione, valore, tagli, nomi, oriz, rif_giorno):
    """Resa per fasce di un valore, come scarto dalla mediana di tutta la popolazione dello stesso giorno."""
    out = []
    for i, nome in enumerate(nomi):
        lo = tagli[i]; hi = tagli[i + 1]
        xs = []
        for p in popolazione:
            v = valore(p)
            if not num(v) or not (lo <= v < hi) or oriz not in E.get(p["id"], {}):
                continue
            r = rif_giorno.get((p["kind"], p["giorno"], oriz))
            if r is None:
                continue
            xs.append((E[p["id"]][oriz], E[p["id"]][oriz] - r))
        if xs:
            out.append("      %-16s n%5d  resa tipica %+6.2f%%  in guadagno %3d%%  rispetto al giorno %+6.2f" % (
                nome, len(xs), med([a for a, _ in xs]), round(100 * sum(1 for a, _ in xs if a > 0) / len(xs)),
                med([b for _, b in xs])))
        else:
            out.append("      %-16s nessun caso" % nome)
    return out


for KIND in ("short", "long"):
    ordine = ORDINE[KIND]
    righe = [(tp, p) for (k, g, tk), (tp, p) in scan.items() if k == KIND]
    pos = {g: i for i, g in enumerate(ordine)}
    print("\n" + "=" * 118)
    print("TIPO %s: decisioni del passaggio iniziale %d (una per titolo e giorno)" % (KIND, len(righe)))
    print("   per tappa:", dict(collections.Counter(tp for tp, _ in righe)))
    # riferimento del giorno: mediana di TUTTO il guardato (dopo i filtri tecnici di prezzo e scambi esclusi? no: tutto)
    rif = {}
    for oriz in ("7g", "30g"):
        pg = collections.defaultdict(list)
        for tp, p in righe:
            if oriz in E.get(p["id"], {}):
                pg[p["giorno"]].append(E[p["id"]][oriz])
        for g, xs in pg.items():
            if len(xs) >= 5:
                rif[(KIND, g, oriz)] = med(xs)

    print("\n### 1. FILTRO PER FILTRO (chi arriva al filtro: fermati qui contro passati oltre)")
    for i, g in enumerate(ordine[:-1]):
        arrivati = [p for tp, p in righe if pos.get(tp, -1) >= i]
        fermati = [p for tp, p in righe if tp == g]
        passati = [p for tp, p in righe if pos.get(tp, -1) > i]
        if not fermati:
            print("\n   %-26s mai scattato" % NOME[g])
            continue
        print("\n   %-26s arrivati %d, fermati %d (%d%%)" % (NOME[g].upper(), len(arrivati), len(fermati), round(100 * len(fermati) / len(arrivati))))
        for oriz in ("7g", "30g"):
            c = confronto(fermati, passati, oriz)
            print("      %-4s %s  -> %s" % (oriz, riga_c(c), giudizio(c)))

    print("\n### 2. LE SOGLIE: resa per fasce del valore che il filtro guarda (rispetto al giorno = scarto dalla mediana di tutto il guardato)")
    tutti = [p for tp, p in righe]
    pp = lambda p: t(p, "price")
    print("   PREZZO (soglia attuale %s $)" % ("3" if KIND == "short" else "1"))
    for l in fasce(tutti, pp, [0, 1, 3, 5, 10, 20, 50, 1e12], ["<1", "1-3", "3-5", "5-10", "10-20", "20-50", "50+"], "30g", rif): print(l)
    print("   SCAMBI AL GIORNO in milioni di $ (soglia attuale %s)" % ("1" if KIND == "short" else "0,3"))
    oltre_prezzo = [p for tp, p in righe if pos.get(tp, -1) >= 1]
    for l in fasce(oltre_prezzo, lambda p: (t(p, "avg_dollar_vol") or 0) / 1e6, [0, 1, 5, 20, 100, 1e12], ["<1", "1-5", "5-20", "20-100", "100+"], "30g", rif): print(l)
    if KIND == "short":
        al_punteggio = [p for tp, p in righe if pos.get(tp, -1) >= 2]
        print("   PUNTEGGIO (soglia attuale 35), ricostruito dagli ingredienti")
        for oriz in ("7g", "30g"):
            print("    a", oriz)
            for l in fasce(al_punteggio, score_breve, [0, 20, 35, 45, 55, 65, 101], ["0-20", "20-35 fermati", "35-45", "45-55", "55-65", "65+"], oriz, rif): print(l)
    al_sconto = [p for tp, p in righe if pos.get(tp, -1) >= ordine.index("sconto_insufficiente")]
    print("   SCONTO DAI MASSIMI DELL'ANNO, fra chi ha passato il punteggio (soglia attuale %s)" % ("-8%" if KIND == "short" else "-12%"))
    for oriz in ("7g", "30g"):
        print("    a", oriz)
        for l in fasce(al_sconto, lambda p: t(p, "dd_high"), [-101, -50, -35, -25, -15, -8, 1], ["oltre -50%", "-50/-35", "-35/-25", "-25/-15", "-15/-8", "-8/0 fermati"], oriz, rif): print(l)
    if KIND == "short":
        al_rr = [p for tp, p in righe if pos.get(tp, -1) >= ordine.index("rischio_rendimento")]
        print("   RISCHIO/RENDIMENTO, fra chi ha passato sconto (soglia attuale 1,5)")
        for oriz in ("7g", "30g"):
            print("    a", oriz)
            for l in fasce(al_rr, lambda p: t(p, "rr"), [0, 1, 1.5, 2, 3, 1e9], ["<1 fermati", "1-1,5 fermati", "1,5-2", "2-3", "3+"], oriz, rif): print(l)
    tenute = [p for tp, p in righe if tp == "TENUTE"]
    print("   CONVENIENZA fra le tenute (cancello per entrare in osservazione: 60)")
    for oriz in ("7g", "30g"):
        print("    a", oriz)
        for l in fasce(tenute, lambda p: p.get("convenienza"), [0, 40, 50, 60, 65, 75, 101], ["<40", "40-50", "50-60 fuori", "60-65 dentro", "65-75 dentro", "75+ dentro"], oriz, rif): print(l)

    if KIND == "short":
        print("\n### 3. DENTRO IL PUNTEGGIO: ogni ingrediente, fra chi arriva al punteggio (prezzo e scambi ok)")
        al_punteggio = [p for tp, p in righe if pos.get(tp, -1) >= 2]
        ingredienti = [
            ("RSI sotto 30 (ipervenduto, fino a +50)", lambda p: num(t(p, "rsi")) and t(p, "rsi") < 30, lambda p: num(t(p, "rsi")) and t(p, "rsi") >= 30),
            ("sotto la banda di Bollinger (+12)", lambda p: t(p, "below_bb") is True, lambda p: t(p, "below_bb") is False),
            ("sopra la media a 200 giorni (+13)", lambda p: t(p, "above_sma200") is True, lambda p: t(p, "above_sma200") is False),
            ("sconto oltre il 30% (fino a +25)", lambda p: num(t(p, "dd_high")) and t(p, "dd_high") < -30, lambda p: num(t(p, "dd_high")) and t(p, "dd_high") >= -30),
            ("inversione confermata (+14)", lambda p: t(p, "reversal_confirmed") is True, lambda p: not t(p, "reversal_confirmed")),
            ("ancora in calo oggi (-18)", lambda p: t(p, "green_day") is False and not t(p, "reversal_confirmed"), lambda p: t(p, "green_day") is True),
            ("volume forte su giorno verde (+5/+10)", lambda p: bool(t(p, "green_day")) and num(t(p, "rvol")) and t(p, "rvol") >= 1.2, lambda p: not (bool(t(p, "green_day")) and num(t(p, "rvol")) and t(p, "rvol") >= 1.2)),
            ("crollo verticale (-22)", lambda p: t(p, "vertical_crash") is True, lambda p: t(p, "vertical_crash") is False),
        ]
        for nome, con, senza in ingredienti:
            a = [p for p in al_punteggio if con(p)]
            b = [p for p in al_punteggio if senza(p)]
            print("\n   %s: con %d, senza %d" % (nome, len(a), len(b)))
            for oriz in ("7g", "30g"):
                c = confronto(b, a, oriz)   # "passati" = con l'ingrediente, "fermati" = senza
                print("      %-4s CON: n%5d %+6.2f%% %3s%% | SENZA: n%5d %+6.2f%% %3s%% | giorni %2d, CON meglio in %2d (diff %s)" % (
                    oriz, c["np"], c["mp"] or 0, c["hp"], c["nf"], c["mf"] or 0, c["hf"], c["gg"], c["vinti"],
                    ("%+.2f" % c["diff"]) if c["diff"] is not None else "—"))

    print("\n### 4. ORIGINE: da quale lista arriva il titolo (tutto il guardato)")
    per_o = collections.defaultdict(list)
    for tp, p in righe:
        per_o[p.get("origine") or "(non registrata)"].append(p)
    for o, ps in sorted(per_o.items(), key=lambda kv: -len(kv[1])):
        for oriz in ("30g",):
            xs = [(E[p["id"]][oriz], E[p["id"]][oriz] - rif[(KIND, p["giorno"], oriz)]) for p in ps
                  if oriz in E.get(p["id"], {}) and (KIND, p["giorno"], oriz) in rif]
            ten = sum(1 for p in ps if tappa(p) == "TENUTE")
            if xs:
                print("   %-28s titoli guardati %5d, tenuti %4d (%2d%%) | a 30g resa tipica %+6.2f%%, rispetto al giorno %+6.2f, in guadagno %3d%%" % (
                    o, len(ps), ten, round(100 * ten / len(ps)), med([a for a, _ in xs]), med([b for _, b in xs]),
                    round(100 * sum(1 for a, _ in xs if a > 0) / len(xs))))

print("\n### 5. LE FASI SUCCESSIVE: comprando in ogni momento, rispetto a tutto il guardato dello stesso giorno")
for KIND in ("short", "long"):
    rif = {}
    for oriz in ("7g", "30g"):
        pg = collections.defaultdict(list)
        for (k, g, tk), (tp, p) in scan.items():
            if k == KIND and oriz in E.get(p["id"], {}):
                pg[g].append(E[p["id"]][oriz])
        for g, xs in pg.items():
            if len(xs) >= 5:
                rif[(g, oriz)] = med(xs)
    print("   %s" % KIND)
    for mom in ("ingresso_osservazione", "ingresso_anticipo", "fine_osservazione", "promozione", "fine_verifica"):
        cel = []
        for oriz in ("7g", "30g"):
            xs = [(E[p["id"]][oriz], E[p["id"]][oriz] - rif[(p["giorno"], oriz)]) for p in prof.values()
                  if p.get("kind") == KIND and p.get("momento") == mom and not p.get("scartata")
                  and oriz in E.get(p["id"], {}) and (p["giorno"], oriz) in rif]
            cel.append(("%s n%4d resa %+6.2f%% rispetto al giorno %+6.2f" % (oriz, len(xs), med([a for a, _ in xs]), med([b for _, b in xs]))) if xs else "%s nessun caso" % oriz)
        print("      %-22s %s | %s" % (mom, cel[0], cel[1]))
