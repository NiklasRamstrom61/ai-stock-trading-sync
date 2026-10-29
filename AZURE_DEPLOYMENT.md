# Azure-drift: säker OneDrive-synkning

Azure Function använder Microsoft Graph direkt för att läsa och ersätta samma
OneDrive-fil. Första produktionssteget är medvetet begränsat till ett
kontrollerat `Run_Log`-test; ingen marknadsdata skrivs ännu.

## Säker driftordning

1. Skapa Azure Function App med Python och en Storage Account.
2. Välj Windows Consumption, eller Linux Premium/Dedicated, om schemat ska
   följa svensk sommartid. Sätt `WEBSITE_TIME_ZONE` till `W. Europe Standard
   Time` på Windows eller `Europe/Stockholm` på Linux Premium/Dedicated.
3. Aktivera systemtilldelad Managed Identity för Function App.
4. Ge identiteten behörighet att skriva Azure Blob i lagringskontot.
5. Ge identiteten Microsoft Graph-appbehörighet till just SharePoint-webbplatsen
   med `Sites.Selected` och tilldela därefter webbplatsens skrivroll. Använd
   inte bred `Files.ReadWrite.All` om ni kan undvika den.
6. Lägg appinställningarna nedan i Function App och distribuera detta repo.
7. Starta med `RUN_MODE=preflight`. Granska loggen.
8. Byt endast för ett övervakat test till `RUN_MODE=run_log_test` och kör en
   gång. Återställ sedan `RUN_MODE=preflight` tills resultatet är granskat.

| Namn | Värde |
|---|---|
| `TIMER_SCHEDULE` | `0 30 21 * * 1-5` |
| `RUN_MODE` | `preflight` först |
| `GRAPH_DRIVE_ID` | det verifierade OneDrive-drive-ID:t |
| `GRAPH_ITEM_ID` | det verifierade item-ID:t för arbetsboken |
| `BACKUP_CONTAINER` | `workbook-backups` |

## Vad skrivtestet bevisar

- filnamn, storlek och Graph-version kontrolleras före ändring
- originalet säkerhetskopieras först till Azure Blob Storage
- exakt en Run_Log-rad kan läggas till med ett fast, dubblettsäkert test-ID
- `If-Match` avvisar uppladdning om någon annan har sparat samtidigt
- filen hämtas tillbaka och jämförs byte för byte efter uppladdning
- alla XLSX-delar utanför `Run_Log` måste vara byte-identiska

Om något steg fallerar avbryts körningen. Funktionen kan inte skapa signaler,
order eller transaktioner och ändrar inte Portfolio eller Market_Data i denna
första fas.
