# Passaggio di consegne — App «Analisi finanziaria»

Aggiornato al **20 ottobre 2026**. Questo documento basta per riprendere il lavoro in una chat nuova senza la storia precedente. Leggerlo tutto prima di toccare qualsiasi cosa: le regole della sezione 2 non sono negoziabili.

---

## 1. Che cos'è

Webapp Streamlit personale che cerca occasioni d'acquisto in borsa, le segue nel tempo e **impara dai propri risultati**. Ha due metà:

- **L'app** (`app.py`, ~5.400 righe) che l'utente apre in locale. L'app **è già aperta sul PC dell'utente**: non va mai avviata altrove, né in un browser, né in anteprima. Le prove si fanno solo in modo nascosto con `streamlit.testing.v1.AppTest`.
- **Il lavoro automatico** (`auto_watch.py`, ~630 righe) che gira su **GitHub Actions** ogni mezz'ora (`cron: "8,38 * * * *"`, `timeout-minutes: 25`). GitHub ne esegue in pratica 4-8 al giorno: è normale, non è un guasto.
- **Il motore** (`finance_utils.py`, ~12.500 righe) usato da entrambi.

**Cartella:** `C:\Users\kevin.munaretti\Documents\programma\finanza\analisi_finanziaria` (spostata a settembre 2026; la vecchia `Documents\finanza\...` non esiste più).

