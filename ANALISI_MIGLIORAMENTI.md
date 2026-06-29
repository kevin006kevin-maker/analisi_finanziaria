# Analisi dell'app "Analisi Finanziaria" — spiegazione semplice, conclusioni e prompt per le modifiche

> Documento di sintesi pensato per essere letto da una persona, non solo da uno sviluppatore.
> App analizzata: questa cartella (`analisi_finanziaria`, Streamlit, porta 8507).
> I riferimenti tipo `FU 3388` sono numeri di riga del file `finance_utils.py`; `app.py` è l'interfaccia.

---

## 1. Cosa fa l'app, in parole semplici

L'app cerca da sola dei titoli "in saldo" (le **occasioni**), li **tiene d'occhio** per qualche giorno
(**osservazione**) e poi, se sembrano partire, li sposta in una lista che segue nel tempo
(**monitoraggio**). Ci sono due tipi di occasione:

- **Breve termine** = un titolo sceso troppo in fretta, che potrebbe rimbalzare (logica "ipervenduto").
- **Lungo termine** = un'azienda di buona qualità che oggi costa poco (logica "qualità in saldo").

Per ogni occasione l'app calcola un punteggio di **Convenienza** e una stima di probabilità di salita.
C'è anche un sistema automatico (gira sul server ogni ~15 minuti, anche a PC spento) che osserva e
promuove i titoli da solo.

---

## 2. Come funziona oggi il "cuore" del sistema

Tre ingranaggi, spiegati semplice:

**a) Il calcolo della Convenienza.**
Per ogni titolo l'app mette insieme tanti segnali (quanto è sceso dai massimi, RSI, qualità dei conti,
rischio, probabilità…) e ne ricava due numeri: **"Occasione"** (un voto 0–100 assoluto) e
**"Convenienza"** (un voto che confronta il titolo con *tutti gli altri titoli scansionati in quel
momento*). La tabella ordina per Convenienza.

**b) L'osservazione.**
*Tutte* le occasioni trovate finiscono automaticamente sotto osservazione per una finestra fissa
(3 giorni il breve, 7 giorni il lungo). Durante questa finestra l'app registra ogni tanto prezzo e
convenienza.

**c) La promozione a monitoraggio.**
Alla fine della finestra, il titolo viene "promosso" nel monitoraggio **se il prezzo è salito di almeno
il 2%**.

---

## 3. I problemi che ho trovato (spiegati in modo chiaro)

Ho letto il codice vero e ho fatto controllare ogni mia conclusione da revisori indipendenti, per non
dire cose finanziariamente sbagliate. Ecco i punti, dal più importante.

### 🔴 IL PROBLEMA NUMERO UNO: la promozione butta via tutto il lavoro fatto

L'app calcola con cura la Convenienza, i fondamentali, l'anti-trappola, le probabilità… e poi, **al
momento di decidere se promuovere un titolo, non guarda niente di tutto questo**: guarda solo se il
prezzo è salito del 2%.

Tecnicamente: nel codice c'è un interruttore (`_PROMO_USE_CONV_TREND`) che dovrebbe far contare anche
l'andamento della Convenienza, ma è **spento** (`= False`, FU 3352). Quindi la condizione di
promozione è di fatto solo "prezzo +2%".

**Perché conta:** vuol dire che viene promosso anche un titolo la cui "storia" è ormai brutta (conti
peggiorati, convenienza crollata), purché abbia avuto un rimbalzo del 2%. È un po' come avere un
medico bravissimo che fa tutti gli esami e poi decide la terapia tirando una monetina.
È paradossale anche perché l'app **misura già** se "la convenienza alta rende davvero di più"
(`track_record_calibration`, FU 3577), ma poi quella convenienza non la usa per decidere.

**Cosa fare:** rimettere un controllo "la tesi è ancora valida?" *insieme* al +2% di prezzo: promuovere
solo se la convenienza è ancora sopra una soglia, non è crollata durante l'osservazione, e (sul lungo)
i conti non sono peggiorati.

### Area 1 — Calcolo della convenienza

