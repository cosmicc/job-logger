# Changelog

All recorded changes to Job Logger are documented in this file.

## Unreleased

- Added the initial `AGENTS.md` project instructions for the Dockerized Python
  Job Logger application.
- Documented the security-first architecture, Cloudflare Tunnel deployment
  expectations, PostgreSQL storage requirements, Autotask review workflow,
  speech-to-text provider configurability, time rounding rules, audit logging
  requirements, Python standards, and changelog policy.
- Created the initial FastAPI application, Docker stack, PostgreSQL/Alembic
  schema, mobile capture page, desktop review page, speech-to-text provider
  interface, Autotask provider interface, CSRF-protected local authentication,
  audit logging, and tests.
- Replaced the OpenAI speech-to-text provider with local faster-whisper
  transcription and updated Docker/environment variables for local model
  caching.
