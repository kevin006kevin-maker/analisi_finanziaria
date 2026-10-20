## 1. Si può fare sui primi tre scenari? Sì — e nel nuovo impianto viene più pulito che nel vecchio

I tre momenti che ti interessano sono già eventi a verbale del diario: `s1_osservazione`, `s2_anticipo`, `s3_fine_osservazione` (`finance_utils.py:7893-7900`). Ogni riga del diario ha la **sua** data e il **suo** prezzo, e il risolutore scarica lo storico del titolo e fa partire la finestra dalla data di quella riga (`finance_utils.py:7942` e `:7949`). Questo è esattamente ciò che serve alla vendita «alla soglia» e che il vecchio impianto **non** fa: là la finestra parte dalla promozione per tutti i momenti d'acquisto (`:5676`, `:5718`), quindi comprare in osservazione e cercare il tocco solo dopo la promozione misura un periodo che l'acquirente non ha vissuto.

Quello che manca è un solo dato: **il bersaglio alla data di quella riga**. Oggi non c'è da nessuna parte per i momenti prima della promozione — i punti di osservazione salvano solo data, prezzo, convenienza e probabilità (`:4326-4333`), il registro dei pre-segnali lo stesso, e la riga del diario non ha il campo (`:7784-7800`). Nel diario la soglia non è nemmeno prevista come regola di vendita: ci sono solo 7, 30 e 365 giorni (`:7905`).

Due strade, da usare insieme:

**Da salvare (da adesso, costo zero).** Il valore esiste già: `opportunity_row` calcola bersaglio e stop per **ogni** titolo guardato (`:2628`, `:2637`, ATR restituito a `:2723`), ma `scan_opportunities` non li copia nelle righe della tabella (`:3724-3733`), quindi vengono buttati. Basta portarli nella riga dello scanner e scriverli in due punti: il punto di osservazione (`:4326-4333`, e nel campo congelato `primo` accanto) e la riga del diario (`:7784-7800`). Nessuna chiamata di rete in più.

**Da ricostruire (per il passato).** La media a 50 giorni si ricalcola quasi esatta: non dipende dalla lunghezza dello storico e non è toccata dai dividendi. Con la regola fissa «ultima chiusura ≤ data» l'errore mediano è **0,078%** (massimo circa 2%); scegliendo l'ancoraggio riga per riga scende sotto lo 0,01%. C'è anche una via gratuita per il breve: `conv_log` salva prezzo e fattore `rebound`, che è (media50/prezzo − 1)×100 (`:3075`, `:2627`), quindi bersaglio = prezzo × (1 + rebound/100) — errore mediano 0,118%, 44 righe su 56 entro lo 0,5%. Copre il **100%** delle righe brevi di osservazione e «in anticipo», ma **zero** righe lunghe (il fattore non viene riempito per il lungo). Per i buchi e per il lungo serve una chiamata per titolo: 159 titoli distinti ≈ **1,6 minuti** misurati.

**Limiti sullo storico, espliciti.**
- La data dell'etichetta è il giorno della scansione, ma il prezzo è la chiusura del giorno **prima**: ancorando al giorno precedente il prezzo registrato si riproduce esatto nell'**89%** dei casi, ancorando alla data d'etichetta solo nel 30%. Se si sbaglia questo, si sbaglia tutto il resto.
- Lo **stop** non si ricostruisce bene nella coda: errore mediano 0,12% ma fino al **16,6%** (SOXL), perché il prezzo usato allora era la quotazione in tempo reale mentre i livelli nascevano dalla chiusura (`:3849-3855`). Per la tua richiesta però non è un ostacolo: gli scenari non vendono mai allo stop (fra `:5624` e `:5760` la parola «stop» non compare).
- Il diario non esiste ancora come file, quindi le righe passate dei tre momenti **non ci sono affatto**: la colonna partirà vuota e si riempirà 30 giorni dopo la prima riga scritta.

## 2. La logica attuale, con i numeri

Misurato sul registro vero (71 righe con bersaglio, 27/07→20/08): distanza mediana **+21,35%**, il **52%** delle righe ha il bersaglio oltre +20%, 6 righe su 71 l'hanno **sotto** il prezzo, il massimo è +531,8% (SION 6,27 → 39,61).

