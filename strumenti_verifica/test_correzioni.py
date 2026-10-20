"""Prove delle correzioni del 07/10/2026 e dei due metodi nuovi.
A. La catena riscritta, con le soglie di prima, decide ESATTAMENTE come il codice di prima.
B. Con le soglie nuove cambia solo quello che deve cambiare, e il verdetto di prima va a verbale giusto.
C. I metodi: insieme di partenza stabile, sistema di prima e sistema corretto.
D. Il lavoro automatico avvia solo i due metodi nuovi.
E. Gli esiti portano il verdetto di prima, e il riferimento dei conti non si sposta."""
import datetime, importlib.util, json, logging, os, random, shutil, sys, tempfile, warnings
warnings.filterwarnings("ignore"); logging.disable(logging.WARNING)
APP = r"C:\Users\kevin.munaretti\Documents\programma\finanza\analisi_finanziaria"
os.chdir(APP); sys.path.insert(0, APP)
os.environ["DATA_LOCAL_FIRST"] = "1"
import pandas as pd
import finance_utils as fu
spec = importlib.util.spec_from_file_location(
    "fu_prima", r"C:\Users\kevin.munaretti\Documents\programma\finanza\analisi_finanziaria\strumenti_verifica\finance_utils_prima.py")
fu_prima = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fu_prima)

TMP = tempfile.mkdtemp(prefix="prova_correzioni_")
for m in (fu, fu_prima):
    m.APPDIR = TMP
    m._data_repo = lambda: None
OK = []


def ok(msg):
    OK.append(msg); print("   ok:", msg)


rnd = random.Random(7)
SETTORI = ["Technology", "Healthcare", "Financial Services", "Energy", "Industrials"]


def riga_casuale(i, kind):
    def forse(v, p=0.08):
        return None if rnd.random() < p else v
    price = round(10 ** rnd.uniform(-0.5, 2.7), 2)
    r = {"ticker": "T%04d" % i, "name": "Nome %d" % i, "price": price,
         "avg_dollar_vol": forse(10 ** rnd.uniform(4.5, 10)), "perf_1y": forse(rnd.uniform(-90, 200)),
         "perf_5d": forse(rnd.uniform(-15, 15)), "perf_1m": forse(rnd.uniform(-40, 40)),
         "rsi": forse(rnd.uniform(8, 85), 0.03), "below_bb": rnd.random() < 0.15,
         "above_sma200": rnd.choice([True, False, None]), "dd_high": forse(rnd.uniform(-95, 0), 0.03),
         "reversal_confirmed": rnd.random() < 0.4, "green_day": rnd.choice([True, False, None]),
         "rvol": forse(rnd.uniform(0.3, 3.0)), "vertical_crash": rnd.random() < 0.07,
         "rr": forse(rnd.uniform(0.1, 6.0)), "rebound_pot": forse(rnd.uniform(-10, 40)),
         "exp_ret": rnd.uniform(-5, 20), "prob_gain": rnd.randint(20, 80), "prob_loss": rnd.randint(5, 50),
         "reliab": "🟡 Media", "rsi_rising": rnd.random() < 0.5, "back_in_bb": rnd.random() < 0.2, "etf": False}
    if kind == "long":
        etf = rnd.random() < 0.25
        r.update({"etf": etf, "fscore": (None if etf else forse(rnd.uniform(0, 100), 0.15)),
                  "sortino": forse(rnd.uniform(-2, 3)), "ulcer": forse(rnd.uniform(0, 40)),
                  "trap": {"strong": rnd.random() < 0.08, "signals": ["x"], "factor": rnd.uniform(0.7, 1.0),
                           "label": "etichetta"}, "sector": rnd.choice(SETTORI)})
    return r


def prepara(m, righe, conv, regime, catena=None):
    cattura = []
    m.opportunity_row = lambda t, with_fundamentals=False: dict(righe[t])
    m._benchmark_perf = lambda: {"perf_5d": 0.5, "perf_1m": 1.0}
    m._score_universe = lambda rows, kind: {r["ticker"]: conv[r["ticker"]] for r in rows}
    m.volatility_regime = lambda: {"factor": regime}
    m._log_convenience = lambda *a, **k: None
    m.registra_regole = lambda *a, **k: None
    m.scala_convenienza = lambda *a, **k: {}
    m._prepara_contesto_scansione = lambda kind, rows: {"giorno": "2026-10-07"}
    m.accoda_senza_profilo = lambda *a, **k: None
    m._candidati_e_origine = lambda kind: {}

    def _cattura(r, kind, motivo, dettaglio=None, conv=None, punteggio=None, ctx=None, catena_di_prima=None):
        cattura.append((r["ticker"], motivo, json.dumps(dettaglio), conv, punteggio, catena_di_prima))
    m._accoda_scarto = _cattura
    if catena is not None:
        m._CATENA_ORA = catena
    return cattura


