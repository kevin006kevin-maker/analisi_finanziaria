# -*- coding: utf-8 -*-
"""VERIFICA DEL TOKEN GITHUB dell'app - da lanciare dopo averlo rigenerato.

Perche' esiste: il token e' scaduto in silenzio e l'app ha continuato a sembrare funzionante,
perche' quando il salvataggio online non riesce nessuno lo dice. Questo script risponde alle due
domande che contano: il token e' valido? e puo' DAVVERO scrivere sul branch dei dati?

Uso:
    python verifica_token.py            solo controlli in lettura (non tocca niente)
    python verifica_token.py --scrivi   prova anche a scrivere: crea un file di prova sul branch
                                        e lo cancella subito dopo

Il token viene letto da .streamlit/secrets.toml: non va mai scritto qui dentro.
"""
import base64
import json
import os
import re
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

QUI = os.path.dirname(os.path.abspath(__file__))
SECRETS = os.path.join(QUI, ".streamlit", "secrets.toml")
PROVA = "_prova_token.json"


def leggi_secrets():
    """Prende token, repo e branch da secrets.toml, senza dipendere da Streamlit."""
    if not os.path.exists(SECRETS):
        print("NON TROVATO: " + SECRETS)
        print("   Crea il file: le istruzioni sono in CREDENZIALI-PRIVATE.txt.")
        sys.exit(1)
    valori = {}
    for riga in open(SECRETS, encoding="utf-8"):
        m = re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"?([^"#\n]*)"?', riga)
        if m:
            valori[m.group(1)] = m.group(2).strip()
    return valori


def main():
    v = leggi_secrets()
    tok = v.get("github_token", "")
    repo = v.get("data_repo", "")
    branch = v.get("data_branch", "auto-data")
    print("=" * 78)
    print("VERIFICA DEL TOKEN GITHUB")
    print("=" * 78)
    print("  repository dati : " + (repo or "(mancante!)"))
    print("  branch dati     : " + branch)
    if tok:
        print("  token           : presente, %d caratteri, inizia con %s" % (len(tok), tok[:10]))
    else:
        print("  token           : MANCANTE")
    if not (tok and repo):
        print("\nESITO: manca il token o il repository in secrets.toml. Nulla da verificare.")
        return 1
    H = {"Authorization": "Bearer " + tok, "Accept": "application/vnd.github+json"}

    print("\n1) Il token e' valido e vede il repository?")
    r = requests.get("https://api.github.com/repos/" + repo, headers=H, timeout=30)
    if r.status_code == 401:
        print("   NO - il token e' SCADUTO o revocato (401). Va rigenerato su GitHub.")
        return 1
    if r.status_code == 404:
        print("   NO - il token non vede questo repository (404).")
        print("        Controlla di avergli dato accesso proprio a questo, in Repository access.")
        return 1
    if r.status_code != 200:
        print("   NO - risposta inattesa: %s %s" % (r.status_code, r.text[:160]))
        return 1
    print("   SI - repository raggiunto (%s)" % r.json().get("full_name"))

    print("\n2) Il token puo' LEGGERE i dati sul branch?")
    r2 = requests.get("https://api.github.com/repos/%s/contents/tracking.json?ref=%s" % (repo, branch),
                      headers=H, timeout=30)
    if r2.status_code == 200:
        print("   SI - permesso Contents in lettura attivo")
    elif r2.status_code == 403:
        print("   NO - permesso Contents assente (403): nel token deve essere Read and write.")
        return 1
    else:
        print("   dubbio - risposta %s (se il file e' grande e' normale che il contenuto non" % r2.status_code)
        print("            arrivi: conta solo che non sia 401 o 403)")

    if "--scrivi" not in sys.argv:
        print("\n" + "=" * 78)
        print("ESITO: il token e' valido e legge. La SCRITTURA non e' stata provata.")
        print("Per provarla davvero (crea un file di prova sul branch e lo cancella subito):")
        print("   python verifica_token.py --scrivi")
        return 0

    print("\n3) Il token puo' SCRIVERE sul branch? (prova reale, poi ripulisce)")
    contenuto = base64.b64encode(json.dumps({"prova": "token ok"}).encode()).decode()
    url = "https://api.github.com/repos/%s/contents/%s" % (repo, PROVA)
    sha = None
    g = requests.get(url + "?ref=" + branch, headers=H, timeout=30)
    if g.status_code == 200:
        sha = g.json().get("sha")          # rimasto da una prova precedente
    body = {"message": "prova del token (file temporaneo)", "branch": branch, "content": contenuto}
    if sha:
        body["sha"] = sha
    p = requests.put(url, headers=H, json=body, timeout=30)
    if p.status_code not in (200, 201):
        print("   NO - scrittura rifiutata: %s %s" % (p.status_code, p.text[:200]))
        print("        Nel token serve Contents: Read and write su questo repository.")
        return 1
    print("   SI - file di prova creato sul branch " + branch)
    nuovo_sha = (p.json().get("content") or {}).get("sha")
    d = requests.delete(url, headers=H, timeout=30,
                        json={"message": "rimuovo il file di prova", "branch": branch,
                              "sha": nuovo_sha})
    if d.status_code == 200:
        print("   pulizia: file di prova rimosso")
    else:
        print("   pulizia: NON rimosso (%s) - cancellalo a mano dal branch: %s" % (d.status_code, PROVA))
    print("\n" + "=" * 78)
    print("ESITO: TUTTO OK - il token legge e scrive. L'app puo' salvare le tue scelte.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
