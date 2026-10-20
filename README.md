# Investimenti Milano: monolocali vicino alle università

Avvio dashboard:   `python3 server.py`  →  http://localhost:8765
Nuova ricerca:     pulsante "Nuova ricerca" sulla pagina, oppure `python3 run.py`
Solo ricalcolo:    pulsante "Ricalcola", oppure `python3 run.py --solo-valuta`

## Agenti
| Agente | File | Cosa fa |
|---|---|---|
| Ricerca | `agents/ricerca.py`, `agents/fonti.py` | Monolocali in vendita da Subito.it, Tecnocasa, Casa.it, Idealista, Immobiliare.it (avvisi email) + affitti (per i canoni); tiene quelli entro `raggio_universita_km` da un ateneo |
| Catalogatore | `agents/catalogatore.py` | Normalizza, estrae spese/email/telefono dal testo, scarta aste/nude proprietà/box, unisce i doppioni tra portali |
| Valutatore | `agents/valutatore.py` | Punteggio 0-100: valore, rendimento netto, posizione, stato, costi, dimensione → top 20 |
| Email | `agents/mailer.py` | Dopo la tua conferma sulla pagina scrive alle agenzie per chiedere un appuntamento |

## Fonti
- **Subito.it, Tecnocasa**: HTTP diretto, stabili.
- **Casa.it, Idealista**: Firefox headless, best-effort; se il portale chiede la verifica anti-bot vengono saltate (sulla pagina risultano "non disponibile").
- **Immobiliare.it**: il sito blocca le visite automatiche (DataDome), quindi gli annunci arrivano
  dagli **avvisi email**: su immobiliare.it salva una ricerca (Milano, monolocali, fascia di prezzo) e
  attiva le notifiche "istantanee". L'agente legge via IMAP le email di `notifiche.immobiliare.it` degli
  ultimi `ricerca.immobiliare_email_giorni` giorni (fonte `immobiliare_email`), con la stessa password per le app.

## Invio email reale (Gmail)
1. Attiva la verifica in 2 passaggi sull'account Google.
2. Crea una "password per le app": https://myaccount.google.com/apppasswords
3. In `config.json` → `email`: `"abilitato": true`, `"password_app": "xxxx xxxx xxxx xxxx"`, ed eventualmente `"telefono"`.
Senza questi dati le email vengono salvate come bozze in `data/bozze/*.eml` (apribili con Thunderbird).

## Parametri
Tutto in `config.json`: budget, raggio, atenei (coordinate), costi (agenzia, imposte, lavori €/mq per stato,
IMU, cedolare, sfitto) e pesi dei criteri.

## Ricerca automatica giornaliera + report email
Timer systemd utente: ogni giorno alle 8:00 esegue `run.py --report`: nuova ricerca, classifica
aggiornata e invio della top 20 con i link a `config.json` → `report.destinatari`.
Se il PC è spento alle 8, la ricerca parte alla prima accensione/login.
- Stato:      `systemctl --user list-timers investimenti-milano.timer`
- Log:        `journalctl --user -u investimenti-milano.service` oppure `data/agenti.log`
- Esegui ora: `systemctl --user start investimenti-milano.service`
- Disattiva:  `systemctl --user disable --now investimenti-milano.timer`
- Solo report della classifica attuale: `python3 run.py --solo-report`

## Prima installazione
`cp config.example.json config.json` e compila la sezione `email` e `report.destinatari`.
`config.json` e `data/` non sono nel repository: contengono password e dati personali.

## Docker (es. NAS QNAP con Container Station)
In `config.json` imposta `"server": {"porta": 8765, "host": "0.0.0.0"}`, poi:
`docker compose up -d --build`  →  http://IP-DEL-NAS:8765
Il container avvia la dashboard e ogni giorno all'orario `report.orario` esegue `run.py --report`
(in Docker non serve il timer systemd). La dashboard non ha password: non esporla su Internet.
