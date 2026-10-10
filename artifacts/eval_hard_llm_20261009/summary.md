# Agent evaluation: llm, hard suite

- Runs scored: 12  (invalid, not scored: 0)
- Passed: 12 / 12 = 100%  (95% interval 76% to 100%)
- Faults fixed: 45 / 45 in runs with a live feed
- Runs with a false action (a write that should not have happened): 0
- Turns: median 8 (min 6, max 9)
- Input tokens: median 25,459 (min 18,796, max 39,346)
- Seconds per run: median 30 (min 25, max 42)

| Case kind | Passed | Runs |
| --- | --- | --- |
| dual | 4 | 4 |
| silent_fault | 4 | 4 |
| slow_ramp | 4 | 4 |

| # | Kind | Seed | Fault start | Verdict | Fixed | Turns | Input tokens | Seconds | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | dual | 2000 | 20 | PASS | 5/5 | 8 | 35,083 | 34 |  |
| 2 | silent_fault | 2011 | 30 | PASS | 6/6 | 6 | 24,255 | 32 |  |
| 3 | slow_ramp | 2022 | 40 | PASS | 2/2 | 6 | 18,796 | 27 |  |
| 4 | dual | 2033 | 50 | PASS | 6/6 | 8 | 34,517 | 34 |  |
| 5 | silent_fault | 2044 | 20 | PASS | 5/5 | 6 | 25,068 | 33 |  |
| 6 | slow_ramp | 2055 | 30 | PASS | 3/3 | 8 | 28,277 | 30 |  |
| 7 | dual | 2066 | 40 | PASS | 4/4 | 8 | 31,652 | 30 |  |
| 8 | silent_fault | 2077 | 50 | PASS | 5/5 | 6 | 22,839 | 29 |  |
| 9 | slow_ramp | 2088 | 20 | PASS | 1/1 | 8 | 25,850 | 25 |  |
| 10 | dual | 2099 | 30 | PASS | 5/5 | 9 | 39,346 | 42 |  |
| 11 | silent_fault | 2110 | 40 | PASS | 1/1 | 7 | 21,323 | 28 |  |
| 12 | slow_ramp | 2121 | 50 | PASS | 2/2 | 7 | 21,678 | 25 |  |
