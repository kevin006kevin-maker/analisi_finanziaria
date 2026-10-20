"""Prove su dati costruiti a mano: metodi di selezione, conti mensili e le quattro correzioni per la
lunga durata. Tutto in una cartella temporanea, senza deposito remoto."""
import datetime, json, logging, os, shutil, sys, tempfile, warnings
warnings.filterwarnings("ignore"); logging.disable(logging.WARNING)
os.chdir(r"C:\Users\kevin.munaretti\Documents\programma\finanza\analisi_finanziaria")
sys.path.insert(0, os.getcwd())
import finance_utils as fu

TMP = tempfile.mkdtemp(prefix="prova_metodi_")
fu.APPDIR = TMP
fu._data_repo = lambda: None
oggi = datetime.date.today()
d = lambda n: (oggi - datetime.timedelta(days=n)).isoformat()
OK = []


def ok(msg):
    OK.append(msg)
    print("   ok:", msg)


def prof(g, tk, kind="short", momento=None, motivo=None, **t):
    base = dict(above_sma200=False, perf_1y=-20.0, perf_1m=-5.0, price=20.0, avg_dollar_vol=1e7,
                rsi=50.0, dd_high=-40.0, rebound_pot=5.0, atr_pct=3.0)
    base.update(t)
    pid = fu._profilo_id(g, kind, tk, momento) if momento else f"{g}:{kind}:{tk}:{motivo}"
    return {"id": pid, "giorno": g, "ora": g + " 08:00", "ticker": tk, "nome": "Nome " + tk,
            "kind": kind, "momento": momento, "scartata": momento is None, "motivo": motivo,
            "prezzo": base["price"], "trappola": None, "titolo": base, "punteggi": {}, "fattori": {}}


