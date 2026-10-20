# Ripresa — sezione Scenari, analisi finanziaria

Fermato il 19 agosto 2026 su richiesta dell'utente. Tutto quello che serve per ripartire è qui.

---

## 1. Il lavoro di ieri è al sicuro

Commit **`64e209c6`** sul branch `main` del repo `analisi_finanziaria`: 818 righe su `app.py`,
`finance_utils.py`, `auto_watch.py`. Contiene i passaggi delle occasioni, la ristrutturazione della
sezione Scenari in sotto-sezioni per momento d'acquisto, `valori_momento` con i filtri per momento,
`scenari_attesa`, `completa_passaggi`, `solidita_campione`, `data_it`.

Verificato prima di fermarsi: 40 combinazioni di scheda / tipo di occasione / filtri, più le altre
sei sezioni dell'app. Zero errori. Il registro degli scenari sul ramo `auto-data` ha 70 righe, tutte
con i passaggi.

In questa cartella: `modifiche_scenari.patch` (la patch completa), `file_modificati/` (copia dei tre
file), `dove_sta_il_lavoro.txt`.

---

## 2. DA FARE PER PRIMA COSA: 7 righe hanno un dato SBAGLIATO

Difetto introdotto ieri da `completa_passaggi`. Per 7 righe su 70 il passaggio «osservazione» è stato
riempito con una osservazione **successiva** dello stesso titolo, quindi data e prezzo sono falsi:

| Titolo | Osservazione scritta | Promozione | Ingresso vero | Prezzo scritto | Prezzo promozione |
|---|---|---|---|---|---|
| NEM | 19 ago | 28 lug | 16 lug | 115,98 | 93,47 |
| CDE | 17 ago | 28 lug | 16 lug | 18,81 | 15,36 |
| SMCI | 17 ago | 30 lug | 18 lug | 38,59 | 25,70 |
| FSM | 18 ago | 4 ago | 25 lug | 10,45 | 8,935 |
| STMMI.MI | 17 ago | 7 ago | 26 lug | 48,38 | 48,19 |
| CAPR | 16 ago | 14 ago | 3 ago | 6,65 | 6,47 |
| CDNL | 18 ago | 14 ago | 11 ago | 42,775 | 39,64 |

I rendimenti NON sono toccati (usano `obs_price`, che è rimasto quello giusto): è sbagliato solo il
passaggio mostrato, cioè la colonna «Comprata il» e i numeri di qualità di quel momento.

**Correzione:** in `_primo_osservazione` e in `completa_passaggi` scartare la fotografia di
`opp_watch` quando la sua data è **successiva** alla data di promozione della riga, e ripiegare su
`obs_date`/`obs_price` della riga. Poi ricalcolare i passaggi di quelle 7 righe.

Verifica rapida dello stato:

    PYTHONIOENCODING=utf-8 python -c "import finance_utils as fu; rows=fu.load_scenario_log(); print(sum(1 for r in rows if str(((r.get('passaggi') or {}).get('osservazione') or {}).get('data') or '')[:10] > str(r.get('date'))[:10]))"

---

## 3. La caccia alle perdite: dove si era fermata

Domanda aperta dell'utente: **«da adesso registra tutto? c'è pericolo che i dati vengano persi
durante l'evoluzione di una occasione?»**

Stato: **51 perdite trovate**, **25 verificate** da un verificatore scettico, **19 confermate reali**,
**26 ancora da verificare**.

File in questa cartella:
- `perdite_trovate.json` — le 51 perdite grezze
- `verdetti_abbinati.json` — i 25 verdetti già dati, agganciati alla loro perdita
- `args_ripresa.json` — pronto da passare al lavoro in parallelo
- `abbina_verdetti.py` / `prepara_args.py` — gli script che li hanno prodotti

### Come far ripartire gli agenti

La ripresa automatica del lavoro in parallelo (`resumeFromRunId`) funziona **solo nella stessa
sessione**, quindi in una sessione nuova non serve. Non importa: i risultati di ieri sono salvati e
il lavoro riparte saltando tutto ciò che era già fatto.

1. Rigenerare l'input (se i file sono cambiati):

       cd "C:/Users/kevin.munaretti/Documents/finanza/backup_lavoro_scenari" && python prepara_args.py

2. Lanciare `continua_caccia.js` passando il contenuto di `args_ripresa.json` come `args`.
   Verifica solo le 26 mancanti e poi sintetizza su tutte e 19 + le nuove confermate.
   (Se il payload da 187 KB è scomodo, si possono togliere i campi `area` e accorciare `sequenza`.)

### Le 19 perdite già confermate

