"""Extraction context and pipeline.

The evidence rule lives here, in exactly one place, so that no extractor can
quietly invent an edge:

    [CODE]        we read the binding - a literal at the call site, or a config
                  key we followed to a concrete value in a file we also read.
    [INFERENCE]   the pattern matched but the target never resolved - an
                  unresolved placeholder, a host we could not map to a service,
                  a gRPC stub with no .proto in scope.
    [UNVERIFIED]  reserved for facts a human or subagent asserted that this
                  pipeline could not confirm by reading a file.

An edge weaker than `[CODE]` must carry a `note` saying *why*. That note is
what `validate_graph_model.py` enforces, what `evidence/sources.md` prints, and
what the reader sees next to the dashed grey line in the diagram.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .configindex import ConfigIndex
from .discovery import FileRecord, RepoScan
from .model import (
    CODE,
    EDGE_CALLS,
    EDGE_CONSUMES,
    EDGE_DEPENDS,
    EDGE_PRODUCES,
    INFERENCE,
    KIND_CACHE,
    KIND_DATASTORE,
    KIND_SERVICE,
    KIND_TOPIC,
    Edge,
    GraphModel,
    Node,
)
from .textutil import Literal, slugify, topic_id, truncate


class ResolvedTopic(object):
    """A topic name plus how well we know it."""

    __slots__ = ("id", "label", "tag", "note")

    def __init__(self, node_id: str, label: str, tag: str, note: str = "") -> None:
        self.id = node_id
        self.label = label
        self.tag = tag
        self.note = note


class Context(object):
    """What every extractor is handed: the scan, the model, and the emitters."""

    def __init__(self, scan: RepoScan, model: GraphModel) -> None:
        self.scan = scan
        self.model = model
        # Provider-side facts registered in phase 1 for phase 2 to resolve against.
        self.grpc_services = {}      # type: Dict[str, Tuple[str, str, Tuple[str, ...]]]
        self.grpc_impl_source = {}   # type: Dict[str, str]
        self.api_paths = {}          # type: Dict[str, List[Tuple[str, str, str]]]

    @property
    def config(self) -> ConfigIndex:
        return self.scan.config

    # -- helpers ------------------------------------------------------------ #
    def owner(self, record: FileRecord) -> str:
        return self.scan.owner_of(record.rel)

    def where(self, record: FileRecord, line: int) -> str:
        return "{0}:{1}".format(record.rel, max(1, int(line)))

    def ensure_service(self, service_id: str, label: str = "",
                       evidence: str = "") -> str:
        if service_id in self.model.services:
            return service_id
        known = self.scan.services.get(service_id)
        citation = evidence or (known.evidence if known else "")
        self.model.add_node(Node(
            id=service_id,
            kind=KIND_SERVICE,
            label=label or (known.label if known else service_id),
            language=known.language if known else "",
            path=known.rel if known else "",
            source_evidence=(citation,) if citation else (),
            # A service nothing in this repository declares is one we only know
            # about because something calls it. Say so, rather than drawing it
            # with the same confidence as a service we found a manifest for.
            attributes=() if known else (("origin", "referenced-only"),),
        ))
        return service_id

    # -- topic resolution --------------------------------------------------- #
    def resolve_topic(self, literal: Optional[Literal], record: FileRecord,
                      line: int) -> Optional[ResolvedTopic]:
        """Turn a call argument into a topic, or decide it is not one."""
        if literal is None or not literal.value.strip():
            return None
        raw = literal.value.strip()

        if literal.resolved:
            if looks_like_noise(raw):
                return None
            return ResolvedTopic(topic_id(raw), raw, CODE)

        hit = self.config.resolve(raw)
        if hit is not None and hit.value and not looks_like_noise(hit.value):
            # We read the reference and we read the value it points at, so this
            # is still directly evidenced - just across two files.
            return ResolvedTopic(
                topic_id(hit.value), hit.value, CODE,
                "topic name read from {0} via `{1}`".format(hit.source, raw))

        if looks_like_noise(raw):
            return None
        return ResolvedTopic(
            topic_id(raw), "{0}\n(unresolved)".format(raw), INFERENCE,
            "`{0}` is a config reference with no value found in this repository".format(raw))

    # -- emitters ----------------------------------------------------------- #
    def add_topic_edge(self, service_id: str, topic: ResolvedTopic, direction: str,
                       record: FileRecord, line: int, detail: str = "",
                       extractor: str = "") -> None:
        self.ensure_service(service_id)
        self.model.add_node(Node(
            id=topic.id,
            kind=KIND_TOPIC,
            label=topic.label,
            source_evidence=(self.where(record, line),),
            attributes=(("unresolved", "true"),) if topic.tag != CODE else (),
        ))
        if direction == EDGE_PRODUCES:
            src, dst = service_id, topic.id
        else:
            src, dst = topic.id, service_id
        self.model.add_edge(Edge(
            src=src, dst=dst, type=direction, protocol="kafka",
            detail=truncate(detail), evidence_tag=topic.tag,
            source=self.where(record, line), note=topic.note, extractor=extractor,
        ))

    def add_call(self, caller: str, target_id: str, target_kind: str,
                 target_label: str, protocol: str, method: str,
                 record: FileRecord, line: int, tag: str, note: str = "",
                 detail: str = "", extractor: str = "") -> None:
        if caller == target_id:
            return  # a service calling itself is not a topology edge
        self.ensure_service(caller)
        if target_kind == KIND_SERVICE:
            self.ensure_service(target_id, target_label, self.where(record, line))
        else:
            self.model.add_node(Node(
                id=target_id, kind=target_kind, label=target_label,
                source_evidence=(self.where(record, line),),
            ))
        edge_type = EDGE_DEPENDS if target_kind in (KIND_DATASTORE, KIND_CACHE) else EDGE_CALLS
        self.model.add_edge(Edge(
            src=caller, dst=target_id, type=edge_type, protocol=protocol,
            method=truncate(method, 48), detail=truncate(detail),
            evidence_tag=tag, source=self.where(record, line), note=note,
            extractor=extractor,
        ))


# --------------------------------------------------------------------------- #
# Noise rejection
# --------------------------------------------------------------------------- #

_NOISE = re.compile(
    r"^(|[/{}\[\]()<>|,;:=+*&^%$#@!?~`'\"\\-]+|https?://.*|\d+|true|false|null|none"
    r"|utf-?8|json|avro|string|bytes?|localhost|latest|earliest|none|all|1|0)$",
    re.IGNORECASE)

_TOPIC_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")


def looks_like_noise(value: str) -> bool:
    """Reject arguments that are clearly not topic names.

    A false positive here loses one edge; a false negative puts a serialiser
    class name in the middle of the architecture diagram. Prefer losing the edge.
    """
    text = (value or "").strip()
    if not text or len(text) > 120:
        return True
    if _NOISE.match(text):
        return True
    if text.startswith(("/", "./", "../")) or text.endswith((".class", ".Serializer")):
        return True
    return not _TOPIC_SHAPE.match(text)


def known_host(context: Context, host: str) -> Optional[Tuple[str, str]]:
    """Map a hostname to a service id, tolerating compose and Kubernetes DNS."""
    if not host:
        return None
    cleaned = host.strip().lower().split(":")[0]
    for suffix in (".svc.cluster.local", ".svc", ".default", ".local", ".internal"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[:-len(suffix)]
    direct = context.config.host_to_service(cleaned)
    if direct is not None:
        return direct
    slug = slugify(cleaned, keep_dots=False)
    if slug in context.model.services or slug in context.scan.services:
        known = context.scan.services.get(slug)
        return slug, known.evidence if known is not None else ""
    return None


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #

def build_model(scan: RepoScan) -> GraphModel:
    """Run every extractor over every applicable file, in a fixed order.

    Phase 1 collects provider-side declarations (OpenAPI paths, .proto service
    definitions, gRPC server registrations). Phase 2 needs them: without
    knowing who *serves* `orders.OrderService`, a client stub can only be
    guessed at, and this tool does not draw guesses as facts.
    """
    from . import extract_kafka, extract_sync  # local import keeps the cycle out

    model = GraphModel(repo=str(scan.root))
    context = Context(scan, model)

    # A service that talks to nothing is still part of the topology.
    for service in scan.services.values():
        model.add_node(Node(
            id=service.id,
            kind=KIND_SERVICE,
            label=service.label,
            language=service.language,
            path=service.rel,
            source_evidence=(service.evidence,) if service.evidence else (),
            attributes=(("files", str(service.files)),),
        ))

    phase_one = (
        ("openapi", extract_sync.applies_openapi, extract_sync.extract_openapi),
        ("grpc-declarations", extract_sync.applies_grpc, extract_sync.extract_grpc_providers),
    )
    phase_two = (
        ("kafka-jvm", extract_kafka.applies_jvm, extract_kafka.extract_jvm),
        ("kafka-python", extract_kafka.applies_python, extract_kafka.extract_python),
        ("kafka-node", extract_kafka.applies_node, extract_kafka.extract_node),
        ("kafka-go", extract_kafka.applies_go, extract_kafka.extract_go),
        ("config", extract_kafka.applies_config, extract_kafka.extract_config),
        ("http-client", extract_sync.applies_http, extract_sync.extract_http),
        ("grpc-clients", extract_sync.applies_grpc, extract_sync.extract_grpc_clients),
        ("datastore", extract_sync.applies_datastore, extract_sync.extract_datastores),
    )

    for stage in (phase_one, phase_two):
        for name, applies, extract in stage:
            for record in scan.files:
                if applies(record):
                    _run(name, extract, context, record, model)

    model.stats["files_scanned"] = len(scan.files)
    model.warnings.extend(scan.warnings)
    return model.finalize()


def _run(name: str, function: Any, context: Context, record: FileRecord,
         model: GraphModel) -> None:
    """One malformed file must not sink a whole-repository scan."""
    try:
        function(context, record)
    except Exception as error:  # noqa: BLE001 - extraction is best-effort by design
        model.warnings.append("{0} failed on {1}: {2}: {3}".format(
            name, record.rel, type(error).__name__, error))