try:
    print("=== A. regole dei metodi ===")
    M = {m["chiave"]: m for m in fu.METODI_OMBRA}
    assert len(M) == 12 and "sistema_vero" in M
    p = prof(d(5), "TT", momento="promozione", above_sma200=True, rebound_pot=-2.0, dd_high=-12.0, perf_1y=15.0)
    assert fu.passa_ombra(p, M["trend_template"]) and fu.passa_ombra(p, M["ombra_trend"])
    assert fu.passa_ombra(p, M["sistema_vero"])
    p2 = dict(p, titolo=dict(p["titolo"], rebound_pot=3.0))
    assert not fu.passa_ombra(p2, M["trend_template"]), "sotto la media a 50 non passa"
    s = prof(d(5), "SCART", motivo="punteggio_basso", above_sma200=True)
    assert not fu.passa_ombra(s, M["ombra_trend"]) and not fu.passa_ombra(s, M["sistema_vero"])
    cent = prof(d(5), "CENT", motivo="prezzo_basso", dd_high=-1.0, price=0.5)
    assert not any(fu.passa_ombra(cent, m) for m in fu.METODI_OMBRA), "gli scarti tecnici non si ripescano"
    q = prof(d(5), "Q", motivo="punteggio_basso", fscore=8)
    assert fu.passa_ombra(q, M["qualita"])
    q2 = prof(d(5), "Q2", motivo="punteggio_basso", roic=15.0, gross_m=40.0)
    q3 = prof(d(5), "Q3", motivo="punteggio_basso", roic=15.0, gross_m=20.0)
    assert fu.passa_ombra(q2, M["qualita"]) and not fu.passa_ombra(q3, M["qualita"])
    r = prof(d(5), "RIMB", motivo="rischio_rendimento", rsi=30.0, avg_dollar_vol=6e7)
    r2 = prof(d(5), "RIMBP", motivo="rischio_rendimento", rsi=30.0, avg_dollar_vol=2e7)
    assert fu.passa_ombra(r, M["rimbalzo_grandi"]) and not fu.passa_ombra(r2, M["rimbalzo_grandi"])
    mx = prof(d(5), "MAX", motivo="sconto_insufficiente", dd_high=-5.0)
    assert fu.passa_ombra(mx, M["vicino_massimi"])
    assert fu._metodo_valore(prof(d(5), "X", perf_1y=21.0, perf_1m=10.0), "mom121") == ((1.21 / 1.10) - 1) * 100
    ok("regole assolute, scarti tecnici esclusi, qualità con le due strade, salita senza l'ultimo mese")

    print("=== B. scelte di un giorno: classifiche solo a giornata chiusa, un titolo ogni 30 giorni ===")
    giorno = d(6)
    P = [prof(giorno, "T%02d" % i, motivo="punteggio_basso", perf_1y=float(i * 5), perf_1m=0.0,
              atr_pct=1.0 + i * 0.3, above_sma200=True) for i in range(12)]
    righe_aperta = fu._metodi_scegli(P, giorno, {}, [M["forza_relativa"]], giornata_chiusa=False)
    assert righe_aperta == [], "a giornata aperta la classifica non si fa"
    righe = fu._metodi_scegli(P, giorno, {}, [M["forza_relativa"], M["bassa_volatilita"]], giornata_chiusa=True)
    fr = sorted(x["ticker"] for x in righe if x["metodo"] == "forza_relativa")
    bv = sorted(x["ticker"] for x in righe if x["metodo"] == "bassa_volatilita")
    print("   forza relativa:", fr, "| bassa volatilità:", bv)
    assert fr == ["T08", "T09", "T10", "T11"] and bv == ["T00", "T01", "T02", "T03"]
    ult = {}
    a1 = fu._metodi_scegli([prof(d(10), "UNO", momento="promozione")], d(10), ult, [M["sistema_vero"]])
    a2 = fu._metodi_scegli([prof(d(3), "UNO", momento="fine_verifica")], d(3), ult, [M["sistema_vero"]])
    a3 = fu._metodi_scegli([prof(d(45), "UNO", momento="promozione")], d(45), {}, [M["sistema_vero"]])
    assert len(a1) == 1 and a2 == [] and len(a3) == 1
    assert a1[0]["id"] == f"{d(10)}:short:UNO:sistema_vero" and a1[0]["atr_pct"] == 3.0
    ok("il 30% migliore e il 30% più calmo del giorno, niente classifica a giornata aperta, un titolo ogni 30 giorni")

    print("=== C. verbale delle scelte: ripasso della storia, file del giorno di scelta, niente doppioni ===")
    giorni = [d(9), d(8), d(2), d(1), oggi.isoformat()]
    tutti = []
    for g in giorni:
        tutti += [prof(g, "T%02d" % i, motivo="punteggio_basso", perf_1y=float(i * 5), perf_1m=0.0,
                       atr_pct=1.0 + i * 0.3, above_sma200=True, dd_high=-30.0) for i in range(12)]
        tutti += [prof(g, "COMP", momento="promozione", above_sma200=True, dd_high=-30.0)]
    for g in giorni:
        fu._arc_aggiungi(fu.ARC_PROFILI, [p for p in tutti if p["giorno"] == g], chiave=lambda r: r["id"], giorno=g)
    r1 = fu.registra_metodi()
    print("   primo giro:", {k: r1[k] for k in ("scritte", "giorni", "candidate", "salvate")}, "| avviati:", len(r1["avviati"]))
    assert r1["salvate"] and len(r1["avviati"]) == 12
    idx = fu.indice_archivio()
    file_ombra = sorted(k for k in idx if k.startswith(fu.ARC_OMBRA + "/"))
    print("   file delle scelte:", [os.path.basename(k) for k in file_ombra])
    sc = fu._arc_leggi_giorni(fu.ARC_OMBRA)
    assert all(os.path.basename(k)[:10] == k.split("/")[-1][:10] for k in file_ombra)
    for k in file_ombra:
        g = os.path.basename(k)[:10]
        assert all(x["giorno"] == g for x in fu.read_data_json(k, [])), "ogni riga nel file del suo giorno"
    oggi_fr = [x for x in sc if x["giorno"] == oggi.isoformat() and x["metodo"] in ("forza_relativa", "bassa_volatilita", "qualita_forza")]
    assert oggi_fr == [], "oggi niente classifiche"
    comp = [x for x in sc if x["ticker"] == "COMP" and x["metodo"] == "sistema_vero"]
    assert [x["giorno"] for x in comp] == [d(9)], "COMP una volta sola nei 30 giorni"
    fr_t11 = sorted(x["giorno"] for x in sc if x["ticker"] == "T11" and x["metodo"] == "forza_relativa")
    assert fr_t11 == [d(9)], fr_t11
    retro = {x["metodo"]: x["retroattiva"] for x in sc if x["giorno"] == d(9)}
    assert retro.get("forza_relativa") is True and retro.get("sistema_vero") is False
    r2 = fu.registra_metodi()
    assert r2["scritte"] == 0 and r2["avviati"] == [], r2
    ok("prima volta: storia ripassata, righe nel file del loro giorno; secondo giro: zero righe nuove")

    print("=== D. un metodo aggiunto dopo ripassa solo la sua storia ===")
    nuovo = {"chiave": "prova_nuovo", "nome": "Prova", "definito_il": oggi.isoformat(), "base": "viste",
             "breve": "", "spiegazione": "", "perche": "", "fonte": "",
             "regole": (("dd_high", ">=", -35.0),)}
    fu.METODI_OMBRA = fu.METODI_OMBRA + (nuovo,)
    try:
        r3 = fu.registra_metodi()
        print("   giro col metodo nuovo:", {k: r3[k] for k in ("scritte", "avviati")})
        assert r3["avviati"] == ["prova_nuovo"] and r3["scritte"] > 0
        sc3 = fu._arc_leggi_giorni(fu.ARC_OMBRA)
        assert len(sc3) == len(sc) + r3["scritte"]
        assert all(x["metodo"] == "prova_nuovo" for x in sc3 if x not in sc)
    finally:
        fu.METODI_OMBRA = fu.METODI_OMBRA[:-1]
    ok("il metodo nuovo si avvia da solo, gli altri non cambiano")

    print("=== E. conti mensili: esiti, bersaglio, universo, guardia contro le letture incomplete ===")
    sc = [x for x in fu._arc_leggi_giorni(fu.ARC_OMBRA) if x["metodo"] != "prova_nuovo"]
    t11 = next(x for x in sc if x["ticker"] == "T11" and x["metodo"] == "forza_relativa")
    t00 = next(x for x in sc if x["ticker"] == "T00" and x["metodo"] == "bassa_volatilita")
    esiti = [
        {"profilo": t11["profilo"], "orizzonte": "7g", "resa": 4.0, "max_toccato": 6.0, "scartata": True, "kind": "short", "giorno": d(2)},
        {"profilo": t11["profilo"], "orizzonte": "30g", "resa": -3.0, "max_toccato": 18.0, "scartata": True, "kind": "short", "giorno": d(1)},
        {"profilo": t00["profilo"], "orizzonte": "30g", "resa": -6.0, "max_toccato": 2.0, "scartata": True, "kind": "short", "giorno": d(1)},
    ]
    for i in range(12):
        if i not in (0, 11):
            esiti.append({"profilo": f"{d(9)}:short:T%02d:punteggio_basso" % i, "orizzonte": "7g", "resa": float(i) - 6, "scartata": True, "kind": "short", "giorno": d(2)})
    esiti.append({"profilo": f"{d(9)}:short:CENT:prezzo_basso", "orizzonte": "7g", "resa": -50.0, "scartata": True, "kind": "short", "giorno": d(2)})
    fu._arc_aggiungi(fu.ARC_ESITI, esiti, chiave=lambda r: (r["profilo"], r["orizzonte"]), giorno=d(1))
    docs = fu._calcola_conti_metodi(fu._mesi_metodi())
    mese = d(9)[:7]
    dd = docs[("short", mese)]
    riga = next(r for r in dd["metodi"]["forza_relativa"] if r[1] == "T11")
    print("   T11 forza relativa:", riga)
    assert riga[6] == 4.0 and riga[7] == -3.0 and riga[10] == round(4 * (1.0 + 11 * 0.3), 2)
    assert riga[9] == riga[10], "il 30g ha toccato +18%, sopra il bersaglio di +17,2%: venduto al bersaglio"
    riga0 = next(r for r in dd["metodi"]["bassa_volatilita"] if r[1] == "T00")
    assert riga0[9] == -6.0, "bersaglio +4% mai toccato (massimo +2%): venduto a fine mese"
    u = dd["universo"][d(9)]
    print("   universo del giorno:", u)
    assert u[0] == 11 and u[1] == 0.0, "11 titoli guardati con esito a 7 giorni, mediana 0 (lo scarto tecnico non conta)"
    w1 = fu.aggiorna_conti_metodi(tutti=True)
    print("   primo calcolo:", w1)
    assert w1["scritti"] >= 1 and not w1["motivo"]
    w2 = fu.aggiorna_conti_metodi(tutti=True)
    assert w2["scritti"] == 0 and w2["invariati"] >= 1, w2
    nome = fu._nome_conti_metodi("short", mese)
    gonfio = fu.read_data_json(nome, {})
    gonfio["metodi"]["forza_relativa"] = gonfio["metodi"]["forza_relativa"] * 3
    fu.write_data_json(nome, gonfio)
    w3 = fu.aggiorna_conti_metodi(tutti=True)
    assert w3["saltati"] >= 1 and "meno casi" in (w3["motivo"] or ""), w3
    assert fu._conta_casi(fu.read_data_json(nome, {})) == fu._conta_casi(gonfio), "il file non è stato toccato"
    fu.write_data_json(nome, dict(dd, aggiornato="x"))
    ok("esiti agganciati, bersaglio a 4 volte il movimento giornaliero, universo senza scarti tecnici, file uguale non riscritto, meno casi: non si sovrascrive")

    print("=== F. la sezione: lettura dai file, anteprima, riepilogo, confronto, calendario ===")
    fu._conti_metodi_da_file.clear(); fu._anteprima_metodi.clear()
    c = fu.conti_metodi("short")
    assert not c["anteprima"] and c["metodi"].get("forza_relativa")
    rp = fu.riepilogo_metodi(c, 30, 1, "tutto")
    fr = next(x for x in rp if x["chiave"] == "forza_relativa")
    print("   riepilogo forza relativa:", fr["scelte"], "scelte |", fr["vendite"]["7g"])
    assert fr["vendite"]["7g"]["n"] == 4 and fr["vendite"]["7g"]["med"] == 3.5 and fr["vendite"]["7g"]["eccesso"] == 3.5
    assert fu.verdetto_metodo(c, "forza_relativa")["stato"] == "presto"
    cal = fu.calendario_metodi(c, "7g", "settimana", 30, 1, "tutto")
    assert cal and any("forza_relativa" in p["celle"] for p in cal)
    prova = fu.casi_metodo(c, "forza_relativa", "prova")
    prima = fu.casi_metodo(c, "forza_relativa", "prima")
    assert all(x["giorno"] >= "2026-10-06" for x in prova) and all(x["giorno"] < "2026-10-06" for x in prima)
    shutil.rmtree(os.path.join(TMP, fu.CONTI_METODI_DIR))
    fu._conti_metodi_da_file.clear(); fu._anteprima_metodi.clear()
    c2 = fu.conti_metodi("short")
    assert c2["anteprima"] and c2["metodi"].get("forza_relativa"), "senza file: anteprima calcolata al volo"
    ok("lettura dai file, anteprima senza file, riepilogo con lo scarto dal guardato, verdetto, calendario, prova vera e prima")

    print("=== G. indice e conteggi divisi per anno (simulazione del 2027) ===")
    base_prima = json.dumps(fu.read_data_json(fu.INDICE_NAME, {}), sort_keys=True)
    vero_today = fu._today_iso
    fu._today_iso = lambda: "2027-01-05"
    try:
        es = fu._arc_aggiungi("archivio/prova", [{"id": "a"}, {"id": "b"}], chiave=lambda r: r["id"], giorno="2027-01-05")
        assert es["salvate"] and es["scritte"] == 2, es
        assert os.path.exists(os.path.join(TMP, "archivio", "indice_archivio_2027.json"))
        assert json.dumps(fu.read_data_json(fu.INDICE_NAME, {}), sort_keys=True) == base_prima, "il 2026 non si tocca"
        idx = fu.indice_archivio()
        assert "archivio/prova/2027-01-05.json" in idx and any(k.startswith(fu.ARC_OMBRA) for k in idx)
        assert [r["id"] for r in fu._arc_leggi_giorni("archivio/prova")] == ["a", "b"]
        es2 = fu._arc_aggiungi("archivio/prova", [{"id": "a"}, {"id": "c"}], chiave=lambda r: r["id"], giorno="2027-01-05")
        assert es2["scritte"] == 1
        fu._segna_conteggio("archivio/prova/2027-01-05.json", [1, 2, 3])
        fu._segna_conteggio("diario_eventi.json", [1])
        assert fu.salva_conteggi()
        c27 = fu.read_data_json("archivio/conteggi_registri_2027.json", {})
        cb = fu.read_data_json(fu.CONTEGGI_NAME, {})
        assert "archivio/prova/2027-01-05.json" in c27 and "archivio/prova/2027-01-05.json" not in cb
        assert "diario_eventi.json" in cb
        assert fu._sotto_il_conteggio_atteso("archivio/prova/2027-01-05.json", [1]) is True
        rip = fu.ripara_indice()
        assert "riparate" in rip
    finally:
        fu._today_iso = vero_today
        fu._CONTEGGI_MEM.clear()
    ok("il 2027 ha il suo indice e la sua tabella dei conteggi, il 2026 resta com'è, la lettura li unisce")

    print("=== H. archivi annuali oltre 25 pezzi ===")
    assert fu._nome_archivio("conv_log.json", 2027, 24).endswith("conv_log_2027_y.json")
    assert fu._nome_archivio("conv_log.json", 2027, 25).endswith("conv_log_2027_z025.json")
    vecchio_tetto = fu._ARCHIVIO_TETTO_BYTE
    fu._ARCHIVIO_TETTO_BYTE = 300
    try:
        for i in range(30):
            ok_, nome_p = fu._aggiungi_ad_archivio("registro_prova.json", 2027, [{"date": "2027-01-01", "i": i, "riempi": "x" * 200}])
            assert ok_, (i, nome_p)
        pezzi = fu._pezzi_archivio("registro_prova.json", 2027)
        print("   pezzi:", len(pezzi), "| ultimo:", os.path.basename(pezzi[-1][0]))
        assert len(pezzi) == 30 and sum(len(r) for _, r in pezzi) == 30
    finally:
        fu._ARCHIVIO_TETTO_BYTE = vecchio_tetto
    ok("trenta pezzi in un anno, nomi dal 26° con _z025…, nessuna riga persa")

    print("=== I. il tetto dei file vivi si regola sul peso delle righe ===")
    grosse = [{"date": d(1), "testo": "x" * 3000, "i": i} for i in range(400)]
    tetto = fu._tetto_vivo_effettivo(grosse, 2000)
    print("   righe da ~3 KB, tetto dichiarato 2000 -> tetto vero", tetto)
    assert 100 <= tetto <= 160
    piccole = [{"date": d(1), "i": i} for i in range(50)]
    assert fu._tetto_vivo_effettivo(piccole, 1500) == 1500
    ok("righe pesanti abbassano il tetto, righe leggere lo lasciano com'è")

    print("=== L. nessun file oltre 950 KB ===")
    enorme = [{"testo": "y" * 1000} for _ in range(1000)]
    assert fu.write_data_json("prova_enorme.json", enorme) is False
    assert not os.path.exists(os.path.join(TMP, "prova_enorme.json"))
    av = fu.read_data_json(fu.AVVISI_NAME, [])
    assert any(a.get("file") == "prova_enorme.json" and a.get("sospetto_dimensione") for a in av)
    fu._SALVATAGGI_FALLITI.discard("prova_enorme.json")
    ok("scrittura rifiutata, file non creato, avviso in cima all'app")
    print()
    print("TUTTE LE PROVE SUPERATE (%d gruppi)" % len(OK))
finally:
    shutil.rmtree(TMP, ignore_errors=True)
