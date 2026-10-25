# Agent evaluation: llm, standard suite

- Runs scored: 20  (invalid, not scored: 0)
- Passed: 20 / 20 = 100%  (95% interval 84% to 100%)
- Faults fixed: 43 / 43 in runs with a live feed
- Runs with a false action (a write that should not have happened): 0
- Turns: median 6 (min 2, max 8)
- Input tokens: median 21,547 (min 4,336, max 33,118)
- Seconds per run: median 24 (min 4, max 33)

| Case kind | Passed | Runs |
| --- | --- | --- |
| freeze | 2 | 2 |
| none | 2 | 2 |
| random | 12 | 12 |
| silent | 2 | 2 |
| spikes_only | 2 | 2 |

| # | Kind | Seed | Fault start | Verdict | Fixed | Turns | Input tokens | Seconds | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | random | 1000 | 20 | PASS | 6/6 | 7 | 33,118 | 33 |  |
| 2 | random | 1011 | 30 | PASS | 1/1 | 7 | 23,255 | 24 |  |
| 3 | none | 1022 | 40 | PASS | 0/0 | 2 | 4,336 | 4 |  |
| 4 | random | 1033 | 50 | PASS | 3/3 | 7 | 27,364 | 27 |  |
| 5 | spikes_only | 1044 | 20 | PASS | 0/0 | 2 | 4,343 | 4 |  |
| 6 | random | 1055 | 30 | PASS | 2/2 | 7 | 25,162 | 24 |  |
| 7 | silent | 1066 | 40 | PASS | 1/1 | 7 | 21,111 | 24 |  |
| 8 | random | 1077 | 50 | PASS | 2/2 | 6 | 18,986 | 22 |  |
| 9 | freeze | 1088 | 20 | PASS | n/a (dead feed) | 2 | 4,386 | 6 |  |
| 10 | random | 1099 | 30 | PASS | 3/3 | 6 | 21,893 | 23 |  |
| 11 | random | 1110 | 40 | PASS | 4/4 | 6 | 23,921 | 29 |  |
| 12 | random | 1121 | 50 | PASS | 1/1 | 7 | 21,201 | 23 |  |
| 13 | none | 1132 | 20 | PASS | 0/0 | 2 | 4,341 | 4 |  |
| 14 | random | 1143 | 30 | PASS | 5/5 | 7 | 29,457 | 33 |  |
| 15 | spikes_only | 1154 | 40 | PASS | 0/0 | 2 | 4,341 | 4 |  |
| 16 | random | 1165 | 50 | PASS | 4/4 | 7 | 26,715 | 28 |  |
| 17 | silent | 1176 | 20 | PASS | 3/3 | 6 | 20,682 | 24 |  |
| 18 | random | 1187 | 30 | PASS | 4/4 | 6 | 23,886 | 26 |  |
| 19 | freeze | 1198 | 40 | PASS | n/a (dead feed) | 2 | 4,388 | 5 |  |
| 20 | random | 1209 | 50 | PASS | 4/4 | 8 | 32,385 | 30 |  |
