# ROADMAP — Analisi Finanziaria (porta 8507): verso l'interpretazione più precisa possibile del mercato

Principio guida di questa roadmap: **nessun cambiamento ai punteggi o ai pesi entra in produzione senza una misura out-of-sample che dimostri il guadagno**. Le proposte sono ordinate per rapporto precisione/rischio reale, non per attrattiva teorica. Ogni voce è ancorata a `finance_utils.py` / `backtest.py` / `ml_verify.py` / `app.py`.

Nota trasversale che pesa su quasi tutto: `conv_log.json` e `conv_weights.json` **non esistono in locale** (vivono sul branch dati, effimeri, cap 6000 righe) e il fit ridge è **dormiente** (`_FIT_MIN_SAMPLES=150`, riga 2805). Molte proposte "validabili sui dati" oggi non lo sono davvero: prima di tutto va garantita e ispezionata la **profondità del conv_log risolto**. Questo è il vero collo di bottiglia (vedi Sezione 3).

---

## 1) Da fare subito — alto impatto / basso rischio

### 1.1 — Benchmark corretto per la forza relativa dei titoli non-USA
- **Cosa**: nello scan la forza relativa usa sempre `^GSPC` (`scan_opportunities` 3107-3109; `relstrength=mom−bench` in `_factor_values` 2689-2690), ma l'universo è per metà EU (RACE.MI, ENI.MI, ASML.AS, SAP.DE…). Esiste già `default_benchmark(ticker)` (950-959) mai chiamata. Raggruppare i ticker per `default_benchmark`, chiamare `_benchmark_perf` una volta per gruppo (cache 900s già presente), assegnare `bench_5d/bench_1m` per-riga. Applicarlo anche al gate forza-relativa in regime alto (3141-3145).
- **Perché più preciso**: `relstrength` (peso 0.5, ed è gate di esclusione) deve isolare l'over/under-performance rispetto al mercato PROPRIO del titolo. Confrontare un .MI con l'S&P inietta rumore macro USA nel residuo idiosincratico. Correzione strutturale, non un parametro fittato.
- **File/funzione**: `scan_opportunities` (3107), `_factor_values` (2689), `default_benchmark` (950).
- **Come validarlo**: IC di `relstrength` vs `ret_21d` sul conv_log segmentato per suffisso mercato, `^GSPC` vs benchmark corretto (ricalcolando `relstrength` dai prezzi storici indice, non dal log che salva già il valore sbagliato). L'IC sui non-USA deve passare da ~0 a positivo. **Non bloccante** per l'adozione (correttezza auto-evidente, downside neutro: se l'indice locale non risolve → `relstrength=None` → fattore neutro).
- **Priorità P1** · **Rischio overfitting: basso** (nessun grado di libertà nuovo).
- **Attenzione**: verificare che i simboli indice risolvano su yfinance (`^FTSEMIB.MI` è dubbio) con fallback esplicito a `^GSPC`; ri-controllare la soglia `−3.0` del gate (3144), tarata sulla distribuzione `^GSPC` — meglio esprimerla in z-score cross-sezionale.

### 1.2 — Prezzi total-return (adjusted) su tutte le fonti
- **Cosa**: `_fmp_history` scarta `adjClose` usando `close` grezzo (41-42); il fallback yfinance usa `auto_adjust=False` (59, 86). Passare yfinance a `auto_adjust=True` (gestisce dividendi+split) e su FMP ricalcolare OHLC col fattore `adjClose/close` (o usare l'endpoint aggiustato, dopo aver verificato che `adjClose` esista nella risposta reale). Mantenere una `RawClose` separata **solo** per il filtro penny `_MIN_PRICE`.
- **Perché più preciso**: il total return è l'unica misura corretta di rendimento/drawdown. Lo stacco cedola fa apparire un falso "sconto dai massimi" e falso RSI ipervenduto proprio sulla classe value/high-yield più presente in un universo "da saldo" (VYM, SCHD, ENI.MI, ISP.MI); gli split non rettificati creano gap fittizi che innescano `_collapsed_or_stale` (3802). Bias sistematico e direzionale.
- **File/funzione**: `_fmp_history` (26-45), `get_history` (49-67), `dd_high/perf` (2224-2228).
- **Come validarlo**: (a) sanity check offline su VYM/SCHD/HYG/ENI.MI/ISP.MI/MO/T, lo scarto medio di `dd_high` grezzo-vs-adjusted deve ≈ yield annuo; (b) `backtest.py horizon=21` prima/dopo su hit-rate e resa netta.
- **Priorità P1** · **Rischio overfitting: basso** (nessun parametro appreso).
- **Requisito NON negoziabile**: nella calibrazione (`resolve_convenience_log` 2866, `resolve_forecasts` 1241) entry ed exit vanno ricalcolati **dalla stessa serie adjusted** — NON confrontare `x['price']` grezzo storico con un exit adjusted ri-fetchato (la serie adjusted è ri-scalata retroattivamente ad ogni dividendo → contaminerebbe proprio la calibrazione). Le righe già risolte con prezzi grezzi vanno messe in quarantena, non mescolate.

### 1.3 — Purge + embargo nel walk-forward ML (SOLO `ml_verify.py`)
- **Cosa**: target `y=Close.shift(-horizon)/Close-1` (riga 48, forward 20g), walk-forward `train=data.iloc[:i]`, `test=data.iloc[i]` senza gap (62-63). Le ultime ~horizon righe di train hanno finestra-obiettivo che sconfina oltre `i` → leakage classico da etichette sovrapposte, mentre la docstring (riga 3) dichiara falsamente "nessun data leakage". Fix: `train=data.iloc[:max(0, i-horizon)]` (purge corretto), `horizon` unico parametro del gap.
- **Perché più preciso**: rimuove un bias ottimistico sistematico dalle metriche (MAE/dir-accuracy) su cui poggia il verdetto ML (riga 126) che l'utente legge per decidere se fidarsi dell'ML. È correttezza metodologica, adottabile a prescindere dal risultato.
- **File/funzione**: `ml_verify.py` righe 48, 57-73.
- **Come validarlo**: run_ml_verify sui 4 ticker default + universo più ampio, before/after: il MAE ML deve peggiorare o restare uguale (se uguale, il leakage non mordeva → nessun danno). Controllo di conferma: shuffle temporale delle etichette → dir-accuracy deve crollare a ~50%. Riportare delta MAE per ticker. Correggere la docstring solo DOPO il fix.
- **Priorità P1** · **Rischio overfitting: basso** (rimuove bias, non aggiunge parametri).
- **Impatto reale ridimensionato**: ~20 righe contaminate su 420-1400 per fold; il verdetto "ML non batte i metodi semplici" probabilmente NON si ribalta. Valore = onestà del check, non salto di precisione. **NON estendere a `backtest.py`**: non ha train da purgare, i trade sono già non sovrapposti (`i += horizon`, riga 105) — vedi Sezione 4.

### 1.4 — Unificare pipeline dati e tracciare la provenienza delle serie
- **Cosa**: `backtest.py` usa `fu.get_history` (FMP→yfinance), mentre `ml_verify.py:44` chiama `yf.Ticker(...).history` diretto: le due validazioni girano su serie diverse. In più `_FMP_STATE='exhausted'` (209-215) fa flippare la fonte tra run senza traccia. Fase A (subito, no backtest): (i) far usare a `ml_verify` `fu.get_history`; (ii) taggare `df.attrs['source']` e `df.attrs['adjusted']` (come già `attrs['intraday']` in `get_chart_history` 82,98); (iii) loggare la fonte in conv_log/forecast_log.
- **Perché più preciso**: la Convenienza usa z-score **cross-sezionali**; se in uno stesso scan alcuni ticker vengono da FMP e altri da Yahoo (per quota/cache) la sezione mescola convenzioni di prezzo → ranking contaminato. Elimina irriproducibilità locale-vs-GitHub Actions.
- **File/funzione**: `get_history` (49-67), `_fmp_history` (26), `ml_verify.py:44`.
- **Come validarlo**: scaricare lo stesso paniere via FMP e via yfinance nello stesso istante, misurare lo scarto su `perf_1m/dd_high/RSI`, isolando i titoli con split recenti (scarto grande) dagli altri (~rumore).
- **Priorità P1** · **Rischio overfitting: basso** (infrastruttura).
- **Attenzione**: prima di far usare a `ml_verify` `fu.get_history`, correggere `_PERIOD_DAYS["max"]` (=0 → nessun filtro `from`) o forzare una finestra lunga esplicita, altrimenti `ml_verify` perde storia e la guardia `>=900` righe fallisce. Aggiungere una guardia che rifiuti/segnali panieri con `source` mista in uno stesso scan.

### 1.5 — Neutralizzare la barra giornaliera parziale sull'RVOL
- **Cosa**: in seduta l'ultima barra daily è incompleta (dati ~15 min ritardati). `RVOL=last_vol/avg20` (2258-2261) confronta un volume parziale con 20 giornate intere → bias sistematico verso il basso proprio sul segnale "conferma capitolazione". Fix più semplice e robusto: **schedulare il cron di scan/snapshot dopo la chiusura del mercato** (risolve alla radice senza codice fragile). In alternativa, calcolare l'RVOL sull'ultima barra chiusa quando la data dell'ultima riga == oggi-exchange.
- **Perché più preciso**: elimina un bias intragiornaliero su un indicatore usato come gate di conferma (rv>=1.2, riga 2520) e allinea il comportamento live al backtest (che gira su barre chiuse).
- **File/funzione**: `opportunity_row` (2258-2261, 2268, 2274), `get_history` (per il flag `partial_last`).
- **Come validarlo**: campionare RVOL/reversal dello stesso ticker a metà seduta e a chiusura per alcuni giorni, misurare il flip-rate della conferma inversione (alto = difetto). Forward collection, non backtest storico.
- **Priorità P1** · **Rischio overfitting: basso**.
- **Nota**: evitare la logica "mercato aperto" basata sull'orologio di sistema (il codice l'ha deliberatamente evitata, commento 3682). `green_day`/`reversal` intraday sono solo *provvisori*, non biased: al più etichettarli, non serve escluderli.

### 1.6 — Coerenza e onestà del "rendimento atteso" (bias di Jensen)
- **Cosa**: `forecast_paths` mostra `expectancy=mean(exp(final))-1` (1095, media aritmetica), `_gain_loss_prob` usa `exp(median(final))-1` (2385, mediana): lo stesso concetto dà numeri diversi in punti diversi dell'app. Con demean (drift log 0) la media è strutturalmente >0 e cresce con σ. **Unificare** in un helper unico che espone entrambe: mediana="tipico", media="atteso", con caption che spiega il divario log-normale.
- **Perché più preciso**: `mean(exp)-1` NON è un bug (è il valore atteso aritmetico corretto), ma mostrarlo da solo come unico "rendimento atteso" induce l'utente a sovrastimare i titoli volatili dove non c'è edge direzionale. Onestà interpretativa.
- **File/funzione**: `forecast_paths` (1095, `ret_p50` già calcolato a 1097), `_gain_loss_prob` (2385), display in `app.py:748`.
- **Come validarlo**: Monte Carlo controllato con drift=0 e σ crescente → "medio" cresce con σ, "tipico" resta ~0 entro errore MC. Script di 10 righe, nessun dato esterno.
- **Priorità P2** (metrica di display, ma effort minimo) · **Rischio overfitting: basso** · **must_backtest: no**.
- **SCARTARE** la sottrazione del termine di Jensen gaussiano `exp(var/2)-1`: incoerente con la distribuzione block-bootstrap non-gaussiana e ridondante col drift già nullo (vedi Sezione 4).

---

## 2) Da validare prima col backtest

Interventi con logica sana ma rischio di sovra-adattamento o dati oggi insufficienti. Per ciascuno indico **esattamente il test che fa fede**.

### 2.1 — Fit della Convenienza cross-sezionale: demean del target PER-DATA
- **Cosa**: `fit_conv_weights` (2889) demedia `ret_21d` **una volta globalmente** (`y=y-y.mean()`), ma le feature X sono z-score cross-sezionali. In mercato direzionale i pesi imparano beta/regime, non alfa. Fix Fase A: raggruppare le righe per `x['date']`, sottrarre la media di giornata da `ret_21d` prima della ridge (mantenendo `np.linalg.solve`). Fix 1b: standardizzare anche X per-data (allinea a `_score_universe`).
- **Perché più preciso**: l'alfa da "convenienza" è per definizione cross-sezionale; regredire il rendimento assoluto confonde market timing con selezione titoli.
- **File/funzione**: `fit_conv_weights` (2875-2899), coerente con `_score_universe` (2755).
- **Test che fa fede**: walk-forward a fold espandenti con embargo ≥21g sul conv_log; rank-IC OOS di **(a) prior, (b) ridge globale attuale, (c) ridge+demean-per-data**. Adottare (c) SOLO se IC OOS >0 e > (a)/(b), con t-stat corretta per l'overlap 21g (**Newey-West o date non sovrapposte, mai `sqrt(n_righe)`**). Guardia: escludere le date con <5 nomi.
- **Priorità P2** · **Rischio overfitting: medio** (mitigato dalle attenuazioni già presenti: rinorm L1 a 2896, alpha≤0.6, blend coi prior).

### 2.2 — Standardizzazione del fit allineata all'applicazione (per-data, non pooled)
- **Cosa**: `fit_conv_weights` (2886) standardizza i fattori pooled su tutte le date; `_score_universe` (2755) ricalcola mediana/MAD sull'universo del singolo scan → train/serve skew. Ri-standardizzare per-data al fit **mantenendo i fattori grezzi nel log** (NON salvare le z precalcolate: romperebbe la retrocompatibilità e impedirebbe il re-processing).
- **Perché più preciso**: i pesi di un modello lineare hanno senso solo rispetto alla scala su cui agiscono; per-data elimina anche un mild look-ahead (le date future contaminano la normalizzazione pooled).
- **File/funzione**: `fit_conv_weights` (2886), `_robust` (2644).
- **Test che fa fede**: IC OOS walk-forward pooled vs per-data + test KS fra la distribuzione delle z di training e quelle degli scan reali. Adottare solo se l'IC OOS sale/si stabilizza in modo non marginale. Fallback pooled se un gruppo-data ha <5 titoli (evita `_robust` neutro).
- **Priorità P2** · **Rischio overfitting: basso** (semmai regolarizzante).
- **Nota**: guadagno atteso piccolo — la rinorm L1 già presente (2896) neutralizza lo skew di scala assoluta, sopravvive solo la distorsione relativa fra fattori. Quantificare prima di investire.

### 2.3 — Calibrare la Convenienza 0-100 + baseline rolling delle statistiche
- **Cosa**: due parti da destini diversi. **(A, adottabile dopo backtest)** ancorare la standardizzazione a una baseline rolling (EMA di mediana/MAD per-fattore persistita) → elimina la varianza spuria da solo cambio-universo. **(B, solo diagnostica gated)** mappa monotona `conv_raw → P(ret_21d>0)` appresa walk-forward, mostrata come colonna diagnostica, NON come driver decisionale.
- **Perché più preciso**: la Convenienza è un rank relativo non stazionario confrontato con costanti fisse (`_OBS_ENTRY_CONV=60`, `_PROMO_MIN_CONV=55`); (A) rende il numero comparabile nel tempo, (B) gli darebbe (se validato) un significato assoluto verificabile.
- **File/funzione**: `_score_universe` (2755), `_conv_from_factors` (2717), soglie a 3290/3587.
- **Test che fa fede**: (A) esperimento a paniere fisso su N scan con universi diversi → riduzione misurabile della varianza della Convenienza. (B) reliability diagram walk-forward sul conv_log che **provi** monotonicità OOS *prima* di applicare l'isotonica; usare `P(ret>0)` (regime-robusto) non `E[ret]`; correggere per overlap 21g. **Non spostare le soglie 60/55 sulla scala calibrata** finché (B) non è stabile su ≥2 fold.
- **Priorità P1 per (A), P2 per (B)** · **Rischio overfitting: alto per (B)** (l'isotonica forza monotonicità anche dove i dati non la sostengono).

### 2.4 — Misurare (non ancora invertire) il SEGNO dei fattori via IC
- **Cosa**: orientamenti cablati a mano (`discount=-dd`, `momentum=-mom`, riga 2675-2679) e `clip(...,0,None)` in `fit_conv_weights` (2898) + `if v>=0` in `_active_weights` (2926) rendono un fattore mis-orientato **non falsificabile**. **Fase 1 (subito, rischio ~zero)**: `factor_ic(kind)` come strumento READ-ONLY — IC rank cross-sezionale per-data (stile Fama-MacBeth), t-stat Newey-West, hit-rate del segno, salvato in un blocco "audit" di `conv_weights.json`. Nessun cambio di comportamento.
- **Perché più preciso**: l'IC è la misura ex-ante standard; oggi il momentum negativo sul long potrebbe cancellare l'edge di quality senza che nessuno lo veda.
- **File/funzione**: `_factor_values` (2668-2697), `fit_conv_weights` (2898), `_active_weights` (2926).
- **Test che fa fede (Fase 2, differita)**: auto-inversione/de-pesatura SOLO se l'IC OOS ha segno opposto al prior con robustezza su ≥2 refit indipendenti, **correzione multiple-testing (Benjamini-Hochberg)** su ~10-19 fattori, e miglioramento dell'IC composito OOS. Per liberare il segno serve modificare SIA il clip (2898, a `[-|prior|,+|prior|]`) SIA il gate `v>=0` (2926).
- **Priorità P1 per la misura, P2 per l'automazione** · **Rischio overfitting: alto per l'auto-flip** (declassare a warning se i dati sono sottili).

### 2.5 — Pesi/scala della Convenienza condizionati al regime di volatilità
- **Cosa**: il regime entra solo come moltiplicatore globale di `_short_score` (3131) e filtro binario (3141), non tocca i pesi/scala della Convenienza. Il mean-reversion da ipervenduto **inverte segno nei crash**. Fase 1 (subito): loggare il bucket di regime in `_log_convenience` (2827) + backfill retroattivo dallo storico `^VIX`. Fase 2: NON ridge per-bucket indipendenti (bucket crash affamato), ma **shrink deterministico** dei pesi oversold/discount verso 0 in alta volatilità (analogo al moltiplicatore già esistente).
- **File/funzione**: `volatility_regime` (3011-3036), `_conv_from_factors` (2717), `_log_convenience` (2827).
- **Test che fa fede**: IC di ciascun fattore per bucket, walk-forward con embargo, contando i **cluster-episodio** (non le righe: i crash sono pochi e autocorrelati). Adottare lo shrink solo se il sign-flip di oversold/discount emerge davvero sui dati.
- **Priorità P2** · **Rischio overfitting: alto** per la variante ridge-per-bucket (da scartare).

### 2.6 — Prossimità agli earnings come feature/affidabilità/gate soft
- **Cosa**: `opportunity_row` (2205-2336) ignora la data trimestrale; il bootstrap di `_gain_loss_prob` (2317) non modella il salto d'evento. Aggiungere `days_to_earnings`; usarlo come moltiplicatore `event_risk` **separato** (non dentro `_reliab_factor`, che misura la qualità della stima), info in tabella, e gate SOFT (declassa, non elimina). Loggarlo subito nel conv_log per abilitare la calibrazione futura.
- **Perché più preciso**: la proximity-to-earnings è un predittore ex-ante riconosciuto della **dispersione** dei rendimenti (non dell'hit-rate direzionale).
- **File/funzione**: `opportunity_row` (2205), `_reliab_factor` (2423-2430).
- **Test che fa fede**: bucket (`≤5g / 6-20g / >20g`) su dispersione/code del `ret_21d` in `backtest.py` esteso (date earnings ricostruibili storicamente via `get_earnings_dates`); IC dei fattori tecnici dentro/fuori finestra; Brier di `prob_gain` segmentato. Attivare il gate SOLO se l'effetto è netto.
- **Priorità P2** · **Rischio overfitting: basso** (1 feature, prior economico chiaro) · **must_backtest: sì**.
- **Attenzione fattibilità**: `get_earnings_dates` è rate-limited/instabile in headless e lacunosa sugli EU; fase 0 di copertura, `days_to_earnings=None` = neutro; cache persistita sul branch. NON è point-in-time ricostruibile per validazione storica → prova forward.

### 2.7 — Universo point-in-time / survivorship bias
- **Cosa**: `_FALLBACK_UNIVERSE` (2594) e le liste EU/ETF sono vincitori odierni; `backtest.py` (47) le usa con storia a ritroso → hit-rate ottimistico. **Fase 0 (obbligatoria, economica)**: eseguire il test A/B prima di investire. **Deliverable subito**: etichetta di onestà nell'output di `backtest.py` ("universo survivor-biased, hit-rate ottimistico") + conteggio ticker senza 2y di storia. **Correzione più impattante**: in `resolve_convenience_log` (2836) trattare un delisting/serie sparita come rendimento fortemente negativo invece di lasciare `ret_21d=None` (che lo fa cadere da `fit_conv_weights`) → i pesi ridge non ereditano survivorship.
- **File/funzione**: `backtest.py:47`, `resolve_convenience_log` (2836), `fit_conv_weights` (2882).
- **Test che fa fede**: iniettare ~15 delisting noti in `backtest.py` — ma prima verificare se yfinance restituisce le loro serie pre-delisting (quasi sempre vuote → delta ~0, l'approccio naive non corregge nulla). Delta materiale (>3-5pp) giustifica la membership storica.
- **Priorità P2 per l'etichettatura+fix-training, P3 per la ricostruzione point-in-time** · **Rischio overfitting: basso** (riduce ottimismo).

---

## 3) Fondamenta / infrastruttura di misura — la leva più importante

Questa è la sezione decisiva. Oggi **il sistema decide di "imparare" contando righe grezze, non prove empiriche**, e valida un segnale diverso da quello mostrato. Chiudere il loop `conv_log/forecast_log → fit → pesi attivi` con misure oneste è ciò che rende la precisione crescente nel tempo. Ordine di costruzione:

### 3.0 — Prerequisito: ispezionare e irrobustire il substrato dati
Prima di ogni altra cosa: recuperare il conv_log reale dal branch e **contare le righe RISOLTE (`ret_21d≠None`) per kind, le DATE distinte e i ticker/data**. Regola di stop generale: procedere alla validazione OOS solo con ≥8-12 date-fold indipendenti, ognuna con ≥15-20 nomi. Poiché il conv_log è cappato a `rec[-6000:]` (2833) su branch effimero, salvare **snapshot periodici degli aggregati per-data** così la profondità walk-forward non si perde al trimming.

### 3.1 — Numerosità EFFETTIVA (campioni non sovrapposti) in gate, alpha e ogni CI
- **Cosa**: `ret_21d` è forward 21g, loggato 1/giorno/ticker → osservazioni fortemente autocorrelate. `_FIT_MIN_SAMPLES=150` (2805) e `alpha=min(0.6, len/1000)` (2897) contano righe grezze: alpha cresce su dati ridondanti riducendo lo shrinkage proprio quando i dati sono più fragili. Calcolare `n_eff` dalla struttura reale **date×ticker** (blocchi non sovrapposti da 21 sedute, coprendo anche la correlazione cross-sezionale di stesso-giorno — NON `len/21` cieco) e usarlo nel gate, nel denominatore di alpha e in TUTTI i CI (block-bootstrap per data).
- **Perché è la leva**: sovrastimare `n` gonfia alpha e restringe falsamente i CI → il sistema si convince di avere evidenza statistica che non ha. La correzione è **conservativa** (tiene il sistema dormiente più a lungo sui prior): può solo renderlo più prudente.
- **File/funzione**: `_log_convenience` (2809), gate 2883, alpha 2897; eredita anche `ml_verify.py:84` e `backtest.py`.
- **Come validarlo**: autocorrelazione delle etichette per ticker (deve decadere ~lineare su 21g); walk-forward fit con `n` grezzo vs `n_eff` → l'IC OOS con `n_eff` deve avere minore varianza tra fold (IR più alto).
- **Priorità P1** · **Rischio overfitting: basso**. La parte **gate+alpha su `n_eff` è sicura da adottare subito**; aggiungere subito il campo diagnostico `n_eff` accanto a `len(rows)` nella scheda voti.

### 3.2 — Attivazione sicura dei pesi appresi: shadow-mode con gate su IC OOS
- **Cosa**: `fit_conv_weights` (2875) fa ridge in-sample su tutto il conv_log; l'attivazione (`_active_weights` 2918) è gated SOLO da `len(rows)>=150`, senza metrica di bontà. Introdurre in `update_conv_weights` uno shadow-mode: fold espandenti con embargo 21g, rank-IC OOS cross-sezionale (conv predetta vs `ret_21d` demeanato per-data) dei pesi PRIOR e APPRESI. **Modulare** alpha con la skill OOS (`alpha_eff = alpha_rows · sigmoid(k·(IC_learned−IC_prior))`) invece di un gate binario, con soglia = estremo inferiore del block-bootstrap > 0 (non `+0.02` fisso). Persistere `oos_ic/streak/asof` in `conv_weights.json` e mostrarli. Loggare entrambe le convenienze in shadow.
- **Perché è la leva**: sposta la decisione di "imparare" da un conteggio di righe (gonfiato dall'overlap) a una prova che i pesi ordinano meglio i titoli per rendimento futuro. È il walk-forward che l'obiettivo pretende.
- **File/funzione**: `update_conv_weights` (2902), `_active_weights` (2918), `fit_conv_weights` (2875).
- **Come validarlo**: sul conv_log esistente, IC_learned vs IC_prior con test appaiato + block-bootstrap sulle date + resa top-decile. Gate giustificato solo se IC_learned domina OOS. Simmetria short/long: per `kind='short'` orientare correttamente il segno di `ret_21d`.
- **Priorità P1** · **Rischio overfitting: medio** (mitigato: cap learned 0.6, blend coi prior).

### 3.3 — Backtestare il punteggio REALMENTE mostrato (Convenienza + Occasione)
- **Cosa**: il numero più prominente (Occasione, `_short_score`/`_long_score`) è a pesi cablati senza feedback; le soglie 35/50 (3132/3166) non hanno copertura empirica; `backtest.py:78` ricostruisce solo la rampa RSI grezza; la tabella è ordinata per Convenienza (3181), mai backtestata. **Fase A (subito)**: `backtest_convenience()` sulla Convenienza loggata — rank-IC per data, IR, decile-spread top-vs-resto, block-bootstrap clusterizzato per data (blocco≥21), `n_eff`. **Fase B (differita)**: aggiungere allo `_log_convenience` lo score Occasione + i campi mancanti (`below_bb`, `reversal_confirmed`, `green_day`, `rvol`, `vertical_crash`, `regime`), poi validare l'Occasione — oggi NON ricostruibile dal conv_log.
- **Perché è la leva**: si valida la cosa sbagliata. È il rischio n.1 per la precisione.
- **File/funzione**: `_short_score` (2462), `_long_score` (2547), `_log_convenience` (2827), `backtest.py:78`.
- **Come validarlo**: per evitare leakage, **rifittare ridge + ristimare le stat robuste per ogni training-fold** point-in-time. Mostrare IC/IR/decile come diagnostica; **NON sostituire 35/50** finché `n_eff` non supera una soglia minima e le soglie non sono stabili tra fold (mai prendere l'argmax puntuale dell'IC). Riportare il p-value deflazionato (Deflated Sharpe/Bailey-López de Prado) dato il grid-search su tutto l'universo.
- **Priorità P1** · **Rischio overfitting: medio/alto** (guidato dalla scarsità di date distinte).

### 3.4 — Scollegare la MISURA di calibrazione dal gate di promozione
- **Cosa**: `track_record` contiene SOLO nomi auto-promossi (`last_conv>=55`, 3761): la fascia <50 di `track_record_calibration` (4073-4112) è **vuota per costruzione** → selection bias, la scheda non può falsificare il punteggio. Usare `conv_log.json` (che logga TUTTO l'universo incondizionato, 3114) come substrato: rank-IC di Spearman conv vs `ret_21d` sull'intera sezione per data. Rinominare `track_record` "esito/rendimento realizzato delle promozioni" e **togliere la parola calibrazione**.
- **Perché è la leva**: è l'unico modo per rispondere onestamente a "l'alta convenienza rende di più?" sulla popolazione su cui il punteggio è realmente applicato.
- **File/funzione**: `track_record_calibration` (4073-4112), `_log_convenience` (3114), gate 3761.
- **Come validarlo**: Spearman IC per data, t-stat corretta per overlap (date non sovrapposte o Newey-West, **non `sqrt(n_righe)`**); spread terzile alto-basso con block-bootstrap per data; gate di maturità (mostrare il verdetto solo con abbastanza date/nomi). Riportare quante righe restano non risolte (survivorship).
- **Priorità P1** · **Rischio overfitting: basso** (strumento di misura, non cambia score/gate).

### 3.5 — Brier onesto: decomposizione di Murphy + Brier Skill Score, PER ORIZZONTE
- **Cosa**: `calibration_report` (1250-1266) calcola solo il Brier grezzo; l'app etichetta "0,25 = a caso" (app.py:1129-1131), ma 0,25 è "a caso" solo se la base-rate è 50%. Implementare `Brier = Reliability − Resolution + Uncertainty` e `BSS = 1 − Brier/(p̄(1−p̄))` come numero-titolo. **Stratificare per orizzonte** (h=21 e h=252 hanno base-rate molto diverse: un BSS pooled mostrerebbe una Resolution fittizia da pura eterogeneità).
- **Perché è la leva**: separa "le probabilità sono oneste" (reliability, correggibile con Platt/isotonica) da "discriminano" (resolution, il vero valore). Un Brier basso può essere tutto Uncertainty con Resolution nulla.
- **File/funzione**: `calibration_report` (1250-1266), `forecast_paths` (demean a 1079).
- **Come validarlo**: sui record risolti, BSS/Reliability/Resolution per orizzonte + CI block-bootstrap (cluster per data). Guardia: non mostrare t-stat/verdetto se `n_resolved < ~50` per orizzonte. Atteso: per h=21 (demean → p_up~50) Resolution~0 e BSS≤0 — è ciò che la decomposizione deve rivelare, non un bug.
- **Priorità P1** · **Rischio overfitting: basso** · **must_backtest: no** (riscrittura algebrica esatta).

### 3.6 — Intervalli di confidenza e significatività su tutta la scheda voti
- **Cosa**: `track_record_stats.hit%` (4066), i bucket di `calibration_report` (1263-1265) e il verdetto a `n>=3` (4102) sono stime puntuali senza incertezza; "la convenienza discrimina" si ribalta su 3 casi. Aggiungere intervalli di **Wilson** (senza scipy: `z=1.96`) per ogni frequenza, e un **permutation test** sullo spread alta-bassa come arbitro del verdetto. Semaforo a tre livelli: "dati insufficienti" (n<3), "provvisorio/possibile rumore" (CI sovrapposti o p≥0.05), "✅ discrimina" (permutazione p<0.05).
- **Perché è la leva**: allinea la scheda voti alla richiesta di suggerimenti validati. Impedisce di agire su segnale illusorio.
- **File/funzione**: `track_record_stats` (4057-4070), `track_record_calibration` (4102), `calibration_report` (1260).
- **Come validarlo**: applicare Wilson/permutazione alle rese per fascia di `backtest.py` e contare quante volte l'attuale verdetto `n>=3` sarebbe stato non-significativo.
- **Priorità P1** · **Rischio overfitting: basso** · **must_backtest: no**.
- **Correzione statistica**: NON usare "CI disgiunti" come *gate* di significatività (corrisponde a un test troppo conservativo, ~0,5%); i CI restano per la visualizzazione, l'arbitro è il permutation test. **NON alzare il gate a `n_eff>=20`** (affamerebbe il verdetto per sempre).

### 3.7 — Calibrazione a orizzonte lungo (252g): segregazione, non finestra
- **Cosa**: la vera causa del mancato consolidamento del lungo NON è la finestra `1y` (il gate usa già i veri giorni di Borsa via `_trading_days_between`, 3693) ma (a) l'eventuale eviction FIFO `rec[-3000:]` (1213) prima della maturazione e (b) il log giovane. **Separare la persistenza per orizzonte** (log breve/lungo distinti o cap FIFO per-h) così le righe 252g non espellono le brevi mature; **segregare Brier/reliability per orizzonte** in `calibration_report` con etichetta "breve verificato / lungo in maturazione"; usare `_trading_days_between` anche per il prezzo-target (elimina il bias ~12g del round calendario).
- **File/funzione**: `resolve_forecasts` (1227-1241), `calibration_report` (1250), cap 1213.
- **Come validarlo**: contare le righe risolte per orizzonte e la data del record più vecchio (se il log è <365g, lo "0 risolti a 252g" è solo giovinezza, non un bug); ri-giocare date passate.
- **Priorità P1 per la segregazione, P2 per la persistenza** · **Rischio overfitting: basso**.
- **SCARTARE** `period='2y'` come cura (diagnosi originaria sbagliata) e le affermazioni che il conv_log/i pesi sarebbero contaminati dal lungo (sono false: `resolve_convenience_log` risolve solo h=5/21) — vedi Sezione 4.

---

## 4) NON fare / bassa priorità

Interventi che sembrano miglioramenti ma non lo sono, o lo sono per un motivo diverso da quello dichiarato. Evitare di sprecare effort qui.

- **Calibrare `_CONV_K` (tanh) via rank-IC / spread decile** — **NON fare come proposto**. `tanh(k·raw/50)` è **strettamente monotona**: il ranking dei titoli è identico per ogni k>0, quindi rank-IC e spread decile per-rango sono **invarianti a k**. La validazione proposta è internamente contraddittoria. Prima verifica banale: confermare su conv_log che `rank-IC(conv, ret_21d)` è costante al variare di k. *Cosa fare invece*: sostituire `int(round())` a riga 2723 con un float (recupera discriminazione nel decile alto) e, se serve, `k=50·1.1/p90(|raw|)` auto-calibrato per-scan (cosmetico, nessun overfit). L'unico effetto reale di k è spostare il cutoff sulla soglia fissa 60: co-calibrare `k` e `_OBS_ENTRY_CONV`, non `k` da solo. **Priorità P3** · overfitting alto se si fitta k sul rumore.

- **Estendere purge/embargo a `backtest.py`** — **NON fare**. `backtest.py` è una simulazione event-driven senza train set da purgare; i trade sono già non sovrapposti (`i += horizon`, riga 105). Il purge non ha nulla su cui agire. La debolezza reale lì è diversa (correlazione cross-ticker contemporanea che sottostima la varianza).

- **Rank-IC come OBIETTIVO del fit** (invece che come metrica) — **NON fare**. Lo Spearman è non-differenziabile, senza soluzione closed-form, e su ~150 campioni sovrapposti è proprio dove nasce il sovra-adattamento. Tenere la ridge least-squares sul target demeanato per-data; usare il rank-IC SOLO per validazione/gate.

- **Ridge per-bucket di regime indipendenti** — **NON fare**. Il bucket "crash" (VIX>35) è raro e fortemente autocorrelato (1-2 episodi): una ridge separata overfitta un singolo crash. Usare shrink deterministico dei pesi mean-reversion in alta volatilità (Sezione 2.5).

- **`clip(-|prior|,+|prior|)` + auto-inversione del segno senza correzione** — **NON fare ora**. Su ~30 osservazioni sovrapposte, invertire il segno su `|t|>2` senza Benjamini-Hochberg flippa fattori sul rumore. Il `clip(0,None)` è blunt ma è un default sicuro. Prima la misura read-only (Sezione 2.4).

- **Breadth calcolata sull'universo di scan** — **NON fare così**. `opportunity_candidates` (3061) è selection-biased (day_losers, penny) e cambia composizione ogni giorno: `pct_above_sma200` misurerebbe la costruzione dello screener, non la partecipazione di mercato → artefatto non-stazionario. Se si vuole la breadth, calcolarla su un **paniere di riferimento FISSO** (costituenti S&P500, o proxy RSP/SPY) come scalare giornaliero separato, validato a livello di GIORNO (cluster per data), e verificare che aggiunga informazione oltre al VIX. Altrimenti skip. **Priorità P2 solo per il logging su paniere fisso**.

- **Potare il fattore `prob` su "IC indistinguibile da zero"** — **NON fare ora**: test sotto-dimensionato (rendimenti sovrapposti + pooling cross-sezionale → poche osservazioni indipendenti), rischio di potare fattori utili sul rumore. *Cosa fare invece, economico*: solo la **matrice di correlazione** dei fattori sul conv_log (costo basso, nessun rischio) — esporrà la collinearità `discount/histcheap/momentum` (il doppio conteggio ribassista, difetto più forte di `prob`); eventualmente fondere quel trio in un unico "cheapness" invece di eliminare `prob`. Per `prob`/`fscore` (input modellati) tracciarne la calibrazione, non assumerne la ridondanza.

- **Ricostruzione point-in-time completa dell'universo (membership storica)** — **P3, rimandare**. La membership storica non è gratuita in modo affidabile e yfinance non conserva i delistati per fallimento; su un universo di 40 mega-cap il survivorship incrementale su 2y è modesto. Fare l'etichettatura di onestà + il fix del training set (Sezione 2.7), non il rebuild.

- **Applicare `net_return_pct` (tassa 26%) alla media degli scenari** — difetto noto (`finance_utils.py:4228`): tassa la media che mescola gain e perdite, sovrastimando l'erosione, e su un rendimento a ~1 mese senza annualizzazione. Bassa priorità ma da correggere quando si tocca il display di Sezione 1.6 (tassare gli scenari positivi, non l'aspettativa).

---

### Sintesi operativa
- **Settimana 1** (nessun dato nuovo richiesto): 1.1 benchmark, 1.3 purge ml_verify, 1.4 pipeline+provenance, 1.5 cron post-chiusura, 1.6 expectancy. Adottare `n_eff` in gate/alpha (3.1, parte sicura).
- **Settimana 2-3**: 1.2 total-return (con caveat calibrazione), + costruire gli **strumenti di misura** 3.3/3.4/3.5/3.6 (rank-IC su conv_log, Brier per-orizzonte, Wilson/permutazione) — sono a rischio ~zero e sbloccano ogni validazione successiva.
- **Dopo accumulo dati** (≥8-12 date-fold risolte per kind): shadow-gate 3.2, poi 2.1/2.2/2.3A/2.4-Fase2 solo se battono i baseline OOS con significatività corretta per overlap.

La leva dominante non è nessun singolo fattore: è **rendere onesta e chiusa la misura** (Sezione 3). Finché il conv_log risolto è sottile, la mossa più precisa è raccogliere dati puliti (total-return, provenance, `n_eff`, logging di regime/earnings/universo) e mostrare incertezza calibrata, non ottimizzare pesi su rumore.


---

## Appendice — proposte verificate (sintesi)

_Audit multi-agente: 8 mappe, 36 proposte grezze, 25 dopo deduplica, 23 sopravvissute alla verifica avversariale._

1. **Eliminare il data-leakage da etichette forward sovrapposte in ml_verify (purge + embargo)** _(=Validazione (backtest/ML))_ — modifica/reale/P1 · modifica/reale/P1
2. **Attivazione sicura dei pesi appresi: shadow-mode con gate su IC out-of-sample walk-forward, invece del solo conteggio righe** _(=Pesi appresi + loop di feedback della Convenienza)_ — modifica/reale/P1 · modifica/reale/P1
3. **Rendere il fit della Convenienza cross-sezionale: demean del target per-data (excess return) e obiettivo rank-IC invece di rendimento assoluto** _(=Pesi appresi + loop di feedback della Convenienza)_ — modifica/reale/P2 · modifica/reale/P2
4. **Allineare la standardizzazione del fit a quella di applicazione: z-score robusto per-data, non pooled** _(=Calcolo Convenienza (core) + fit)_ — modifica/reale/P2 · modifica/reale/P2
5. **Contare la numerosità EFFETTIVA (campioni non sovrapposti) in gate, alpha e in TUTTI gli intervalli di confidenza** _(=Pesi appresi + tutte le misure di calibrazione)_ — tieni/reale/P1 · modifica/reale/P1
6. **Validare e, se serve, invertire il SEGNO di ogni fattore con l'Information Coefficient walk-forward, invece di cablarlo e azzerare i pesi negativi** _(=Calcolo Convenienza (core) + orientamento fattori + fit)_ — modifica/reale/P2 · modifica/reale/P2
7. **Correggere il bias di Jensen nell'expectancy e unificare la definizione media/mediana tra i due entrypoint** _(=Probabilità e previsioni)_ — modifica/reale/P2 · modifica/reale/P2
8. **Calibrare la Convenienza 0-100 su rendimento/probabilità forward realizzati (mappa monotona appresa) e sganciare le soglie fisse non stazionarie** _(=Calcolo Convenienza (core) + Osservazione/promozione)_ — modifica/reale/P1 · modifica/reale/P1
9. **Calibrare empiricamente _CONV_K (saturazione tanh) o passare a una trasformazione a rango, invece del valore cablato 11.0** _(=Calcolo Convenienza (core))_ — modifica/no/P2 · modifica/reale/P2
10. **Rendere risolvibile la calibrazione a orizzonte lungo (252g): finestra dati insufficiente → Brier illusorio e FIFO avvelenato** _(=Probabilità e previsioni / Pesi appresi)_ — modifica/no/P2 · modifica/reale/P1
11. **Backtestare il punteggio REALE mostrato (Occasione e Convenienza) dal conv_log, con rank-IC, decile spread e CI a blocchi** _(=Punteggi Occasione + Validazione (backtest))_ — modifica/reale/P1 · modifica/reale/P1
12. **Misurare l'IC marginale dei fattori e potare/de-correlare i ridondanti (a partire da 'prob')** _(=Calcolo Convenienza (feature) + Probabilità)_ — modifica/no/P2 · modifica/reale/P2
13. **Forza relativa (relstrength) calcolata contro il benchmark corretto per mercato/valuta del titolo** _(=Punteggi Occasione / Dati-universo-regime)_ — tieni/reale/P1 · modifica/reale/P1
14. **Aggiungere la prossimità agli earnings come feature, fattore di affidabilità e gate soft** _(=Fabbrica feature (opportunity_row) + filtri scan)_ — modifica/reale/P2 · modifica/reale/P2
15. **Condizionare pesi/scala della Convenienza al REGIME di volatilità: il mean-reversion inverte segno nei crash** _(=Calcolo Convenienza + regime)_ — modifica/reale/P2 · modifica/reale/P2
16. **Aggiungere la BREADTH di mercato come segnale di timing del mean-reversion** _(=Regime / contesto di mercato)_ — modifica/no/P2 · modifica/reale/P2
17. **Usare prezzi TOTAL-RETURN (adjusted close) invece del close grezzo: dividendi e split contaminano ogni feature di prezzo** _(=Dati, universo, regime)_ — modifica/reale/P1 · modifica/reale/P1
18. **Universo non point-in-time: il survivorship bias struttura la 'normalità' cross-sezionale e gonfia i backtest** _(=Dati, universo, regime)_ — modifica/reale/P2 · modifica/reale/P1
19. **Convenzioni di aggiustamento incoerenti tra fonti e nessuna provenienza registrata sulle serie** _(=Dati, universo, regime)_ — modifica/reale/P1 · modifica/reale/P1
20. **Barra giornaliera parziale e dati fermi non gestiti: RVOL/reversal falsati intraday e 'stale' confuso con delisting** _(=Dati, universo, regime / Monitoraggio e uscita)_ — modifica/reale/P2 · modifica/reale/P1
21. **Brier onesto: decomposizione di Murphy e Brier Skill Score contro la base-rate, non soglia fissa 0,20/0,25** _(=Probabilità e previsioni — calibrazione)_ — modifica/reale/P1 · modifica/reale/P2
22. **Scollegare la MISURA di calibrazione della Convenienza dal gate di promozione: track_record è affetto da selection bias massimo** _(=Misura/calibrazione — track_record)_ — modifica/reale/P1 · modifica/reale/P1
23. **Intervalli di confidenza e test di significatività su tutta la scheda voti: 55% su n=4 non è come 55% su n=400** _(=Misura/calibrazione — scheda voti e bucket)_ — modifica/reale/P1 · modifica/reale/P2
