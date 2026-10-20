"""Quanto cresce ogni file del ramo dati, e quando sbatterebbe contro un limite. Solo lettura."""
import collections, datetime, json, os, subprocess, sys, warnings, logging
warnings.filterwarnings("ignore"); logging.disable(logging.WARNING)
APP = r"C:\Users\kevin.munaretti\Documents\programma\finanza\analisi_finanziaria"
os.chdir(APP); sys.path.insert(0, APP)
import finance_utils as fu

REF = "origin/auto-data"
oggi = datetime.date.today()


def ls():
    out = subprocess.run(["git", "ls-tree", "-r", "-l", REF], capture_output=True, text=True).stdout
    d = {}
    for riga in out.splitlines():
        parti = riga.split(None, 4)
        if len(parti) == 5 and parti[3].isdigit():
            d[parti[4]] = int(parti[3])
    return d


def gs(f):
    r = subprocess.run(["git", "show", f"{REF}:{f}"], capture_output=True, text=True, encoding="utf-8")
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None


def data_di(r):
    if isinstance(r, dict):
        for k in ("date", "data", "removed", "added", "obs_date", "pre_date"):
            v = r.get(k)
            if v and len(str(v)) >= 10 and str(v)[:4].isdigit():
                return str(v)[:10]
    return None


FILES = ls()
print("file sul ramo dati:", len(FILES), "| sopra 800 KB:", [(k, v) for k, v in FILES.items() if v > 800_000])
print()
TETTI = {"conv_log.json": fu._CONV_LOG_MAX, "forecast_log.json": fu._FORECAST_MAX,
         "exit_history.json": fu._EXIT_HISTORY_MAX_LIVE, "scenario_log.json": fu._SCENARIO_MAX_LIVE,
         "presignal_log.json": fu._PRESIGNAL_MAX_LIVE, "track_record.json": fu._TRACK_RECORD_MAX,
         "diario_eventi.json": getattr(fu, "_DIARIO_MAX", None)}
print("%-20s %6s %8s %6s %7s | %9s | %8s %8s | %s" % ("registro", "righe", "byte", "B/riga", "tetto", "vivo max", "righe/g", "pezzi/a", "giudizio"))
for nome in sorted(fu._REGISTRI_APPEND_ONLY):
    vivo = gs(nome) or []
    byte_vivo = FILES.get(nome, 0)
    bpr = byte_vivo / len(vivo) if vivo else 0
    tetto = TETTI.get(nome)
    vivo_max = (tetto * fu._MARGINE_TETTO * bpr) if tetto else None
    base = nome[:-5]
    arc = []
    for f in sorted(FILES):
        if f.startswith(f"archivio/{base}_") and f.endswith(".json"):
            d = gs(f) or []
            arc += d
    tutte = arc + vivo
    dal = (oggi - datetime.timedelta(days=28)).isoformat()
    recenti = [r for r in tutte if (data_di(r) or "") >= dal]
    rpg = len(recenti) / 28.0
    pezzi_anno = 365 * rpg * bpr / fu._ARCHIVIO_TETTO_BYTE if bpr else 0
    note = []
    if vivo_max and vivo_max > 900_000:
        note.append("VIVO OLTRE 900 KB")
    if pezzi_anno > fu._ARCHIVIO_MAX_PEZZI * 0.8:
        note.append("PEZZI ANNUALI OLTRE IL TETTO (%d)" % fu._ARCHIVIO_MAX_PEZZI)
    print("%-20s %6d %8d %6.0f %7s | %8.0fK | %8.1f %8.1f | %s" % (
        nome, len(vivo), byte_vivo, bpr, tetto, (vivo_max or 0) / 1000, rpg, pezzi_anno, ", ".join(note) or "ok"))

print()
idx = gs("archivio/indice_archivio.json") or {}
cnt = gs("archivio/conteggi_registri.json") or {}
voci_giorno = collections.Counter(os.path.basename(k)[:10] for k in idx if "/" in k and os.path.basename(k)[:4].isdigit())
recenti = [v for g, v in voci_giorno.items() if g >= (oggi - datetime.timedelta(days=28)).isoformat()]
vpg = sum(recenti) / 28.0
bpv = FILES.get("archivio/indice_archivio.json", 0) / max(1, len(idx))
print("indice: %d voci, %.0f byte/voce, %.1f voci/giorno -> +%.0f KB/anno, 1 MB fra %.1f anni" % (
    len(idx), bpv, vpg, vpg * 365 * bpv / 1000, (1_000_000 - FILES.get("archivio/indice_archivio.json", 0)) / max(1, vpg * 365 * bpv)))
bpc = FILES.get("archivio/conteggi_registri.json", 0) / max(1, len(cnt))
print("conteggi: %d voci, %.0f byte/voce -> 1 MB fra %.1f anni (stesso ritmo dell'indice)" % (
    len(cnt), bpc, (1_000_000 - FILES.get("archivio/conteggi_registri.json", 0)) / max(1, vpg * 365 * bpc)))

print()
per_area = collections.defaultdict(list)
for f, b in FILES.items():
    if f.startswith("archivio/") and f.count("/") == 2 and "scartati" not in f:
        per_area[f.split("/")[1]].append((f, b))
print("archivi giornalieri (pezzo piu' grande, pezzi nel giorno piu' pieno):")
for area, fs in sorted(per_area.items()):
    mx = max(b for _, b in fs)
    pezzi_g = collections.Counter(os.path.basename(f)[:10] for f, _ in fs)
    print("   %-14s file %4d | pezzo max %4.0f KB | max pezzi in un giorno %d" % (area, len(fs), mx / 1000, max(pezzi_g.values())))

print()
print("file di stato e conti (ricalcolati, non crescono con la storia):")
for f in ("tracking.json", "opp_watch.json", "profili_sintesi.json", "settori_titoli.json", "conv_weights.json"):
    print("   %-24s %7.0f KB" % (f, FILES.get(f, 0) / 1000))
