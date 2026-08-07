# Guida all'installazione e all'avvio — Analisi Finanziaria

Questa guida spiega **passo per passo** come far funzionare l'app su un **nuovo PC Windows**
partendo dalla sola cartella copiata. È scritta per chi non è pratico: segui i passi in ordine.

> **Il modo più semplice (senza digitare comandi):**
> 1. Installa **Python 3.12** spuntando **"Add python.exe to PATH"** (vedi sezione 2).
> 2. Doppio clic su **`installa.bat`**: crea l'ambiente, installa tutto e avvia l'app **da solo**.
>    Si apre su `http://localhost:8507`. Le volte successive, ri-doppio-clic su `installa.bat` (parte subito).
>
> **In alternativa, a mano:** installa le librerie con `python -m pip install -r requirements.txt` nella
> cartella, poi doppio clic su **`avvia.bat`**.
>
> Se qualcosa non va, vai alla sezione **8) Risoluzione problemi**.

---

## 1) Cosa serve (in sintesi)

La cartella contiene **tutto il codice, la configurazione e i dati**. Però **NON** contiene il
"motore" per eseguirla, che va installato una volta sola sul nuovo PC:

| Serve | Perché | Incluso nella cartella? |
|---|---|---|
| **Python 3.12** | è il linguaggio con cui gira l'app | ❌ da installare |
| **Le librerie** (streamlit, pandas, ecc.) | funzioni usate dall'app | ❌ da installare con `pip` |
| **Connessione a internet** | scarica i dati di mercato in tempo reale | ❌ (serve la rete) |
| Codice dell'app (`.py`) | l'app vera e propria | ✅ già presente |
| Configurazione (`.streamlit\secrets.toml`) | chiavi API, password, collegamento ai dati | ✅ già presente |
| Dati (`tracking.json`, ecc.) | occasioni seguite, storico | ✅ già presenti |

> **In pratica:** installi Python, dai **un comando** per installare le librerie, e da lì in poi
> avvii l'app con un doppio clic. Fine.

---

## 2) Prerequisito: installare Python 3.12

1. Vai su **https://www.python.org/downloads/** e scarica **Python 3.12.x** per Windows
   (va bene anche 3.11 o 3.13; **3.12 è la scelta consigliata** perché ha tutte le librerie già pronte).
2. Avvia l'installazione. **IMPORTANTISSIMO:** nella prima schermata spunta la casella in basso
   **"Add python.exe to PATH"** prima di cliccare *Install Now*. Se salti questo passo, i comandi
   `python` non verranno riconosciuti.
3. Al termine, verifica che sia installato: apri il **Menu Start → digita "PowerShell" → invio**, e scrivi:
   ```powershell
   python --version
   ```
   Deve rispondere `Python 3.12.x`. Poi:
   ```powershell
   python -m pip --version
   ```
   Deve rispondere con una versione di pip. Se entrambi rispondono, sei pronto.

> Se `python --version` dà errore "non riconosciuto", Python non è nel PATH: reinstallalo
> ricordandoti la spunta **"Add python.exe to PATH"** (o vedi la sezione 8).

---

## 3) Aprire il Terminale DENTRO la cartella del progetto

Devi dare i comandi **dentro** la cartella `analisi_finanziaria`. Due modi:

**Modo A (più semplice):**
- Apri la cartella `analisi_finanziaria` in Esplora File.
- Clic **destro** in un punto vuoto della cartella → **"Apri nel Terminale"**
  (su Windows 10: tieni premuto **Shift** + clic destro → *"Apri finestra di PowerShell qui"*).

**Modo B (con comando):**
- Apri PowerShell dal Menu Start e spostati nella cartella (adatta il percorso al tuo nuovo PC):
  ```powershell
  cd "$env:USERPROFILE\Documenti\analisi_finanziaria"
  ```
  (oppure il percorso dove hai messo la cartella, es. `cd "D:\App\analisi_finanziaria"`).

Per sapere se sei nel posto giusto, scrivi `dir` e premi invio: devi vedere `app.py`, `avvia.bat`,
`requirements.txt`.

---

## 4) Installare le librerie (una volta sola)

> 💡 **Scorciatoia (consigliata):** invece dei passi 3 e 4, puoi fare **doppio clic su `installa.bat`**:
> crea l'ambiente, installa le librerie e avvia l'app da solo, senza digitare niente. Si auto-ripara
> anche se la cartella `.venv` è stata copiata da un altro PC. I passi manuali qui sotto restano validi
> se preferisci farli a mano.

Dal terminale aperto **dentro la cartella**, lancia questi due comandi:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

- Il primo aggiorna lo strumento di installazione (pip).
- Il secondo installa **tutte** le librerie elencate in `requirements.txt`. Richiede **internet** e può
  metterci **qualche minuto** (scarica alcune centinaia di MB la prima volta). È normale vedere tanto testo.
- Quando torna il cursore senza errori in rosso, è finito.

