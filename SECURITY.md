# Security Policy

## Supported versions

Security fixes are released for the latest minor version. Upgrade to the newest patch release
of a supported line to receive fixes.

| Version | Supported |
| ------- | --------- |
| 1.0.x   | Yes       |
| < 1.0   | No        |

## Reporting a vulnerability

**Do not open a public issue, pull request or discussion for a security problem.**

Report it privately through GitHub's
[private vulnerability reporting](https://github.com/imranmali/prompt-versioning/security/advisories/new)
(repository **Security** tab, **Report a vulnerability**). Please include:

- the affected version or image digest and deployment type;
- a description of the issue and its impact;
- steps or a proof of concept to reproduce it;
- any suggested fix or mitigation.

What to expect:

- acknowledgement within 3 business days;
- an initial assessment and severity within 7 business days;
- a fix, a GitHub Security Advisory (with a CVE where appropriate) and a patch release, with
  credit to the reporter unless you prefer to remain anonymous.

Please give us a reasonable time to release a fix before any public disclosure.

## Handling API keys and secrets

- **API keys are shown once.** PromptLab stores only a hash of each key; a lost key cannot be
  recovered, only revoked and re-issued (`DELETE /v1/api-keys/{id}`, then `POST /v1/api-keys`).
- **Least privilege.** Give applications `runtime` keys (resolve, render, events). Reserve
  `editor` for prompt authors and `admin` for operators.
- **Bootstrap admin key.** `PROMPTLAB_BOOTSTRAP_ADMIN_KEY` is a break-glass credential. Use it
  to create a named admin key, then remove it from the environment/Secret and restart. Generate
  it with at least 32 random bytes (for example `openssl rand -hex 32`).
- **Never commit secrets.** `.env` files are git-ignored; in Kubernetes keep
  `PROMPTLAB_DATABASE_URL` and the bootstrap key in the `promptlab-secrets` Secret (ideally
  managed by External Secrets, Sealed Secrets or SOPS), never in the ConfigMap or manifests.
- **Transport.** Terminate TLS in front of the service (ingress or load balancer); API keys
  travel in request headers.
- **Rotation.** Rotate keys by issuing a new key, rolling it out to clients, then revoking the
  old one. Rotate immediately if a key appears in logs, tickets or source control.

## Supply chain

- Dependencies are locked in `uv.lock`; Dependabot proposes weekly updates.
- The `Security` workflow audits locked runtime dependencies with `pip-audit` on every pull
  request, on `main` and weekly.
- Release images are built in GitHub Actions, run as a non-root user and are published to
  GitHub Container Registry with SBOM and provenance attestations.
