# Private package publication policy

Quay repositories must not publish packages to public registries. This is
generic CI tooling; it contains no product code, credentials, or private
network addresses. It is hosted in the organization's public `.github`
repository so GitHub can require the same workflow in public and private
repositories.

The checker uses Python 3.11+ and the standard library. It reads tracked
manifests and release configuration without installing dependencies or
executing the inspected repository's code. Run locally with:

```sh
python3 -I policy/test_check.py
python3 -I policy/check.py /path/to/repository
```

Rules:

- Rust packages must explicitly disable publishing, or allow only the `quay`
  registry with its centrally approved index. Workspace inheritance and nested
  Cargo configurations are checked. Downloads from public registries remain
  permitted.
- Every npm package must set `private: true`.
- Python distributions must declare `Private :: Do Not Upload` statically.
  PyPI rejects this classifier; it does not restrict private package installs.
- Ordinary workflows, shell scripts and npm scripts may not upload packages,
  request public Cargo tokens, or override the private registry. Releases use
  separately reviewed private infrastructure.
- New recognized package ecosystems fail until the central policy supports
  them. Malformed files and symlinks outside the tracked repository fail closed.

Repository callers pin the shared workflow to a full commit SHA. The
organization ruleset must independently select the trusted workflow and target
all repositories' default branches, with no bypass actors. A local workflow
or template alone is not mandatory enforcement and does not cover new repos.
Ruleset installation and the rollout inventory are maintained privately in
`quay-infra`.

This prevents common accidental publication paths. Static checks cannot prove
that arbitrary programs never upload data. They do not revoke developers'
credentials, block network traffic, inspect external submodules, prevent a
privileged owner from changing the organization rules, or stop an untrusted
branch's other workflows from running before merge. Keep public registry
credentials and trusted-publisher grants out of release infrastructure; restrict
release credentials and network access to the approved private registry.
