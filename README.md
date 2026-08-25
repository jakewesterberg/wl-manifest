# wl-manifest

The `wl.yaml` contract for Westerberg Lab packages: the manifest schema and the
host-selector grammar (`dws`, `rig/sglx`, and the rest), plus a check that runs
against one repository's own `wl.yaml` and nothing else.

This package holds no lab data. It knows nothing about which packages exist,
what depends on what, or which machines are real — that is `wl-orchestrator`'s
registry, a separate repository. `wl_manifest` never imports it; the
dependency runs the other way, the same one-way rule `wl-preproc` holds
against `wl-sync`. A repository depends on `wl-manifest` for the schema
without ever pulling in the registry that changes underneath it.

## Install

```
pip install wl-manifest
```

## Check a manifest

```
$ wl-check .
wl.yaml: no findings
```

Run it from a repository's own root, or point it at a directory or a file
directly: `wl-check ../wl-preproc`, `wl-check some/other/wl.yaml`. Findings
print one per line — a level, a code (`C001`–`C007`), a message — and the
command never raises: a malformed manifest is a finding, not a traceback.
Exit 0 means no `error`-level finding; a lone `note` still exits 0.

## What's here

`wl_manifest.models` — `PackageManifest`, `ThirdPartyDep`, `Status`, and the
schema's `Literal` aliases. `wl_manifest.hosts` — `HostSelector`, the `class`
or `class/role` grammar host identity is written in. `wl_manifest.check` — the
rules themselves, and `CheckFinding`. None of it reads a registry, because
there isn't one here to read.
