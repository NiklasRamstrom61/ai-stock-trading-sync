# ai-stock-trading-sync

Molnunderlag för säker kvällssynkning av marknadsdata till
`AI_Stock_Trading_Simulator_v1.xlsx`.

Projektet innehåller ingen Excel-fil, inga OneDrive-länkar och inga hemligheter.
Se [RUNBOOK.md](RUNBOOK.md) för spärrar och körordning.

## Codex Cloud

Begär den personliga miljövariabeln `EODHD_API_KEY` och ge nätåtkomst endast
till `eodhd.com` och `api.riksbank.se`. Codex Cloud kan göra säkra
förkontroller, men ska inte skriva arbetsboken: anslutningen ger inte en råfil
som går att säkerhetskopiera och byte-verifiera.

## Azure för obevakad körning

Azure-varianten finns i `function_app.py` och `src/`. Den använder Microsoft
Graph med Managed Identity och har en Azure Blob-säkerhetskopia. Läs
[AZURE_DEPLOYMENT.md](AZURE_DEPLOYMENT.md) innan första körningen.
