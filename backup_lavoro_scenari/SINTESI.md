## Risposta breve

**No: "da adesso registra tutto" non regge ancora.** Dei quattro passaggi, oggi ne registra davvero due e mezzo:

| Passaggio | Stato verificato adesso (74 righe di scenario sul branch) |
|---|---|
| entra in osservazione | data e prezzo: sì (il campo «primo» ora c'è su 38 voci su 41). Ma **7 righe su 74 portano ancora una data e un prezzo FALSI** sul branch: la correzione esiste solo sul mio disco, non è pubblicata (`git show HEAD:finance_utils.py` non contiene la guardia `entro_data`) |
| entra in «In anticipo» | **26 righe su 74 completamente vuote; probabilità di salita/perdita: 0 righe su 74**, perché il registro dei pre-segnali non le ha su nessuna delle sue 125 righe |
| entra in Monitoraggio | sì, questo è l'unico momento solido (61 righe su 74 hanno anche i numeri di qualità; le 13 vuote sono di fine luglio, scritte da codice precedente) |
| supera il periodo di conferma | **8 righe su 74 vuote per sempre** (i titoli sono usciti dal monitoraggio) e delle 54 riempite **38 hanno un prezzo diverso da quello su cui i rendimenti sono calcolati** |

**E sì, c'è pericolo che un dato già scritto venga perso durante l'evoluzione dell'occasione**, in cinque punti distinti: gli scatti del monitoraggio vengono cancellati all'uscita (unica fonte del quarto momento), il salvataggio sul branch può fallire senza che nessuno lo guardi, PC e lavoro automatico si sovrascrivono a vicenda senza fusione, la protezione anti-cancellazione conta solo le righe (non i campi dentro le righe), e l'archiviazione pota il registro vivo fidandosi di una rilettura del proprio file locale.

39 segnalazioni reali (19 di ieri + 20 di oggi; 8 sono state refutate) confluiscono in **14 problemi distinti**.

---

# (c) PRIMA DI TUTTO: i problemi che scrivono un dato SBAGLIATO invece di lasciarlo vuoto

Sono i peggiori perché un vuoto lo vedi, un numero falso no — e sono esattamente le righe che i filtri tengono dentro.

### C1 — L'inizio dell'osservazione viene timbrato con la fotografia di un episodio SUCCESSIVO
**5 segnalazioni** (+ una in parte, vedi C4). Quando capita: **sempre, finché la correzione non viene pubblicata**. Gravità: massima.

- **Cosa si perde:** data e prezzo veri dell'ingresso in osservazione, sostituiti da quelli di settimane dopo. Sul branch: NEM promossa il 28/07 con osservazione datata 19/08 a 115.98 contro un prezzo vero di 90.83; poi CDE, SMCI, FSM, STMMI.MI, CAPR, CDNL. Sono le uniche righe con i numeri di qualità su quel momento, quindi con un filtro attivo la scheda "compro appena entra in osservazione" resta popolata **solo** da righe che guardano nel futuro.
- **Sequenza:** un titolo viene promosso, poi torna in osservazione; chi ricostruisce il passaggio legge il registro delle osservazioni di adesso, che contiene il nuovo episodio. Nessun confronto con la data di promozione, e il ripiego sul prezzo vero scatta solo se il prezzo manca — quindi un prezzo sbagliato vince su quello giusto.
- **Correzione minima:** è **già scritta ma non committata**. `finance_utils.py:5205` (parametro `entro_data`), `finance_utils.py:5221` (la guardia), `finance_utils.py:5287` e `finance_utils.py:5321` (le due chiamate), `finance_utils.py:5278-5284` (riparazione delle righe già a verbale). Il file locale è già pulito (0 righe false), il branch no. **Finché il commit non c'è, il lavoro automatico riscrive il dato falso a ogni giro.**

### C2 — La conferma prende i numeri di uno scatto di un ALTRO giorno (e domani di un altro episodio)
**4 segnalazioni + 1 in parte.** Quando capita: **sempre** come incoerenza di prezzo, **raro** come salto di settimane. Gravità: alta.

- **Cosa si perde:** convenienza e probabilità del giorno di fine verifica; al loro posto ci sono quelle di un altro momento. Già misurabile: **38 righe su 54** hanno nel passaggio un prezzo diverso da quello usato per i rendimenti (fino a -6,7% su QS, +7,2% su REPL). 30 voci di monitoraggio su 77 hanno un giorno di Borsa mancante (il 6 agosto il lavoro non ha girato): per quei titoli una conferma su quel giorno prende per costruzione un altro giorno.
- **Sequenza:** si cerca il primo scatto a partire dalla data di verifica, e se non c'è si prende l'ultimo disponibile. Nessun controllo di distanza, né in avanti né indietro. Le 8 righe con conferma vuota vengono ritentate a ogni giro: se uno di quei titoli rientra nel monitoraggio, il primo scatto del NUOVO periodo viene scritto come conferma.
- **Correzione minima:** `finance_utils.py:5246-5247` — tenere solo gli scatti entro pochi giorni dalla data richiesta e, se non ce n'è nessuno, restituire un passaggio vuoto invece di `dopo[0]`/`snaps[-1]`. Più una riga a `finance_utils.py:5472` che forza data e prezzo del passaggio a `conf_date`/`conf_price`, così il prezzo a verbale è lo stesso su cui il rendimento è calcolato.

### C3 — «In anticipo» viene preso dal pre-segnale più vecchio di tutta la storia
**4 segnalazioni.** Quando capita: **raro oggi, sistematico dal 27 agosto circa.** Gravità: alta.

- **Cosa si perde:** data e prezzo del vero ingresso in «In anticipo», sostituiti da quelli di un episodio chiuso. Un caso già nei dati: CLBT promosso stamattina su un episodio iniziato il 17 agosto, ma il passaggio porta il pre-segnale del 14 agosto a 10,8 mentre il nuovo episodio parte a 10,445. Il rendimento della casella "compro in anticipo" per CLBT è calcolato su un prezzo di un altro episodio.
- **Sequenza:** la selezione della riga di pre-segnale ha solo un limite superiore (non oltre oggi) e poi prende deliberatamente la più antica; nessun limite inferiore all'episodio in corso, a differenza della funzione gemella dell'osservazione che quel limite ce l'ha. La deduplica a 30 giorni impedisce di registrare il pre-segnale del nuovo episodio, quindi resta solo quello vecchio. Il registro dei pre-segnali ha 24 giorni di vita contro una deduplica di 30: **oggi zero titoli duplicati su 125 righe, dal ~27 agosto cominceranno.**
- **Correzione minima:** `finance_utils.py:5153-5156` — aggiungere il limite inferiore preso dalla stessa fonte che usa l'osservazione (la voce delle osservazioni: campo `ripartita`, altrimenti `primo.date`), lasciando invariata la scelta del più vecchio dentro l'episodio. Facoltativo ma coerente: a `finance_utils.py:5282-5285` svuotare l'anticipo quando la sua data precede quella dell'osservazione, così le righe già false (CAPR, CLBT) non restano a verbale.

### C4 — Nel momento «In anticipo» prezzo, convenienza e probabilità sono di istanti diversi
**1 segnalazione + 1 in parte.** Quando capita: **spesso** (già oggi). Gravità: media.

- **Cosa si perde:** la coerenza della fotografia. La riga di pre-segnale mette la data di oggi, il prezzo dell'ultimo punto osservato, e convenienza e probabilità dell'**ultimo valore NOTO**, che può essere di un altro giorno. Verificato: la riga di ENEL.MI del 19/08 ha prezzo 9.467 del punto del 19, ma convenienza 67 del punto del 18 — e oggi la stessa riga si riscriverebbe sfasata.
- **Sequenza:** l'ultimo prezzo viene sempre dall'ultimo punto, mentre gli altri valori risalgono indietro finché trovano un punto valido; i punti aggiunti fuori orario non hanno quei valori. Nessun controllo di freschezza.
- **Correzione minima:** `finance_utils.py:4955-4961` — esporre anche il punto da cui vengono i valori di qualità; `finance_utils.py:6289-6299` — scrivere data, prezzo, convenienza e probabilità **tutti da quel punto**.

### C5 — Il prezzo di inizio osservazione cambia significato a metà registro
**2 segnalazioni.** Quando capita: **sempre** nelle medie. Gravità: media.

- **Cosa si perde:** la comparabilità. Le righe promosse usano la fotografia immune alla potatura, le righe "come se il +2% non esistesse" usano il primo punto della lista potata a 12 giorni: due basi diverse **nella stessa media**, e tre delle quattro righe scritte oggi sono di quel secondo tipo. Sul branch il divario tra inizio osservazione e promozione è di 11-12 giorni in 13 righe (8 esattamente a 12, cioè al taglio) e 22/23/25/43 giorni in altre 5: appena la fotografia e il primo punto superstite divergono, le due definizioni divergono anche nei numeri. I rendimenti già calcolati sono congelati e nessun campo dice su quale base sono.
- **Sequenza:** alla promozione, se il passaggio dell'osservazione ha un prezzo, quel prezzo sostituisce quello dedotto dalla lista potata; le righe scartate dal +2% non fanno mai quella sostituzione.
- **Correzione minima:** `finance_utils.py:5371-5372` — usare la stessa fotografia delle promosse anche per le scartate; `finance_utils.py:5335` — aggiungere un campo che dichiara la base usata; `finance_utils.py:5652` — contarlo nella scheda.

---

# (a) Problemi sui dati NUOVI: il dato non viene messo a verbale, o viene cancellato dopo

### A1 — La conferma vive solo negli scatti del monitoraggio, che vengono cancellati all'uscita
**8 segnalazioni: è il gruppo più grande.** Quando capita: **spesso**, a ogni uscita anticipata. Gravità: alta.

- **Cosa si perde:** convenienza, probabilità e affidabilità alla fine del periodo di verifica. Già perse per sempre 8 righe su 74 (AEO, MPLT, STRL, WSO, BIOA, SSTK, AZN, USNA): tutte con la data di conferma valorizzata e il passaggio vuoto, tutte con il titolo assente dal monitoraggio. La lapide dell'uscita salva solo i prezzi, verificato sulle 26 lapidi vere. Nessun altro registro copre quella data.
- **Sequenza:** un titolo esce (crollo, stop, deterioramento) prima dei 5 o 10 giorni di Borsa della conferma; con la voce spariscono tutti gli scatti. Nello stesso giro le rimozioni girano prima dei risolutori, quindi chi esce oggi non ha più scatti quando si prova a chiudere la conferma.
- **Effetto collaterale:** su quelle 8 righe il contatore dice "8 righe completate" a ogni giro pur non completando niente (`finance_utils.py:5275-5277`), e il registro viene riscritto a vuoto.
- **Nota:** per le righe "come se il +2% non esistesse" la qualità alla conferma resterà sempre vuota, perché quei titoli non sono monitorati. È un limite dichiarato, non un dato falso.
- **Correzione minima:** `finance_utils.py:4412` — salvare nella lapide la lista degli scatti (è già calcolata due righe sopra, a 4396); `finance_utils.py:5238-5241` — se la voce di monitoraggio manca, ripiegare sulla lapide. Più `finance_utils.py:5275-5277` — contare solo quando il passaggio è stato davvero riempito.

### A2 — «In anticipo» non nasce mai quando la promozione arriva nello stesso giro
**3 segnalazioni reali contro 2 refutazioni** (è il punto più contestato dell'intera caccia). Quando capita: **spesso per le ri-promozioni**. Gravità: alta.

- **Cosa si perde:** tutti e quattro i valori del secondo momento. 26 righe su 74 hanno quel passaggio vuoto e per nessuna esiste una riga di pre-segnale, a nessuna data. Il nucleo certo sono le **ri-promozioni dopo il periodo di attesa**: AA, RPT, AAON e TMUS escono il 4 agosto, l'attesa scade l'11, e tutti e quattro vengono ri-promossi l'11 con convenienza 66/73/71/68, cioè sopra la soglia dei pre-segnali, con l'anticipo vuoto. Prima non potevano essere registrati (erano seguiti o in attesa), in quel giro la promozione ha girato prima, dopo sono esclusi per sempre.
- **Onestà:** un agente ha refutato la parte generale, mostrando che per la maggioranza delle altre righe la convenienza era in calo, quindi non avrebbero comunque superato i criteri di «In anticipo»: per loro il vuoto è corretto. Resta reale il caso delle ri-promozioni e di tutte le future.
- **Sequenza:** nel lavoro automatico la promozione gira a `auto_watch.py:207`, la registrazione dei pre-segnali 114 righe dopo a `auto_watch.py:324`; e la registrazione scarta i titoli già seguiti. Le soglie sono diverse (55 per promuovere, 65 per il pre-segnale), quindi il primo superamento di 65 può cadere proprio quel giorno.
- **Correzione minima:** **spostare una sola cosa**: prendere il blocco `auto_watch.py:321-327` e metterlo prima della promozione, subito dopo la scansione (dopo `auto_watch.py:203`). La registrazione non dipende da altro che dalle osservazioni, già aggiornate.

### A3 — Le probabilità del momento «In anticipo» non esistono, e la deduplica le farà mancare anche alle prossime
**2 segnalazioni.** Quando capita: **sempre**. Gravità: alta.

- **Cosa si perde:** probabilità di salita e di perdita e affidabilità all'ingresso in «In anticipo»: **0 righe su 125** nel registro dei pre-segnali, **0 righe su 74** negli scenari. La scheda "compro appena entra in In anticipo" con un filtro attivo resta senza campione. E non è solo storia: **19 candidate ancora in osservazione hanno già una riga recente senza quei numeri**, e quando verranno promosse nasceranno di nuovo senza.
- **Sequenza:** la riga di pre-segnale si scrive una volta sola; i campi nuovi sono solo nel ramo delle righe nuove. Sul ramo "già registrato negli ultimi 30 giorni" c'è un salto secco che non tocca mai i campi mancanti della riga esistente.
- **Correzione minima:** `finance_utils.py:6282-6288` — trasformare l'insieme delle chiavi recenti in un dizionario chiave→riga e, prima del salto, completare i campi mancanti prendendoli dal punto delle osservazioni **alla data di quella riga** (non da quello di oggi, altrimenti si rifà l'errore C1). **Questa modifica sta nella stessa funzione di C4 e si fa in un colpo solo.**

### A4 — L'ingresso manuale «Segui ora» non crea nessuna riga
**2 segnalazioni.** Quando capita: **solo se usi quel pulsante** (finora 0 casi). Gravità: media.

- **Cosa si perde:** tutti e quattro i momenti, e per sempre. L'occasione non compare nelle schede né nei filtri.
- **Sequenza:** il pulsante chiama solo la funzione che mette in monitoraggio; le due funzioni che creano righe di scenario sono chiamate solo dalla promozione automatica, che come primo filtro scarta i titoli già seguiti. Dal clic in poi entrambe le strade sono chiuse.
- **Correzione minima:** `app.py:1318` — dopo la messa in monitoraggio, chiamare lo stesso registratore usato da `finance_utils.py:4563`. Tutti e quattro i momenti arrivano gratis, perché quel registratore costruisce già i passaggi. Stessa riga da aggiungere dopo `app.py:1062` per l'altro ingresso manuale.

### A5 — Il salvataggio sul branch può fallire e nessuno guarda l'esito
**2 segnalazioni.** Quando capita: **solo in caso di guasto, ma invisibile**. Gravità: alta.

- **Cosa si perde:** l'intera riga appena nata (sui runner il file locale muore col giro), oppure — sul PC — una scelta manuale che sembra salvata e al riavvio non c'è più, perché la lettura torna a preferire il branch e la scrittura successiva sovrascrive l'unica copia locale. È la stessa dinamica che si vede **adesso**: la correzione delle 7 righe false è ferma sul mio disco.
- **Sequenza:** l'esito del salvataggio remoto viene chiamato e buttato (`finance_utils.py:2276`, istruzione a sé, nessun `if`, nessun log), e quella funzione restituisce falso in silenzio su token scaduto, errore o rete assente. Il titolo resta però nel monitoraggio, e il cancello "già seguito" impedisce per sempre di rifare la riga.
- **Correzione minima:** `finance_utils.py:2276` — leggere l'esito, ritentare una volta, e in caso di fallimento lasciare un segno (un insieme in memoria da stampare in fondo al giro, `auto_watch.py:370`, e un file-marcatore accanto al dato, così la sessione dopo riparte dal locale e ripubblica). Facoltativo ma risolutivo: in `completa_passaggi` (`finance_utils.py:5254`) ricreare la riga mancante per ogni titolo seguito automaticamente che non ne ha una.

### A6 — Nessuno unisce le modifiche: la protezione conta solo le righe, e i campi dentro le righe si sovrascrivono
**2 segnalazioni.** Quando capita: **spesso** (ogni volta che PC e lavoro automatico scrivono nella stessa mezz'ora). Gravità: alta.

- **Cosa si perde:** un passaggio appena aggiunto dal lavoro automatico, cancellato dalla riscrittura dell'app; oppure gli scatti del monitoraggio presi nel frattempo, che sono la fonte unica del quarto momento. Sul branch ci sono 42 salvataggi fatti dal PC accanto a quelli del lavoro automatico, e uno di essi cade 35 minuti dopo un salvataggio del lavoro automatico sullo stesso file: quella volta non si è perso niente, ma nessuna guardia se ne sarebbe accorta.
- **Sequenza:** ogni scrittura è "leggo tutto, cambio un pezzo, riscrivo tutto", mai una fusione; la guardia rifiuta solo le scritture che **accorciano**, e un passaggio svuotato dentro una riga non cambia il numero di righe. Per il file dei titoli seguiti c'è un'aggravante: pesa 1,71 MB e sopra 1 MB la protezione definitiva non riesce nemmeno a leggere il contenuto del branch, quindi è spenta.
- **Correzione minima:** `finance_utils.py:2207` — a parità di righe, rifiutare la scrittura che **svuota un passaggio già pieno** (solo il blocco dei passaggi, altrimenti si bloccano le pulizie legittime). Più `finance_utils.py:4066-4067` (e gli altri tre punti che riscrivono il file dei titoli seguiti: 4029, 4048, 4077) — scartare la copia locale e la cache prima di rileggere, così non si parte da una base vecchia di ore.

### A7 — L'archiviazione si auto-conferma leggendo il proprio file locale
**1 segnalazione.** Quando capita: **solo in caso di guasto, ma il ramo è attivo a ogni giro**. Gravità: la più alta del gruppo (può cancellare migliaia di righe in una volta).

- **Cosa si perde:** le righe spostate in archivio. Il registro delle convenienze è a 2600 righe contro un tetto di 2000, quindi l'archiviazione parte ogni volta; l'archivio dell'anno esiste già con 7364 righe e pesa 2,32 MB, cioè oltre il muro dove il controllo non vede più il contenuto: la scrittura passa e sovrascrive 7364 righe con il solo lotto nuovo. Poi il registro vivo viene potato comunque, perché la verifica rilegge il file locale appena scritto.
- **Sequenza:** si scrive l'archivio, si rilegge per verifica — ma la rilettura prende il file locale del runner, non il branch, quindi il controllo passa sempre; poi il vivo viene riscritto accorciato con la protezione disattivata.
- **Correzione minima:** `finance_utils.py:2365-2368` — far dipendere la potatura dall'esito **reale** della scrittura (`if not write_data_json(arc, nuovo): return rows`), che richiede la stessa modifica di A5 a `finance_utils.py:2276`. **Due problemi, una modifica.**

### A8 — I tetti dei registri sono tarati su righe che ora pesano tre volte tanto
**2 segnalazioni.** Quando capita: **solo in caso di guasto, fra circa un anno**. Gravità: alta.

- **Cosa si perde:** potenzialmente il registro intero. Il tetto dichiara "circa 330 byte per riga"; misurato sul branch, una riga pesa **947 byte** (di cui 554 sono i soli passaggi). A 2000 righe il file vale 1,89 MB e con il margine fino a 2,46 MB: superato 1 MB — a circa 1.100 righe, cioè in circa un anno al ritmo attuale di 85 righe al mese — la protezione definitiva si spegne **e non si riaccende più**, perché l'archiviazione tiene il vivo a 2000 righe. Stesso problema sul registro delle convenienze (già 817 KB) e sul registro delle osservazioni, che di tetto non ne ha nessuno.
- **Correzione minima:** `finance_utils.py:2181` — portare il tetto degli scenari da 2000 a 600 e correggere il commento; `finance_utils.py:2185` — ricalibrare il registro delle convenienze con lo stesso metodo. Niente si perde: l'eccedenza va in archivio e i risolutori la completano comunque.

### A9 — La qualità della promozione viene da una nuova chiamata di rete invece che dai dati già in mano
**1 segnalazione.** Quando capita: **solo in caso di guasto, mai avvenuto**. Gravità: bassa.

- **Cosa si perde:** i quattro numeri di qualità della promozione, se lo scatto iniziale non riesce (è una chiamata di rete). I dati sono già in mano due righe più su.
- **Correzione minima:** `finance_utils.py:4562` — usare come ripiego un dizionario con i valori dell'ultima osservazione invece di uno vuoto (un dizionario intero, non campo per campo, altrimenti uno zero legittimo passa per dato mancante).

---

# (b) Quello che riguarda SOLO lo storico (non recuperabile, va dichiarato)

- Le **probabilità del momento «In anticipo» su tutte e 74 le righe**: solo 2 righe su 48 sarebbero ricostruibili dalle osservazioni, il resto non esiste in nessun registro.
- Le **9 righe di anticipo perse per l'ordine delle chiamate** (RPT, AAON, PSN, VISN, TMUS, DIS, PUMP, AA, SOXL): il dato non è in nessun registro.
- Le **8 conferme dei titoli già usciti**: né la lapide né gli altri registri coprono quella data.
- I **rendimenti già congelati** calcolati sulla base vecchia del prezzo di osservazione.

Per tutte, la cosa corretta è **lasciare il vuoto e dichiararlo** nelle schede, come già fa il conteggio delle righe senza dato. Non riempirle con i valori di oggi: sarebbe rifare l'errore C1.

Fuori elenco, refutate con verifica: il campo «primo» esiste (38 su 41, e dove manca il ripiego dà lo stesso valore); le righe scartate dal +2% ricevono i passaggi nello stesso giro; i formati di data misti non danneggiano nessun lettore (tutti e tre tagliano al giorno); la scrittura non atomica non perde dati perché il branch fa da copia; la promozione non perde la riga per un'eccezione (ogni pezzo chiamato è già difeso).

---

# Ordine in cui conviene correggere

1. **Committare la correzione già scritta di C1.** È la sola cosa che ferma un dato falso che si riscrive ogni mezz'ora, e il codice c'è già. Poi far girare una volta il completamento dei passaggi, perché le 7 righe false restano sul branch fino a quel giro.
2. **Spostare la registrazione dei pre-segnali prima della promozione** (`auto_watch.py:321-327` → prima di `auto_watch.py:205`). Una riga spostata: chiude A2 e fa esistere la riga del nuovo episodio, quindi aiuta anche C3.
3. **Limite inferiore nella scelta del pre-segnale** (`finance_utils.py:5153-5156`) + svuotamento dell'anticipo falso (`5282-5285`): chiude C3 e la coda di C5 sull'anticipo. Da fare **prima del 27 agosto**, quando la deduplica a 30 giorni comincerà a produrre righe doppie.
4. **Una sola modifica in `record_presignals`** (`finance_utils.py:6282-6299`, con l'aggiunta a `4955-4961`): chiude **C4 e A3 insieme**.
5. **Guardia di distanza nella conferma** (`finance_utils.py:5246-5247`) + forzatura di data e prezzo (`5472`): chiude C2. È la stessa forma di guardia del punto 1, quindi si scrive di seguito senza pensarci due volte.
6. **Salvare gli scatti nella lapide** (`finance_utils.py:4412`) + ripiego (`5238-5241`) + contatore onesto (`5275-5277`): chiude A1 e ferma la riscrittura a vuoto del registro.
7. **Leggere l'esito del salvataggio remoto** (`finance_utils.py:2276`) + potatura condizionata (`2365-2368`): **una modifica chiude A5 e A7**, ed è quella che protegge dal danno più grosso (7364 righe d'archivio).
8. **Guardia sui passaggi svuotati** (`finance_utils.py:2207`) + rilettura fresca prima di riscrivere i titoli seguiti (`4066-4067`, `4029`, `4048`, `4077`): chiude A6.
9. **Ricalibrare i tetti** (`finance_utils.py:2181` e `2185`): chiude A8. Non urgente, ma va fatto entro qualche mese.
10. **Riga di scenario dopo l'ingresso manuale** (`app.py:1318` e `1062`): chiude A4.
11. **Ripiego con i dati già in mano alla promozione** (`finance_utils.py:4562`): chiude A9.
12. **Dichiarare la base del prezzo di osservazione** (`finance_utils.py:5335`, `5371-5372`, `5652`): chiude C5.

**Coppie che si chiudono con la stessa modifica:** A5+A7 (l'esito del salvataggio), C4+A3 (la funzione dei pre-segnali), A2+C3 (ordine del lavoro automatico e limite inferiore, che agiscono sullo stesso buco da due lati), C1+C2 (stessa guardia di data, scritta due volte).

Dopo i punti 1-6 la promessa "da adesso registra tutto" diventa vera per i **dati nuovi**; lo storico resterà con i vuoti dichiarati sopra, e va detto nelle schede invece di sembrare completo.