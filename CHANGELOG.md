# Changelog

All notable changes will be documented in this file. The project follows semantic versioning
once a stable public API is declared.

## [Unreleased]

### Added

- Project-root `.env` loading and safe configuration preflight.
- Cross-platform local startup scripts and a root navigation page.
- Readiness diagnostics that do not expose API keys.
- GitHub quality, security, contribution, and community files.

### Changed

- Docker and Compose configuration now match the in-memory local MVP.
- Repository, artifact, and run paths resolve relative to the project root.
- OpenAI base URLs must use HTTPS and cannot embed credentials.

## [0.1.0] - 2026-08-22

- Initial runnable Cloud Agent Platform MVP.
