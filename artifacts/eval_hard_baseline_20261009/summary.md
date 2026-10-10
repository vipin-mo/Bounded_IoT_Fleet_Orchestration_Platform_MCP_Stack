# Agent evaluation: baseline, hard suite

- Runs scored: 12  (invalid, not scored: 0)
- Passed: 12 / 12 = 100%  (95% interval 76% to 100%)
- Faults fixed: 45 / 45 in runs with a live feed
- Runs with a false action (a write that should not have happened): 0
- Turns: median 2 (min 2, max 2)
- Input tokens: median 0 (min 0, max 0)
- Seconds per run: median 8 (min 8, max 8)

| Case kind | Passed | Runs |
| --- | --- | --- |
| dual | 4 | 4 |
| silent_fault | 4 | 4 |
| slow_ramp | 4 | 4 |

| # | Kind | Seed | Fault start | Verdict | Fixed | Turns | Input tokens | Seconds | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | dual | 2000 | 20 | PASS | 5/5 | 2 | 0 | 8 |  |
| 2 | silent_fault | 2011 | 30 | PASS | 6/6 | 2 | 0 | 8 |  |
| 3 | slow_ramp | 2022 | 40 | PASS | 2/2 | 2 | 0 | 8 |  |
| 4 | dual | 2033 | 50 | PASS | 6/6 | 2 | 0 | 8 |  |
| 5 | silent_fault | 2044 | 20 | PASS | 5/5 | 2 | 0 | 8 |  |
| 6 | slow_ramp | 2055 | 30 | PASS | 3/3 | 2 | 0 | 8 |  |
| 7 | dual | 2066 | 40 | PASS | 4/4 | 2 | 0 | 8 |  |
| 8 | silent_fault | 2077 | 50 | PASS | 5/5 | 2 | 0 | 8 |  |
| 9 | slow_ramp | 2088 | 20 | PASS | 1/1 | 2 | 0 | 8 |  |
| 10 | dual | 2099 | 30 | PASS | 5/5 | 2 | 0 | 8 |  |
| 11 | silent_fault | 2110 | 40 | PASS | 1/1 | 2 | 0 | 8 |  |
| 12 | slow_ramp | 2121 | 50 | PASS | 2/2 | 2 | 0 | 8 |  |