**Repository:** `kevin006kevin-maker/analisi_finanziaria` su GitHub, **pubblico** (l'utente lo sa; renderlo privato è una sua decisione ancora aperta).
- ramo `main`: il codice. Ultimo commit: `bc18cb35` del 7/10/2026.
- ramo `auto-data`: **tutti i dati**. Si legge con `git fetch origin auto-data` e `git show origin/auto-data:<file>`.

**Utente:** scrive in italiano, vuole spiegazioni semplici e numeri veri. Chiede spesso «sei sicuro?»: la risposta deve essere onesta e misurata, anche se è «no».

---

## 2. Regole dell'utente (da rispettare sempre)

1. **Mai perdere dati.** Storico da tenere per sempre, anche quando un'occasione viene promossa o tolta. Nessun dato si cancella: al massimo si sposta in archivio. L'incidente del 16/08/2026 (una lettura fallita ha riscritto `[]` sopra due registri) è il motivo di tutte le protezioni.
2. **Nessun file sopra 1 MB.** Sopra 1 MB l'API di GitHub non restituisce più il contenuto e le protezioni anti-cancellazione si spengono in silenzio. Oggi c'è un muro universale a 950 KB in `write_data_json`.
3. **I commit li fa l'utente.** Non fare mai `git commit` né `git push`. A fine lavoro si dà il comando da copiare.
4. **Non avviare a mano il lavoro automatico** su GitHub senza chiedere.
5. **Non aprire l'app** da nessuna parte (browser, anteprima). È già aperta dall'utente.
6. **Verificare sui dati veri**, non sul codice. Ogni affermazione con un numero misurato.
7. **Testo dell'interfaccia in italiano semplice**, senza codici interni o gergo tra parentesi, ma con le spiegazioni di come funziona. Le emoji nell'app vanno bene (è lo stile dell'app).
8. **Regole ferme dei metodi in ombra:** una volta definite non si cambiano mai. Regole diverse = metodo nuovo con chiave nuova.
9. **L'importo per operazione resta 30 € di default** (deciso dall'utente il 7/10).
10. Prima di agire su cose importanti, spiegare brevemente cosa si farà e chiedere se ci sono dubbi.

---

## 3. Trappole tecniche già incontrate

- **Due orologi:** gli orari dell'API GitHub sono **UTC**, il PC è in ora italiana (**+2**). Confonderli ha già prodotto falsi allarmi due volte.
- **`conv_stats.json`** viene riscritto dalle prove: dopo ogni prova eseguire `git checkout conv_stats.json`.
- **Le prove AppTest** saltano la password con `at.session_state["auth_ok"] = True`. La password non si scrive mai.
- **Heredoc bash con testo italiano** (apostrofi, «») si rompe: scrivere lo script con lo strumento di scrittura file e poi lanciarlo con `python`.
- **`DATA_LOCAL_FIRST=1`** è attivo solo nel lavoro automatico: lì le letture sono da disco locale. Nell'app le letture sono remote (raw GitHub, cache 2 minuti).
- **`write_data_json` restituisce True anche se è riuscito solo il salvataggio locale**: controllare `_SALVATAGGI_FALLITI` dopo ogni scrittura importante.
- **`gh` non è installato**: per i giri del lavoro automatico usare l'API pubblica, es. `curl -s "https://api.github.com/repos/kevin006kevin-maker/analisi_finanziaria/actions/runs?per_page=60"`.
- Su Windows, `print` di caratteri come «» fallisce senza `PYTHONIOENCODING=utf-8`.

---

## 4. Come funziona il sistema

### 4.1 La catena delle occasioni

1. **Lista di partenza (universo):** liste di mercato (maggiori ribassi, ETF, Europa e Borsa Italiana, società piccole in salita, più scambiati, grandi sottovalutate, crescita sottovalutata, titoli a basso prezzo) con un tetto (40 breve / 20 lungo). Quelli oltre il tetto sono registrati come «mai guardata».
2. **Filtri iniziali** in `_verdetto_catena(r, kind, regime, soglie)`, in quest'ordine:
   - breve: prezzo minimo → scambi minimi → crollo nell'anno → punteggio ≥ 35 → sconto dai massimi ≤ −8% → rischio/rendimento ≥ 1,5 → (solo mercato agitato) cade più del mercato;
   - lungo: prezzo → scambi → crollo → trappola di valore conclamata → punteggio ≥ 50 → sconto ≤ −12% → tetto di 4 per settore.
3. **Ingresso in osservazione:** convenienza ≥ 60 (`_OBS_ENTRY_CONV`), altrimenti scarto «convenienza_sotto_cancello».
4. **In anticipo:** convenienza ≥ 65.
5. **Promozione in monitoraggio:** dopo 3 giorni (breve) / 7 (lungo) di osservazione, prezzo salito ≥ 2% e convenienza ancora ≥ 55.
6. **Monitoraggio e uscite:** stop a −2×ATR, «in perdita da troppi giorni» (5 breve / 10 lungo). La presa di profitto **avvisa soltanto**, non vende: tutte le uscite registrate sono per perdita.

### 4.2 Le correzioni del 7/10/2026 (in vigore)

Decise dopo l'indagine del 6/10. Applicate al sistema vero, breve e lungo:

| Filtro | Prima | Ora |
|---|---|---|
| Prezzo minimo | 3 $ breve, 1 $ lungo | 10 $ |
| Scambi minimi al giorno | 1 M$ breve, 300 k$ lungo | 20 M$ |
| Crollo nell'anno | nessun limite | fuori sotto −30% (motivo `crollato_nell_anno`) |

- Costanti: `_MIN_PRICE`, `_MIN_DOLLAR_VOL`, `_MIN_PRICE_LONG`, `_MIN_DOLLAR_VOL_LONG`, `_CROLLO_ANNO_MAX`, raccolte in `_CATENA_ORA`. La catena vecchia è in `_CATENA_PRIMA`.
- Quando un titolo è fermato da una delle correzioni, il profilo porta `catena_di_prima` = che cosa avrebbe deciso la catena vecchia («tenuta» o un motivo). Il campo viene copiato anche negli esiti.
- Verificato: con le soglie vecchie la catena riscritta decide **identicamente** al codice precedente su 10.000 titoli inventati (`test_correzioni.py`).
- `regole_del_giorno()` registra ogni giorno le soglie in `archivio/regole`.

### 4.3 I dati (ramo `auto-data`)

**File vivi** (con tetto e archiviazione automatica negli archivi annuali `archivio/<registro>_<anno>.json`, divisi in pezzi `_b … _y`, poi `_z025 …`, fino a 400 pezzi):

| File | A cosa serve |
|---|---|
| `tracking.json` | titoli in monitoraggio con i loro scatti |
| `opp_watch.json` | titoli in osservazione |
| `diario_eventi.json` | diario: un evento per ogni cambio di stato, con i valori del momento |
| `conv_log.json` | registro della convenienza: alimenta i pesi appresi (`conv_weights.json`) |
| `exit_history.json` | uscite dal monitoraggio |
| `presignal_log.json` | pre-segnali per «In anticipo» |
| `scenario_log.json`, `forecast_log.json`, `track_record.json` | registri vecchi, vedi sezione 7 |
| `profili_sintesi.json` | statistiche dell'archivio per l'app (due volte al giorno) |
| `avvisi_salvataggio.json` | salvataggi falliti: banner in cima a ogni pagina dell'app |

**Archivio dell'apprendimento** (`archivio/<area>/<giorno>.json`, un file per giorno, i giorni passati non si riscrivono, dedup per id, pezzi a 450 righe / 600 KB):

| Area | Contenuto |
|---|---|
| `profili` | ogni titolo guardato, comprato o scartato, con tutte le caratteristiche, il motivo dello scarto, la convenienza, il mondo |
| `esiti` | com'è andata a 7, 30, 365 giorni, più «sistema» (vendita quando il sistema toglie il titolo), con massimo e minimo toccati |
| `mondo`, `settori` | contesto del giorno |
| `notizie` | notizie col riassunto |
| `scatti`, `osservazioni` | punti vecchi spostati dai file vivi |
| `regole` | soglie in vigore ogni giorno |
| `ombra` | scelte dei metodi in ombra, nel file del giorno di scelta |
| `metodi_avvii` | quando un metodo è stato avviato |

- **Indice:** `archivio/indice_archivio.json` (2026) + `archivio/indice_archivio_<anno>.json` dal 2027. Funzioni: `indice_archivio()`, `_indice_o_niente(anno)`, `_nome_indice()`.
- **Conteggi:** `archivio/conteggi_registri.json` + `conteggi_registri_<anno>.json` dal 2027 (`_nome_conteggi`).
- **Protezioni:** `_riduce_storico` (registri e tutto `archivio/`), `_crollo_stato` (file vivi), `_svuota_un_campo`, conteggi attesi, `_tetto_vivo_effettivo` (il tetto del file vivo scende se le righe pesano di più, obiettivo 450 KB), muro 950 KB.
- **Conti dei metodi per l'app:** `metodi/<short|long>_<YYYY-MM>.json` + `metodi/stato.json`. Non sono storia: si ricalcolano dall'archivio.
- **Noti, sopra 800 KB e fermi:** `archivio/conv_log_2026.json` (797 KB, primo pezzo scritto prima della divisione) e la cartella `archivio/scartati-2026-08-21/` (3,5 MB, dati messi da parte il 21/08 su richiesta dell'utente, nessuno li legge né li scrive). Eliminarla contraddirebbe la regola 1: decisione dell'utente.

### 4.4 Il lavoro automatico, fasi principali (in ordine)

scansione e osservazioni → previsioni → pre-segnali → promozioni → scatti → uscite e avvisi → registri vecchi → scarico profili → diario e suoi esiti → riconciliazione profili → riparazioni (soglie, prezzi, settori) → esiti dell'archivio → esiti di sistema → `registra_metodi()` → `salva_sintesi()` → `aggiorna_conti_metodi()` → archiviazione scatti e osservazioni → conteggi → avvisi → pesi della convenienza.

### 4.5 Le sezioni dell'app

Analisi di un titolo · Occasioni di mercato · In osservazione · In anticipo · Monitoraggio · Portafoglio · Scenari · **Metodi di selezione** · Diario dei dati · Archivio · Attualità.

- **Scenari:** riepilogo, cinque momenti d'acquisto (dal diario), calendario, effetto dei filtri, scheda voti, «seguendo il sistema».
- **Metodi di selezione** (dal 6/10): riepilogo con tabella, barre «meglio del guardato» e un riquadro per metodo contro il sistema vero; metodo per metodo; calendario; contro il sistema vero con verdetto. Colori: blu `#3987e5` metodo, arancione `#d95926` sistema vero (verificati sullo sfondo scuro `#13151a`).
- **Archivio:** copertura, calendario, singola occasione, «Cosa se ne impara» (classifica delle caratteristiche con tre difese: occasioni distinte, giornate d'accordo, conferma sulla metà recente; orizzonte «sistema» con chiuse e aperte contate a parte).

---

## 5. I metodi in ombra

Girano accanto al sistema vero **senza comprare niente**. Le scelte vanno in `archivio/ombra`; gli esiti sono quelli dell'archivio. Un titolo conta una volta ogni 30 giorni. I metodi con classifica del giorno («il 30% migliore») scelgono solo a giornata chiusa. Un metodo nuovo, al primo giro, ripassa tutta la storia (giorni marcati «prima», cioè retroattivi).

`METODI_OMBRA` (12 voci) in `finance_utils.py`:

| Chiave | Nome | Dal | Regole in breve |
|---|---|---|---|
| `sistema_vero` | Il sistema vero | riferimento | quello che il sistema compra davvero |
| `sistema_di_prima` | Il sistema di prima | 7/10 | catena senza le correzioni del 7/10 |
| `sistema_corretto` | Sistema corretto | 7/10 | filtri nuovi **senza** punteggio e rischio/rendimento, convenienza ≥ 60 |
| `ombra_trend` | Solo in trend positivo | 5/10 | comprate dal sistema di prima, solo sopra la media a 200 giorni |
| `ombra_regole_nuove` | Regole nuove: qualità e trend | 5/10 | sopra media 200, anno ≥ −10%, prezzo ≥ 10, scambi ≥ 5 M$, niente trappola |
| `forza_relativa` | Forza relativa 12-1 | 6/10 | 30% migliore del giorno per salita sull'anno senza l'ultimo mese |
| `vicino_massimi` | Vicino ai massimi dell'anno | 6/10 | al massimo −10% dal massimo dell'anno |
| `trend_template` | Trend template semplificato | 6/10 | sopra medie 200 e 50, entro −25% dal massimo, anno positivo |
| `bassa_volatilita` | Bassa volatilità | 6/10 | 30% più calmo del giorno |
| `qualita` | Qualità dei conti | 6/10 | Piotroski ≥ 7 o ROIC ≥ 12% con margine lordo ≥ 35% |
| `qualita_forza` | Qualità e forza relativa | 6/10 | le due insieme |
| `rimbalzo_grandi` | Rimbalzo solo sui titoli grandi | 6/10 | RSI ≤ 35, prezzo ≥ 10, scambi ≥ 50 M$ |

Quasi tutti chiedono anche prezzo ≥ 10 $ e scambi ≥ 5 M$.

- **Insieme di partenza stabile:** `_verdetto_di_prima` e `_metodi_visto` usano il verdetto della catena vecchia, così le correzioni del 7/10 non cambiano da dove scelgono i metodi. Verificato: le 2.377 scelte già archiviate, ricalcolate col codice nuovo, sono identiche.
- **Basi:** `_metodo_in_base(p, base)` con «viste», «comprate», «comprate_prima», «tutte».
- **Vendite misurate:** breve al bersaglio / 7 giorni / 30 giorni; lungo al bersaglio / 30 / 365. Il bersaglio è uguale per tutti: una chiusura a +4 volte il movimento giornaliero (ATR%) entro 30 giorni (breve) o un anno (lungo).
- **«Meglio del guardato»:** resa meno la mediana di tutto ciò che la catena di prima guardava con un giudizio, lo stesso giorno.
- **Quando si decide:** a 30 giorni, sulla sola prova vera, con almeno 30 occasioni e 15 giornate con entrambi; un metodo «vince» se batte il sistema vero in 2 giornate su 3. Data prevista: **metà/fine novembre 2026**.

---

## 6. Stato al 20 ottobre 2026

**Funzionamento:** tutte le registrazioni scrivono ogni giorno. Lavoro automatico 4-8 giri al giorno dal 13/10, tutti riusciti, durata massima 15 minuti. Nessun avviso di salvataggio aperto, nessun file nuovo sopra 800 KB. Esiti a 7 e 30 giorni presenti per il 100% dei profili dovuti. L'apertura nascosta di tutte le 16 viste dell'app è passata senza errori sia il 12/10 sia il 20/10.

| Archivio | Righe totali |
|---|---|
| Profili | 15.190 |
| Esiti | 24.652 |
| Scelte dei metodi | 3.804 |
| Scatti | 19.863 |
| Osservazioni | 15.009 |

**Effetto delle correzioni:** ogni giorno fermano 33-76 titoli per prezzo, 3-9 per scambi, 12-25 per crollo. Il sistema vero ora fa entrare in osservazione **0-1 titoli al giorno** (prima 2-15). La prova vera del sistema cresce quindi lentamente.

**Mercato dal 6/10 al 20/10:** S&P 500 −1,6%, Nasdaq −5,4%, piccole −3,6%, **ETF momentum −8,9%**. È arrivato un calo dei titoli forti proprio all'inizio della prova vera.

**Prova vera, breve periodo, a 7 giorni** (pochi casi, nessun esito a 30 giorni ancora):

| Metodo | Casi | Resa tipica | Meglio del guardato |
|---|---|---|---|
| Bassa volatilità | 11 | +0,17% | +2,11 |
| Sistema corretto | 14 | −0,07% | +1,78 |
| Qualità dei conti | 14 | −0,23% | +1,26 |
| Il sistema vero | 18 | −0,96% | +0,87 |
| Forza relativa 12-1 | 48 | −6,58% | −4,46 |
| Trend template | 26 | −12,64% | −9,40 |
| Vicino ai massimi | 19 | −13,69% | −9,16 |

I metodi di forza, i migliori sui giorni passati, nella prova vera stanno perdendo molto per il calo dei titoli forti. È il motivo per cui la prova si fa in ombra. «Sistema corretto» resta il candidato più solido: buono sui giorni passati (+0,25% a 30 giorni, +3,6 sul guardato, 143 casi) e meglio del sistema vero nei primi giorni della prova vera.

**Sui giorni passati (costruiti guardando quei giorni, quindi non provano niente):** a 30 giorni nel breve il sistema vero fa −5,57% con il 30% in guadagno; Sistema corretto +0,25% (50%); Solo in trend positivo +0,01% (50%); Forza relativa −0,10% (49%).

---

## 7. Cose aperte

### Decisioni dell'utente ancora in sospeso
- **Pulizia dell'app** (proposta il 7/10, non ancora approvata). Candidati, tutti misurati:
  1. sezione **Portafoglio**: `portfolio.json` vuoto dal 21/06, sette funzioni, due fasi del lavoro automatico;
  2. **previsioni per la calibrazione**: `forecast_log.json` 409 KB, ~93 righe al giorno, nessuna pagina lo mostra;
  3. **registro vecchio degli scenari** `scenario_log.json`: le schede usano il diario; ~700 righe del motore. Attenzione: `resolve_scenarios` e `completa_passaggi` sono ancora chiamate da app e lavoro;
  4. **Scheda voti** (dichiara di essere «in attesa» dal 21/08); il suo registro `track_record.json` è usato anche da `auto_promote_opportunities`;
  5. **15 funzioni mai chiamate** (~400 righe: `scenari_senza_osservazione`, `scenari_attesa`, `scenari_perche_vuoto`, `riallinea_diario_osservazioni`, `track_record_calibration`, `verify_with_sec`, `universo_benchmark`, `calibration_report`, `storia_osservazioni`, `azzera_conteggio`, `notizie_del_giorno`, `add_position`, `_pre_entry_for`, `scatti_del_giorno`, `ticker_exists`) e costanti mai usate (`_REL_FACTOR`, `TRACKING_FILE`, `OPP_WATCH_FILE`, `_SCENARIO_SELLS`, `SCENARIO_VARIANTI`, alias `registra_ombra`);
  6. **tre testi** che rimandano a una scheda che non esiste più, «Quali indicatori funzionano» (`app.py` righe ~257, ~724, ~2385);
  7. **doppioni**: «Seguendo il sistema» (stesso conto in Archivio e Metodi), «La versione eseguibile» nello scenario 2, «Effetto dei filtri», due calendari, Diario dei dati;
  8. **testo**: 77.600 caratteri, 11 spiegazioni sopra i 600 caratteri; proposta: due frasi al massimo più un riquadro «Come funziona» chiuso.
  Da **non** toccare: «In osservazione», «In anticipo», il registro dei pre-segnali, `conv_log` (alimenta i pesi appresi).
- **Repository pubblico** → privato?
- **Allargare la lista di partenza** con titoli in salita: rimandato («non ora») dall'utente il 6/10.
- **Presa di profitto** che oggi solo avvisa: registrarla come evento nel diario, o farla vendere.
- **Cartella `scartati-2026-08-21`** da tenere o eliminare.

### Difetti noti, innocui
- **407 scelte scritte due volte** in `archivio/ombra` (metodi `ombra_trend` e `ombra_regole_nuove`): il codice del 5/10 le aveva messe tutte nel file del 6/10, quello nuovo nel file del loro giorno. `_calcola_conti_metodi` deduplica per id: i conti sono giusti.
- **Un momento d'acquisto senza profilo** nel diario dal 20/09 (26/09): buco dichiarato.

### Risultati dell'indagine sui criteri (6/10), base delle decisioni
Nel passaggio iniziale, sul breve, a 30 giorni, chi viene fermato contro chi passa, negli stessi giorni:
- prezzo minimo: funziona (17 giornate su 17), soglia troppo bassa;
- scambi minimi: funziona ma fermava l'1%;
- **punteggio: al contrario** (chi passa va meglio solo in 2 giornate su 17);
- sconto minimo: non distingue;
- **rischio/rendimento: al contrario** (4 su 16).
Dentro il punteggio lavorano al contrario: ipervenduto (RSI), inversione confermata, volume su giorno verde, penalità «ancora in calo oggi». L'unico ingrediente giusto è «sopra la media a 200 giorni» (18 su 18), che pesa solo +13. La lista «società piccole in salita» è la peggiore ed è quella da cui il sistema teneva di più. Nel lungo: punteggio al contrario, tetto per settore al contrario, sconto minimo funziona, ETF meglio delle azioni ma mai tenuti.

---

## 8. Strumenti di verifica

Nella cartella `strumenti_verifica/` (copiati dallo spazio temporaneo della chat precedente; si possono committare, non contengono segreti). Lanciarli dalla cartella dell'app con `PYTHONIOENCODING=utf-8 python strumenti_verifica/<file>` e poi `git checkout conv_stats.json`.

| File | Che cosa fa | Durata |
|---|---|---|
| `reg.py` | regressione: compila, controlla le funzioni chiave, i pesi dei file sul ramo dati, apre 16 viste dell'app in AppTest | ~12-15 min |
| `giro_registrazioni.py` | giro delle registrazioni: righe per giorno e area, effetto dei filtri, registri vivi, classifica dei metodi (tutti i giorni e prova vera), confronto col sistema vero | ~2 min |
| `giro_registrazioni_2.py` | copertura degli esiti, esiti di sistema, buchi del diario, scelte dei metodi per giorno | ~3 min |
| `audit_crescita.py` | crescita di ogni file e quando toccherebbe un limite | ~1 min |
| `indagine_criteri.py` | indagine filtro per filtro sui criteri del sistema (crea una cache dell'archivio se manca) | ~1-2 min |
| `metodi_alternativi.py` | misura metodi di selezione candidati sull'archivio | ~1 min |
| `test_metodi.py` | prove sintetiche: metodi, conti mensili, indice e conteggi per anno (simula il 2027), pezzi oltre 25, tetti, muro 950 KB | ~1 min |
| `test_correzioni.py` | prove delle correzioni del 7/10: confronto con `finance_utils_prima.py` (copia del motore al commit `f3517236`) | ~2 min |
| `verifica_vera_correzioni.py` | sui dati veri: i metodi avviati ricalcolati devono coincidere con l'archivio | ~2 min |
| `prova_vera_metodi.py` | calcolo in memoria delle scelte di tutti i metodi e del peso dei conti mensili | ~1 min |
| `inventario.py` | inventario per la pulizia: righe per sezione, funzioni morte, registri | ~1 min |

`reg.py` contiene `assert` sullo stato attuale (12 metodi, soglie 10 $ / 20 M$): aggiornarli se cambiano.

---

## 9. Comandi utili

```bash
cd /c/Users/kevin.munaretti/Documents/programma/finanza/analisi_finanziaria
git fetch -q origin main auto-data
git status -sb
git log -3 --format="%cd %s" --date=format-local:"%Y-%m-%d %H:%M" origin/auto-data
```

Giri del lavoro automatico (orari UTC):

```bash
curl -s "https://api.github.com/repos/kevin006kevin-maker/analisi_finanziaria/actions/runs?per_page=30"
```

Leggere un file dati:

```bash
git show origin/auto-data:archivio/indice_archivio.json
```

---

## 10. Come riprendere

1. Leggere questo documento e la memoria del progetto (`project_analisi_finanziaria.md` nella memoria di Claude).
2. `git fetch` e `git status`: il codice in locale deve coincidere con `origin/main`.
3. Lanciare `giro_registrazioni.py` per vedere lo stato aggiornato.
4. Prima di proporre modifiche al sistema vero, ricordare che la decisione sui metodi va presa sulla **prova vera a 30 giorni**, non sui giorni passati.
5. Ogni modifica: prova sintetica, prova sui dati veri in sola lettura, `reg.py`, `git checkout conv_stats.json`, poi comando di commit per l'utente.
