"""Sui dati veri, in sola lettura: i metodi gia' avviati scelgono come prima, i due nuovi come previsto."""
import collections, json, logging, os, statistics as st, sys, warnings
warnings.filterwarnings("ignore"); logging.disable(logging.WARNING)
os.chdir(r"C:\Users\kevin.munaretti\Documents\programma\finanza\analisi_finanziaria")
sys.path.insert(0, os.getcwd())
import finance_utils as fu
fu.write_data_json = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("nessuna scrittura in questa prova"))

profili = [p for p in fu._arc_leggi_giorni(fu.ARC_PROFILI) if isinstance(p, dict)]
archiviate = [r for r in fu._arc_leggi_giorni(fu.ARC_OMBRA) if isinstance(r, dict)]
print("profili:", len(profili), "| scelte gia' in archivio:", len(archiviate))

# 1. l'insieme «visto» non cambia sui profili esistenti
vecchio = lambda p: (p.get("motivo") in fu._OMBRA_MOTIVI_VISTI) if p.get("scartata") else bool(p.get("momento"))
diversi = [p["id"] for p in profili if p.get("prezzo") and p.get("kind") in ("short", "long") and fu._metodi_visto(p) != vecchio(p)]
print("profili con «visto» diverso dal codice di prima:", len(diversi), diversi[:3])
print("profili gia' con il verdetto di prima a verbale:", sum(1 for p in profili if p.get("catena_di_prima")))

# 2. ricalcolo delle scelte con il codice nuovo, giorni chiusi, contro quelle in archivio
per_g = collections.defaultdict(list)
for p in profili:
    per_g[str(p.get("giorno"))[:10]].append(p)
oggi = fu._arc_oggi()
ultimo, ricalcolate = {}, []
for g in sorted(k for k in per_g if len(k) == 10 and k < oggi):
    ricalcolate += fu._metodi_scegli(per_g[g], g, ultimo, fu.METODI_OMBRA, giornata_chiusa=True)
avviati = {m for m in {r["metodo"] for r in archiviate}}
ids_arch = {r["id"] for r in archiviate if r["giorno"] < oggi}
ids_ric = {r["id"] for r in ricalcolate if r["metodo"] in avviati}
print("\nmetodi gia' avviati:", len(avviati))
print("scelte dei giorni chiusi: in archivio %d, ricalcolate col codice nuovo %d" % (len(ids_arch), len(ids_ric)))
solo_arch = sorted(ids_arch - ids_ric)
solo_ric = sorted(ids_ric - ids_arch)
print("solo in archivio: %d %s" % (len(solo_arch), solo_arch[:4]))
print("solo ricalcolate: %d %s" % (len(solo_ric), solo_ric[:4]))
per_m = collections.Counter(i.rsplit(":", 1)[1] for i in solo_arch + solo_ric)
print("differenze per metodo:", dict(per_m))
# le differenze possono venire solo dall'ultimo giorno chiuso, se il lavoro automatico l'aveva visto a meta'
gg = collections.Counter(i[:10] for i in solo_arch + solo_ric)
print("differenze per giorno:", dict(gg))

# 3. i due metodi nuovi sui giorni passati
for kind in ("short", "long"):
    print("\n%s" % kind)
    for k in ("sistema_vero", "sistema_di_prima", "sistema_corretto"):
        xs = [r for r in ricalcolate if r["metodo"] == k and r["kind"] == kind]
        print("   %-18s scelte %4d in %3d giornate" % (k, len(xs), len({r["giorno"] for r in xs})))
    a = {r["id"].rsplit(":", 1)[0] for r in ricalcolate if r["metodo"] == "sistema_vero" and r["kind"] == kind}
    b = {r["id"].rsplit(":", 1)[0] for r in ricalcolate if r["metodo"] == "sistema_di_prima" and r["kind"] == kind}
    print("   prima del 7 ottobre il sistema di prima coincide col sistema vero:", a == b)

docs = fu._calcola_conti_metodi(fu._mesi_metodi(), scelte=ricalcolate)
for kind in ("short", "long"):
    c = fu._unisci_conti([d for (k, _m), d in docs.items() if k == kind], kind)
    print("\n=== %s, tutti i giorni (tutti «prima» per i due metodi nuovi) ===" % kind)
    for r in fu.riepilogo_metodi(c, 30, 1, "tutto"):
        if r["chiave"] not in ("sistema_vero", "sistema_di_prima", "sistema_corretto", "forza_relativa", "ombra_regole_nuove"):
            continue
        cel = []
        for v in fu.METODI_VENDITE[kind][1:]:
            s = r["vendite"][v]
            cel.append(("%s n%4d %+6.2f%% vince %3d%% meglio del guardato %s" % (v, s["n"], s["med"], s["hit"], ("%+.2f" % s["eccesso"]) if s.get("eccesso") is not None else "—")) if s.get("n") else "%s nessun caso" % v)
        print("   %-28s scelte %4d | %s" % (r["nome"][:28], r["scelte"], " | ".join(cel)))
    pes = [len(json.dumps(d, ensure_ascii=False, indent=0).encode()) / 1024 for (k, _m), d in docs.items() if k == kind]
    print("   peso dei conti mensili: massimo %.0f KB" % max(pes))
