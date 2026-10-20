"""Il giro del 12/10: ogni registrazione, giorno per giorno, dal ramo dei dati. Solo lettura."""
import collections, datetime, json, logging, os, statistics as st, subprocess, sys, warnings
warnings.filterwarnings("ignore"); logging.disable(logging.WARNING)
APP = r"C:\Users\kevin.munaretti\Documents\programma\finanza\analisi_finanziaria"
os.chdir(APP); sys.path.insert(0, APP)
REF = "origin/auto-data"


def gs(f):
    r = subprocess.run(["git", "show", f"{REF}:{f}"], capture_output=True, text=True, encoding="utf-8")
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None


def ls():
    out = subprocess.run(["git", "ls-tree", "-r", "-l", REF], capture_output=True, text=True).stdout
    d = {}
    for riga in out.splitlines():
        p = riga.split(None, 4)
        if len(p) == 5 and p[3].isdigit():
            d[p[4]] = int(p[3])
    return d


FILES = ls()
oggi = datetime.date.today()
ultimo_commit = subprocess.run(["git", "log", "-1", "--format=%cd", "--date=format-local:%Y-%m-%d %H:%M", REF], capture_output=True, text=True).stdout.strip()
print("ultimo salvataggio sul ramo dati:", ultimo_commit, "(ora italiana) | file:", len(FILES))
grossi = [(f, b) for f, b in FILES.items() if b > 800_000 and "scartati" not in f and f != "archivio/conv_log_2026.json"]
print("file nuovi sopra 800 KB:", grossi or "nessuno", "| il piu' grosso fra i vivi:", max(((b, f) for f, b in FILES.items() if "/" not in f), default=None))

# ---------------------------------------------------------------- 1. archivio giornaliero per area
idx = gs("archivio/indice_archivio.json") or {}
print("\n### 1. ARCHIVIO: righe scritte per giorno (file datati per giorno)")
aree = ["profili", "esiti", "mondo", "settori", "notizie", "scatti", "osservazioni", "regole", "ombra", "metodi_avvii"]
giorni = [(oggi - datetime.timedelta(days=i)).isoformat() for i in range(11, -1, -1)]
righe = {a: {} for a in aree}
for nome, info in idx.items():
    parti = nome.split("/")
    if len(parti) != 3 or not isinstance(info, dict):
        continue
    a, g = parti[1], os.path.basename(nome)[:10]
    if a in righe:
        righe[a][g] = righe[a].get(g, 0) + int(info.get("righe") or 0)
print("   %-14s " % "area" + " ".join(g[5:] for g in giorni))
for a in aree:
    print("   %-14s " % a + " ".join("%5d" % righe[a].get(g, 0) for g in giorni))
tot = {a: sum(v.values()) for a, v in righe.items()}
print("   totali:", {a: tot[a] for a in aree})
senza_oggi = [a for a in ("profili", "mondo", "settori", "regole", "ombra") if not righe[a].get(oggi.isoformat()) and not righe[a].get(giorni[-2])]
print("   aree senza scritture negli ultimi due giorni:", senza_oggi or "nessuna")

# ---------------------------------------------------------------- 2. le correzioni del 7/10 nei profili
print("\n### 2. I FILTRI CORRETTI: che cosa e' cambiato nei profili dal 8/10")
prof_rec = []
for nome in sorted(idx):
    if nome.startswith("archivio/profili/") and os.path.basename(nome)[:10] >= "2026-10-01":
        prof_rec += [p for p in (gs(nome) or []) if isinstance(p, dict)]
per_g = collections.defaultdict(lambda: collections.Counter())
for p in prof_rec:
    g = p["giorno"]
    if p.get("scartata"):
        per_g[g][p.get("motivo")] += 1
    elif p.get("momento") == "ingresso_osservazione":
        per_g[g]["ENTRATE IN OSSERVAZIONE"] += 1
    if p.get("catena_di_prima"):
        per_g[g]["(con verdetto di prima)"] += 1
for g in sorted(per_g):
    c = per_g[g]
    print("   %s: entrate %2d | prezzo_basso %3d  poco_scambiato %3d  crollato %3d  punteggio %3d  rischio %3d | con verdetto di prima %3d" % (
        g, c["ENTRATE IN OSSERVAZIONE"], c["prezzo_basso"], c["poco_scambiato"], c["crollato_nell_anno"], c["punteggio_basso"], c["rischio_rendimento"], c["(con verdetto di prima)"]))

