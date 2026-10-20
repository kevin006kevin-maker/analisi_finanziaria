"""Seconda parte del giro: copertura degli esiti, esiti di sistema, diario senza profilo, scelte dei metodi per giorno."""
import collections, datetime, json, os, subprocess, sys, warnings, logging
warnings.filterwarnings("ignore"); logging.disable(logging.WARNING)
APP = r"C:\Users\kevin.munaretti\Documents\programma\finanza\analisi_finanziaria"
os.chdir(APP); sys.path.insert(0, APP)
REF = "origin/auto-data"
oggi = datetime.date.today()


def gs(f):
    r = subprocess.run(["git", "show", f"{REF}:{f}"], capture_output=True, text=True, encoding="utf-8")
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None


idx = gs("archivio/indice_archivio.json") or {}
def area(a, dal=None):
    out = []
    for nome in sorted(idx):
        if nome.startswith(f"archivio/{a}/") and (dal is None or os.path.basename(nome)[:10] >= dal):
            out += [r for r in (gs(nome) or []) if isinstance(r, dict)]
    return out

profili = area("profili", "2026-08-19")
esiti = area("esiti", "2026-08-26")
E = collections.defaultdict(set)
for e in esiti:
    E[e.get("profilo")].add(e.get("orizzonte"))
print("### A. COPERTURA DEGLI ESITI (profili con prezzo e caratteristiche)")
for oriz, gg in (("7g", 7), ("30g", 30)):
    lim = (oggi - datetime.timedelta(days=gg + 4)).isoformat()      # scaduti da almeno 4 giorni
    dovuti = [p for p in profili if p.get("prezzo") and p.get("titolo") and p["giorno"] <= lim]
    fatti = [p for p in dovuti if oriz in E.get(p["id"], ())]
    per_g = collections.defaultdict(lambda: [0, 0])
    for p in dovuti:
        per_g[p["giorno"]][0] += 1
        per_g[p["giorno"]][1] += oriz in E.get(p["id"], ())
    peggiori = sorted(((v[1] / v[0], g, v) for g, v in per_g.items() if v[0] >= 20))[:3]
    print("   %-3s dovuti %5d, con esito %5d (%d%%) | giornate peggiori: %s" % (
        oriz, len(dovuti), len(fatti), round(100 * len(fatti) / max(1, len(dovuti))),
        [(g, "%d su %d" % (v[1], v[0])) for _q, g, v in peggiori]))
sosp = sum(1 for e in esiti if e.get("dati_sospetti"))
inc = sum(1 for e in esiti if e.get("finestra_incompleta"))
print("   esiti marcati sospetti %d, finestra incompleta %d, su %d" % (sosp, inc, len(esiti)))

print("\n### B. ESITI «DI SISTEMA» (vendita quando il sistema toglie il titolo)")
sist = [e for e in esiti if e.get("orizzonte") == "sistema"]
per_g = collections.Counter(e.get("giorno") for e in sist)
print("   totali %d | ultimi giorni: %s" % (len(sist), {g: per_g[g] for g in sorted(per_g)[-6:]}))
diario = gs("diario_eventi.json") or []
usc = collections.Counter(str(r.get("data") or "")[:10] for r in diario if r.get("evento") == "uscita")
print("   uscite a verbale nel diario, ultimi giorni:", {g: usc[g] for g in sorted(usc)[-6:]})
motivi = collections.Counter(str(e.get("motivo_uscita") or "")[:28] for e in sist if e.get("giorno", "") >= "2026-10-05")
print("   motivi delle uscite dal 5/10:", dict(motivi.most_common(5)))

print("\n### C. MOMENTI D'ACQUISTO NEL DIARIO SENZA PROFILO (buchi)")
import finance_utils as fu
acq = fu.eventi_acquisto()
ids = {p["id"] for p in profili}
buchi = collections.Counter()
for r in diario:
    if r.get("evento") in acq and str(r.get("data") or "")[:10] >= "2026-09-20":
        pid = fu._profilo_id(str(r.get("data"))[:10], r.get("kind"), r.get("ticker"), r.get("evento"))
        if pid not in ids:
            buchi[str(r.get("data"))[:10]] += 1
print("   dal 20/09: %d momenti senza profilo %s" % (sum(buchi.values()), dict(buchi) or ""))

print("\n### D. SCELTE DEI METODI PER GIORNO (breve), dopo le correzioni")
ombra = area("ombra", "2026-10-05")
tab = collections.defaultdict(lambda: collections.Counter())
for r in ombra:
    if r.get("kind") == "short":
        tab[r["metodo"]][r["giorno"]] += 1
giorni = sorted({r["giorno"] for r in ombra})
print("   %-22s " % "metodo" + " ".join(g[5:] for g in giorni))
for m in [x["chiave"] for x in fu.METODI_OMBRA]:
    print("   %-22s " % m[:22] + " ".join("%5d" % tab[m].get(g, 0) for g in giorni))
# l'insieme di partenza e' rimasto stabile?
per_g = collections.defaultdict(lambda: [0, 0, 0])
for p in profili:
    if p["giorno"] >= "2026-10-01" and p.get("kind") == "short":
        per_g[p["giorno"]][0] += 1
        per_g[p["giorno"]][1] += fu._metodi_visto(p)
        per_g[p["giorno"]][2] += fu._metodo_in_base(p, "comprate_prima")
print("   profili al giorno (breve): totali / guardati con giudizio / comprabili dal sistema di prima")
print("   " + " | ".join("%s %d/%d/%d" % (g[5:], v[0], v[1], v[2]) for g, v in sorted(per_g.items())))
