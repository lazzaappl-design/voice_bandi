# Voice Bandi Monitor

Programma che ogni lunedì legge ~54 fonti (CSVnet, 8x1000, fondazioni bancarie e di comunità, Regioni, Ministeri...)
e produce un report in italiano con i **nuovi link che sembrano bandi**, le pagine modificate e le fonti che non funzionano.

Non usa password né account di terzi. Non valuta se Voice può candidarsi: produce candidati da verificare
(poi li passi a Claude per punteggio e inserimento in dashboard).

File:
- `sources.csv`   elenco fonti (si modifica con Excel o un editor di testo; una riga = una fonte)
- `monitor.py`    il programma
- `.github/workflows/settimanale.yml`   la pianificazione automatica del lunedì (GitHub Actions)
- `state/state.json`   la "memoria" della settimana precedente (la scrive il programma)
- `output/ultimo_report.md`   l'ultimo report

Limiti noti:
- Le pagine che caricano i contenuti con JavaScript risultano "quasi vuote": il report le segnala, vanno controllate a mano.
- Alcuni siti bloccano i programmi automatici (errore 403): vengono segnalati.
- Gli indirizzi in sources.csv non sono stati tutti verificati: la prima esecuzione serve a scoprire quali vanno corretti.
- Le pagine successive di CSVnet (page/2/ ...) sono un'ipotesi sulla struttura del sito.