- **Le trappole vengono solo "scontate", non escluse.** Se un'azienda ha i conti che peggiorano, l'app
  abbassa il suo voto del 25% (FU 2516) ma non la elimina: un titolo molto sceso può comparire lo
  stesso tra le occasioni. E questo segnale "attenzione trappola" non entra nemmeno nel punteggio di
  Convenienza mostrato per primo. → *Escludere* le trappole conclamate e farle pesare sul punteggio.

- **Sul lungo termine manca il filtro liquidità/prezzo.** Sul breve l'app scarta i titoli troppo
  piccoli o illiquidi (dove i numeri sono inaffidabili e comprare è difficile), sul lungo no (FU
  2908). → Aggiungere lo stesso filtro anche al lungo. *(Intervento facile.)*

- **I rendimenti mostrati sono al lordo.** Probabilità di salita e guadagno atteso non considerano la
  tassa italiana del 26%, le commissioni e i dividendi. E "probabilità di salita" dice solo se il
  titolo sale, non se sale *abbastanza* da ripagare il rischio. → Mostrare anche il guadagno netto e
  una misura di "vantaggio" reale.

- **Il punteggio "sfora" facilmente.** I pesi dei vari segnali e una costante di scala (`k=11`) sono
  scelti a mano e mai verificati sui risultati veri; per come è fatto il calcolo, un titolo solo un po'
  migliore della media arriva subito a 100 e schiaccia le differenze. → Usare una curva morbida che
  non saturi e iniziare a registrare "convenienza di oggi vs come è andata poi".

- **La Convenienza è "relativa" e quindi instabile.** Lo stesso titolo prende un voto diverso a seconda
  di *quali altri titoli* sono nello scan. Va bene per fare una classifica del momento, ma rende
  ballerino il dato salvato nel tempo. → Almeno spiegarlo nell'interfaccia e rendere stabile il voto
  del singolo titolo guardato da solo.

- **Gli ETF di lungo sono giudicati solo da "quanto sono scesi".** Un ETF di obbligazioni e uno
  azionario aggressivo vengono trattati con lo stesso metro. → Tenere conto anche di rischio e tendenza.

- **Nel breve manca il confronto col mercato.** Quando crolla tutta la borsa, *ogni* titolo sembra
  "ipervenduto" e passa il filtro. → Premiare chi scende *più del mercato* (forza relativa), non chi
  scende come tutti.

- **Doppio conteggio della redditività** nei fondamentali (gli stessi indicatori pesano due volte).

- *Rifiniture minori:* il punteggio RSI a "scalini" crea salti artificiali; l'universo di riserva
  contiene solo le grandi aziende di oggi (distorsione); due punteggi simili (Occasione/Convenienza)
  possono confondere.

### Area 2 — Criteri di osservazione

- **Si osserva tutto.** Il criterio per mettere un titolo "in osservazione" è lo stesso del filtro che
  lo ha trovato: così la lista è affollata e rumorosa. → Mettere in osservazione solo le occasioni
  davvero migliori (soglia più alta o solo le prime N).

- **Si contano i giorni di calendario, non quelli di borsa.** Sabato e domenica "consumano" la finestra
  anche se la borsa è chiusa, e una finestra può scadere senza nuovi dati. → Contare solo i giorni di
  mercato. *(Stesso errore anche nel confronto delle previsioni.)*

- **Non si registra com'era il mercato.** Si salva prezzo e convenienza, ma non come andava l'indice in
  quei giorni: poi non si può capire se un titolo è salito per merito suo o perché saliva tutto. →
  Salvare anche l'andamento dell'indice e se la "tesi" iniziale regge ancora.

- *Rifiniture:* lo stesso titolo può comparire due volte (breve e lungo); alcuni punti "stale" (solo
  prezzo) sporcano i conteggi; ci sono tetti nascosti che fanno sparire occasioni a metà finestra.

### Area 3 — Promozione a monitoraggio

- **Vedi il problema numero uno** (la promozione usi la Convenienza).

