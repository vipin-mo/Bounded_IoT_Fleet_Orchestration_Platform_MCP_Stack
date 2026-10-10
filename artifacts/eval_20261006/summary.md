# Agent evaluation

- Runs scored: 20  (invalid, not scored: 0)
- Passed: 20 / 20 = 100%  (95% interval 84% to 100%)
- Faults fixed: 43 / 43 in runs with a live feed
- Runs with a false action (a write that should not have happened): 0
- Turns: median 6 (min 2, max 7)
- Input tokens: median 20,935 (min 4,331, max 26,266)
- Seconds per run: median 26 (min 4, max 139)

| Case kind | Passed | Runs |
| --- | --- | --- |
| freeze | 2 | 2 |
| none | 2 | 2 |
| random | 12 | 12 |
| silent | 2 | 2 |
| spikes_only | 2 | 2 |

| # | Kind | Seed | Fault start | Verdict | Fixed | Turns | Input tokens | Seconds | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | random | 1000 | 20 | PASS | 6/6 | 6 | 26,266 | 34 |  |
| 2 | random | 1011 | 30 | PASS | 1/1 | 7 | 20,950 | 139 |  |
| 3 | none | 1022 | 40 | PASS | 0/0 | 2 | 4,334 | 4 |  |
| 4 | random | 1033 | 50 | PASS | 3/3 | 6 | 20,920 | 26 |  |
| 5 | spikes_only | 1044 | 20 | PASS | 0/0 | 2 | 4,338 | 5 |  |
| 6 | random | 1055 | 30 | PASS | 2/2 | 6 | 20,332 | 24 |  |
| 7 | silent | 1066 | 40 | PASS | 1/1 | 7 | 23,299 | 27 |  |
| 8 | random | 1077 | 50 | PASS | 2/2 | 6 | 18,689 | 23 |  |
| 9 | freeze | 1088 | 20 | PASS | n/a (dead feed) | 2 | 4,387 | 5 |  |
| 10 | random | 1099 | 30 | PASS | 3/3 | 7 | 25,150 | 30 |  |
| 11 | random | 1110 | 40 | PASS | 4/4 | 6 | 22,143 | 26 |  |
| 12 | random | 1121 | 50 | PASS | 1/1 | 7 | 22,952 | 25 |  |
| 13 | none | 1132 | 20 | PASS | 0/0 | 2 | 4,331 | 4 |  |
| 14 | random | 1143 | 30 | PASS | 5/5 | 6 | 25,170 | 28 |  |
| 15 | spikes_only | 1154 | 40 | PASS | 0/0 | 2 | 4,342 | 4 |  |
| 16 | random | 1165 | 50 | PASS | 4/4 | 6 | 21,711 | 27 |  |
| 17 | silent | 1176 | 20 | PASS | 3/3 | 6 | 20,677 | 26 |  |
| 18 | random | 1187 | 30 | PASS | 4/4 | 6 | 23,515 | 31 |  |
| 19 | freeze | 1198 | 40 | PASS | n/a (dead feed) | 2 | 4,391 | 4 |  |
| 20 | random | 1209 | 50 | PASS | 4/4 | 6 | 23,342 | 26 |  |
