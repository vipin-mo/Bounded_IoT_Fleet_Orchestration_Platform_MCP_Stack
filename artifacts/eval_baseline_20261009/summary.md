# Agent evaluation: baseline, standard suite

- Runs scored: 20  (invalid, not scored: 0)
- Passed: 20 / 20 = 100%  (95% interval 84% to 100%)
- Faults fixed: 43 / 43 in runs with a live feed
- Runs with a false action (a write that should not have happened): 0
- Turns: median 2 (min 1, max 2)
- Input tokens: median 0 (min 0, max 0)
- Seconds per run: median 8 (min 0, max 8)

| Case kind | Passed | Runs |
| --- | --- | --- |
| freeze | 2 | 2 |
| none | 2 | 2 |
| random | 12 | 12 |
| silent | 2 | 2 |
| spikes_only | 2 | 2 |

| # | Kind | Seed | Fault start | Verdict | Fixed | Turns | Input tokens | Seconds | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | random | 1000 | 20 | PASS | 6/6 | 2 | 0 | 8 |  |
| 2 | random | 1011 | 30 | PASS | 1/1 | 2 | 0 | 8 |  |
| 3 | none | 1022 | 40 | PASS | 0/0 | 1 | 0 | 0 |  |
| 4 | random | 1033 | 50 | PASS | 3/3 | 2 | 0 | 8 |  |
| 5 | spikes_only | 1044 | 20 | PASS | 0/0 | 1 | 0 | 0 |  |
| 6 | random | 1055 | 30 | PASS | 2/2 | 2 | 0 | 8 |  |
| 7 | silent | 1066 | 40 | PASS | 1/1 | 2 | 0 | 8 |  |
| 8 | random | 1077 | 50 | PASS | 2/2 | 2 | 0 | 8 |  |
| 9 | freeze | 1088 | 20 | PASS | n/a (dead feed) | 1 | 0 | 0 |  |
| 10 | random | 1099 | 30 | PASS | 3/3 | 2 | 0 | 8 |  |
| 11 | random | 1110 | 40 | PASS | 4/4 | 2 | 0 | 8 |  |
| 12 | random | 1121 | 50 | PASS | 1/1 | 2 | 0 | 8 |  |
| 13 | none | 1132 | 20 | PASS | 0/0 | 1 | 0 | 0 |  |
| 14 | random | 1143 | 30 | PASS | 5/5 | 2 | 0 | 8 |  |
| 15 | spikes_only | 1154 | 40 | PASS | 0/0 | 1 | 0 | 0 |  |
| 16 | random | 1165 | 50 | PASS | 4/4 | 2 | 0 | 8 |  |
| 17 | silent | 1176 | 20 | PASS | 3/3 | 2 | 0 | 8 |  |
| 18 | random | 1187 | 30 | PASS | 4/4 | 2 | 0 | 8 |  |
| 19 | freeze | 1198 | 40 | PASS | n/a (dead feed) | 1 | 0 | 0 |  |
| 20 | random | 1209 | 50 | PASS | 4/4 | 2 | 0 | 8 |  |