- **Si scartano i titoli per rumore.** Il monitoraggio elimina un titolo se dopo 5/10 giorni è anche
  solo leggermente sotto zero (FU 3454). Ma un −1% è normale oscillazione. → Eliminare solo se viene
  violato uno *stop* basato sulla volatilità (l'app lo calcola già), non alla prima perdita minima.

- **Manca una "regola di uscita".** Una volta in monitoraggio, non c'è un segnale che dica "ora è il
  momento di mollare" (RSI tornato alto, conti peggiorati, obiettivo raggiunto). → Aggiungerla.

- **Si promuove dopo il +2%**, cioè si entra quando è già salito. → Valutare una conferma più tempestiva.

- *Rifiniture:* le notifiche scattano troppo facilmente (poco utili); le probabilità sono mostrate come
  numeri secchi senza un margine di incertezza.

### Trasversale (vale per tutto)

- **Manca la prova del nove: il backtest.** Non c'è nessuno strumento che provi sui dati storici se
  tutta la catena (trova → osserva → promuove) avrebbe davvero fatto guadagnare. C'è un file
  (`ml_verify.py`) ma è scollegato e non viene mai usato dall'app. → Creare un vero backtest storico
  "passo dopo passo nel tempo": è l'informazione più importante che oggi manca.

- **Il sistema misura ma non impara.** L'app calcola già quanto sono affidabili le sue probabilità
  (Brier score) e se la convenienza alta rende di più, ma non usa questi risultati per *correggersi*. →
  Chiudere il cerchio: usare i risultati reali per ritarare pesi e soglie.

- *Rifiniture:* tante "manopole" (soglie, pesi, finestre) sparse nel codice andrebbero raccolte in un
  unico posto; gli avvisi arrivano solo via Telegram; sul cloud alcuni dati si azzerano ai riavvii.

---

## 4. Conclusioni

1. **Il difetto più grave non è in un calcolo, ma in una "scollatura":** l'app calcola benissimo la
   Convenienza e poi non la usa per la decisione che conta (la promozione). Sistemare questo è
   l'intervento con il miglior rapporto valore/sforzo.

2. **La logica di base è solida e curata** (block bootstrap per le probabilità, anti-trappola, radar di
   qualità, regime di volatilità): non va riscritta, va *rifinita e collegata*.

3. **Manca un modo per sapere se funziona davvero:** senza un backtest storico, tutte le scelte (pesi,
   soglie, finestre) restano opinioni. È la seconda priorità.

4. **Molti miglioramenti sono facili e a basso rischio** (filtro liquidità sul lungo, giorni di borsa,
   gate di osservazione più selettivo, esclusione delle trappole forti) e da soli alzano parecchio la
   qualità delle segnalazioni.

5. **Ordine consigliato:** prima il collegamento Convenienza→promozione e i quick-win facili; poi il
   backtest; infine i lavori grossi (forza relativa, convenienza stabile, apprendimento dei pesi).

---

## 5. Prompt da usare in futuro per farmi applicare le modifiche

Copia e incolla il testo qui sotto in una nuova sessione di Claude Code aperta in questa cartella
(`C:\Users\kevin.munaretti\Documenti\analisi_finanziaria`), quando vorrai che implementi davvero le
modifiche. È scritto per essere autosufficiente.

```text
Lavora sull'app in C:\Users\kevin.munaretti\Documenti\analisi_finanziaria (Streamlit, porta 8507,
file principali finance_utils.py e app.py). Leggi prima il documento di analisi completo
ANALISI_MIGLIORAMENTI.md in questa stessa cartella: contiene la spiegazione dei problemi e la lista
prioritizzata dei miglioramenti su (1) calcolo della convenienza, (2) criteri di osservazione,
(3) promozione a monitoraggio, più gli interventi trasversali.

Obiettivo: implementare TUTTI i miglioramenti descritti, procedendo in fasi e verificando a ogni passo,
senza azzerare il flusso di occasioni esistente.

Vincoli importanti:
- NON compromettere la logica esistente che funziona (block bootstrap, anti-trappola, radar qualità,
  regime di volatilità): vanno rifinite e collegate, non riscritte.
- Nessun look-ahead: usa solo dati disponibili alla data simulata/decisa.
- Prima di ogni modifica importante, mostrami un piano breve e fai un test di non-regressione
  confrontando l'output di scan_opportunities('short') e ('long') prima/dopo (numero occasioni,
  ordine, distribuzione della Convenienza).

Ordine di esecuzione (fai una fase alla volta e fermati a mostrarmi il risultato):

FASE 1 — Quick-win ad alto impatto e basso rischio:
  - PROMOZIONE: in auto_promote_opportunities (finance_utils.py) sostituisci il trend_ok sempre-vero
    con un quality-gate "tesi viva" in AND col +2% di prezzo: ultima convenienza nota >= soglia
    (es. 55), convenienza non decaduta sulla finestra, e sul lungo fondamentali non peggiorati
    (anti-trappola non a 0.75). Logga fscore/trap all'apertura finestra se serve. Rendi le soglie
    parametri in cima al file.
  - CONVENIENZA: aggiungi al ramo "long" di scan_opportunities un filtro liquidità/prezzo (riusa
    avg_dollar_vol già calcolato; soglia piu' bassa del breve, es. 200-500k) e prezzo minimo.
  - CONVENIENZA: escludi le trappole forti (non solo *0.75) ed esponi un campo signals/strong da
    value_trap_check; fai pesare l'anti-trappola anche nella Convenienza v2.
  - OSSERVAZIONE: rendi piu' selettivo l'ingresso in osservazione (soglia di convenienza/occasione
    piu' alta o top-N) e conta i giorni in giorni di BORSA, non di calendario (correggi anche
    resolve_forecasts).
  - MONITORAGGIO: in manage_monitoring rimuovi i titoli in base a uno stop di volatilita' (ATR gia'
    calcolato), non con la soglia 0%.

FASE 2 — Trasparenza e qualita' dei numeri:
  - Mostra i rendimenti NETTI (tassa IT 26% + commissioni) accanto ai lordi e aggiungi una misura di
    "vantaggio" (es. P(ret > soglia) o expectancy) accanto a P(salita).
  - Togli la saturazione del punteggio di convenienza (squashing morbido, es. tanh, oppure tara k) e
    inizia a loggare convenienza + sotto-fattori vs rendimento forward a 5/21 giorni.
  - Etichetta in UI che la Convenienza e' relativa allo scan; rendi auto-ancorata la convenienza del
    singolo titolo. Elimina il doppio conteggio della redditivita' nei pilastri fondamentali.
  - Aggiungi una "tesi di uscita" al monitoraggio (RSI ipercomprato / fondamentali peggiorati /
    target raggiunto) e salva il contesto di mercato (rendimento indice) nelle osservazioni.

FASE 3 — Lavori strutturali:
  - Crea backtest.py: walk-forward espandente che ricostruisce la pipeline reale (filtri scan,
    finestre, regola di promozione, manage_monitoring) e riporta hit-rate, resa media NETTA, curva
    equity vs benchmark e separazione per fascia di convenienza. Integra ml_verify come funzione
    importabile e mostra l'esito nella pagina di calibrazione.
  - Breve termine: aggiungi un fattore di forza relativa vs un indice condiviso (una sola serie per
    scan) e usalo come filtro nei regimi ad alta volatilita'.
  - ETF di lungo: sostituisci il gate "solo sconto" con una combinazione sconto+rischio+tendenza.
  - Loop di feedback: quando ci sono abbastanza esiti risolti, stima i pesi di convenienza con una
    regressione regolarizzata walk-forward (pesi a mano come prior), garantendo prima la persistenza
    degli esiti sul cloud.
  - Centralizza i parametri sparsi (soglie, pesi, finestre) in un unico blocco di configurazione.

Rifiniture minori (P3) da fare dove comodo: RSI continuo invece che a gradini; variare il seed del
bootstrap; deduplicare short/long sullo stesso ticker; ripulire i punti "stale"; loggare i
troncamenti dei tetti; notifiche meno banali; intervalli di confidenza sulle probabilita'.

Verifica finale: avvia l'app (avvia.bat, porta 8507) e controlla le tre sezioni
"Occasioni di mercato" / "In osservazione" / "Monitoraggio" con i nuovi gate e le nuove colonne
(reso netto, tesi di uscita). Scrivi qualche test per auto_promote_opportunities (tesi viva vs
decaduta) e per i nuovi filtri. Riassumimi cosa e' cambiato e i risultati del backtest.
```

---

*Documento generato dall'analisi del 2026-06-26. Il dettaglio tecnico completo (47 osservazioni
verificate, con riferimenti di riga e priorità P1–P3) è la base di questo riassunto.*
