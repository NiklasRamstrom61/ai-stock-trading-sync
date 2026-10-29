# Säker dagsuppdatering – AI Stock Trading Simulator

## Syfte

Detta projekt hämtar och validerar en komplett daglig EODHD-snapshot för sex
instrument samt dagsaktuell USD/SEK från Sveriges Riksbank. Koden skapar bara
en snapshot. Excel-redigering utförs först efter alla kontroller nedan.

## Obligatoriska spärrar

1. `EODHD_API_KEY` ska finnas som en hemlighet och får aldrig skrivas till logg,
   fil eller Git.
2. Alla sex instrument ska ha samma kompletta sessionsdatum.
3. USA-sessionen måste ha stängt och 30 minuter måste ha passerat.
4. USD/SEK-datumet måste vara samma som USA-sessionens datum.
5. Hämta exakt OneDrive-filen `AI_Stock_Trading_Simulator_v1.xlsx` och kontrollera
   dess drive-id, item-id och aktuella version före skrivning.
6. Spara en lokal säkerhetskopia före ändring.
7. Vägra skrivning om en komplett rad redan finns för ticker + sessionsdatum,
   eller om Run ID redan finns.
8. Ändra endast `Market_Data` och lägg till exakt en rad i `Run_Log`.
9. Ändra aldrig `AI_Decisions`, `Portfolio`, `Transactions`, innehav, signaler
   eller order.
10. Kontrollera formler efter uppdatering och hämta tillbaka uppladdad fil för
    byte-för-byte-verifiering.

## Tillåtna nätmål

* `eodhd.com`
* `api.riksbank.se`
* OneDrive/SharePoint via den anslutna Microsoft-anslutningen

## Schemalagd körning

Kör vardagar 21.30 svensk tid. Svara med `DATA UPPDATERAD` endast när både
uppladdning och efterkontroll lyckats, annars `ÅTGÄRD KRÄVS` utan skrivning.