Raggruppate per argomento; molte sono la stessa cosa vista da agenti diversi, e la sintesi deve
unirle.

**Il passaggio «osservazione»**
1. L'osservazione viene timbrata con una data posteriore alla promozione — 7 righe su 7 false (è il punto 2 qui sopra)
2. `completa_passaggi` ha scritto come «inizio osservazione» la fotografia di un episodio successivo
3. Il momento «osservazione» viene riscritto con i valori di un ciclo posteriore alla promozione
4. `primo` non viene mai chiuso alla promozione e poi sovrascrive il prezzo su cui la promozione si basava
5. `opp_watch` non ha alcun tetto: cresce fino a spegnere la protezione anti-cancellazione

**Il passaggio «conferma»** (il più fragile: nessuno lo scrive, si ricava)
6. Resta vuoto per sempre proprio per i titoli usciti presto dal monitoraggio
7. Muore insieme alla voce di monitoraggio: chi esce prima non l'avrà mai
8. Ha una sola finestra di cattura e la sua unica fonte viene distrutta all'uscita
9. Può essere riempito con lo scatto sbagliato, senza controllo di distanza dalla data
10. Può essere riempito con gli scatti di una promozione successiva dello stesso titolo
11. Un solo tentativo: quando `conf_price` è scritto, `resolve_scenarios` non riprova più
12. Resta vuoto su 8 righe su 62 già oggi

**Il passaggio «in anticipo»**
13. La deduplica a 30 giorni cancella il vero ingresso, e `_pre_row_for` pesca quello di settimane prima
14. Quando c'è, è il pre-segnale più vecchio, non quello che ha portato a questa promozione
15. Non viene mai registrato per le ri-promozioni
16. Le probabilità non ci sono su nessuna riga esistente

**Casi che non passano dal percorso normale**
17. Un'occasione seguita a mano con «Segui ora» non nasce con nessuno dei quattro momenti
18. Le righe «come se il +2% non esistesse» nascono senza passaggi e non potranno mai avere la conferma
19. (vedi `verdetti_abbinati.json` per motivo e correzione minima di ciascuna)

### Scartate dal verificatore — non riproporle come vere

Righe finite in archivio che non ricevono i passaggi (falso: l'archiviazione non scatta a queste
dimensioni) · il file locale stantio che sovrascrive il branch · gli esiti a 7 e 30 giorni delle
candidate archiviate · l'osservazione a verbale che non è l'inizio dell'osservazione · l'occasione
che diventa solida e viene promossa nello stesso giro.

---

## 4. I tre sospetti di fondo, ancora aperti

1. La fotografia dell'osservazione vive in `opp_watch`, che è un **file di stato**, non un registro
   storico. Oggi è passato da 69 KB a 11 KB. Finché la promozione non la copia nella riga di
   scenario, quella è l'unica copia.
2. La conferma non viene scritta da nessuno: si ricava dagli scatti del monitoraggio. Se l'occasione
   esce prima della fine della verifica, quello scatto può non esistere mai.
3. Le scritture **non sono atomiche** e non esiste copia di sicurezza. È la voce 21 dell'elenco delle
   33, mai sistemata, e vale per tutti i registri compresi quelli nuovi.

---

## 5. Decisioni già prese dall'utente — non richiederle

- Filtri condivisi fra tutte le sotto-sezioni: una sola impostazione, visibile in ognuna.
- La scheda eseguibile «Comprando in anticipo» sta **dentro** la sezione «Compro in anticipo».
- Registrare da ora + recuperare dallo storico solo il recuperabile.
- I 4 registri cancellati il 19 agosto alle 11:54 (`scenario_log`, `track_record`, `exit_history`,
  `conv_log`): **non ripristinare, non indagare**, è stata l'altra sessione.
- La scheda «⚖️ Effetto dei filtri» l'ho tenuta di mia iniziativa: l'utente può volerla togliere.
- Stile: italiano semplice, senza codici interni o gergo tra parentesi, ma spiegando come funziona.

## 6. Altro rimasto indietro

- Delle 33 voci dell'elenco iniziale ne sono state fatte poche: i passaggi (1, 3, 4 in parte),
  la chiarezza della matrice (25, 26, 27, 28, 29), il calendario (col totale). Restano aperte le
  correzioni di calcolo (dividendi, guardia anti-frazionamento, cambio valuta, obiettivi non
  validati, uscita allo stop) e tutta la parte sulla durabilità dei file (21, 22, 23).
- L'artefatto con le 33 voci: https://claude.ai/code/artifact/77ad660e-6970-4c16-a445-0ee9dc293be6
- I due mockup: `Documenti/finanza/mockup_scenari/`
