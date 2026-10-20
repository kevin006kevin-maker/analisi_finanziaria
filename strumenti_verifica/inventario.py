"""Inventario dell'app: sezioni e schede con righe e testo, funzioni del motore mai chiamate,
registri dei dati che nessuno legge. Solo lettura."""
import ast, collections, json, os, re, subprocess
APP = r"C:\Users\kevin.munaretti\Documents\programma\finanza\analisi_finanziaria"
os.chdir(APP)
app = open("app.py", encoding="utf-8").read()
fu_src = open("finance_utils.py", encoding="utf-8").read()
aw = open("auto_watch.py", encoding="utf-8").read()
righe_app = app.splitlines()
print("app.py: %d righe | finance_utils.py: %d righe | auto_watch.py: %d righe" % (len(righe_app), len(fu_src.splitlines()), len(aw.splitlines())))

# ---------------------------------------------------------------- sezioni dell'app
inizi = [(i, m.group(1)) for i, l in enumerate(righe_app) for m in [re.match(r'^if section\.startswith\("(.+?)"\)', l)] if m]
print("\n### SEZIONI (righe di codice, caratteri di testo per l'utente, schede)")
TESTO = re.compile(r'st\.(caption|info|warning|success|error|markdown|write)\(|help=')
def testo_in(blocco):
    # somma dei caratteri delle stringhe letterali nelle righe di spiegazione
    tot = 0
    for l in blocco:
        if TESTO.search(l) or l.strip().startswith(('"', "f\"", "'")):
            tot += sum(len(x) for x in re.findall(r'"([^"]*)"', l))
    return tot
prima = righe_app[:inizi[0][0]]
print("   %-28s %6d righe | testo %6d car. | (prima della prima sezione: intestazione, filtri, aiuti)" % ("comune", len(prima), testo_in(prima)))
tot_testo = 0
for k, (i, nome) in enumerate(inizi):
    j = inizi[k + 1][0] if k + 1 < len(inizi) else len(righe_app)
    blocco = righe_app[i:j]
    t = testo_in(blocco); tot_testo += t
    tabs = []
    for l in blocco:
        for m in re.finditer(r'"([a-z_0-9]+)":\s*"([^"]{3,40})"', l):
            if re.search(r'_TABS|_MTABS|_ATABS|tab', l) or "📋" in l or "⚖️" in l:
                tabs.append(m.group(2))
    print("   %-28s %6d righe | testo %6d car. | schede: %s" % (nome, j - i, t, ", ".join(dict.fromkeys(tabs)) or "—"))
