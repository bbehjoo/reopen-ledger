# Feed hours, measured

Generated 2026-11-08 from `data/raw/feeds` (every `AnswerUpdated` of every phase aggregator since 2026-08-24). Checks the session in `config/calendar.yaml`.

| token | updates | closed spans | updates inside a closed span | first update after reopen, median min | max min | median updates per open day |
|---|---:|---:|---:|---:|---:|---:|
| AAPLc | 462 | 10 | 0 | 0.8 | 1.6 | 7 |
| AMZNc | 644 | 10 | 0 | 0.6 | 0.9 | 8 |
| CRCLc | 3046 | 10 | 0 | 0.7 | 0.9 | 55 |
| GOOGLc | 639 | 10 | 0 | 0.7 | 0.8 | 10 |
| INTCc | 2474 | 10 | 0 | 0.7 | 1.4 | 39 |
| METAc | 1095 | 10 | 0 | 0.6 | 0.9 | 16 |
| MSFTc | 554 | 10 | 0 | 0.6 | 0.9 | 8 |
| MSTRc | 3128 | 10 | 0 | 0.6 | 0.9 | 55 |
| NVDAc | 798 | 10 | 0 | 0.6 | 0.9 | 11 |
| SNDKc | 3077 | 10 | 0 | 0.5 | 0.8 | 48 |
| SPCXc | 1652 | 10 | 0 | 0.6 | 0.9 | 25 |
| TSLAc | 1090 | 10 | 0 | 0.7 | 0.9 | 15 |

The three 24/7 feeds (GOOGL, NVDA, TSLA) first published on 2026-11-04 and 2026-11-05 (one phase each), so no measured closed span contains them yet. They did update during the span in progress when this note was written (GOOGL last at Sun 2026-11-08 17:12 EST, NVDA 18:03, TSLA 17:18). The weekend of Nov 6 to 8 is the first with a 24/7 value to set next to the DEX price.

Closed spans measured: closed 2026-08-28 (Fri) -> 2026-08-30 (Sun), closed 2026-09-04 (Fri) -> 2026-09-07 (Mon), closed 2026-09-11 (Fri) -> 2026-09-13 (Sun), closed 2026-09-18 (Fri) -> 2026-09-20 (Sun), closed 2026-09-25 (Fri) -> 2026-09-27 (Sun), closed 2026-10-02 (Fri) -> 2026-10-04 (Sun), closed 2026-10-09 (Fri) -> 2026-10-11 (Sun), closed 2026-10-16 (Fri) -> 2026-10-18 (Sun), closed 2026-10-23 (Fri) -> 2026-10-25 (Sun), closed 2026-10-30 (Fri) -> 2026-11-01 (Sun).

Reading: no 24/5 feed updated inside any closed span, Labor Day included (the span ran Friday Sep 4 20:00 to Monday Sep 7 20:00 ET). Every feed published within minutes after 20:00 ET at each reopen. The calendar in `config/calendar.yaml` matches the data.
