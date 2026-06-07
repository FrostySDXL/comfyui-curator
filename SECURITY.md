# Security Policy

## Supported Versions

This is a single-user, operator-maintained curation tool.
Only the latest commit on the default branch is actively maintained.

## Reporting a Vulnerability

This project is operator-maintained and not a public-facing service.
If you discover a security concern:

1. Do not open a public issue.
2. Describe the concern with steps to reproduce.
3. Include the affected version or commit hash.

Security findings should be reported directly to the repository maintainer
via private communication channels.

## Scope

Issues considered in scope:

- Path traversal that allows reading/writing outside configured directories
- Unsanitized user input rendered in the web UI (XSS)
- Credential or secret exposure through error messages or API responses
- Remote code execution vectors

Issues considered out of scope:

- Denial of service from untrusted local processes
- Local privilege escalation (the service runs as the operator)
- Physical access threats
- Social engineering

## Dependencies

Dependencies are pinned in `requirements-lock.txt` and
`requirements-dev-lock.txt`. Review `requirements.in` and
`requirements-dev.in` for the direct dependency list.
