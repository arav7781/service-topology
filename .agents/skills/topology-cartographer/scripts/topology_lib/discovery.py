"""Repository walk and service discovery.

Read-only. Produces the file inventory, the service roots every file is
attributed to, and the config index the extractors resolve symbols against.

Service identity is the one judgement call in this module, so it is made from
declared names in manifests - `spring.application.name`, `artifactId`,
package.json `name`, the go.mod module - and only falls back to the directory
name when a repository declares nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from .configindex import (
    CONFIG_FILENAMES,
    CONFIG_SUFFIXES,
    ConfigIndex,
    parse_properties,
    parse_yaml,
)
from .textutil import line_of, slugify

IGNORE_DIRS = frozenset("""
    .git .hg .svn .idea .gradle .mvn .terraform .serverless .dart_tool
    node_modules bower_components jspm_packages vendor Pods DerivedData
    venv .venv env virtualenv site-packages __pycache__ .mypy_cache
    .pytest_cache .ruff_cache .tox .nox .cache .parcel-cache .turbo .yarn
    dist build target out bin obj coverage htmlcov .next .nuxt .svelte-kit
    .angular .output .terragrunt-cache generated gen
""".split())

IGNORE_FILE_SUFFIXES = (
    ".min.js", ".min.css", ".map", ".lock", "-lock.json", ".snap",
    ".pb.go", "_pb2.py", "_pb2_grpc.py", ".pb.cc", ".pb.h", "_grpc.pb.go",
)

SOURCE_SUFFIXES = frozenset("""
    .py .java .kt .kts .scala .go .js .jsx .ts .tsx .mjs .cjs .cs .rb .rs
    .php .proto .yml .yaml .json .properties .tf .tfvars .gradle .xml
