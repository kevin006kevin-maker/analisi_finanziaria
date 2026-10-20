# Riaggancia ogni verdetto del verificatore alla perdita che doveva refutare.
# Il giornale del lavoro salva agentId + risultato, ma non l'etichetta; il titolo della perdita
# sta invece nella domanda ricevuta dall'agente, dentro il suo verbale.
import glob
import io
import json
import os

D = (r"C:\Users\kevin.munaretti\.claude\projects\C--Users-kevin-munaretti"
     r"\d7e669d0-9484-43d5-b8b3-4c7f6f2d34d3\subagents\workflows\wf_6bcca1d4-edc")
MARK = "PERDITA DA REFUTARE"


def testo_di(v):
    """Estrae il testo da un pezzo di messaggio, in qualunque forma sia salvato."""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return "\n".join(testo_di(x) for x in v)
    if isinstance(v, dict):
        for k in ("text", "content", "value", "message", "prompt"):
            if k in v:
                return testo_di(v[k])
    return ""


# 1) agentId -> risultato
risultati = {}
for line in io.open(os.path.join(D, "journal.jsonl"), encoding="utf-8"):
    try:
        j = json.loads(line)
    except Exception:
        continue
    if j.get("type") == "result":
        risultati[j.get("agentId")] = j.get("result")

# 2) agentId -> titolo della perdita che doveva refutare
titoli = {}
for f in glob.glob(os.path.join(D, "agent-*.jsonl")):
    aid = os.path.basename(f)[len("agent-"):-len(".jsonl")]
    for line in io.open(f, encoding="utf-8", errors="ignore"):
        try:
            j = json.loads(line)
        except Exception:
            continue
        t = testo_di(j)
        if MARK not in t:
            continue
        dopo = t.split(MARK, 1)[1]
        for riga in dopo.splitlines():
            riga = riga.strip()
            if riga.startswith("titolo:"):
                titoli[aid] = riga[len("titolo:"):].strip()
                break
        if aid in titoli:
            break

coppie = []
for aid, v in risultati.items():
    if isinstance(v, dict) and "reale" in v and aid in titoli:
        coppie.append({"titolo": titoli[aid], "reale": bool(v.get("reale")),
                       "motivo": v.get("motivo"), "correzione": v.get("correzione_minima")})

print("risultati nel giornale:", len(risultati))
print("verbali con una perdita da refutare:", len(titoli))
print("verdetti riagganciati:", len(coppie), "| di cui REALI:", sum(1 for c in coppie if c["reale"]))

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verdetti_abbinati.json")
io.open(out, "w", encoding="utf-8").write(json.dumps(coppie, ensure_ascii=False, indent=1))
print("salvato:", os.path.basename(out))
print()
for c in sorted(coppie, key=lambda c: not c["reale"]):
    print(("[REALE]    " if c["reale"] else "[SCARTATA] ") + str(c["titolo"])[:92])
