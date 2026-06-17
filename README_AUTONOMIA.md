# 🤖 Sistema autonomo — occasioni aggiornate ogni 15 min (anche a PC spento)

Obiettivo: le occasioni si aggiornano **da sole ogni ~15 minuti sui server di GitHub**
(anche con il tuo PC spento), e le migliori — quelle in salita per **3 giorni di fila** —
finiscono **automaticamente** nel «📌 Monitoraggio». Tu le vedi dal telefono, ovunque.

## Come funziona (in breve)
- Un **GitHub Action** (`.github/workflows/auto_watch.yml`) parte ogni 15 min, esegue
  `auto_watch.py` (scansiona le occasioni, registra l'evoluzione, promuove le migliori)
  e **salva i dati sul branch `auto-data`** del repo.
- L'**app** (anche da telefono) **legge** quei dati dal branch: vede sempre l'ultimo
  aggiornamento, indipendentemente dal tuo PC.

---

## Configurazione (una volta sola)

### 1) Carica il nuovo codice su GitHub
Con GitHub Desktop: **Commit** di tutte le modifiche + **Push** sul branch `main`.
(Vengono caricati i nuovi file: `auto_watch.py`, `.github/workflows/auto_watch.yml`, ecc.)

### 2) Imposta le chiavi API come "Secret" del repo
Servono al job per scaricare i dati di mercato (le stesse che usi sull'app).

Su GitHub, nel repo → **Settings → Secrets and variables → Actions → New repository secret**.
Aggiungi (se le usi):
- `FMP_API_KEY` = la tua chiave Financial Modeling Prep
- `FINNHUB_API_KEY` = la tua chiave Finnhub

> Senza chiavi il job funziona lo stesso, ma con dati più limitati (yfinance/SEC).

### 3) Avvia il job la prima volta
GitHub → scheda **Actions** → workflow **«Aggiornamento autonomo occasioni»** →
**Run workflow**. Dopo 1-2 minuti comparirà il branch `auto-data` con i dati.
Da lì in poi riparte da solo ogni ~15 minuti.

> ⏱️ Il cron di GitHub è "best-effort": a volte ritarda o salta qualche giro sotto carico.
> Per seguire l'evoluzione su più giorni è comunque più che sufficiente.

### 4) Di' all'app dove leggere i dati (Secret su Streamlit Cloud)
Su https://share.streamlit.io → la tua app → **Settings → Secrets**, aggiungi:
```
data_repo = "kevin006kevin-maker/analisi_finanziaria"
```
(opzionale, solo se cambi il nome del branch: `data_branch = "auto-data"`)

Salva: l'app si riavvia e mostrerà «🤖 Sistema autonomo attivo sul server».

### 5) (Opzionale) Salvare i preferiti dal telefono in modo permanente
Se vuoi che anche i «📌 Segui» / «🗑️ Smetti» fatti **a mano dal telefono** restino salvati
(non solo le aggiunte automatiche), serve un token che permetta all'app di scrivere sul repo:

1. GitHub → **Settings (profilo) → Developer settings → Personal access tokens →
   Fine-grained tokens → Generate new token**.
   - Repository access: **Only select repositories** → `analisi_finanziaria`
   - Permissions → **Contents: Read and write**
2. Copia il token e su Streamlit Cloud → **Secrets** aggiungi:
   ```
   github_token = "il-token-che-hai-copiato"
   ```

Senza questo token: le aggiunte **automatiche** funzionano comunque (le scrive il job);
solo le scelte manuali fatte sul telefono potrebbero azzerarsi al riavvio dell'app.

---

## Cose da sapere
- I **3 giorni consecutivi** si contano sui giorni reali: servono almeno 3 giorni di run
  del job perché scattino le prime promozioni automatiche.
- **Frequenza:** per cambiarla, modifica la riga `cron:` in `.github/workflows/auto_watch.yml`
  (es. `"*/30 * * * *"` per ogni 30 min). Repo pubblico = minuti Actions gratis e illimitati.
- **Dati gratuiti:** le API gratuite hanno limiti giornalieri; quando si esauriscono il job
  usa le fonti di riserva (Finnhub/SEC/yfinance), come già fa l'app.
- In **locale** (senza `data_repo` configurato) l'app continua a funzionare come prima:
  il motore gira mentre la pagina Occasioni è aperta.

---

## 🔔 Notifiche su Telegram (occasioni promosse)

Quando un'occasione viene promossa automaticamente (in salita da 3 giorni), il sistema
ti manda un **messaggio Telegram** sul telefono. Gratis. Configurazione una tantum:

### 1) Crea il bot
- Sul telefono apri **Telegram** → cerca **@BotFather** → avvia la chat.
- Scrivi `/newbot` e segui le istruzioni (nome a piacere; lo *username* deve finire con `bot`).
- BotFather ti dà un **token** tipo `123456789:AAH...` → copialo.

### 2) Trova il tuo chat_id
- Su Telegram cerca **@userinfobot** → avvia → ti risponde con **Id: 123456789**.
  Quel numero è il tuo **chat_id**.
- ⚠️ Importante: apri anche la chat con **il TUO bot** (quello creato al punto 1) e premi
  **Avvia/Start**, altrimenti il bot non può scriverti.

### 3) Metti i due valori nei Secret del repo
GitHub → repo → **Settings → Secrets and variables → Actions → New repository secret**:
- `TELEGRAM_BOT_TOKEN` = il token del punto 1
- `TELEGRAM_CHAT_ID` = il numero del punto 2

### 4) Prova che funzioni
GitHub → **Actions** → workflow **«Aggiornamento autonomo occasioni»** → **Run workflow** →
spunta la casella **«Invia solo una notifica Telegram di prova»** → **Run workflow**.
Dopo pochi secondi dovresti ricevere su Telegram il messaggio di prova ✅.

Fatto questo, riceverai una notifica ogni volta che un titolo viene promosso automaticamente.
Senza questi Secret, il sistema funziona comunque: semplicemente non invia notifiche.
