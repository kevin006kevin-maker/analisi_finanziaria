export const meta = {
  name: 'continua-caccia-perdite',
  description: 'Riprende la caccia alle perdite dei passaggi: verifica solo quelle rimaste senza verdetto, poi sintetizza tutto',
  phases: [
    { title: 'Refuta', detail: 'verifica avversaria delle perdite rimaste senza verdetto' },
    { title: 'Sintesi', detail: 'risposta finale sui problemi distinti, con le correzioni minime' },
  ],
}

// `args` porta solo i TITOLI (piccoli): il dettaglio di ogni perdita lo legge l'agente dal file,
// perché gli script non possono leggere il disco ma gli agenti sì.
const TITOLI = (args && args.titoli) || []
const ROOT = 'C:/Users/kevin.munaretti/Documents/finanza/analisi_finanziaria'
const CARTELLA = 'C:/Users/kevin.munaretti/Documents/finanza/backup_lavoro_scenari'

const BASE = `Webapp Streamlit in ${ROOT}. app.py = interfaccia, finance_utils.py = motore,
auto_watch.py = lavoro automatico ogni 30 minuti. Registri JSON in locale e sul branch GitHub
«auto-data» (i file assenti dal disco si leggono con: git show origin/auto-data:<file>).

CONTESTO: un'occasione attraversa quattro passaggi — entra in osservazione, entra in «In anticipo»,
entra in Monitoraggio, supera il periodo di conferma. Per ognuno si vogliono a verbale data, prezzo,
convenienza e probabilità di salita/perdita, coi valori VERI di quel giorno. Realizzato con: il
campo «primo» in opp_watch, record_presignals, il dizionario «passaggi» nella riga di scenario,
_snap_alla_data per la conferma, completa_passaggi per lo storico, valori_momento per i filtri.

STATO DI STAMATTINA (20 agosto): le perdite da verificare sono state trovate IERI, quindi qualcuna
può essere superata dai fatti. Verifica sempre sul codice e sui dati di ADESSO:
 · il lavoro automatico ha girato nella notte: il campo «primo» ORA esiste su 38 voci di opp_watch
   su 41 (ieri su nessuna). Una perdita basata su «primo non esiste» va giudicata sui dati veri.
 · il registro degli scenari ha ORA 74 righe (ieri 70), tutte con «passaggi».
 · È GIÀ CONFERMATO, e in corso di correzione mentre lavori, questo difetto: 7 righe hanno il
   momento «osservazione» riempito con una osservazione SUCCESSIVA dello stesso titolo (data e
   prezzo falsi). Se la perdita che ti tocca è questa, dichiarala reale e passa oltre.

REGOLE:
- SOLA LETTURA. Non modificare né scrivere NESSUN file. Nessun git checkout, nessun ripristino.
- Cita file:riga. Non dedurre: verifica nel codice e, dove serve, sui dati.
- python senza stampare i registri interi; con emoji metti davanti PYTHONIOENCODING=utf-8.
- Rispondi in italiano.`

const VERDETTO = {
  type: 'object', additionalProperties: false,
  required: ['titolo', 'reale', 'motivo', 'correzione_minima'],
  properties: {
    titolo: { type: 'string', description: 'il titolo della perdita che hai verificato, copiato uguale' },
    reale: { type: 'boolean', description: 'true SOLO se la sequenza è davvero possibile nel codice di adesso' },
    motivo: { type: 'string' },
    correzione_minima: { type: 'string' },
  },
}

phase('Refuta')
log(`Riprendo da ieri: 19 perdite già confermate, ${TITOLI.length} da verificare`)

const nuovi = (await parallel(TITOLI.map((t, i) => () =>
  agent(`${BASE}

Sei un VERIFICATORE SCETTICO.

1. Apri il file ${CARTELLA}/perdite_trovate.json e trova, nella lista "perdite", la voce il cui
   campo "titolo" è ESATTAMENTE questo:
   ${t}
   (usa python per estrarla e leggerne sequenza, cosa_si_perde e prova; non stampare tutto il file)
2. Il tuo compito è REFUTARLA: prova che quella sequenza NON è possibile nel codice attuale, perché
   un altro pezzo la impedisce o perché il dato è già salvato altrove. Default: se non trovi la
   prova che la perdita è possibile, reale=false.
3. Se invece è reale, indica la correzione più PICCOLA che la chiude, con file:riga.

Ricopia il titolo nel campo "titolo" della risposta, identico, così il verdetto resta agganciato.`,
    { label: `refuta:${i}:${String(t).slice(0, 26)}`, phase: 'Refuta', schema: VERDETTO, effort: 'high' })
))).filter(Boolean)

const reali = nuovi.filter(v => v && v.reale)
log(`Verificate ${nuovi.length}: reali ${reali.length}, scartate ${nuovi.length - reali.length}`)

phase('Sintesi')

const finale = await agent(
  `${BASE}

Scrivi la risposta finale alla domanda dell'utente: «da adesso registra tutto? c'è pericolo che i
dati vengano persi durante l'evoluzione di una occasione?».

MATERIALE:
 · le 19 perdite confermate IERI stanno in ${CARTELLA}/verdetti_abbinati.json (voci con reale=true),
   e il loro dettaglio in ${CARTELLA}/perdite_trovate.json. Leggili.
 · i verdetti di OGGI sono qui sotto.

COMPITO:
1. Rispondi con onestà: la promessa «da adesso registra tutto» regge o no, e dove esattamente no.
2. RAGGRUPPA le segnalazioni che sono la stessa cosa detta da agenti diversi: molte si sovrappongono.
   Voglio un elenco di PROBLEMI DISTINTI, non un elenco di segnalazioni. Di' quante segnalazioni
   confluiscono in ciascun problema.
3. Ordina per quanto capitano davvero (sempre / spesso / raro / solo in caso di guasto) e gravità.
4. Per ciascuno: cosa si perde, la sequenza in due righe, la correzione minima con file:riga.
5. Separa: (a) problemi che riguardano i dati NUOVI, (b) solo lo storico, (c) problemi che scrivono
   un dato SBAGLIATO invece di lasciarlo mancante — questi vanno per primi, sono i peggiori.
6. Chiudi con l'ordine in cui conviene correggerli, e quali si chiudono con la stessa modifica.
7. Italiano semplice, senza gergo tra parentesi, spiegando come funziona.

VERDETTI DI OGGI (${nuovi.length}):
${JSON.stringify(nuovi, null, 1)}`,
  { label: 'sintesi', phase: 'Sintesi', effort: 'high' }
)

return { verificate_oggi: nuovi.length, reali_oggi: reali.length, verdetti_oggi: nuovi, finale }
