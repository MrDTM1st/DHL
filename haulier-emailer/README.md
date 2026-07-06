# DHL Haulier Emailer

Reads the "Synergy DHL Haulier Extract" spreadsheet, finds the orders that
belong to your region, and prepares the customer emails for you.

## Your region

Your region is defined in `regions.json`.

- `active_region` says which region is in use. Right now it's `region_2`.
- Each region lists the delivery **postcode areas** that are yours — the
  letters at the start of a delivery postcode (e.g. `DN3 1RA` -> `DN`).

### Region 2 (current)

23 postcode areas:
`B, CB, CO, CV, DE, DN, DY, HR, IP, LE, LL, LN, NG, NN, NR, PE, S, ST, SY, TF, WR, WS, WV`

### To change your region later

- Tweak Region 2: add or remove a code in its `postcode_areas` list.
- Switch to a whole new region: add a new block under `regions` (copy the
  `region_2` shape, name it `region_3`), then point `active_region` at it.
- Or just ask me and I'll do it.

## Rules

1. **Region filter** — only orders whose *delivery* postcode is in your
   region are picked up. *(in force)*
2. **Supplier-rails book-in** — skip orders moving within the same company
   (same firm collecting and delivering); those get booked in, not emailed.
   *(on hold — to build)*
3. **Reply tracking** — flag out-of-office auto-replies, chase non-repliers,
   and later format answers into a draft. *(to build)*
