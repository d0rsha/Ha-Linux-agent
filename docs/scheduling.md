# Scheduled reports

v0.4 deliberately keeps scheduling outside the Python process. Use systemd or cron to invoke the deterministic `ha-agent report` command.

## Home Assistant notification delivery

Set a Home Assistant notify service in `.env`:

```env
REPORT_NOTIFY_SERVICE=ALL_DEVICES
```

The value is the service name below `notify`, with or without the `notify.` prefix. Leave it blank to print the report to stdout only.

The report prompt lives in `prompts/house_health.md` and can be replaced with `REPORT_PROMPT_PATH`.

## Manual checks

```bash
docker compose run --rm -T ha-agent report
```

Anomaly-only mode suppresses notification delivery when the agent returns exactly `NO_ALERT`:

```bash
docker compose run --rm -T ha-agent report --anomalies-only
```

The command exits non-zero on model/tool/delivery failures. Exit 75 means another report process already holds the report lock.

## systemd example

Create `/etc/systemd/system/ha-linux-agent-report.service`:

```ini
[Unit]
Description=HA Linux Agent morning report
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
WorkingDirectory=/opt/Ha-Linux-agent
ExecStart=/usr/bin/docker compose run --rm -T ha-agent report
TimeoutStartSec=5min
```

Create `/etc/systemd/system/ha-linux-agent-report.timer`:

```ini
[Unit]
Description=Run HA Linux Agent morning report

[Timer]
OnCalendar=*-*-* 07:30:00
Persistent=true
RandomizedDelaySec=60

[Install]
WantedBy=timers.target
```

Then enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ha-linux-agent-report.timer
systemctl list-timers ha-linux-agent-report.timer
```

Adjust `WorkingDirectory` and `OnCalendar` for the host. systemd owns the schedule; the agent only performs one bounded report run.

## Anomaly timer

A second timer can invoke `report --anomalies-only` at a desired cadence. Avoid frequent schedules until the anomaly prompt and entity coverage have been tested to prevent notification noise.
