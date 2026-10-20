# Prepara i dati di ieri da passare a continua_caccia.js (gli script del lavoro in parallelo non
# possono leggere file: tutto passa da `args`). Stampa il JSON da usare come `args`.
import io
import json
import os

Q = os.path.dirname(os.path.abspath(__file__))
perdite = json.load(io.open(os.path.join(Q, "perdite_trovate.json"), encoding="utf-8"))["perdite"]
abbinati = json.load(io.open(os.path.join(Q, "verdetti_abbinati.json"), encoding="utf-8"))

# I titoli già giudicati ieri (reali o scartati): quelli non si rifanno.
visti = {str(a["titolo"]).strip() for a in abbinati}
confermate = []
for a in abbinati:
    if not a.get("reale"):
        continue
    orig = next((p for p in perdite if str(p.get("titolo")).strip() == str(a["titolo"]).strip()), {})
    confermate.append({**orig, "verdetto": {"reale": True, "motivo": a.get("motivo"),
                                            "correzione_minima": a.get("correzione")}})

da_verificare = [p for p in perdite if str(p.get("titolo")).strip() not in visti]

args = {"da_verificare": da_verificare, "gia_confermate": confermate}
out = os.path.join(Q, "args_ripresa.json")
io.open(out, "w", encoding="utf-8").write(json.dumps(args, ensure_ascii=False))
print("perdite totali trovate ieri :", len(perdite))
print("gia' giudicate              :", len(visti))
print("  di cui confermate reali   :", len(confermate))
print("ancora da verificare        :", len(da_verificare))
print()
print("scritto:", os.path.basename(out))
print("Domani: passare il contenuto di questo file come `args` a continua_caccia.js")
