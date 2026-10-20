import logging, os, subprocess, sys, time, warnings
warnings.filterwarnings("ignore"); logging.disable(logging.WARNING)
APP = r"C:\Users\kevin.munaretti\Documents\programma\finanza\analisi_finanziaria"
os.chdir(APP); sys.path.insert(0, APP)
import py_compile
for f in ("finance_utils.py", "app.py", "auto_watch.py"):
    py_compile.compile(f, doraise=True)
print("i tre file compilano", flush=True)
import finance_utils as fu, auto_watch
for n in ("esiti_di_sistema", "registra_regole", "scala_convenienza", "impara_settore", "salva_settori_titoli",
          "esiti_sistema_aperti", "registra_metodi", "aggiorna_conti_metodi", "conti_metodi", "passa_ombra",
          "riepilogo_metodi", "confronto_col_vivo", "verdetto_metodo", "calendario_metodi",
          "_tetto_vivo_effettivo", "_nome_indice", "_nome_conteggi", "_verdetto_catena", "_verdetto_di_prima", "_metodo_in_base"):
    assert callable(getattr(fu, n)), n
assert len(fu.METODI_OMBRA) == 12 and fu.METODI_OMBRA[0]["chiave"] == "sistema_vero"
assert fu._MIN_PRICE == 10.0 and fu._MIN_DOLLAR_VOL == 20_000_000 and fu._CATENA_PRIMA["short"]["prezzo"] == 3.0
assert fu._ARCHIVIO_MAX_PEZZI >= 100 and fu._TETTO_FILE_BYTE <= 950_000
print("le aggiunte sono presenti (misura sistema, metodi di selezione, tetti) e il lavoro automatico si importa", flush=True)

# NESSUN FILE DEL DEPOSITO VICINO A 1 MB, tranne i due che nessuno riscrive piu' oltre il tetto
subprocess.run(["git", "fetch", "-q", "origin", "auto-data"], capture_output=True)
out = subprocess.run(["git", "ls-tree", "-r", "-l", "origin/auto-data"], capture_output=True, text=True).stdout
NOTI = {"archivio/scartati-2026-08-21/conv_log_2026.json": "dati messi da parte il 21/08: nessuno li legge ne' li scrive",
        "archivio/conv_log_2026.json": "primo pezzo scritto prima della divisione in pezzi: fermo, e il muro di 950 KB gli impedisce di crescere"}
grossi = []
for riga in out.splitlines():
    p = riga.split(None, 4)
    if len(p) == 5 and p[3].isdigit() and int(p[3]) > 800_000:
        grossi.append((p[4], int(p[3])))
for nome, b in grossi:
    print("   file sopra 800 KB: %-52s %5.0f KB  %s" % (nome, b / 1024, ("(noto: " + NOTI[nome] + ")") if nome in NOTI else "<-- DA GUARDARE"), flush=True)
nuovi_grossi = [n for n, _ in grossi if n not in NOTI]
print("controllo dei pesi:", "ok" if not nuovi_grossi else "FILE NUOVI SOPRA 800 KB: %s" % nuovi_grossi, flush=True)

from streamlit.testing.v1 import AppTest
SEZ = [("Analisi di un titolo", {}), ("Occasioni di mercato", {}), ("In osservazione", {}), ("In anticipo", {}),
       ("Monitoraggio", {}), ("Portafoglio", {}), ("Scenari", {}), ("Scenari", {"scen_tab": "lettera"}),
       ("Metodi di selezione", {}), ("Metodi di selezione", {"met_tab": "metodo"}),
       ("Metodi di selezione", {"met_tab": "calendario"}), ("Metodi di selezione", {"met_tab": "confronto", "met_kind": "long"}),
       ("Diario dei dati", {}), ("Archivio", {}),
       ("Archivio", {"arc_tab": "imparato", "arc_imp_oriz": "sistema"}), ("Attualità", {})]
err = 0
for s, extra in SEZ:
    t0 = time.time()
    at = AppTest.from_file("app.py", default_timeout=900)
    at.session_state["auth_ok"] = True; at.session_state["section_radio"] = s
    for k, v in extra.items():
        at.session_state[k] = v
    try:
        at.run(); e = [str(x.value)[:200] for x in at.exception]
    except Exception as ex:
        e = ["ECCEZIONE: " + str(ex)[:150]]
    dt = time.time() - t0
    nome = s + (" > " + ", ".join(f"{k}={v}" for k, v in extra.items()) if extra else "")
    if e:
        err += 1; print("  ERRORE %-52s (%.0fs): %s" % (nome, dt, e[0]), flush=True)
    else:
        print("  ok %-54s (%.0fs)" % (nome, dt), flush=True)
print(); print("prove:", len(SEZ), "| errori:", err, "| file nuovi sopra 800 KB:", len(nuovi_grossi), flush=True)