### Cosa viene installato e a cosa serve
| Libreria | A cosa serve |
|---|---|
| `streamlit` | l'interfaccia web dell'app (le pagine che vedi nel browser) |
| `yfinance` | scarica i dati di mercato gratuiti (prezzi, storici) |
| `pandas`, `numpy` | fanno tutti i calcoli sui dati |
| `plotly` | i grafici interattivi |
| `matplotlib` | le tabelle colorate |
| `deep-translator` | traduce in italiano notizie e descrizioni |
| `streamlit-autorefresh` | aggiorna da solo le occasioni ogni tot minuti |
| `tzdata` | gestisce i fusi orari (ora di Roma) |
| `requests` | parla con le API (FMP, Finnhub, GitHub) |
| `scikit-learn` | la verifica statistica/ML (facoltativa: se manca, l'app funziona lo stesso) |
| `exchange-calendars` | il calendario di Borsa (esclude weekend e festivi nei conteggi); se manca, l'app ripiega sui giorni feriali |

---

## 5) Avviare l'app

1. Torna nella cartella in Esplora File e fai **doppio clic su `avvia.bat`**.
   (In alternativa, dal terminale nella cartella: `python -m streamlit run app.py --server.port 8507`.)
2. Si apre una finestra nera (il "motore") e dopo pochi secondi il **browser** si apre da solo su
   **http://localhost:8507**. Se non si apre da solo, apri il browser e vai a quell'indirizzo a mano.
3. **Al primo avvio Windows può chiedere il permesso del firewall**: clicca **Consenti accesso**
   (serve solo per farla girare in locale, non espone nulla su internet).
4. L'app chiede una **password d'ingresso**: è quella salvata in `secrets.toml` (campo `app_password`),
   la stessa che usi sul telefono/cloud.

**Per fermarla:** chiudi la finestra nera, oppure premi `Ctrl + C` dentro di essa. (Finché quella
finestra è aperta, l'app è accesa.)

---

## 6) La configurazione (`.streamlit\secrets.toml`)

**Buona notizia: è già dentro la cartella e già configurata → non devi fare niente.**
Serve solo sapere cosa contiene e come rifarlo in caso di bisogno.

> 📄 Le stesse credenziali, **in chiaro e con etichette**, sono anche nel file
> **`CREDENZIALI-PRIVATE.txt`** in questa cartella (comodo per ricreare `secrets.toml` se serve, o per
> ricordarti la password d'ingresso). Anche quel file è **escluso da Git**: non condividerlo, non
> caricarlo online.

Il file si trova in `.streamlit\secrets.toml` e contiene queste voci:

| Voce | A cosa serve | Se manca |
|---|---|---|
| `app_password` | la password chiesta all'apertura | l'app non parte finché non c'è |
| `fmp_api_key` | chiave dati Financial Modeling Prep | usa le fonti di riserva (Finnhub/SEC/yfinance) |
| `finnhub_api_key` | chiave dati Finnhub | idem, degrada con grazia |
| `data_repo` | il repo GitHub da cui leggere i dati del sistema autonomo | usa solo i dati locali della cartella |
| `data_branch` | il ramo dei dati (`auto-data`) | come sopra |
| `github_token` | permette di **salvare online** le modifiche manuali (aggiungi/togli titoli) | l'app funziona ma le modifiche restano solo locali |

### Se dovessi ricrearlo da zero
Crea un file di testo chiamato **`secrets.toml`** dentro una sottocartella **`.streamlit`**, con
**questo formato** (metti i TUOI valori al posto dei segnaposto tra virgolette):

```toml
app_password = "<la-tua-password>"
fmp_api_key = "<la-tua-chiave-FMP>"
finnhub_api_key = "<la-tua-chiave-Finnhub>"

data_repo = "kevin006kevin-maker/analisi_finanziaria"
data_branch = "auto-data"

github_token = "<il-tuo-token-GitHub>"
```

> 🔒 **Sicurezza — leggi qui.** Questo file contiene credenziali vere. In particolare `github_token`
> dà accesso **in scrittura** al tuo repository, e `app_password` è la password dell'app.
> **Tieni la copia della cartella solo su dispositivi tuoi e fidati.** Non caricare `secrets.toml`
> online, non condividerlo, non metterlo in email/chat. (Il file è già escluso da Git apposta.)
> Se sospetti che il token sia finito in giro, rigeneralo su GitHub → *Settings → Developer settings
> → Personal access tokens* e aggiorna il valore qui e nei Secret di Streamlit Cloud.

---

## 7) Come funzionano i dati (per capire cosa vedrai)

- **Dati di mercato** (prezzi, grafici, indicatori): arrivano **da internet in tempo reale** (con ~15
  min di ritardo, dati gratuiti). Serve quindi la connessione.
- **Occasioni in osservazione / Monitoraggio**: l'app li **legge dal cloud** (il ramo `auto-data` del
  repo indicato in `data_repo`). Quindi su questo nuovo PC vedrai **le stesse occasioni** che vedi sul
  telefono e sul sito cloud, aggiornate dal sistema autonomo.
- **Il sistema autonomo gira sul cloud (GitHub Actions), NON su questo PC.** Non devi tenere il PC
  acceso: questo PC è un **visore + strumento manuale**. Le occasioni continuano ad aggiornarsi da sole
  online anche a PC spento.
- Se togli/aggiungi manualmente un titolo dal Monitoraggio, grazie a `github_token` la modifica viene
  **salvata online** e la ritrovi ovunque entro pochi minuti.

---

## 8) Risoluzione problemi

| Sintomo | Causa probabile | Soluzione |
|---|---|---|
| `python non riconosciuto...` | Python non è nel PATH | Reinstalla Python spuntando **"Add python.exe to PATH"**; poi riapri il terminale |
| `pip non riconosciuto` | idem | Usa sempre la forma `python -m pip ...` |
| `streamlit non riconosciuto` | le librerie non sono installate (o su un Python diverso) | Rifai `python -m pip install -r requirements.txt` nella cartella; avvia con `python -m streamlit run app.py` |
| Errori di rete/SSL durante `pip install` | manca internet, oppure proxy/antivirus bloccano | Verifica la connessione; se sei in rete aziendale può servire un proxy; riprova |
| `Port 8507 is already in use` | la porta è occupata (app già aperta?) | Chiudi l'altra finestra, oppure avvia su un'altra porta: `python -m streamlit run app.py --server.port 8600` |
| `exchange_calendars` non si installa | dipendenza non disponibile | Non è un problema: **l'app funziona lo stesso** (usa i giorni feriali). Volendo: `python -m pip install exchange-calendars` |
| Finestra firewall all'avvio | Windows chiede il permesso | Clicca **Consenti accesso** |
| La pagina non si apre da sola | il browser non parte in automatico | Apri il browser e vai a **http://localhost:8507** |
| Nessun dato / grafici vuoti / errori yfinance | limiti temporanei delle fonti gratuite o rete assente | Aspetta qualche minuto e ricarica; controlla la connessione |
| "Errore password" | password sbagliata | È il valore `app_password` in `secrets.toml` |
| Errori di installazione di `numpy`/`pandas`/`scikit-learn` | versione di Python troppo nuova senza librerie pronte | Usa **Python 3.12** (consigliato): ha tutte le librerie precompilate |

---

## 9) (Facoltativo) Ambiente virtuale, per tenere il PC pulito

I comandi della sezione 4 installano le librerie a livello globale: è il modo più semplice e
`avvia.bat` funziona subito. Se preferisci isolare le librerie in un ambiente dedicato:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.port 8507
```

> Nota: con questo metodo devi **attivare** l'ambiente (`.\.venv\Scripts\Activate.ps1`) ogni volta
> prima di avviare, oppure lanciare l'app con `.\.venv\Scripts\python.exe -m streamlit run app.py`.
> Il doppio clic su `avvia.bat` invece usa il Python globale, quindi se scegli il venv non passa da lì.

---

## 10) (Facoltativo) Aggiornare l'app in futuro

Se un domani modifichi il codice sul PC principale e vuoi riportarlo qui, basta **ricopiare i file
`.py`** aggiornati (`app.py`, `finance_utils.py`, `auto_watch.py`, ecc.) e, se cambiano le librerie,
rifare `python -m pip install -r requirements.txt`.
La cartella contiene anche una copia Git (`.git`): chi sa usarlo può fare `git pull` — ma attenzione,
solo se il codice sul PC principale è stato prima pubblicato sul repository.

---

## 11) Cosa c'è nella cartella (inventario)

| File / cartella | Cos'è |
|---|---|
| `app.py` | l'interfaccia dell'app (tutte le pagine) |
| `finance_utils.py` | il cuore: calcoli, punteggi, convenienza, dati |
| `auto_watch.py` | il motore del sistema autonomo (gira sul **cloud**, non serve avviarlo qui) |
| `backtest.py`, `ml_verify.py` | strumenti di validazione (usati dalla pagina "Validazione") |
| `requirements.txt` | l'elenco delle librerie da installare |
| `installa.bat` | **lanciatore tutto-in-uno**: al 1° avvio crea l'ambiente e installa le librerie da solo, poi avvia; le volte dopo avvia soltanto |
| `avvia.bat` | lanciatore semplice: avvia l'app (richiede che le librerie siano già installate) |
| `.streamlit\secrets.toml` | la configurazione con chiavi e password (**sensibile**) |
| `tracking.json`, `opp_watch.json`, `conv_stats.json`, `forecast_log.json`, `portfolio.json` | dati locali (occasioni, storico, portafoglio) |
| `README_AUTONOMIA.md`, `README_TELEFONO.md` | guide sul sistema autonomo e sull'uso da telefono |
| `ANALISI_MIGLIORAMENTI.md/.docx`, `ANALISI_PRECISIONE_MERCATO.md` | analisi e roadmap di miglioramento |
| `.github/`, `.devcontainer/` | configurazioni per il cloud (GitHub Actions / Codespaces): **non servono in locale**, non cancellarle se pensi di usare ancora il cloud |
| `__pycache__/` | file temporanei generati da Python: si possono ignorare |

---

### Promemoria finale
1. **Python 3.12** con *"Add to PATH"*.
2. Terminale nella cartella → `python -m pip install -r requirements.txt`.
3. Doppio clic su **`avvia.bat`** → `http://localhost:8507`.

Buon lavoro!