try:
    print("=== A. con le soglie di prima la catena nuova decide come il codice di prima ===")
    vere = dict(fu._CATENA_ORA)
    for kind in ("short", "long"):
        for regime in (1.0, 0.8):
            righe = {}
            for i in range(2500):
                r = riga_casuale(i, kind)
                righe[r["ticker"]] = r
            conv = {tk: rnd.randint(10, 95) for tk in righe}
            c_prima = prepara(fu_prima, righe, conv, regime)
            df_prima = fu_prima.scan_opportunities(list(righe), kind)
            c_nuova = prepara(fu, righe, conv, regime, catena=dict(fu._CATENA_PRIMA))
            df_nuova = fu.scan_opportunities(list(righe), kind)
            fu._CATENA_ORA = vere
            a = sorted(x[:5] for x in c_prima)
            b = sorted(x[:5] for x in c_nuova)
            assert a == b, (kind, regime, [x for x in a if x not in b][:3], [x for x in b if x not in a][:3])
            assert df_prima.fillna("—").equals(df_nuova.fillna("—")), (kind, regime)
            assert all(x[5] is None for x in c_nuova) or all(x[1] in fu._MOTIVI_DELLE_CORREZIONI for x in c_nuova if x[5])
            motivi = sorted({x[1] for x in c_prima})
            print("   %-5s regime %.1f: %4d scarti identici, %3d tenute identiche | motivi %s" % (kind, regime, len(a), len(df_prima), motivi))
    ok("2.500 titoli per tipo e regime: scarti, dettagli, punteggi e tabella delle tenute identici al codice di prima")

    print("=== B. con le soglie nuove cambia solo quello che deve cambiare ===")
    for kind in ("short", "long"):
        righe = {}
        for i in range(3000):
            r = riga_casuale(i, kind)
            righe[r["ticker"]] = r
        conv = {tk: rnd.randint(10, 95) for tk in righe}
        c_prima = prepara(fu_prima, righe, conv, 1.0)
        df_prima = fu_prima.scan_opportunities(list(righe), kind)
        c_nuova = prepara(fu, righe, conv, 1.0)
        df_nuova = fu.scan_opportunities(list(righe), kind)
        dec_prima = {x[0]: x[1] for x in c_prima}
        for tk in df_prima.index:
            dec_prima[tk] = "tenuta"
        dec_nuova = {x[0]: (x[1], x[5]) for x in c_nuova}
        for tk in df_nuova.index:
            dec_nuova[tk] = ("tenuta", None)
        cambiati = correzioni = 0
        for tk, (m_new, prima) in dec_nuova.items():
            m_old = dec_prima[tk]
            if m_old == "troppi_dello_stesso_settore":
                m_old = "tenuta"            # il tetto per settore dipende da quante ne restano: si guarda prima del tetto
            if m_new == "troppi_dello_stesso_settore":
                m_new = "tenuta"
            if m_new in fu._MOTIVI_DELLE_CORREZIONI:
                correzioni += 1
                assert prima == m_old, (tk, m_new, prima, m_old)
                if m_new != m_old:
                    cambiati += 1
            else:
                assert prima is None and m_new == m_old, (tk, m_new, m_old)
        # nessuna tenuta nuova sotto le soglie nuove
        for tk in df_nuova.index:
            r = righe[tk]
            assert r["price"] >= 10 and (r["avg_dollar_vol"] is None or r["avg_dollar_vol"] >= 2e7)
            assert r["perf_1y"] is None or r["perf_1y"] >= -30
        print("   %-5s: tenute prima %d, ora %d | fermati dalle correzioni %d, di cui %d prima passavano oltre quel filtro" % (
            kind, len(df_prima), len(df_nuova), correzioni, cambiati))
        assert len(df_nuova) <= len(df_prima) + 4 * len(SETTORI)
    ok("le correzioni fermano solo prezzo, scambi e crolli; per quei titoli il verdetto di prima è quello del codice di prima; tutto il resto decide uguale")

    print("=== C. i metodi: insieme di partenza stabile, sistema di prima, sistema corretto ===")
    M = {m["chiave"]: m for m in fu.METODI_OMBRA}
    assert len(M) == 12 and list(M)[:3] == ["sistema_vero", "sistema_di_prima", "sistema_corretto"]

    def prof(motivo=None, momento=None, prima=None, conv=70, kind="short", **t):
        base = dict(price=25.0, avg_dollar_vol=5e7, perf_1y=5.0, dd_high=-20.0, above_sma200=True)
        base.update(t)
        p = {"id": "x", "giorno": "2026-10-07", "kind": kind, "ticker": "X", "prezzo": base["price"],
             "scartata": momento is None, "motivo": motivo, "momento": momento, "convenienza": conv,
             "titolo": base, "trappola": None}
        if prima:
            p["catena_di_prima"] = prima
        return p
    # un titolo da 5 dollari: prima veniva giudicato e scartato per punteggio, ora lo ferma il prezzo
    p1 = prof(motivo="prezzo_basso", prima="punteggio_basso", price=5.0)
    assert fu._verdetto_di_prima(p1) == "punteggio_basso" and fu._metodi_visto(p1)
    # prima sarebbe entrato in osservazione: per il sistema di prima e' una comprata
    p2 = prof(motivo="poco_scambiato", prima="tenuta", conv=72, avg_dollar_vol=5e6)
    assert fu._metodo_in_base(p2, "comprate_prima") and not fu._metodo_in_base(p2, "comprate")
    assert fu.passa_ombra(p2, M["sistema_di_prima"]) and not fu.passa_ombra(p2, M["sistema_vero"])
    p3 = prof(motivo="poco_scambiato", prima="tenuta", conv=55, avg_dollar_vol=5e6)
    assert not fu.passa_ombra(p3, M["sistema_di_prima"]), "sotto il cancello di 60 non entrava"
    # un titolo da 2 dollari: non era guardato con un giudizio nemmeno prima
    p4 = prof(motivo="prezzo_basso", prima="prezzo_basso", price=2.0)
    assert not fu._metodi_visto(p4) and fu._metodo_in_base(p4, "tutte")
    # i profili di prima del 7 ottobre si leggono come sempre
    vecchio_visto = lambda p: (p.get("motivo") in fu._OMBRA_MOTIVI_VISTI) if p.get("scartata") else bool(p.get("momento"))
    for mot in ("punteggio_basso", "sconto_insufficiente", "rischio_rendimento", "convenienza_sotto_cancello",
                "troppi_dello_stesso_settore", "prezzo_basso", "poco_scambiato", "trappola_di_valore"):
        q = prof(motivo=mot)
        assert fu._metodi_visto(q) == vecchio_visto(q), mot
    for mom in ("ingresso_osservazione", "promozione"):
        q = prof(momento=mom)
        assert fu._metodi_visto(q) and fu._metodo_in_base(q, "comprate") and fu._metodo_in_base(q, "comprate_prima")
    # il sistema corretto rifa' la catena senza punteggio e rischio/rendimento
    sc = M["sistema_corretto"]
    assert fu.passa_ombra(prof(motivo="punteggio_basso", conv=65), sc), "fermato dal punteggio: per il corretto passa"
    assert fu.passa_ombra(prof(motivo="rischio_rendimento", conv=61), sc)
    assert not fu.passa_ombra(prof(motivo="punteggio_basso", conv=59), sc), "convenienza sotto 60"
    assert not fu.passa_ombra(prof(motivo="punteggio_basso", conv=65, price=9.0), sc)
    assert not fu.passa_ombra(prof(motivo="punteggio_basso", conv=65, avg_dollar_vol=1.9e7), sc)
    assert not fu.passa_ombra(prof(motivo="punteggio_basso", conv=65, perf_1y=-31.0), sc)
    assert not fu.passa_ombra(prof(motivo="punteggio_basso", conv=65, dd_high=-5.0), sc), "sconto sotto l'8%"
    assert fu.passa_ombra(prof(motivo="punteggio_basso", conv=65, dd_high=-10.0), sc)
    assert not fu.passa_ombra(prof(motivo="punteggio_basso", conv=65, dd_high=-10.0, kind="long"), sc), "nel lungo serve il 12%"
    trap = prof(motivo="punteggio_basso", conv=65, dd_high=-20.0, kind="long")
    trap["trappola"] = {"etichetta": "🛑", "conclamata": True}
    assert not fu.passa_ombra(trap, sc)
    print("   regole del sistema corretto:", fu._ombra_regole_testo(sc))
    ok("insieme di partenza invariato per i profili vecchi, sistema di prima e sistema corretto con le loro regole")

    print("=== D. il lavoro automatico avvia solo i due metodi nuovi ===")
    oggi = datetime.date.today()
    d = lambda n: (oggi - datetime.timedelta(days=n)).isoformat()
    profili = []
    for g in (d(9), d(2)):
        for i in range(12):
            q = prof(motivo="punteggio_basso", conv=65, dd_high=-20.0)
            q.update({"id": f"{g}:short:P{i:02d}:punteggio_basso", "giorno": g, "ticker": "P%02d" % i,
                      "ora": g + " 08:00", "titolo": dict(q["titolo"], perf_1m=0.0, perf_1y=float(i * 3), atr_pct=2.0)})
            profili.append(q)
    for g in (d(9), d(2)):
        fu._arc_aggiungi(fu.ARC_PROFILI, [q for q in profili if q["giorno"] == g], chiave=lambda r: r["id"], giorno=g)
    vecchi = [m["chiave"] for m in fu.METODI_OMBRA if m["chiave"] not in ("sistema_di_prima", "sistema_corretto")]
    fu._arc_aggiungi(fu.ARC_METODI_AVVII, [{"id": k, "metodo": k, "giorno": d(1)} for k in vecchi],
                     chiave=lambda r: r["id"], giorno=d(1))
    r1 = fu.registra_metodi()
    print("   giro:", {k: r1[k] for k in ("scritte", "avviati", "salvate")})
    assert sorted(r1["avviati"]) == ["sistema_corretto", "sistema_di_prima"]
    scelte = fu._arc_leggi_giorni(fu.ARC_OMBRA)
    corr = [x for x in scelte if x["metodo"] == "sistema_corretto"]
    assert corr and all(x["giorno"] == d(9) for x in corr), "ripasso della storia, un titolo ogni 30 giorni"
    assert all(x["retroattiva"] for x in corr)
    assert not [x for x in scelte if x["metodo"] == "sistema_di_prima"], "nessuna comprata: il sistema di prima non sceglie"
    ok("solo i due metodi nuovi ripassano la storia, con i giorni marcati «prima»")

    print("=== E. esiti e riferimento dei conti ===")
    pid_vecchio = f"{d(9)}:short:P01:punteggio_basso"
    pid_nuovo = f"{d(2)}:short:P02:prezzo_basso"
    esiti = [{"profilo": pid_vecchio, "orizzonte": "7g", "resa": 1.0, "scartata": True, "kind": "short", "giorno": d(2)},
             {"profilo": pid_nuovo, "orizzonte": "7g", "resa": 3.0, "scartata": True, "kind": "short", "giorno": d(1),
              "catena_di_prima": "punteggio_basso"},
             {"profilo": f"{d(2)}:short:P03:prezzo_basso", "orizzonte": "7g", "resa": -40.0, "scartata": True,
              "kind": "short", "giorno": d(1), "catena_di_prima": "prezzo_basso"}]
    fu._arc_aggiungi(fu.ARC_ESITI, esiti, chiave=lambda r: (r["profilo"], r["orizzonte"]), giorno=d(1))
    docs = fu._calcola_conti_metodi(fu._mesi_metodi())
    u = {}
    for (k, m), doc in docs.items():
        u.update(doc["universo"])
    print("   universo:", {g: v for g, v in u.items()})
    assert u[d(2)][0] == 1 and u[d(2)][1] == 3.0, "il fermato dal prezzo che prima era giudicato resta nel riferimento, il titolo da 2 dollari no"
    # risolvi_esiti copia il verdetto di prima
    q = prof(motivo="prezzo_basso", prima="punteggio_basso", price=6.0)
    q.update({"id": f"{d(8)}:short:RES:prezzo_basso", "giorno": d(8), "ticker": "RES", "ora": d(8) + " 08:00"})
    fu._arc_aggiungi(fu.ARC_PROFILI, [q], chiave=lambda r: r["id"], giorno=d(8))
    idx = pd.bdate_range(d(30), oggi.isoformat())
    fu.get_history = lambda tk, period="2y": pd.DataFrame({"Close": [6.0 + 0.01 * i for i in range(len(idx))]}, index=idx)
    re_ = fu.risolvi_esiti()
    nuovi = [e for e in fu._arc_leggi_giorni(fu.ARC_ESITI) if e.get("profilo") == q["id"]]
    print("   esiti nuovi:", re_["nuovi"], "| verdetto di prima sull'esito:", [e.get("catena_di_prima") for e in nuovi])
    assert nuovi and all(e.get("catena_di_prima") == "punteggio_basso" for e in nuovi)
    ok("gli esiti portano il verdetto di prima e il riferimento dei conti resta quello di prima")

    print("=== F. le regole del giorno registrano le soglie nuove ===")
    rg = fu.regole_del_giorno()
    print("   breve:", {k: rg["filtri_breve"][k] for k in ("prezzo_minimo", "scambi_minimi", "crollo_massimo_nell_anno")})
    print("   lungo:", {k: rg["filtri_lungo"][k] for k in ("prezzo_minimo", "scambi_minimi", "crollo_massimo_nell_anno")})
    assert rg["filtri_breve"]["prezzo_minimo"] == 10.0 and rg["filtri_lungo"]["scambi_minimi"] == 20_000_000
    assert "crollato_nell_anno" in fu.MOTIVI_SCARTO
    ok("soglie nuove nelle regole del giorno, motivo nuovo spiegato in italiano")
    print()
    print("TUTTE LE PROVE SUPERATE (%d gruppi)" % len(OK))
finally:
    shutil.rmtree(TMP, ignore_errors=True)
