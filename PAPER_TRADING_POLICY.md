# Paper-trading policy

## Scope
This policy is for the six approved instruments only and is **paper trading only**. It never submits broker orders.

## Entry screen
A new long **candidate** requires all of the following from a completed common market session:

- closing price above the prior 20-session simple moving average;
- 5-session return of at least 2%;
- latest volume at least 80% of the preceding 20-session average;
- no existing holding in the same instrument;
- no duplicate pending order; and
- the target workbook, completed data session, FX date, and workbook formulas all pass the existing fail-closed checks.

## Portfolio limits
- At most three open positions.
- At most one position per instrument.
- At most one sixth of available paper cash per new position.
- No borrowing, leverage, short positions, or pyramiding.

## Execution and exits
- A candidate can be proposed only after the completed session.
- A separately approved paper order is queued for the next eligible session open; no retroactive fills.
- A position is proposed for exit at the next eligible open if either the close is at least 8% below its entry price or it closes below its 20-session moving average.
- Every proposed order needs an explicit user approval before it is written to Excel or OneDrive.

## Audit requirements
Before any write, create an Azure backup, check the exact OneDrive version, preserve formulas, and verify after upload that only the approved paper-trading fields changed. The daily read-only screen and signal candidates do not alter Excel or OneDrive.
