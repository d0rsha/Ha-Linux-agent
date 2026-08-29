Produce a concise morning house-health report using Home Assistant live state and historical tools where data is available.

Check these areas without inventing missing data:
- unusual water consumption or leaks
- RPi3/server availability and recent interruptions
- important low batteries
- indoor versus outdoor temperature and unusual temperature trends
- recent electricity consumption/current load
- Nordpool/current electricity price situation and useful cheap-hour information

Prioritize actionable anomalies. Include measurements and timestamps where useful. Explicitly say when a requested historical signal is unavailable instead of treating missing data as normal. Do not perform write actions as part of this report.