Tasso di tocco vero, con la regola del codice (chiusure, finestra del codice): **15 su 65 = 23%** dei bersagli sopra il prezzo. Controprova indipendente: 19 titoli su 77 con allarme «bersaglio» nel monitoraggio = 25%. Nessuna riga ha compiuto i 30 giorni (mediana 10 sedute su ~21), quindi **23% è un limite inferiore**, non il valore finale.

Il risultato più utile è il crollo con la distanza:

| distanza del bersaglio | toccato |
|---|---|
| sotto il prezzo | 6/6 (non è un bersaglio) |
| 0-5% | 6/6 |
| 5-10% | 5/10 |
| 10-20% | 2/12 |
| 20-50% | 2/22 |
| oltre 50% | 0/15 |

Dove funziona: quando il bersaglio è vicino (entro il 10%) e come valore **stabile** — la media a 50 giorni si muove dello 0,37% del prezzo al giorno, la più ferma di tutte le formule provate. Dove non funziona: la distanza non è una scelta, è un effetto collaterale di quanto il titolo è caduto. Su un titolo crollato il bersaglio finisce a +180% o +530%, cioè fuori portata in 30 giorni; su un titolo appena rientrato finisce sotto il prezzo, cioè non c'è. Da notare: `rr` è per costruzione la distanza in ATR diviso 2 (`:2643`), quindi il filtro Rischio/Rendimento ≥ 1,5 (`:3714`, `:2843`) è già un filtro sulla distanza della media a 50 giorni.

## 3. Cosa consiglio

**Bersaglio = il più basso fra la media a 50 giorni e prezzo + 4×ATR, alla data del momento d'acquisto, e nessuna cella se il bersaglio è ≤ al prezzo.** Più la finestra dei 30 giorni che parte da quella data.

Perché: non cambia la logica di fondo (che è la più stabile), toglie per costruzione i casi tipo SION, e nel backtest replicato in modo indipendente tocca leggermente più spesso con la stessa mediana. Sono onesto: **il guadagno è piccolo**. Serve come rete di sicurezza contro i bersagli assurdi, non come miglioramento di rendimento. Il vantaggio di «maggiore confrontabilità fra titoli» che era stato attribuito a questo tetto **non c'è**: misurando davvero fra titoli, la variabilità resta 0,19 in entrambi i casi.

| logica | calcolabile subito | stabile | confrontabile fra titoli | difetti |
|---|---|---|---|---|
| media 50 giorni (attuale) | sì, già in mano | la migliore (0,37%/giorno) | media (0,19) | distanza arbitraria: fino a +530% o sotto il prezzo; tocca il 23% |
| media 20 giorni | sì, già calcolata ma mai letta (`:7255`) | buona (0,67%) | la migliore (0,12) | tocca quasi il 48% ma a 1,55 ATR = rapporto 0,78, sotto il minimo che l'app stessa pretende: guadagno medio il più basso di tutti |
| prezzo + 4×ATR | sì | la peggiore (1,62%, ~4× la media 50) | perfetta per costruzione | tocca solo il 15%, mediana dell'esito negativa; rende tautologico il filtro Rischio/Rendimento |
| metà della caduta dal massimo a 60 giorni | sì, da `spark` (`:2669`) | media (0,80%) | discreta | dipende da un singolo picco; su un titolo in caduta il bersaglio scende insieme al prezzo |
| banda di Bollinger alta | sì, calcolata e mai usata (`:7266`) | media | discreta | tocca il 18%: dietro alla media 50 senza compensi |
| **minimo fra media 50 e prezzo+4×ATR** | **sì** | **come la media 50** | **come la media 50 (nessun guadagno)** | **guadagno marginale; vale come guardrail** |

Nota pratica: con le formule ancorate a una media, riusare il bersaglio di un altro momento sbaglia poco (scarto mediano 0,29 ATR su 5 giorni). Con quelle ancorate al prezzo il ricalcolo alla data è **obbligatorio**, perché la promozione richiede un rialzo (mediana +4,66%, cioè 0,66 ATR) e il bersaglio della promozione applicato all'osservazione sarebbe sistematicamente troppo alto.

## 4. Come scegliere misurando, invece di decidere a tavolino

