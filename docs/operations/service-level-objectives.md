# Service-Level Objectives

These are ProcureSignal's initial operating contracts. They are targets to validate with
production traffic, not claims about historical performance. Review them monthly for the
first three production months and quarterly afterward; the service owner approves changes.

## Objectives and measurement

| Service | Objective | Indicator | Alert window |
| --- | --- | --- | --- |
| API availability | At least 99.5% of handled requests do not return 5xx | `procuresignal:api_availability:ratio_5m` | Below target for 10 minutes |
| API latency | p95 below 500 ms | `procuresignal:api_latency_p95_seconds:5m` | Above target for 10 minutes |
| Notification delivery | At least 99% of attempted deliveries succeed | `procuresignal:notification_delivery_success:ratio_30m` | Below target for 15 minutes |

Availability and latency include application routes recorded by the HTTP middleware and
exclude `/metrics`, which is deliberately not counted as user traffic. Client 4xx responses
are not availability failures. Notification success includes only rows for which a transport
was actually called; queued rows that were never attempted are represented by the separate
outbox-backlog gauge and alert. All ratio alerts require positive traffic, so an idle system
does not page or masquerade as measured success.

## Alert response

- `ApiTargetDown` or `WorkerTargetDown`: restore scrape coverage first. Other indicators from
  the missing target are incomplete and must not be interpreted as healthy.
- `ApiAvailabilitySloBurn`: inspect 5xx routes, recent deploys, database health, and dependency
  failures. Roll back a causal deploy or disable a failing optional dependency when safe.
- `ApiLatencySloBurn`: identify slow route templates, database saturation, and external calls.
  Availability being green does not make a sustained latency breach acceptable.
- `NotificationDeliverySloBurn`: inspect transport-specific failures, credentials, provider
  health, and the outbox. Preserve at-least-once delivery and do not mark failed rows delivered.
- `NotificationsNotDraining`: inspect the scheduled delivery worker and queue age even when the
  delivery-success ratio is healthy; no attempts means the ratio alone has no evidence.

Record the incident start, alert, diagnosis, mitigation, and recovery time. A threshold may
change only after at least four weeks of representative traffic, a documented business-impact
review, and evidence that the current threshold is either unattainable for valid reasons or
too weak to protect users. Never relax an objective solely to silence a noisy alert; fix the
measurement or underlying failure first.

Planned maintenance may be excluded only when announced, time-bounded, and recorded. Load-test
traffic may be excluded when it uses an identified environment or route. Third-party failures
remain included when ProcureSignal surfaces them as a 5xx or failed notification because that
is the outcome users receive. Revisit these exclusions when the deployment topology and formal
support commitments are selected.
