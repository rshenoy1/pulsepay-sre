# PulsePay — Site Reliability Engineering (SRE) Reference Project

Demonstrates core **SRE Observability, SLOs, and Resilience** patterns:
- **Four Golden Signals (`/metrics`):** Prometheus instrumentation exposing latency histograms, traffic rates, and error counters.
- **Load Shedding (`HTTP 429`):** Sliding-window rate limiter protecting downstream PostgreSQL from traffic spikes while exempting `/health` and `/metrics`.
- **SLO Alerting (`monitoring/` & `terraform/sre_monitoring.tf`):** Prometheus alert rules and AWS CloudWatch p95 latency / 5xx error-budget alarms wired to SNS on-call notifications + ECS Auto Scaling.
