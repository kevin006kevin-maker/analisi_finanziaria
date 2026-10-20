"""Sui dati veri, in sola lettura: le scelte dei metodi, i conti mensili e il loro peso."""
import collections, json, logging, os, sys, time, warnings
warnings.filterwarnings("ignore"); logging.disable(logging.WARNING)
os.chdir(r"C:\Users\kevin.munaretti\Documents\programma\finanza\analisi_finanziaria")
sys.path.insert(0, os.getcwd())
import finance_utils as fu

scritture = []
_vero_write = fu.write_data_json
fu.write_data_json = lambda name, obj, force=False: scritture.append(name) or True   # nessuna scrittura

t0 = time.time()
scelte = fu._scelte_in_memoria()
print("scelte calcolate: %d in %.0fs" % (len(scelte), time.time() - t0))
per = collections.Counter((r["kind"], r["metodo"]) for r in scelte)
giorni = collections.defaultdict(set)
for r in scelte:
    giorni[(r["kind"], r["metodo"])].add(r["giorno"])
for kind in ("short", "long"):
    print("\n%s" % kind)
    for m in fu.METODI_OMBRA:
        k = (kind, m["chiave"])
        n, g = per.get(k, 0), len(giorni.get(k, ()))
        print("   %-26s scelte %5d  giornate %3d  al giorno %4.1f" % (m["nome"][:26], n, g, (n / g if g else 0)))
print("\nrighe al giorno in media: %.1f | peso medio di una riga: %.0f byte" % (
    len(scelte) / max(1, len({r["giorno"] for r in scelte})),
    len(json.dumps(scelte, ensure_ascii=False, indent=0).encode("utf-8")) / max(1, len(scelte))))
print("oggi, metodi con classifica: %d righe (devono essere 0)" % sum(
    1 for r in scelte if r["giorno"] == fu._arc_oggi() and r["metodo"] in ("forza_relativa", "bassa_volatilita", "qualita_forza")))

t0 = time.time()
docs = fu._calcola_conti_metodi(fu._mesi_metodi(), scelte=scelte)
print("\nconti mensili calcolati in %.0fs:" % (time.time() - t0))
for (kind, mese), d in sorted(docs.items()):
    peso = len(json.dumps(dict(d, aggiornato="2026-10-06 12:00"), ensure_ascii=False, indent=0).encode("utf-8"))
    print("   %-5s %s  casi %5d  giornate dell'universo %3d  peso %6.1f KB" % (kind, mese, fu._conta_casi(d), len(d["universo"]), peso / 1024))

for kind in ("short", "long"):
    c = fu._unisci_conti([d for (k, _m), d in docs.items() if k == kind], kind)
    print("\n=== %s: riepilogo (tutti i giorni) ===" % kind)
    vend = fu.METODI_VENDITE[kind]
    print("   %-26s %6s | %s" % ("metodo", "scelte", " | ".join("%-34s" % v for v in vend)))
    for r in fu.riepilogo_metodi(c, 30, 1, "tutto"):
        celle = []
        for v in vend:
            s = r["vendite"][v]
            celle.append(("n%4d %+6.2f%% %3d%% ecc %s" % (s["n"], s["med"], s["hit"], ("%+.2f" % s["eccesso"]) if s.get("eccesso") is not None else "  —  ")) if s.get("n") else "%-34s" % "nessun caso")
        print("   %-26s %6d | %s" % (r["nome"][:26], r["scelte"], " | ".join("%-34s" % x for x in celle)))
print("\nscritture tentate durante la prova:", scritture or "nessuna")
