from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


NODE_LOCKFILES = ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb")
PYTHON_LOCKFILES = ("poetry.lock", "Pipfile.lock", "uv.lock", "requirements.lock")
LIFECYCLE_SCRIPTS = {"preinstall", "install", "postinstall", "prepare"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--kind", choices=["node", "python", "ci"], required=True)
    args = parser.parse_args()

    project = Path(args.project)
    if not project.exists():
        print(f"not found: {project}", file=sys.stderr)
        return 1

    if args.kind == "node":
        findings = check_node_project(project)
    elif args.kind == "python":
        findings = check_python_project(project)
    else:
        findings = check_ci_project(project)

    for bug_class, detail in findings:
        print(f"{bug_class}: {detail}")
    return 1 if findings else 0


def check_node_project(project: Path) -> list[tuple[str, str]]:
    manifest_path = project / "package.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [("missing_lockfile", f"not found: {manifest_path}")]
    except json.JSONDecodeError as exc:
        return [("deprecated_script", f"schema mismatch: malformed package.json line {exc.lineno}")]

    findings: list[tuple[str, str]] = []
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        dependencies = manifest.get(section, {})
        if isinstance(dependencies, dict):
            for name, spec in dependencies.items():
                if is_unpinned_node_spec(str(spec)):
                    findings.append(("unpinned_dependency", f"{section}.{name} uses floating range {spec}"))

    if has_dependency_section(manifest) and not any((project / name).exists() for name in NODE_LOCKFILES):
        findings.append(("missing_lockfile", f"no Node lockfile found beside {manifest_path.name}"))

    engine = str(manifest.get("engines", {}).get("node", "")) if isinstance(manifest.get("engines"), dict) else ""
    nvmrc = read_optional(project / ".nvmrc").strip()
    engine_major = first_major_version(engine)
    nvm_major = first_major_version(nvmrc)
    if engine_major and nvm_major and engine_major != nvm_major:
        findings.append(("engine_mismatch", f"package.json requires Node {engine}; .nvmrc pins {nvmrc}"))

    scripts = manifest.get("scripts", {})
    if isinstance(scripts, dict):
        if "prepublish" in scripts:
            findings.append(("deprecated_script", "prepublish runs on install-era npm workflows; use prepare/prepublishOnly"))
        for name, body in scripts.items():
            if name in LIFECYCLE_SCRIPTS and is_insecure_lifecycle_body(str(body)):
                findings.append(("insecure_lifecycle_script", f"{name} executes remote or shell-expanded code"))

    return findings


def check_python_project(project: Path) -> list[tuple[str, str]]:
    pyproject = project / "pyproject.toml"
    try:
        text = pyproject.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [("missing_lockfile", f"not found: {pyproject}")]

    findings: list[tuple[str, str]] = []
    requires_python = find_toml_string(text, "requires-python")
    minimum = first_major_minor(requires_python)
    if minimum and minimum < (3, 9):
        findings.append(("stale_python_requires", f"requires-python {requires_python} allows unsupported runtimes"))

    for dependency in find_toml_array_strings(text, "dependencies"):
        if is_unpinned_python_spec(dependency):
            findings.append(("unpinned_dependency", f"project dependency is not pinned: {dependency}"))

    if "dependencies" in text and not any((project / name).exists() for name in PYTHON_LOCKFILES):
        findings.append(("missing_lockfile", f"no Python lockfile found beside {pyproject.name}"))

    return findings


def check_ci_project(project: Path) -> list[tuple[str, str]]:
    workflows = sorted((project / ".github" / "workflows").glob("*.yml"))
    workflows.extend(sorted((project / ".github" / "workflows").glob("*.yaml")))
    if not workflows:
        return [("missing_lockfile", f"not found: {project / '.github' / 'workflows'}")]

    findings: list[tuple[str, str]] = []
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        for action, ref in re.findall(r"uses:\s*([A-Za-z0-9_.\-/]+)@([^\s#]+)", text):
            if ref in {"main", "master"} or not re.fullmatch(r"v?\d+(?:\.\d+){1,2}", ref):
                findings.append(("unpinned_dependency", f"{workflow.name} uses {action}@{ref}"))
        if re.search(r"\bnpm install\b", text):
            findings.append(("deprecated_script", f"{workflow.name} uses npm install in CI instead of npm ci"))
        if re.search(r"node-version:\s*['\"]?20", text) and (project / ".nvmrc").exists():
            nvm_major = first_major_version(read_optional(project / ".nvmrc"))
            if nvm_major and nvm_major != 20:
                findings.append(("engine_mismatch", f"{workflow.name} uses Node 20 while .nvmrc pins {nvm_major}"))
    return findings


def has_dependency_section(manifest: dict[str, Any]) -> bool:
    return any(isinstance(manifest.get(section), dict) and manifest[section] for section in ("dependencies", "devDependencies", "optionalDependencies"))


def is_unpinned_node_spec(spec: str) -> bool:
    value = spec.strip().lower()
    return (
        value in {"*", "latest", "next"}
        or value.startswith(("^", "~", ">", ">=", "<", "<="))
        or "x" in value
        or value.endswith(".*")
    )


def is_unpinned_python_spec(spec: str) -> bool:
    return "==" not in spec or any(token in spec for token in (">=", "<=", "~=", "*"))


def is_insecure_lifecycle_body(body: str) -> bool:
    lowered = body.lower()
    remote_fetch = "curl " in lowered or "wget " in lowered or "invoke-webrequest" in lowered
    shell_pipe = "| sh" in lowered or "| bash" in lowered or "bash -c" in lowered or "sh -c" in lowered
    return remote_fetch or shell_pipe


def first_major_version(value: str) -> int | None:
    match = re.search(r"(\d+)", value)
    return int(match.group(1)) if match else None


def first_major_minor(value: str) -> tuple[int, int] | None:
    match = re.search(r"(\d+)(?:\.(\d+))?", value)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2) or 0)


def find_toml_string(text: str, key: str) -> str:
    match = re.search(rf"^\s*{re.escape(key)}\s*=\s*['\"]([^'\"]+)['\"]", text, flags=re.MULTILINE)
    return match.group(1) if match else ""


def find_toml_array_strings(text: str, key: str) -> list[str]:
    match = re.search(rf"^\s*{re.escape(key)}\s*=\s*\[(.*?)\]", text, flags=re.MULTILINE | re.DOTALL)
    if not match:
        return []
    return re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))


def read_optional(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
