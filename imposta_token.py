# -*- coding: utf-8 -*-
"""IMPOSTA IL TOKEN GITHUB nei file locali, in un colpo solo.

Perche' esiste: il token va scritto in TRE posti e uno e' facilissimo da dimenticare
(in CREDENZIALI-PRIVATE.txt compare DUE volte, in due formati diversi). Il terzo posto e'
Streamlit Cloud e va fatto dal browser: questo script te lo ricorda alla fine.

Uso:
    python imposta_token.py

Ti chiede il token senza mostrarlo a schermo (non resta nella cronologia del terminale),
fa una copia di sicurezza dei file, sostituisce, e poi verifica che funzioni davvero.
"""
import getpass
import os
import re
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

QUI = os.path.dirname(os.path.abspath(__file__))
CRED = os.path.join(QUI, "CREDENZIALI-PRIVATE.txt")
SECRETS = os.path.join(QUI, ".streamlit", "secrets.toml")


def sostituisci(percorso, attesi):
    """Sostituisce il valore di github_token nei due formati possibili. Ritorna quante righe ha
    cambiato, senza mai stampare il token."""
    if not os.path.exists(percorso):
        print("   SALTATO (non esiste): " + percorso)
        return 0
    shutil.copy2(percorso, percorso + ".bak")
    righe = open(percorso, encoding="utf-8").read().splitlines(keepends=True)
    fatti = 0
    for i, riga in enumerate(righe):
        # formato 1:  github_token    : valore
        m1 = re.match(r'^(\s*github_token\s*:\s*)\S.*?(\r?\n?)$', riga)
        # formato 2:  github_token = "valore"
        m2 = re.match(r'^(\s*github_token\s*=\s*")[^"]*("\s*\r?\n?)$', riga)
        if m2:
            righe[i] = m2.group(1) + TOKEN + m2.group(2)
            fatti += 1
        elif m1:
            righe[i] = m1.group(1) + TOKEN + m1.group(2)
            fatti += 1
    open(percorso, "w", encoding="utf-8").writelines(righe)
    nome = os.path.basename(percorso)
    esito = "OK" if fatti == attesi else "ATTENZIONE"
    print("   %-28s righe aggiornate: %d (attese %d)  %s" % (nome, fatti, attesi, esito))
    if fatti != attesi:
        print("      la copia di sicurezza e' in " + nome + ".bak")
    return fatti


print("=" * 78)
print("IMPOSTAZIONE DEL TOKEN GITHUB")
print("=" * 78)
print("Incolla il token nuovo (non verra' mostrato a schermo) e premi Invio.")
print("Deve iniziare con  github_pat_  oppure  ghp_")
if sys.stdin.isatty():
    TOKEN = getpass.getpass("Token: ").strip()
else:
    # senza un terminale vero (es. avvio da uno script) getpass si bloccherebbe: qui si legge
    # normalmente, avvisando che il token resta visibile a schermo.
    print("(nota: qui l'input NON viene nascosto, il token sara' visibile)")
    TOKEN = (sys.stdin.readline() or "").strip()

if not TOKEN:
    print("\nNessun token inserito: non ho toccato niente.")
    sys.exit(1)
if not re.match(r'^(github_pat_[A-Za-z0-9_]+|ghp_[A-Za-z0-9]+)$', TOKEN):
    print("\nQuesto non sembra un token GitHub (deve iniziare con github_pat_ o ghp_ e non")
    print("contenere spazi). Non ho toccato niente: controlla di averlo copiato per intero.")
    sys.exit(1)
print("\nToken ricevuto: %d caratteri, inizia con %s\n" % (len(TOKEN), TOKEN[:11]))

print("1) Aggiorno i file locali (con copia di sicurezza .bak)")
a = sostituisci(CRED, attesi=2)          # nel file credenziali compare DUE volte
b = sostituisci(SECRETS, attesi=1)

if a + b == 0:
    print("\nNon ho trovato nessuna riga github_token da sostituire: controlla i file a mano.")
    sys.exit(1)

print("\n2) Verifico che il token funzioni davvero (lettura e scrittura)")
ver = os.path.join(QUI, "verifica_token.py")
if os.path.exists(ver):
    esito = subprocess.run([sys.executable, ver, "--scrivi"]).returncode
else:
    print("   verifica_token.py non trovato: salto la verifica")
    esito = 0

print("\n" + "=" * 78)
print("RESTA DA FARE A MANO (dal browser), se usi l'app anche dal telefono:")
print("  share.streamlit.io -> apri l'app -> i tre puntini -> Settings -> Secrets")
print("  sostituisci la riga  github_token = \"...\"  e salva. L'app si riavvia da sola.")
print()
print("Poi chiudi e riapri l'app in locale.")
print("Quando tutto funziona puoi cancellare i file .bak.")
sys.exit(esito)