print("   testo totale per l'utente: %d caratteri (~%d pagine A4)" % (tot_testo, tot_testo // 3000))

# ---------------------------------------------------------------- funzioni mai chiamate
tree = ast.parse(fu_src)
defs = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
costanti = [t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)]
tutto = app + aw + fu_src
def usi(nome):
    return len(re.findall(r'\b' + re.escape(nome) + r'\b', tutto)) - 1   # meno la definizione
mai = [d for d in defs if usi(d) == 0]
# chiamate solo da funzioni a loro volta mai chiamate (a cascata)
corpo = {n.name: ast.get_source_segment(fu_src, n) for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
morte = set(mai)
cambiato = True
while cambiato:
    cambiato = False
    for d in defs:
        if d in morte:
            continue
        chiamanti = []
        for altro, src in corpo.items():
            if altro != d and re.search(r'\b' + re.escape(d) + r'\b', src):
                chiamanti.append(altro)
        fuori = len(re.findall(r'\b' + re.escape(d) + r'\b', app + aw))
        if not fuori and chiamanti and all(c in morte for c in chiamanti):
            morte.add(d); cambiato = True
righe_fn = {n.name: (n.end_lineno - n.lineno + 1) for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
print("\n### FUNZIONI DEL MOTORE MAI CHIAMATE (ne' dall'app, ne' dal lavoro automatico, ne' dal motore)")
for d in sorted(morte, key=lambda d: -righe_fn[d]):
    print("   %-40s %4d righe %s" % (d, righe_fn[d], "(chiamata solo da funzioni morte)" if d not in mai else ""))
print("   totale: %d funzioni, %d righe" % (len(morte), sum(righe_fn[d] for d in morte)))
mai_c = [c for c in costanti if usi(c) == 0]
print("\n### COSTANTI MAI USATE:", mai_c)

# ---------------------------------------------------------------- registri dei dati
print("\n### FILE DEI DATI: peso, chi li scrive e chi li legge")
out = subprocess.run(["git", "ls-tree", "-r", "-l", "origin/auto-data"], capture_output=True, text=True).stdout
pesi = {}
for riga in out.splitlines():
    p = riga.split(None, 4)
    if len(p) == 5 and p[3].isdigit():
        pesi[p[4]] = int(p[3])
nomi = {}
for m in re.finditer(r'^([A-Z_]+_NAME)\s*=\s*"([^"]+)"', fu_src, re.M):
    nomi[m.group(1)] = m.group(2)
for cost, f in sorted(nomi.items(), key=lambda kv: -pesi.get(kv[1], 0)):
    if f.startswith("archivio/"):
        continue
    legge = len(re.findall(r'read_data_json\(\s*' + cost, fu_src)) + len(re.findall(r'load_registro_completo\(\s*' + cost, fu_src))
    scrive = len(re.findall(r'(write_data_json|salva_registro)\(\s*' + cost, fu_src))
    # quali funzioni usano questa costante, e se quelle funzioni sono usate dall'app
    fn_usano = [n for n, src in corpo.items() if re.search(r'\b' + cost + r'\b', src)]
    fn_vive = [n for n in fn_usano if n not in morte]
    in_app = [n for n in fn_vive if re.search(r'\bfu\.' + n + r'\b', app)]
    in_job = [n for n in fn_vive if re.search(r'\bfu\.' + n + r'\b', aw)]
    print("   %-26s %7.0f KB | letto %2d scritto %2d | funzioni vive %2d, usate nell'app %2d, nel lavoro %2d %s" % (
        f, pesi.get(f, 0) / 1024, legge, scrive, len(fn_vive), len(in_app), len(in_job),
        ("<-- VUOTO" if pesi.get(f, 0) <= 2 else "")))
    if f in ("scenario_log.json", "forecast_log.json", "presignal_log.json", "track_record.json", "portfolio.json", "sell_alerts.json", "exit_cooldown.json"):
        print("        app usa:", in_app[:8], "| lavoro usa:", in_job[:8])

# ---------------------------------------------------------------- le schede degli Scenari e ciò che leggono
print("\n### SCHEDE DEGLI SCENARI: quali funzioni del motore chiama ciascuna")
i0 = next(i for i, n in inizi if n == "Scenari")
i1 = next(i for i, n in inizi if n == "Metodi")
blocco = righe_app[i0:i1]
tab_corrente, per_tab = "comune", collections.OrderedDict()
for l in blocco:
    m = re.match(r'\s*(if|elif) _stab == "(\w+)"', l) or re.match(r'\s*elif _stab\.startswith\("s"\)', l)
    if m:
        tab_corrente = m.group(2) if m.lastindex and m.lastindex >= 2 else "s1-s5"
    per_tab.setdefault(tab_corrente, [0, set()])
    per_tab[tab_corrente][0] += 1
    per_tab[tab_corrente][1].update(re.findall(r'\bfu\.(\w+)\(', l))
for tab, (n, fns) in per_tab.items():
    print("   %-10s %4d righe | %s" % (tab, n, ", ".join(sorted(fns))))

# ---------------------------------------------------------------- fasi del lavoro automatico
print("\n### FASI DEL LAVORO AUTOMATICO (chiamate fu.* in ordine)")
print("   " + ", ".join(dict.fromkeys(re.findall(r'\bfu\.(\w+)\(', aw))))
