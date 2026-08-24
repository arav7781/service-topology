"""Config index - the half of the topology that is not in the code.

Real services rarely hard-code a topic name. They write

    @KafkaListener(topics = "${app.topics.orders}")

and put the value in `application.yml`, or read `ORDERS_TOPIC` from an
environment set by docker-compose, a Helm chart, or Terraform. Reading those
files is what lets a config-keyed binding be tagged `[CODE]` rather than
demoted to `[INFERENCE]`: we read both ends of the reference.

The YAML parser here is a deliberate *subset* - block mappings, block
sequences, scalars, quotes, comments, multi-document files. No anchors, no
merge keys, no block scalars. That covers configuration files; it is not a YAML
library and does not pretend to be one. Adding PyYAML would break this
repository's standard-library-only rule.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .textutil import line_of, slugify

CONFIG_FILENAMES = (
    "application.yml", "application.yaml", "application.properties",
    "bootstrap.yml", "bootstrap.yaml",
    "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
    "values.yaml", "values.yml",
    ".env", ".env.example", ".env.sample", ".env.local", ".env.dist",
)
CONFIG_SUFFIXES = (".tf", ".tfvars")

# Container image or service name -> the external system it stands for.
IMAGE_KINDS = (
    ("postgres", "datastore", "PostgreSQL"),
    ("mysql", "datastore", "MySQL"),
    ("mariadb", "datastore", "MariaDB"),
    ("mongo", "datastore", "MongoDB"),
    ("cassandra", "datastore", "Cassandra"),
    ("elasticsearch", "datastore", "Elasticsearch"),
    ("opensearch", "datastore", "OpenSearch"),
    ("clickhouse", "datastore", "ClickHouse"),
    ("cockroach", "datastore", "CockroachDB"),
    ("dynamodb", "datastore", "DynamoDB"),
    ("minio", "datastore", "MinIO"),
    ("redis", "cache", "Redis"),
    ("valkey", "cache", "Valkey"),
    ("memcached", "cache", "Memcached"),
    ("kafka", "broker", "Kafka"),
    ("redpanda", "broker", "Redpanda"),
    ("zookeeper", "broker", "ZooKeeper"),
    ("rabbitmq", "broker", "RabbitMQ"),
    ("vault", "external_api", "Vault"),
)


# --------------------------------------------------------------------------- #
# Subset YAML
# --------------------------------------------------------------------------- #

_KEY_LINE = re.compile(r"^(?P<key>[^:#\-\s][^:#]*?)\s*:\s*(?P<value>.*)$")

# `refundCallbackProcessorTopic` -> `REFUND_CALLBACK_PROCESSOR_TOPIC`
_CAMEL_TO_SNAKE = re.compile(r"([a-z0-9])([A-Z])")


def _scalar(text: str) -> Any:
    text = text.strip()
    if not text:
        return ""
    if len(text) >= 2 and text[0] in "\"'" and text[-1] == text[0]:
        return text[1:-1]
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        return [_scalar(part) for part in _split_flow(inner)] if inner else []
    if text.startswith("{") and text.endswith("}") and ":" in text:
        mapping = {}  # type: Dict[str, Any]
        for part in _split_flow(text[1:-1]):
            if ":" in part:
                key, _, value = part.partition(":")
                mapping[key.strip().strip("\"'")] = _scalar(value)
        return mapping
    lowered = text.lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    if lowered in ("null", "~"):
        return None
    if re.match(r"^-?\d+$", text):
        return int(text)
    if re.match(r"^-?\d+\.\d+$", text):
        return float(text)
    return text


def _split_flow(text: str) -> List[str]:
    parts, current = [], []  # type: List[str], List[str]
    depth, quote = 0, None  # type: int, Optional[str]
    for char in text:
        if quote is not None:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            current.append(char)
        elif char in "[{":
            depth += 1
            current.append(char)
        elif char in "]}":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        parts.append("".join(current).strip())
    return [part for part in parts if part]


def _strip_yaml_comment(line: str) -> str:
    quote = None  # type: Optional[str]
    for index, char in enumerate(line):
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char == "#" and (index == 0 or line[index - 1] in " \t"):
            return line[:index]
    return line


def parse_yaml_documents(text: str) -> List[Any]:
    """Parse a subset-YAML file into its list of documents."""
    documents, current = [], []  # type: List[Any], List[str]
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped == "---":
            documents.append(_parse_document(current))
            current = []
            continue
        if stripped == "...":
            continue
        current.append(raw)
    documents.append(_parse_document(current))
    return [doc for doc in documents if doc not in (None, {}, [], "")]


def parse_yaml(text: str) -> Any:
    """Parse, merging multi-document files into one mapping where possible."""
    documents = parse_yaml_documents(text)
    if not documents:
        return {}
    if len(documents) == 1:
        return documents[0]
    merged = {}  # type: Dict[str, Any]
    for index, document in enumerate(documents):
        if isinstance(document, dict):
            for key, value in document.items():
                merged.setdefault(key, value)
        else:
            merged["__document_{0}".format(index)] = document
    return merged


def _parse_document(lines: List[str]) -> Any:
    cleaned = []  # type: List[Tuple[int, str]]
    for raw in lines:
        expanded = raw.replace("\t", "    ")
        stripped = _strip_yaml_comment(expanded)
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        cleaned.append((indent, stripped.strip()))
    if not cleaned:
        return {}
    value, _ = _parse_nodes(cleaned, 0, cleaned[0][0])
    return value


def _parse_nodes(lines: List[Tuple[int, str]], index: int, indent: int) -> Tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    content = lines[index][1]
    if content == "-" or content.startswith("- "):
        return _parse_sequence(lines, index, indent)
    return _parse_mapping(lines, index, indent)


def _parse_mapping(lines: List[Tuple[int, str]], index: int, indent: int) -> Tuple[Any, int]:
    result = {}  # type: Dict[str, Any]
    while index < len(lines):
        line_indent, content = lines[index]
        if line_indent < indent:
            break
        if line_indent > indent:
            index += 1  # stray deeper line; skip rather than misparse
            continue
        match = _KEY_LINE.match(content)
        if not match:
            index += 1
            continue
        key = match.group("key").strip().strip("\"'")
        inline = match.group("value").strip()
        index += 1
        if inline:
            result[key] = _scalar(inline)
            continue
        if index < len(lines) and lines[index][0] > line_indent:
            child, index = _parse_nodes(lines, index, lines[index][0])
            result[key] = child
        elif (index < len(lines) and lines[index][0] == line_indent
              and lines[index][1].startswith("-")):
            # A sequence indented level with its own key - very common in YAML.
            child, index = _parse_sequence(lines, index, line_indent)
            result[key] = child
        else:
            result[key] = None
    return result, index


def _parse_sequence(lines: List[Tuple[int, str]], index: int, indent: int) -> Tuple[Any, int]:
    items = []  # type: List[Any]
    while index < len(lines):
        line_indent, content = lines[index]
        if line_indent < indent or not content.startswith("-"):
            break
        body = content[1:].strip()
        index += 1
        if not body:
            if index < len(lines) and lines[index][0] > line_indent:
                child, index = _parse_nodes(lines, index, lines[index][0])
                items.append(child)
            else:
                items.append(None)
            continue
        if _KEY_LINE.match(body) and not body.startswith(("http:", "https:")):
            # `- name: foo` opens a mapping that may continue on later lines.
            inner_indent = line_indent + 2
            block = [(inner_indent, body)]
            while (index < len(lines) and lines[index][0] > line_indent
                   and not lines[index][1].startswith("-")):
                block.append((inner_indent, lines[index][1]))
                index += 1
            mapping, _ = _parse_mapping(block, 0, inner_indent)
            items.append(mapping)
        else:
            items.append(_scalar(body))
    return items, index


# --------------------------------------------------------------------------- #
# Flatteners
# --------------------------------------------------------------------------- #

def flatten(data: Any, prefix: str = "") -> Dict[str, str]:
    """Nested config -> dotted keys, the way Spring addresses them."""
    out = {}  # type: Dict[str, str]
    if isinstance(data, dict):
        for key, value in data.items():
            path = "{0}.{1}".format(prefix, key) if prefix else str(key)
            out.update(flatten(value, path))
    elif isinstance(data, list):
        for position, value in enumerate(data):
            out.update(flatten(value, "{0}[{1}]".format(prefix, position)))
    elif data is not None and prefix:
        out[prefix] = str(data)
    return out


def parse_properties(text: str) -> Dict[str, str]:
    out = {}  # type: Dict[str, str]
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "!")):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
        elif ":" in line:
            key, _, value = line.partition(":")
        else:
            continue
        out[key.strip()] = value.strip()
    return out


def parse_dotenv(text: str) -> Dict[str, str]:
    out = {}  # type: Dict[str, str]
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


_TF_RESOURCE = re.compile(
    r"resource\s+\"(?P<type>[A-Za-z0-9_]*(?:kafka|msk|event_hub|pubsub|sns|sqs)"
    r"[A-Za-z0-9_]*)\"\s+\"(?P<label>[^\"]+)\"\s*\{(?P<body>[^}]*)\}",
    re.IGNORECASE | re.DOTALL,
)
_TF_NAME = re.compile(r"\bname\s*=\s*\"(?P<name>[^\"]+)\"")
_TF_TOPIC = re.compile(r"\btopic\w*\s*=\s*\"(?P<topic>[^\"]+)\"")


def parse_terraform_topics(text: str) -> List[Tuple[str, str]]:
    """(topic name, resource type) for every topic declared as a resource."""
    found = []  # type: List[Tuple[str, str]]
    for block in _TF_RESOURCE.finditer(text):
        body = block.group("body")
        name_match = _TF_NAME.search(body) or _TF_TOPIC.search(body)
        name = None
        if name_match:
            name = name_match.groupdict().get("name") or name_match.groupdict().get("topic")
        found.append((name or block.group("label"), block.group("type")))
    return found


# --------------------------------------------------------------------------- #
# The index
# --------------------------------------------------------------------------- #

class ConfigValue(object):
    __slots__ = ("value", "source", "key")

    def __init__(self, value: str, source: str, key: str) -> None:
        self.value = value
        self.source = source        # "path/to/file:LINE"
        self.key = key

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "ConfigValue({0!r} from {1})".format(self.value, self.source)


class ConfigIndex(object):
    """Every config key and environment variable found, and where it was read."""

    def __init__(self) -> None:
        self.values = {}            # type: Dict[str, ConfigValue]
        self.env = {}               # type: Dict[str, ConfigValue]
        self.declared_topics = {}   # type: Dict[str, str]
        self.service_hosts = {}     # type: Dict[str, Tuple[str, str]]
        self.compose_systems = {}   # type: Dict[str, Tuple[str, str, str]]

    # -- population --------------------------------------------------------- #
    def _record(self, bucket: Dict[str, ConfigValue], key: str,
                value: Any, source: str) -> None:
        if not key or value in (None, "", True, False):
            return
        text = str(value)
        if not text or len(text) > 200:
            return
        bucket.setdefault(key, ConfigValue(text, source, key))

    def add_file(self, filename: str, rel: str, text: str) -> None:
        lines = text.splitlines()
        lower = filename.lower()
        suffix = ("." + lower.rsplit(".", 1)[-1]) if "." in lower else ""

        if lower.endswith(".properties"):
            for key, value in parse_properties(text).items():
                self._record(self.values, key, value,
                             "{0}:{1}".format(rel, line_of(lines, key)))
            return
        if lower.startswith(".env"):
            for key, value in parse_dotenv(text).items():
                self._record(self.env, key, value,
                             "{0}:{1}".format(rel, line_of(lines, key)))
            return
        if suffix in CONFIG_SUFFIXES:
            for topic, _kind in parse_terraform_topics(text):
                self.declared_topics.setdefault(
                    topic, "{0}:{1}".format(rel, line_of(lines, topic)))
            return
        if suffix in (".yml", ".yaml"):
            is_compose = lower.startswith(("docker-compose", "compose"))
            for document in parse_yaml_documents(text):
                if not isinstance(document, (dict, list)):
                    continue
                self._add_mapping(flatten(document), rel, lines)
                if is_compose and isinstance(document, dict):
                    self._add_compose(document, rel, lines)
            return
        if suffix == ".json":
            try:
                self._add_mapping(flatten(json.loads(text)), rel, lines)
            except (ValueError, TypeError):
                pass

    def _add_mapping(self, flat: Dict[str, str], rel: str, lines: List[str]) -> None:
        for key, value in flat.items():
            leaf = key.split(".")[-1].split("[")[0]
            source = "{0}:{1}".format(rel, line_of(lines, leaf))
            self._record(self.values, key, value, source)
            if leaf.isupper() and "_" in leaf:
                self._record(self.env, leaf, value, source)
            # Kubernetes and compose spell env vars as name/value pairs.
            if key.endswith(".name") and str(value).isupper():
                sibling = flat.get(key[:-len(".name")] + ".value")
                if sibling:
                    self._record(self.env, str(value), sibling, source)

    def _add_compose(self, document: Dict[str, Any], rel: str, lines: List[str]) -> None:
        services = document.get("services")
        if not isinstance(services, dict):
            return
        for name, spec in services.items():
            if not isinstance(spec, dict):
                continue
            source = "{0}:{1}".format(rel, line_of(lines, str(name)))
            haystack = "{0} {1}".format(name, spec.get("image") or "").lower()
            for needle, kind, label in IMAGE_KINDS:
                if needle in haystack:
                    self.compose_systems.setdefault(
                        slugify(str(name), keep_dots=False),
                        (kind, "{0}\n({1})".format(label, name), source))
                    break
            environment = spec.get("environment")
            if isinstance(environment, dict):
                for key, value in environment.items():
                    self._record(self.env, str(key), value, source)
            elif isinstance(environment, list):
                for entry in environment or []:
                    if isinstance(entry, str) and "=" in entry:
                        key, _, value = entry.partition("=")
                        self._record(self.env, key.strip(), value.strip(), source)

    # -- lookup ------------------------------------------------------------- #
    def resolve(self, symbol: str) -> Optional[ConfigValue]:
        """Resolve a config key, environment variable, or dotted symbol.

        A camelCase identifier is tried as SNAKE_CASE too: code says
        `refundCallbackProcessorTopic`, the `.env` says
        `REFUND_CALLBACK_PROCESSOR_TOPIC`, and without that split the two never
        meet - which silently costs a real topic edge.
        """
        if not symbol:
            return None
        tail = symbol.rsplit(".", 1)[-1]
        dotted = symbol.replace("_", ".").lower()
        shouty = symbol.replace(".", "_").replace("-", "_").upper()
        snake = _CAMEL_TO_SNAKE.sub(r"\1_\2", tail).upper()
        for candidate in (symbol, tail, dotted, symbol.lower(), shouty, snake):
            if candidate in self.env:
                return self.env[candidate]
            if candidate in self.values:
                return self.values[candidate]
        # Spring nests config under an arbitrary prefix, so match on the tail.
        if dotted.count(".") >= 1:
            for key in sorted(self.values):
                if key.lower().endswith(dotted):
                    return self.values[key]
        if len(shouty) > 4:
            for key in sorted(self.env):
                if key.upper().endswith(shouty):
                    return self.env[key]
        return None

    def register_service_host(self, host: str, service_id: str, source: str) -> None:
        if host:
            self.service_hosts.setdefault(host.strip().lower(), (service_id, source))

    def host_to_service(self, host: str) -> Optional[Tuple[str, str]]:
        return self.service_hosts.get((host or "").strip().lower())

    def summary(self) -> Dict[str, int]:
        return {
            "config_keys": len(self.values),
            "env_vars": len(self.env),
            "declared_topics": len(self.declared_topics),
            "service_hosts": len(self.service_hosts),
            "infrastructure_containers": len(self.compose_systems),
        }