""".split())

CODE_SUFFIXES = frozenset(
    ".py .java .kt .kts .scala .go .js .jsx .ts .tsx .mjs .cjs .cs .rb .rs .php".split())

LANGUAGE_BY_SUFFIX = {
    ".py": "python", ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
    ".scala": "scala", ".go": "go", ".js": "javascript", ".jsx": "javascript",
    ".mjs": "javascript", ".cjs": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".cs": "csharp", ".rb": "ruby", ".rs": "rust",
    ".php": "php",
}

MANIFESTS = (
    "pom.xml", "build.gradle", "build.gradle.kts", "package.json", "go.mod",
    "pyproject.toml", "setup.py", "requirements.txt", "Cargo.toml",
    "Dockerfile", "Chart.yaml",
)

MAX_FILE_BYTES = 2000000


@dataclass(frozen=True)
class FileRecord:
    path: Path
    rel: str
    suffix: str
    size: int

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def language(self) -> str:
        return LANGUAGE_BY_SUFFIX.get(self.suffix, "")

    @property
    def is_code(self) -> bool:
        return self.suffix in CODE_SUFFIXES


@dataclass
class ServiceRoot:
    id: str
    label: str
    rel: str                        # repository-relative dir, "" for the root
    language: str = ""
    evidence: str = ""              # "path/to/manifest:LINE"
    files: int = 0
    manifests: Tuple[str, ...] = ()

    @property
    def depth(self) -> int:
        return 0 if not self.rel else self.rel.count("/") + 1


@dataclass
class RepoScan:
    root: Path
    files: List[FileRecord] = field(default_factory=list)
    services: Dict[str, ServiceRoot] = field(default_factory=dict)
    config: ConfigIndex = field(default_factory=ConfigIndex)
    warnings: List[str] = field(default_factory=list)
    text_cache: Dict[str, List[str]] = field(default_factory=dict, repr=False)
    owners: Dict[str, str] = field(default_factory=dict, repr=False)

    def read_lines(self, record: FileRecord) -> List[str]:
        cached = self.text_cache.get(record.rel)
        if cached is None:
            try:
                content = record.path.read_text(encoding="utf-8", errors="replace")
            except OSError as error:
                self.warnings.append("could not read {0}: {1}".format(record.rel, error))
                content = ""
            cached = content.splitlines()
            self.text_cache[record.rel] = cached
        return cached

    def read_text(self, record: FileRecord) -> str:
        return "\n".join(self.read_lines(record))

    def owner_of(self, rel: str) -> str:
        """The service that owns a file, or "" when no service root covers it.

        Returning "" matters: a docker-compose.yml at the repository root
        belongs to no single service, and attributing it to whichever service
        happens to sort first would invent edges. Extractors skip unattributed
        files, except the compose reader, which resolves per compose service.
        """
        return self.owners.get(rel, "")

    @property
    def default_service_id(self) -> str:
        if not self.services:
            return slugify(self.root.name, keep_dots=False)
        shallowest = sorted(self.services.values(), key=lambda s: (s.depth, s.id))[0]
        return shallowest.id


# --------------------------------------------------------------------------- #
# Walking
# --------------------------------------------------------------------------- #

def _skip_dir(name: str) -> bool:
    if name in IGNORE_DIRS:
        return True
    return name.startswith(".") and name != ".github"


def _skip_file(name: str) -> bool:
    if name.startswith(".") and not name.startswith(".env"):
        return True
    return any(name.endswith(suffix) for suffix in IGNORE_FILE_SUFFIXES)


def _is_interesting(name: str, suffix: str) -> bool:
    if name in CONFIG_FILENAMES or name.startswith(".env") or name in MANIFESTS:
        return True
    return suffix in SOURCE_SUFFIXES or suffix in CONFIG_SUFFIXES


def walk_repo(root: Path, scope: Iterable[str] = ()) -> List[FileRecord]:
    """Deterministic, sorted file inventory for `root` (or the named subtrees)."""
    root = Path(root).expanduser().resolve()
    bases = [root / part.strip() for part in scope if str(part).strip()] or [root]
    found = {}  # type: Dict[str, FileRecord]

    for base in bases:
        if not base.exists():
            continue
        if base.is_file():
            rel = base.relative_to(root).as_posix()
            found[rel] = FileRecord(base, rel, base.suffix.lower(), base.stat().st_size)
            continue
        stack = [base]
        while stack:
            current = stack.pop()
            try:
                entries = sorted(current.iterdir(), key=lambda item: item.name)
            except OSError:
                continue
            for entry in entries:
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if not _skip_dir(entry.name):
                        stack.append(entry)
                    continue
                if _skip_file(entry.name):
                    continue
                suffix = entry.suffix.lower()
                if not _is_interesting(entry.name, suffix):
                    continue
                try:
                    size = entry.stat().st_size
                except OSError:
                    continue
                if size > MAX_FILE_BYTES:
                    continue
                rel = entry.relative_to(root).as_posix()
                found[rel] = FileRecord(entry, rel, suffix, size)

    return [found[key] for key in sorted(found)]


# --------------------------------------------------------------------------- #
# Service naming
# --------------------------------------------------------------------------- #

_POM_ARTIFACT = re.compile(r"<artifactId>\s*([^<]+?)\s*</artifactId>")
_POM_PARENT = re.compile(r"<parent>.*?</parent>", re.DOTALL)
_GRADLE_NAME = re.compile(r"rootProject\.name\s*=\s*['\"]([^'\"]+)['\"]")
_GO_MODULE = re.compile(r"^module\s+(\S+)", re.MULTILINE)
_TOML_NAME = re.compile(r"^\s*name\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE)
_JSON_NAME = re.compile(r"\"name\"\s*:\s*\"([^\"]+)\"")
_SETUP_NAME = re.compile(r"name\s*=\s*[\"']([^\"']+)[\"']")


def _name_from_manifest(name: str, text: str) -> Optional[Tuple[str, str, int]]:
    """-> (declared name, language, 1-based line) or None."""
    lines = text.splitlines()

    if name == "pom.xml":
        # The parent block's artifactId names the parent, not this module.
        match = (_POM_ARTIFACT.search(_POM_PARENT.sub("", text))
                 or _POM_ARTIFACT.search(text))
        if match:
            return match.group(1), "java", line_of(lines, match.group(1))
    elif name.startswith("build.gradle"):
        match = _GRADLE_NAME.search(text)
        if match:
            return match.group(1), "java", line_of(lines, match.group(1))
    elif name == "package.json":
        match = _JSON_NAME.search(text)
        if match:
            # "@acme/orders-svc" is one service called orders-svc.
            return match.group(1).split("/")[-1], "javascript", line_of(lines, match.group(1))
    elif name == "go.mod":
        match = _GO_MODULE.search(text)
        if match:
            module = match.group(1).rstrip("/")
            return module.split("/")[-1], "go", line_of(lines, match.group(1))
    elif name in ("pyproject.toml", "Cargo.toml"):
        match = _TOML_NAME.search(text)
        if match:
            language = "python" if name == "pyproject.toml" else "rust"
            return match.group(1), language, line_of(lines, match.group(1))
    elif name == "setup.py":
        match = _SETUP_NAME.search(text)
        if match:
            return match.group(1), "python", line_of(lines, match.group(1))
    elif name == "Chart.yaml":
        parsed = parse_yaml(text)
        if isinstance(parsed, dict) and parsed.get("name"):
            declared = str(parsed["name"])
            return declared, "", line_of(lines, declared)
    return None


def _spring_application_name(text: str, suffix: str) -> Optional[Tuple[str, int]]:
    lines = text.splitlines()
    if suffix in (".yml", ".yaml"):
        parsed = parse_yaml(text)
        if isinstance(parsed, dict):
            spring = parsed.get("spring")
            if isinstance(spring, dict):
                application = spring.get("application")
                if isinstance(application, dict) and application.get("name"):
                    declared = str(application["name"])
                    return declared, line_of(lines, declared)
    else:
        declared = parse_properties(text).get("spring.application.name")
        if declared:
            return declared, line_of(lines, declared)
    return None


def _module_root(rel_dir: str) -> str:
    """`orders/src/main/resources` -> `orders`. An application.yml lives deep."""
    for marker in ("/src/main/resources", "/src/main/java", "/src/test/resources",
                   "/src/resources", "/src", "/config", "/resources"):
        probe = "/" + rel_dir
        index = probe.find(marker)
        if index >= 0:
            return probe[1:index] if index > 0 else ""
    return rel_dir


def discover_services(scan: RepoScan) -> None:
    """Find service roots, name them, and attribute every file to one."""
    candidates = {}  # type: Dict[str, ServiceRoot]

    manifest_records = [
        record for record in scan.files
        if record.name in MANIFESTS
        or record.name.startswith(("application.", "bootstrap."))
    ]

    # Deepest first, so a nested module claims its own directory.
    ordered_manifests = sorted(
        manifest_records, key=lambda r: (-r.rel.count("/"), r.rel))

    for record in ordered_manifests:
        rel_dir = record.path.parent.relative_to(scan.root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        is_spring_config = record.name.startswith(("application.", "bootstrap."))
        if is_spring_config:
            rel_dir = _module_root(rel_dir)

        declared, language, line = None, "", 1
        if record.name in MANIFESTS:
            parsed = _name_from_manifest(record.name, scan.read_text(record))
            if parsed is not None:
                declared, language, line = parsed
            elif record.name == "Dockerfile":
                declared = record.path.parent.name if rel_dir else scan.root.name
        else:
            spring = _spring_application_name(scan.read_text(record), record.suffix)
            if spring is not None:
                declared, language, line = spring[0], "java", spring[1]

        existing = candidates.get(rel_dir)
        if declared is None:
            if existing is not None:
                existing.manifests = tuple(sorted(set(existing.manifests) | {record.rel}))
                continue
            declared = record.path.parent.name if rel_dir else scan.root.name

        manifests = tuple(sorted(
            set(existing.manifests if existing else ()) | {record.rel}))
        # spring.application.name is the most authoritative name a JVM service
        # has, so it overrides an artifactId picked up from the same directory.
        if existing is None or is_spring_config:
            candidates[rel_dir] = ServiceRoot(
                id=slugify(declared, keep_dots=False),
                label=declared,
                rel=rel_dir,
                language=language or (existing.language if existing else ""),
                evidence="{0}:{1}".format(record.rel, line),
                manifests=manifests,
            )
        else:
            existing.language = existing.language or language
            existing.manifests = manifests

    if not candidates:
        candidates[""] = ServiceRoot(
            id=slugify(scan.root.name, keep_dots=False),
            label=scan.root.name,
            rel="",
            evidence="{0}:1".format(_first_code_rel(scan)),
        )

    _attribute_files(scan, candidates)


def _attribute_files(scan: RepoScan, candidates: Dict[str, ServiceRoot]) -> None:
    by_depth = sorted(candidates.values(), key=lambda s: (-s.depth, s.rel))
    counts = dict((service.rel, 0) for service in by_depth)
    language_votes = dict((service.rel, {}) for service in by_depth)  # type: Dict[str, Dict[str, int]]

    for record in scan.files:
        for service in by_depth:
            if (service.rel == "" or record.rel == service.rel
                    or record.rel.startswith(service.rel + "/")):
                scan.owners[record.rel] = service.id
                counts[service.rel] += 1
                if record.is_code and record.language:
                    votes = language_votes[service.rel]
                    votes[record.language] = votes.get(record.language, 0) + 1
                break

    # A workspace wrapper - a root package.json over per-service packages - owns
    # no code of its own. Drop it rather than drawing a service that isn't one.
    kept = {}  # type: Dict[str, ServiceRoot]
    for service in sorted(candidates.values(), key=lambda s: (s.depth, s.rel)):
        votes = language_votes[service.rel]
        if not votes and len(candidates) > 1:
            continue
        service.files = counts[service.rel]
        if not service.language and votes:
            service.language = max(sorted(votes.items()), key=lambda kv: kv[1])[0]
        kept[service.id] = service

    if not kept:  # every candidate was a wrapper - keep them all, not none
        for service in candidates.values():
            service.files = counts[service.rel]
            kept[service.id] = service

    # Re-point files whose owner was dropped at a surviving root.
    fallback = sorted(kept.values(), key=lambda s: (s.depth, s.id))[0].id
    for rel, owner in list(scan.owners.items()):
        if owner not in kept:
            scan.owners[rel] = _closest_owner(rel, kept, fallback)

    scan.services = dict(sorted(kept.items()))


def _closest_owner(rel: str, services: Dict[str, ServiceRoot], fallback: str) -> str:
    best = None  # type: Optional[ServiceRoot]
    for service in services.values():
        if service.rel == "" or rel.startswith(service.rel + "/"):
            if best is None or service.depth > best.depth:
                best = service
    return best.id if best is not None else fallback


def _first_code_rel(scan: RepoScan) -> str:
    for record in scan.files:
        if record.is_code:
            return record.rel
    return scan.files[0].rel if scan.files else "."


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def scan_repository(root: str, scope: Iterable[str] = ()) -> RepoScan:
    """Walk, index config, and discover services. Reads only; writes nothing."""
    resolved = Path(root).expanduser().resolve()
    scan = RepoScan(root=resolved)
    scan.files = walk_repo(resolved, scope)

    for record in scan.files:
        if (record.name in CONFIG_FILENAMES or record.name.startswith(".env")
                or record.suffix in CONFIG_SUFFIXES):
            scan.config.add_file(record.name, record.rel, scan.read_text(record))

    discover_services(scan)

    # Inside a compose network or a Kubernetes namespace, a service's name is
    # also its hostname - that is what lets `http://orders-svc/...` resolve.
    for service in scan.services.values():
        scan.config.register_service_host(service.id, service.id, service.evidence)
        scan.config.register_service_host(service.label, service.id, service.evidence)
        if service.rel:
            scan.config.register_service_host(
                service.rel.split("/")[-1], service.id, service.evidence)
    return scan
