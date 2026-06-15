# 📱 Come usare l'app dal telefono (come un'app installata)

Obiettivo: aprire l'app **dal telefono, ovunque, anche con il PC spento**, con un'icona in schermata Home e protetta da **password**.

La soluzione è pubblicare l'app gratuitamente su **Streamlit Community Cloud**. Si fa una volta sola.

---

## 1) Scegli la password
Apri il file `.streamlit/secrets.toml` e sostituisci `cambia-questa-password` con la password che vuoi.
La stessa password la reimposterai sul cloud (passo 5).

## 2) Crea un account GitHub (gratis)
- Vai su https://github.com → **Sign up**.
- GitHub serve a ospitare il codice dell'app.

## 3) Carica la cartella del progetto su GitHub
Modo più semplice (senza comandi):
1. Scarica e installa **GitHub Desktop**: https://desktop.github.com
2. Accedi con il tuo account GitHub.
3. `File → Add local repository` → seleziona la cartella `analisi_finanziaria`.
   (Se chiede di creare il repository, accetta: "create a repository".)
4. Dai un nome (es. `analisi-finanziaria`) → **Publish repository**.
   - Lascia pure la spunta **"Keep this code private"** se vuoi che sia privato.

> Il file con la password (`.streamlit/secrets.toml`) **non** viene caricato: è già escluso apposta.

## 4) Pubblica l'app su Streamlit Cloud
1. Vai su https://share.streamlit.io → **Sign in with GitHub** (stesso account).
2. Clicca **Create app** → **Deploy a public app from GitHub**.
3. Compila:
   - **Repository**: `tuo-utente/analisi-finanziaria`
   - **Branch**: `main`
   - **Main file path**: `app.py`
4. Clicca **Advanced settings** → **Secrets** e incolla:
   ```
   app_password = "la-tua-password"
   ```
   (la stessa del passo 1)
5. Clicca **Deploy**. Dopo 1-2 minuti avrai un link tipo:
   `https://analisi-finanziaria-xxxx.streamlit.app`

## 5) Apri il link sul telefono e mettilo in Home (come un'app)
Apri quel link dal telefono, inserisci la password, poi:

- **iPhone (Safari):** tocca il pulsante **Condividi** (quadrato con freccia) → **Aggiungi a Home**.
- **Android (Chrome):** tocca il menu **⋮** in alto a destra → **Installa app** (o **Aggiungi a schermata Home**).

Comparirà un'**icona** in schermata Home: aprendola, l'app parte a tutto schermo come un'applicazione, da qualsiasi rete e anche con il PC spento.

---

## Aggiornare l'app in futuro
Se modifichi il codice: in GitHub Desktop fai **Commit** + **Push**. Streamlit Cloud si aggiorna da solo in un minuto.

## Cose da sapere
- **Watchlist:** sul cloud la lista dei preferiti può azzerarsi quando l'app viene riavviata (il cloud non conserva i file). Se ti serve persistente, dimmelo e la sposto su un piccolo database.
- **Velocità/dati:** sul cloud i dati gratuiti (Yahoo Finance) a volte sono un po' più lenti o con qualche limite rispetto al PC: normale.
- **Password:** per cambiarla in futuro, modifica il Secret su Streamlit Cloud (menu dell'app → *Settings → Secrets*).