Scrivere nella riga del diario **tutti** i bersagli candidati alla data dell'evento (media 50, media 20, prezzo+4×ATR, versione con tetto) e risolvere una colonna «alla soglia» per ciascuno, sulle **stesse** righe e nella **stessa** finestra. Essendo un confronto appaiato, servono molte meno righe di un test indipendente. Cosa confrontare: quota di tocchi, rendimento mediano e medio al netto della commissione, quota di celle vuote (bersaglio non valido), e giorni fino al tocco.

Quanto tempo: la prima cella matura 30 giorni dopo la prima riga scritta. L'afflusso di righe sul primo scenario è almeno quello delle promozioni (74 righe in 25 giorni, cioè circa 3 al giorno) e in pratica più alto, perché solo una parte di ciò che entra in osservazione viene promosso. Per separare un 33% da un 48% di tocchi servono nell'ordine di 80-100 righe risolte: **circa due-tre mesi** dall'accensione del salvataggio. Il backtest su 3 anni e 10-14 mila situazioni è già disponibile oggi e serve a scremare (dice che la media 20 tocca più spesso ma guadagna meno); la misura dal vivo serve a confermare, non a scoprire.

Aggiungerei due numeri che si possono misurare **su ogni riga da subito** e che valgono più della colonna sì/no: **giorni fino al tocco** e **escursione massima favorevole in ATR** (mediana realizzata 1,41 ATR). Sono loro che permettono di tarare il bersaglio sui dati invece di postularlo.

Un avvertimento sull'orizzonte: la soglia a 7 giorni non ha senso. Anche prendendo per buona la formula ottimista, solo il 36% dei bersagli è geometricamente raggiungibile in 5 sedute, e con la taratura sui dati veri (la formula sovrastima di circa 1,8 volte) si scende al 13%. La colonna «alla soglia» misurerebbe quasi sempre la chiusura di ripiego. Va tenuta a 30 giorni.

## 5. Limiti, detti chiaramente

**Non si potrà sapere sullo storico:** niente, per i tre momenti nel nuovo impianto — il diario non esiste ancora, quindi la colonna nasce vuota e non è recuperabile. Sul vecchio registro non esiste **nemmeno un** esito «alla soglia» (162 celle risolte, tutte a 7 giorni) perché la soglia matura a 30 giorni e la riga più vecchia ne ha 24. Lo stop di allora non è ricostruibile con affidabilità nella coda (fino al 16,6%), ma per la soglia non serve.

**Si saprà da subito:** il bersaglio ricostruito per il passato con errore mediano intorno allo 0,1% (gratis per il breve, 1,6 minuti di rete per il resto); la distanza del bersaglio in percentuale e in ATR per ogni riga; quali bersagli sono impossibili; e il fatto che il tasso di tocco reale sia intorno al 23-25% con un crollo netto oltre il +20% di distanza.

**Due cose da sistemare insieme alla modifica**, non dopo: far partire la finestra dei 30 giorni dalla data del momento d'acquisto (oggi resta ancorata alla promozione, `:5676`) e non creare la cella quando il bersaglio è ≤ al prezzo. Su quest'ultimo punto, la direzione della tua richiesta è la più sicura, non la più rischiosa: simulando la risoluzione oggi, «in anticipo» dà 0 celle negative, «osservazione» 1, mentre il momento «promozione» che esiste già ne dà **6** — e le 6 righe impossibili sono tutte anteriori al 17/08, quando è entrato in funzione il controllo `_livelli_validi` (`:3960`) sul percorso di scrittura. Vanno ripulite o marcate, ma non sono un buco aperto.

**Conclusione senza entusiasmo:** nessuna formula rende la soglia contemporaneamente frequente e redditizia. Abbassare il bersaglio (media 20) lo fa toccare spesso ma sotto il rischio che si corre; alzarlo (4×ATR) lo rende omogeneo ma quasi mai raggiunto. La scelta del bersaglio è una decisione su quanto spesso vuoi avere ragione contro quanto vuoi guadagnare quando l'hai. Per questo la cosa davvero utile da fare adesso è **salvare bersaglio, stop e ATR al momento dell'evento e misurare più formule in parallelo**; cambiare formula oggi, sulla base di quello che si sa, non è misurabilmente migliore.