# Security policy

## Reporting a vulnerability

**Use GitHub's private vulnerability reporting**, from the *Security* tab of this
repository, or directly at
[Report a vulnerability](https://github.com/catincloud-labs/dagster-dex/security/advisories/new).

That opens a private advisory only the maintainer can see. Please do not open a
public issue for a security problem - an issue is world-readable the moment it is
filed, and it cannot be made private afterwards.

There is deliberately **no email address here.** A published address is permanent
and gets harvested; private reporting gives the same channel without one.

## What to expect

This is a side project maintained by one person. I aim to acknowledge a report
within **a week**, and I would rather say that plainly than publish a response
time I cannot hold to. If a report is valid I will work with you on a fix and
credit you in the advisory unless you would prefer otherwise.

## Supported versions

| Version | Supported |
| --- | --- |
| `0.1.x` | Yes |

The package is alpha and the contract may move before 1.0. There is no long-term
support branch, and there will not be one until the seam settles.

## The surface, stated honestly

This is a small library with a deliberately narrow footprint, and the most useful
thing this file can do is tell you where to look rather than assert that it is
safe.

- **It parses YAML you supply** - declaration, semantic and source documents -
  using `yaml.safe_load`. That is the whole untrusted-input surface. Documents
  come from paths named in `.dex/config.yml`, and it also reads a JSON artefact
  written by `dagster_dex.artifact.dumps`.
- **It imports a module you name.** The `assets:` option is a dotted
  `module:attribute` path and resolving it imports that module. That is ordinary
  plugin behaviour and it is worth knowing: whoever controls `.dex/config.yml`
  controls an import.
- **It makes no network calls, spawns no subprocesses, and writes no files.**
- **It handles no credentials.** `ProjectContext.options` is read from committed
  configuration, so a secret placed there would be a secret in version control;
  the code refuses to treat it as a credential store rather than accommodating one.

If you find any of the above to be untrue, that is itself worth reporting.
