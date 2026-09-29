import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("check", Path(__file__).with_name("check.py"))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class PolicyTest(unittest.TestCase):
    def audit(self, files):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            return check.Audit(root, map(Path, files)).run()

    def test_new_rust_package_fails_closed(self):
        self.assertTrue(self.audit({"new/Cargo.toml": '[package]\nname="new"\nversion="0.1.0"'}))

    def test_rust_disabled(self):
        self.assertFalse(self.audit({"Cargo.toml": '[package]\npublish=false'}))

    def test_public_registry_rejected(self):
        for publish in ('true', '["crates-io"]', '["quay", "crates-io"]'):
            with self.subTest(publish=publish):
                self.assertTrue(self.audit({"Cargo.toml": f'[package]\npublish={publish}'}))

    def test_workspace_inheritance(self):
        self.assertFalse(self.audit({
            "Cargo.toml": '[workspace.package]\npublish=false',
            "member/Cargo.toml": '[package]\npublish.workspace=true',
        }))

    def test_unsafe_workspace_inheritance(self):
        self.assertTrue(self.audit({
            "Cargo.toml": '[workspace.package]\npublish=true',
            "member/Cargo.toml": '[package]\npublish.workspace=true',
        }))

    def test_missing_workspace_fails(self):
        self.assertTrue(self.audit({"Cargo.toml": '[package]\npublish.workspace=true'}))

    def test_explicit_workspace(self):
        self.assertFalse(self.audit({
            "build/Cargo.toml": '[workspace.package]\npublish=false',
            "member/Cargo.toml": '[package]\nworkspace="../build"\npublish.workspace=true',
        }))

    def test_untracked_workspace_rejected(self):
        self.assertTrue(self.audit({
            "Cargo.toml": '[package]\nworkspace=".."\npublish.workspace=true',
        }))

    def test_private_alias_needs_exact_index(self):
        self.assertTrue(self.audit({"Cargo.toml": '[package]\npublish=["quay"]'}))
        self.assertTrue(self.audit({
            "Cargo.toml": '[package]\npublish=["quay"]',
            ".cargo/config.toml": '[registries.quay]\nindex="sparse+https://index.crates.io/"',
        }))

    def test_nested_config_override_rejected(self):
        self.assertTrue(self.audit({
            "sub/.cargo/config": '[registries.quay]\nindex="https://example.org/index"',
        }))

    def test_migration_accepts_each_exact_approved_index_only(self):
        # Synthetic addresses keep private infrastructure out of public tooling.
        indexes = ("sparse+https://legacy.example.invalid/index/", "sparse+https://managed.example.invalid/index/")
        approved = frozenset(hashlib.sha256(value.encode()).hexdigest() for value in indexes)
        with patch.object(check, "CARGO_INDEX_SHA256", approved):
            for index in indexes:
                self.assertFalse(self.audit({
                    "Cargo.toml": '[package]\npublish=["quay"]',
                    ".cargo/config.toml": '[registries.quay]\nindex=' + json.dumps(index),
                }))
                self.assertFalse(check.Audit.valid_index(index + "other"))
                self.assertFalse(check.Audit.valid_index(index.rstrip("/")))
            self.assertFalse(check.Audit.valid_index("sparse+https://index.crates.io/"))
            self.assertFalse(check.Audit.valid_index(None))

    def test_environment_override_rejected(self):
        self.assertTrue(self.audit({
            ".cargo/config.toml": '[env]\nCARGO_REGISTRIES_QUAY_INDEX="https://example.org"',
        }))

    def test_npm_private_required(self):
        for private in (None, False, "true", 1):
            self.assertTrue(self.audit({"package.json": json.dumps({"private": private})}))
        self.assertFalse(self.audit({"package.json": '{"private":true}'}))

    def test_npm_public_script_rejected_even_for_private_package(self):
        self.assertTrue(self.audit({"package.json": json.dumps({
            "private": True, "scripts": {"release": "npm publish --access public"},
        })}))

    def test_python_private_classifier(self):
        self.assertTrue(self.audit({"pyproject.toml": '[project]\nname="private"'}))
        self.assertFalse(self.audit({"pyproject.toml": '[project]\nclassifiers=["Private :: Do Not Upload"]'}))

    def test_dynamic_classifier_rejected(self):
        self.assertTrue(self.audit({"pyproject.toml": '[project]\nclassifiers=["Private :: Do Not Upload"]\ndynamic=["classifiers"]'}))

    def test_poetry_classifier(self):
        self.assertTrue(self.audit({"pyproject.toml": '[tool.poetry]\nname="private"'}))

    def test_setup_metadata_without_executing(self):
        self.assertTrue(self.audit({"setup.py": 'raise RuntimeError("must never execute")\nsetup(name="secret")'}))
        self.assertFalse(self.audit({"setup.py": 'setup(classifiers=["Private :: Do Not Upload"])'}))
        self.assertFalse(self.audit({"setup.py": 'print("an operations script, not a distribution")'}))

    def test_setup_cfg(self):
        self.assertTrue(self.audit({"setup.cfg": '[metadata]\nname=secret'}))
        self.assertFalse(self.audit({"setup.cfg": '[metadata]\nclassifiers=\n Private :: Do Not Upload'}))

    def test_publishing_commands(self):
        for command in (
            "cargo publish", "cargo +stable publish", "npm publish", "pnpm publish",
            "yarn npm publish", "uv publish", "maturin publish", "poetry publish",
            "python -m twine upload dist/*", "docker push org/app",
            "docker buildx build . --push", "npx semantic-release", "lerna publish",
            "cargo \\\n publish", "cargo publish --registry quay",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.audit({"ci/release.sh": command}))

    def test_public_auth_action(self):
        self.assertTrue(self.audit({".github/workflows/release.yaml":
            'steps:\n - uses: rust-lang/crates-io-auth-action@abc'}))

    def test_no_workflow_opt_out(self):
        self.assertTrue(self.audit({".github/workflows/release.yml":
            'if: false\nrun: npm publish'}))

    def test_public_token_env(self):
        self.assertTrue(self.audit({".github/workflows/release.yml":
            'env:\n CARGO_REGISTRY_TOKEN: ${{ secrets.TOKEN }}'}))

    def test_dependency_downloads_allowed(self):
        self.assertFalse(self.audit({"ci/check.sh":
            'cargo fetch\nnpm ci\npython -m pip install build\ncargo package --locked'}))

    def test_malformed_input_fails_closed(self):
        for name in ("Cargo.toml", "pyproject.toml", "package.json", "setup.py"):
            self.assertTrue(self.audit({name: "[invalid"}))

    def test_no_secret_values_in_findings(self):
        failures = self.audit({".github/workflows/release.yml": 'CARGO_REGISTRY_TOKEN: confidential'})
        self.assertTrue(failures)
        self.assertNotIn("confidential", str(failures))

    def test_symlink_cannot_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Cargo.toml").symlink_to("/etc/passwd")
            self.assertTrue(check.Audit(root, [Path("Cargo.toml")]).run())

    def test_internal_symlink_is_inspected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "run.sh").write_text("npm publish")
            (root / "release.sh").symlink_to("run.sh")
            errors = check.Audit(root, [Path("run.sh"), Path("release.sh")]).run()
            self.assertEqual(len(errors), 2)
            (root / "run.sh").write_text("cargo test")
            self.assertFalse(check.Audit(root, [Path("run.sh"), Path("release.sh")]).run())
            self.assertTrue(check.Audit(root, [Path("release.sh")]).run())

    def test_unimplemented_ecosystem_fails_closed(self):
        for manifest in ("pom.xml", "new.gemspec", "sub/go.mod"):
            self.assertTrue(self.audit({manifest: ""}))


if __name__ == "__main__":
    unittest.main()