# ---------------------------------------------------------------- 3. gli altri registri
print("\n### 3. GLI ALTRI REGISTRI")
diario = gs("diario_eventi.json") or []
per_g = collections.Counter(str(r.get("data") or "")[:10] for r in diario)
print("   diario: %d eventi vivi | ultimi giorni: %s" % (len(diario), {g: per_g[g] for g in giorni[-6:]}))
tr = gs("tracking.json") or {}
print("   monitoraggio: %d titoli seguiti | ultimo scatto: %s" % (len(tr), max((str((e.get("snapshots") or [{}])[-1].get("date") or "") for e in tr.values()), default=None)))
w = gs("opp_watch.json") or {}
print("   osservazione: %d voci | ultima osservazione: %s" % (len(w), max((str((e.get("obs") or [{}])[-1].get("date") or "") for e in w.values()), default=None)))
av = gs("avvisi_salvataggio.json") or []
aperti = [a for a in av if isinstance(a, dict) and not a.get("risolto")]
print("   avvisi di salvataggio aperti: %d %s" % (len(aperti), [(a.get("file"), a.get("ultimo")) for a in aperti][:4]))
cw = gs("conv_weights.json") or {}
au = (cw.get("_audit") or {}).get("short") or {}
print("   pesi della convenienza: aggiornati il %s, adottati %s" % (au.get("data"), au.get("adottati")))
ps = gs("profili_sintesi.json") or {}
print("   statistiche dell'archivio: aggiornate il %s UTC, viste %d" % (ps.get("aggiornato"), len(ps.get("viste") or {})))
stato = gs("metodi/stato.json") or {}
print("   conti dei metodi: ricalcolo completo il %s UTC | file: %s" % (stato.get("ricalcolo_completo"), sorted(f for f in FILES if f.startswith("metodi/"))))
avvii = gs("archivio/metodi_avvii/2026-10-06.json") or []
for f in FILES:
    if f.startswith("archivio/metodi_avvii/") and not f.endswith("2026-10-06.json"):
        avvii += gs(f) or []
print("   metodi avviati: %d -> %s" % (len(avvii), sorted((r.get("metodo"), r.get("giorno")) for r in avvii)))

# ---------------------------------------------------------------- 4. i metodi: qual e' il migliore
print("\n### 4. I METODI: com'e' andata")
import finance_utils as fu
for kind in ("short", "long"):
    docs = [gs(f) for f in sorted(FILES) if f.startswith(f"metodi/{kind}_")]
    c = fu._unisci_conti([d for d in docs if isinstance(d, dict)], kind)
    vend = fu.METODI_VENDITE[kind]
    print("\n   %s | conti aggiornati al %s" % (kind.upper(), c.get("aggiornato")))
    for periodo, et in (("tutto", "TUTTI I GIORNI"), ("prova", "PROVA VERA (dal giorno delle regole)")):
        print("   -- %s --" % et)
        print("      %-28s %6s | %s" % ("metodo", "scelte", " | ".join("%-38s" % v for v in vend[1:])))
        rp = fu.riepilogo_metodi(c, 30, 1, periodo)
        for r in rp:
            cel = []
            for v in vend[1:]:
                s = r["vendite"][v]
                cel.append(("n%4d %+6.2f%% vince %3d%% vs guardato %s" % (s["n"], s["med"], s["hit"], ("%+.2f" % s["eccesso"]) if s.get("eccesso") is not None else "  —  ")) if s.get("n") else "%-38s" % "nessun caso maturo")
            print("      %-28s %6d | %s" % (r["nome"][:28], r["scelte"], " | ".join("%-38s" % x for x in cel)))
    print("   -- contro il sistema vero, prova vera, giornata per giornata --")
    for k in [m["chiave"] for m in fu.METODI_OMBRA if not m.get("riferimento")]:
        for v in vend[1:2]:
            b = fu.confronto_col_vivo(c, k, v, "prova")
            if b["ombra"]["quante"]:
                print("      %-28s %s: metodo n%3d %+6.2f%% | sistema vero n%3d %+6.2f%% | giornate vinte %d su %d" % (
                    fu.metodo_info(k)["nome"][:28], v, b["ombra"]["quante"], b["ombra"]["mediana"], b["vivo"]["quante"], b["vivo"]["mediana"] or 0, b["giornate_ombra_meglio"], b["giornate_con_entrambi"]))
