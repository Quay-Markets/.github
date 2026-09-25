#!/usr/bin/env python3
"""Read-only, dependency-free checks against accidental public package releases.

Run with Python 3.11+ in isolated mode. Never imports or executes inspected code.
The organization ruleset must select this checker from a trusted, pinned commit.
"""

import argparse
import ast
import configparser
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib


PRIVATE_CLASSIFIER = "Private :: Do Not Upload"
# Exact approved indexes, represented as digests so public CI tooling need not
# disclose private network topology. Keep the legacy index during the managed
# registry migration; changing this set requires central policy review.
CARGO_INDEX_SHA256 = frozenset({
    "dd2db90a42d697b93486f48b1f471b857195b6f152a8a73961687de54d644e6d",  # legacy
    "f827a28855ee0dcd1eb26f80249fe7600f9fba98e6e8285f432b6626a53566cb",  # managed
})
MANIFESTS = {"Cargo.toml", "package.json", "pyproject.toml", "setup.py", "setup.cfg"}
UNSUPPORTED = {"pom.xml", "build.gradle", "build.gradle.kts", "composer.json",
               "go.mod", "mix.exs", "pubspec.yaml", "Package.swift"}
PUBLISH = re.compile(
    r"\b(?:cargo(?:\s+\+[^\s]+)?\s+publish|"
    r"(?:npm|pnpm|yarn)\s+(?:npm\s+)?publish|"
    r"(?:maturin|poetry|uv)\s+publish|twine\s+upload|"
    r"(?:docker|podman)\s+push|docker\s+buildx\s+build[^\n]*--push|"
    r"(?:npx\s+)?semantic-release|lerna\s+publish)\b", re.I
)
PUBLISH_ACTIONS = re.compile(
    r"\buses:\s*['\"]?(?:rust-lang/crates-io-auth-action|"
    r"pypa/gh-action-pypi-publish|js-devtools/npm-publish|"
    r"pascalgn/npm-publish-action|svenstaro/upload-release-action)@", re.I
)
OVERRIDE = re.compile(
    r"\b(?:CARGO_REGISTRY_TOKEN|CARGO_REGISTRIES_CRATES_IO_TOKEN|"
    r"CARGO_REGISTRIES_QUAY_INDEX|CARGO_REGISTRY_DEFAULT)\s*[:=]"
)


def tracked_paths(root):
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return [Path(p.decode("utf-8")) for p in result.stdout.split(b"\0") if p]


def is_script(path):
    return (path.suffix in {".sh", ".bash", ".ps1"}
            or path.name in {"Makefile", "justfile", "Justfile"}
            or (".github" in path.parts and path.suffix in {".yml", ".yaml"})
            or path.name.startswith((".releaserc", "release.config")))


