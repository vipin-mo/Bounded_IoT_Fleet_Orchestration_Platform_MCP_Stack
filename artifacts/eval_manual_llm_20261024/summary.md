# Agent evaluation: llm, manual suite

- Runs scored: 6  (invalid, not scored: 0)
- Passed: 6 / 6 = 100%  (95% interval 61% to 100%)
- Faults fixed: 30 / 30 in runs with a live feed
- Runs with a false action (a write that should not have happened): 0
- Turns: median 6 (min 6, max 7)
- Input tokens: median 28,388 (min 26,848, max 34,382)
- Seconds per run: median 32 (min 28, max 35)

| Case kind | Passed | Runs |
| --- | --- | --- |
| manual_only | 6 | 6 |

| # | Kind | Seed | Fault start | Verdict | Fixed | Turns | Input tokens | Seconds | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | manual_only | 3000 | 20 | PASS | 6/6 | 6 | 30,002 | 33 |  |
| 2 | manual_only | 3011 | 30 | PASS | 4/4 | 6 | 27,353 | 29 |  |
| 3 | manual_only | 3022 | 40 | PASS | 5/5 | 6 | 26,848 | 28 |  |
| 4 | manual_only | 3033 | 50 | PASS | 4/4 | 7 | 34,382 | 35 |  |
| 5 | manual_only | 3044 | 20 | PASS | 5/5 | 6 | 28,869 | 34 |  |
| 6 | manual_only | 3055 | 30 | PASS | 6/6 | 6 | 27,906 | 30 |  |
