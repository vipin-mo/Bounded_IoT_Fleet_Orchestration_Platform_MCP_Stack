# FLEET MANAGEMENT EXTRAORDINARY FAULT CODES MANUAL

## Error Code: ERR_BATT_THERMAL_RUNAWAY
- **Trigger Metrics:** Moving window Z-score calculations above 2.5 on core vehicle battery temperature channels.
- **Root Cause:** Cellular degradation of internal cooling gel layers or localized cooling fan micro-failures.
- **Mitigation Directive:** The AI Orchestrator must deploy an Over-The-Air command setting the vehicle power mode parameter to 'eco_mode' to throttle core current draws and decrease thermodynamic dissipation rates.

## Error Code: ERR_CABIN_OVERHEATING_CRITICAL
- **Trigger Metrics:** Live cabin status register reporting 'overheating_critical' accompanied by sustained speed spikes.
- **Root Cause:** Climate control compressor power inverter component short circuit.
- **Mitigation Directive:** Isolate live tracking metrics, query tracking moving histories, and apply an active speed governor to mitigate cabin internal thermal pressure.
