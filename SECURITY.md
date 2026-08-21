# Security Policy

## Supported scope

This repository is an alpha, local-development Cloud Agent Platform MVP. It is not a
production boundary for arbitrary hostile code. The `local` sandbox is only for trusted
development input. For untrusted repositories, use the Docker backend on a dedicated host
and validate the isolation controls in your own environment.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability or include credentials, private
repositories, exploit payloads, or customer data in an issue.

Until a dedicated security contact is published, create a private GitHub Security Advisory
for the repository owner. Include the affected version, impact, minimal reproduction,
prerequisites, and a proposed mitigation when available.

## Secret handling

- Never commit `.env`, API keys, access tokens, private repository credentials, logs, runs,
  artifacts, or local databases.
- Rotate a secret immediately if it is exposed, even when the commit is later removed.
- OpenAI credentials must stay in server-side environment configuration and must not enter
  model prompts, tool output, events, logs, or artifacts.

## Security boundary

The detailed threat model and MVP limitations are documented in
[`docs/security-boundary.md`](docs/security-boundary.md). Production deployment additionally
requires persistent identity and authorization, rate and cost limits, stronger sandboxing,
dependency and image scanning, audit retention, incident response, and disaster recovery.