class Audit:
    def __init__(self, root, paths):
        self.root = Path(root).resolve()
        self.paths = set(paths)
        self.errors = []
        self.cache = {}

    def fail(self, path, message):
        # Do not echo source text: a misconfigured file could contain credentials.
        self.errors.append(f"{path}: {message}")

    def read(self, path):
        full = self.root / path
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("unsafe path")
        resolved = full.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError("policy-relevant symlink escapes the repository")
        if resolved != full and resolved.relative_to(self.root) not in self.paths:
            raise ValueError("policy-relevant symlink targets an untracked file")
        if full.stat().st_size > 2_000_000:
            raise ValueError("policy-relevant file exceeds 2 MB")
        return full.read_text(encoding="utf-8")

    def toml(self, path):
        if path not in self.cache:
            self.cache[path] = tomllib.loads(self.read(path))
        return self.cache[path]

    def workspace_publish(self, path, package):
        explicit = package.get("workspace")
        if explicit is not None:
            workspace = (self.root / path.parent / explicit / "Cargo.toml").resolve()
            if not workspace.is_relative_to(self.root):
                raise ValueError("publish inherits a workspace outside the repository")
            candidates = [workspace.relative_to(self.root)]
        else:
            candidates = [p / "Cargo.toml" for p in path.parents]
        for candidate in candidates:
            if candidate in self.paths:
                data = self.toml(candidate)
                if "workspace" in data:
                    return data["workspace"].get("package", {}).get("publish")
        return None

    def cargo(self, path):
        data = self.toml(path)
        packages = [data["package"]] if "package" in data else []
        # Workspace defaults must also be safe for future members.
        if "publish" in data.get("workspace", {}).get("package", {}):
            packages.append(data["workspace"]["package"])
        for package in packages:
            publish = package.get("publish")
            if publish == {"workspace": True}:
                publish = self.workspace_publish(path, package)
            if publish is False or publish == []:
                continue
            if publish != ["quay"]:
                self.fail(path, 'set publish = false or publish = ["quay"]')
                continue
            # Require the approved definition in the repository root as well as
            # checking every nested config; developer home config is not trusted.
            config = Path(".cargo/config.toml")
            if config not in self.paths:
                self.fail(path, "private release requires the root Cargo registry configuration")
            elif not self.valid_index(self.toml(config).get("registries", {}).get("quay", {}).get("index")):
                self.fail(path, "private registry index does not match organization policy")

    @staticmethod
    def valid_index(value):
        return isinstance(value, str) and hashlib.sha256(value.encode()).hexdigest() in CARGO_INDEX_SHA256

    def cargo_config(self, path):
        data = self.toml(path)
        default = data.get("registry", {}).get("default")
        if default is not None and default != "quay":
            self.fail(path, "Cargo default registry must be quay")
        quay = data.get("registries", {}).get("quay", {})
        if "index" in quay and not self.valid_index(quay["index"]):
            self.fail(path, "Cargo quay index override is not approved")
        # Reject environment/alias indirection around the manifest restriction.
        for key in data.get("env", {}):
            if key.startswith(("CARGO_REGISTRY", "CARGO_REGISTRIES")):
                self.fail(path, "registry environment overrides are prohibited in tracked Cargo config")
        for value in data.get("alias", {}).values():
            self.commands(path, value if isinstance(value, str) else " ".join(value))

    def npm(self, path):
        data = json.loads(self.read(path))
        if data.get("private") is not True:
            self.fail(path, 'set "private": true; npm releases are disabled')
        if data.get("publishConfig", {}).get("access") == "public":
            self.fail(path, "public npm access is prohibited")
        for value in data.get("scripts", {}).values():
            self.commands(path, value)

    def python_project(self, path):
        data = self.toml(path)
        for project in (data.get("project"), data.get("tool", {}).get("poetry")):
            if project is None:
                continue
            if PRIVATE_CLASSIFIER not in project.get("classifiers", []):
                self.fail(path, "Python distributions must carry the private classifier")
            if "classifiers" in project.get("dynamic", []):
                self.fail(path, "private classifiers must be static")

    def setup_py(self, path):
        tree = ast.parse(self.read(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", getattr(node.func, "attr", None))
            if name != "setup":
                continue
            values = [k.value for k in node.keywords if k.arg == "classifiers"]
            if values:
                try:
                    valid = PRIVATE_CLASSIFIER in ast.literal_eval(values[0])
                except (ValueError, TypeError):
                    valid = False
            else:
                adjacent = path.parent / "pyproject.toml"
                valid = adjacent in self.paths and PRIVATE_CLASSIFIER in self.toml(adjacent).get("project", {}).get("classifiers", [])
            if not valid:
                self.fail(path, "setup() requires a statically declared private classifier")

    def commands(self, path, source):
        source = re.sub(r"\\\r?\n", " ", source)
        for line in source.splitlines():
            if line.lstrip().startswith("#"):
                continue
            if PUBLISH_ACTIONS.search(line):
                self.fail(path, "public package publishing action is prohibited")
            if OVERRIDE.search(line):
                self.fail(path, "public credentials or Cargo registry overrides are prohibited")
            if re.search(r"\bpush:\s*(?:true|\$\{\{)", line, re.I):
                self.fail(path, "container registry push requires a separately reviewed private publisher")
            if PUBLISH.search(line):
                # Private publishing is performed by reviewed infrastructure,
                # not by ordinary repository CI/shell scripts.
                self.fail(path, "package upload command prohibited; use the reviewed private publisher")

    def run(self):
        for path in sorted(self.paths):
            if path.name in UNSUPPORTED or path.suffix in {".gemspec", ".nuspec", ".csproj"}:
                self.fail(path, "new package ecosystem requires central private-publishing support")
                continue
            cargo_config = ".cargo" in path.parts and path.name in {"config", "config.toml"}
            if path.name not in MANIFESTS and not cargo_config and not is_script(path):
                continue
            try:
                if path.name == "Cargo.toml": self.cargo(path)
                elif path.name == "package.json": self.npm(path)
                elif path.name == "pyproject.toml": self.python_project(path)
                elif path.name == "setup.py": self.setup_py(path)
                elif path.name == "setup.cfg":
                    data = configparser.ConfigParser(interpolation=None)
                    data.read_string(self.read(path))
                    if data.has_section("metadata") and PRIVATE_CLASSIFIER not in data.get("metadata", "classifiers", fallback=""):
                        self.fail(path, "Python distributions must carry the private classifier")
                elif cargo_config: self.cargo_config(path)
                if is_script(path): self.commands(path, self.read(path))
            except (ValueError, OSError, SyntaxError, TypeError, KeyError, AttributeError, configparser.Error):
                self.fail(path, "cannot safely parse policy-relevant file")
        return sorted(set(self.errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path)
    args = parser.parse_args()
    try:
        failures = Audit(args.repository, tracked_paths(args.repository)).run()
    except (OSError, ValueError, subprocess.CalledProcessError):
        print("Cannot enumerate repository; refusing to pass", file=sys.stderr)
        return 1
    for failure in failures:
        print(failure)
    print(f"Private publishing policy: {'FAIL' if failures else 'PASS'} ({len(failures)} violations)")
    return bool(failures)


if __name__ == "__main__":
    sys.exit(main())
