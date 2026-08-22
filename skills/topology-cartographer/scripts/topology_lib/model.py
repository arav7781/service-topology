"""Graph model - the single source of truth every renderer reads.

Layout and rendering never re-derive a fact; they only read what extraction
wrote here. That is what makes the pipeline auditable: every edge carries the
`path/to/file:LINE` it came from and the evidence tag that says how strongly it
is known.

Determinism is a hard requirement, so this module never records a timestamp,
never records an absolute path in serialised output, and sorts every collection
before writing. Scanning unchanged code twice produces byte-identical JSON.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

SCHEMA = "topology-cartographer/graph-model"
SCHEMA_VERSION = "1.0.0"

# --- evidence tags -----------------------------------------------------------
# The same three tags contributor-scout uses, with the same meanings. `[TEST]`,
# `[HISTORY]`, `[MAINTAINER]` and `[DOCS]` do not apply to topology extraction
# and are deliberately absent - see references/evidence-classification.md.
CODE = "CODE"
INFERENCE = "INFERENCE"
UNVERIFIED = "UNVERIFIED"
EVIDENCE_TAGS = (CODE, INFERENCE, UNVERIFIED)

# Anything weaker than CODE renders dashed and grey, and is listed separately as
# "inferred, not confirmed".
CONFIRMED_TAGS = (CODE,)

# --- node kinds --------------------------------------------------------------
KIND_SERVICE = "service"
KIND_TOPIC = "topic"
KIND_DATASTORE = "datastore"
KIND_CACHE = "cache"
KIND_EXTERNAL_API = "external_api"
NODE_KINDS = (KIND_SERVICE, KIND_TOPIC, KIND_DATASTORE, KIND_CACHE, KIND_EXTERNAL_API)
EXTERNAL_KINDS = (KIND_DATASTORE, KIND_CACHE, KIND_EXTERNAL_API)

# --- edge types --------------------------------------------------------------
EDGE_PRODUCES = "produces"      # service -> topic
EDGE_CONSUMES = "consumes"      # topic   -> service
EDGE_CALLS = "calls"            # service -> service or external API
EDGE_DEPENDS = "depends_on"     # service -> datastore or cache
EDGE_TYPES = (EDGE_PRODUCES, EDGE_CONSUMES, EDGE_CALLS, EDGE_DEPENDS)

SOURCE_RE = re.compile(r"^[^\s:][^:]*:\d+(?:-\d+)?$")


def _drop_empty(mapping: Dict[str, Any]) -> Dict[str, Any]:
    """Omit empty optional fields so the JSON stays readable and stable."""
    return dict((k, v) for k, v in mapping.items() if v not in (None, "", [], {}, ()))


# --------------------------------------------------------------------------- #
# Nodes and edges
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Node:
    """A service, a Kafka topic, or an external system drawn as a leaf."""

    id: str
    kind: str
    label: str = ""
    language: str = ""
    path: str = ""
    source_evidence: Tuple[str, ...] = ()
    attributes: Tuple[Tuple[str, str], ...] = ()

    @property
    def display(self) -> str:
        return self.label or self.id

    def to_json(self) -> Dict[str, Any]:
        return _drop_empty({
            "id": self.id,
            "kind": self.kind,
            "label": self.display,
            "language": self.language,
            "path": self.path,
            "source_evidence": list(self.source_evidence),
            "attributes": dict(self.attributes),
        })

    @classmethod
    def from_json(cls, raw: Dict[str, Any]) -> "Node":
        attributes = raw.get("attributes") or {}
        return cls(
            id=str(raw["id"]),
            kind=str(raw.get("kind", KIND_SERVICE)),
            label=str(raw.get("label", "")),
            language=str(raw.get("language", "")),
            path=str(raw.get("path", "")),
            source_evidence=tuple(raw.get("source_evidence", ()) or ()),
            attributes=tuple(sorted((str(k), str(v)) for k, v in attributes.items())),
        )


@dataclass(frozen=True)
class Edge:
    """One producer/consumer binding or one synchronous call.

    `source` is mandatory and is always `path/to/file:LINE`. An edge without one
    is a guess, and this tool does not draw guesses.
    """

    src: str
    dst: str
    type: str
    evidence_tag: str
    source: str
    detail: str = ""        # "key=order_id", "group=billing", "depends_on"
    protocol: str = ""      # kafka | http | grpc | sql | redis | ...
    method: str = ""        # "GET /orders/{id}" | "GetOrder"
    note: str = ""          # why this is an inference, when it is one
    extractor: str = ""     # which extractor produced it
    also_at: Tuple[str, ...] = ()   # further sightings of the same binding

    @property
    def sort_key(self) -> Tuple[str, ...]:
        return (self.src, self.dst, self.type, self.protocol, self.method,
                self.detail, self.source, self.evidence_tag)

    @property
    def identity(self) -> Tuple[str, ...]:
        """What makes two sightings the same fact.

        Deliberately excludes `source`: three files publishing to the same
        topic with the same key is one arrow with three citations, not three
        arrows stacked on top of each other.

        `depends_on` collapses further still. A service either uses a database
        or it does not; that one fact turning up in docker-compose *and* in a
        connection string is two citations, never two arrows.
        """
        if self.type == EDGE_DEPENDS:
            return (self.src, self.dst, self.type)
        return (self.src, self.dst, self.type, self.protocol, self.method,
                self.detail)

    @property
    def relation(self) -> Tuple[str, ...]:
        """The bare relationship, ignoring how well it happens to be labelled."""
        return (self.src, self.dst, self.type, self.protocol)

    @property
    def citations(self) -> Tuple[str, ...]:
        return (self.source,) + tuple(self.also_at)

    @property
    def confirmed(self) -> bool:
        return self.evidence_tag in CONFIRMED_TAGS

    @property
    def label(self) -> str:
        """What the edge says on the diagram."""
        parts = [self.method] if self.method else []
        if self.detail:
            parts.append(self.detail)
        return "\n".join(parts)

    def to_json(self) -> Dict[str, Any]:
        return _drop_empty({
            "from": self.src,
            "to": self.dst,
            "type": self.type,
            "protocol": self.protocol,
            "method": self.method,
            "detail": self.detail,
            "evidence_tag": self.evidence_tag,
            "source": self.source,
            "also_at": list(self.also_at),
            "note": self.note,
            "extractor": self.extractor,
        })

    @classmethod
    def from_json(cls, raw: Dict[str, Any]) -> "Edge":
        return cls(
            src=str(raw["from"]),
            dst=str(raw["to"]),
            type=str(raw.get("type", EDGE_CALLS)),
            evidence_tag=str(raw.get("evidence_tag", UNVERIFIED)),
            source=str(raw.get("source", "")),
            detail=str(raw.get("detail", "")),
            protocol=str(raw.get("protocol", "")),
            method=str(raw.get("method", "")),
            note=str(raw.get("note", "")),
            extractor=str(raw.get("extractor", "")),
            also_at=tuple(raw.get("also_at", ()) or ()),
        )


# --------------------------------------------------------------------------- #
# The model
# --------------------------------------------------------------------------- #

@dataclass
class GraphModel:
    repo: str = ""
    scope: Tuple[str, ...] = ()
    services: Dict[str, Node] = field(default_factory=dict)
    topics: Dict[str, Node] = field(default_factory=dict)
    external_systems: Dict[str, Node] = field(default_factory=dict)
    edges: List[Edge] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    layout: Dict[str, Any] = field(default_factory=dict)

    # -- mutation ---------------------------------------------------------- #
    def _bucket(self, kind: str) -> Dict[str, Node]:
        if kind == KIND_SERVICE:
            return self.services
        if kind == KIND_TOPIC:
            return self.topics
        return self.external_systems

    def add_node(self, node: Node) -> Node:
        """Insert, or merge into what is already there.

        Merging unions the evidence and keeps the more informative label, so the
        order files happen to be scanned in cannot change the result.
        """
        bucket = self._bucket(node.kind)
        existing = bucket.get(node.id)
        if existing is None:
            bucket[node.id] = node
            return node
        attributes = dict(existing.attributes)
        attributes.update(dict(node.attributes))
        merged = Node(
            id=existing.id,
            kind=existing.kind,
            label=existing.label or node.label,
            language=existing.language or node.language,
            path=existing.path or node.path,
            source_evidence=tuple(sorted(
                set(existing.source_evidence) | set(node.source_evidence))),
            attributes=tuple(sorted(attributes.items())),
        )
        bucket[merged.id] = merged
        return merged

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

    def finalize(self) -> "GraphModel":
        """Dedupe and sort. Idempotent - call before serialising or rendering."""
        grouped = {}  # type: Dict[Tuple[str, ...], List[Edge]]
        for edge in self.edges:
            grouped.setdefault(edge.identity, []).append(edge)

        collapsed = []  # type: List[Edge]
        for identity in sorted(grouped):
            sightings = grouped[identity]
            citations = sorted(set(
                citation for edge in sightings for citation in edge.citations if citation))
            # A CODE sighting always wins over a weaker sighting of the same
            # fact; among equals, the better-labelled one is the canonical one,
            # then the earliest citation.
            best = sorted(sightings, key=lambda e: (
                -_tag_rank(e), -_label_rank(e), e.source))[0]
            note = best.note
            if not note:
                note = next((e.note for e in sightings
                             if e.note and _tag_rank(e) == _tag_rank(best)), "")
            # The winning sighting keeps its own citation as the canonical
            # one. Taking citations[0] instead would make a second finalize()
            # pass promote a different line, which breaks idempotency.
            if best.source in citations:
                canonical = best.source
            else:
                canonical = citations[0] if citations else best.source
            collapsed.append(Edge(
                src=best.src, dst=best.dst, type=best.type,
                evidence_tag=best.evidence_tag,
                source=canonical,
                detail=best.detail, protocol=best.protocol, method=best.method,
                note=note, extractor=best.extractor,
                also_at=tuple(c for c in citations if c != canonical),
            ))
        self.edges = sorted(_absorb_unlabelled(collapsed), key=lambda e: e.sort_key)
        self.services = dict(sorted(self.services.items()))
        self.topics = dict(sorted(self.topics.items()))
        self.external_systems = dict(sorted(self.external_systems.items()))
        self.warnings = sorted(set(self.warnings))
        counted = dict(
            (key, value) for key, value in self.stats.items()
            if key.startswith("files") or key == "focus"
        )
        self.stats = dict(
            services=len(self.services),
            topics=len(self.topics),
            external_systems=len(self.external_systems),
            edges=len(self.edges),
            edges_code=sum(1 for e in self.edges if e.evidence_tag == CODE),
            edges_inference=sum(1 for e in self.edges if e.evidence_tag == INFERENCE),
            edges_unverified=sum(1 for e in self.edges if e.evidence_tag == UNVERIFIED),
        )
        self.stats.update(counted)
        return self

    # -- lookups ----------------------------------------------------------- #
    @property
    def nodes(self) -> Dict[str, Node]:
        merged = {}  # type: Dict[str, Node]
        merged.update(self.services)
        merged.update(self.topics)
        merged.update(self.external_systems)
        return merged

    def node(self, node_id: str) -> Optional[Node]:
        return self.nodes.get(node_id)

    def edges_touching(self, node_id: str) -> List[Edge]:
        return [e for e in self.edges if e.src == node_id or e.dst == node_id]

    def edge_count_by_service(self) -> Dict[str, int]:
        counts = dict((sid, 0) for sid in self.services)
        for edge in self.edges:
            for end in (edge.src, edge.dst):
                if end in counts:
                    counts[end] += 1
        return counts

    def inferred_edges(self) -> List[Edge]:
        return [e for e in self.edges if not e.confirmed]

    # -- serialisation ------------------------------------------------------ #
    def to_json(self) -> Dict[str, Any]:
        payload = {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "repo": self.repo,
            "scope": list(self.scope),
            "stats": self.stats,
            "services": [n.to_json() for n in self.services.values()],
            "topics": [n.to_json() for n in self.topics.values()],
            "external_systems": [n.to_json() for n in self.external_systems.values()],
            "edges": [e.to_json() for e in self.edges],
            "warnings": list(self.warnings),
        }
        if self.layout:
            payload["layout"] = self.layout
        return payload

    def dumps(self, indent: int = 2) -> str:
        return json.dumps(self.to_json(), indent=indent, ensure_ascii=False) + "\n"

    @classmethod
    def from_json(cls, raw: Dict[str, Any]) -> "GraphModel":
        model = cls(repo=str(raw.get("repo", "")), scope=tuple(raw.get("scope", ()) or ()))
        for key in ("services", "topics", "external_systems"):
            for item in raw.get(key, []) or []:
                model.add_node(Node.from_json(item))
        model.edges = [Edge.from_json(e) for e in raw.get("edges", []) or []]
        model.warnings = list(raw.get("warnings", []) or [])
        model.stats = dict(raw.get("stats", {}) or {})
        model.layout = dict(raw.get("layout", {}) or {})
        return model

    @classmethod
    def loads(cls, text: str) -> "GraphModel":
        return cls.from_json(json.loads(text))

    @classmethod
    def load(cls, path: str) -> "GraphModel":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.loads(handle.read())


def _tag_rank(edge: Edge) -> int:
    return {CODE: 3, INFERENCE: 2, UNVERIFIED: 1}.get(edge.evidence_tag, 0)


def _label_rank(edge: Edge) -> int:
    return len(edge.method) + len(edge.detail)


def _absorb_unlabelled(edges: List[Edge]) -> List[Edge]:
    """Fold a bare sighting into a labelled one of the same relationship.

    `NewWriter(WriterConfig{Topic: "orders.created"})` and
    `WriteMessages(Message{Topic: "orders.created", Key: id})` are the same
    arrow seen twice, once without the key. Drawing both puts two parallel
    lines between the same pair of boxes, one of them saying nothing. Keep the
    labelled edge and move the bare one's citation onto it.
    """
    by_relation = {}  # type: Dict[Tuple[str, ...], List[Edge]]
    for edge in edges:
        by_relation.setdefault(edge.relation, []).append(edge)

    kept = []  # type: List[Edge]
    for relation in sorted(by_relation):
        group = by_relation[relation]
        labelled = [e for e in group if _label_rank(e)]
        bare = [e for e in group if not _label_rank(e)]
        if not labelled or not bare:
            kept.extend(group)
            continue
        extra = sorted(set(
            citation for edge in bare for citation in edge.citations if citation))
        anchor = sorted(labelled, key=lambda e: e.sort_key)[0]
        merged = sorted((set(anchor.also_at) | set(extra)) - {anchor.source})
        kept.append(Edge(
            src=anchor.src, dst=anchor.dst, type=anchor.type,
            evidence_tag=anchor.evidence_tag, source=anchor.source,
            detail=anchor.detail, protocol=anchor.protocol, method=anchor.method,
            note=anchor.note, extractor=anchor.extractor, also_at=tuple(merged),
        ))
        kept.extend(edge for edge in labelled if edge is not anchor)
    return kept


# --------------------------------------------------------------------------- #
# Micro topology
# --------------------------------------------------------------------------- #

def subgraph_for_service(model: GraphModel, service_id: str) -> GraphModel:
    """A strict subset of `model`: `service_id` and its direct neighbours.

    Kafka gets two hops, because a topic on its own tells you nothing - the
    point of a micro topology is seeing who is on the other end of the topic
    you publish to. Only edges through a topic this service touches are pulled
    in; the rest of the system stays out.
    """
    if service_id not in model.services:
        raise KeyError(service_id)

    direct = [e for e in model.edges if e.src == service_id or e.dst == service_id]
    topics = set()
    for edge in direct:
        for end in (edge.src, edge.dst):
            if end in model.topics:
                topics.add(end)
    second_hop = [
        e for e in model.edges
        if e not in direct and (e.src in topics or e.dst in topics)
    ]

    sub = GraphModel(repo=model.repo, scope=(service_id,))
    for edge in sorted(set(direct + second_hop), key=lambda e: e.sort_key):
        sub.add_edge(edge)
        for end in (edge.src, edge.dst):
            node = model.node(end)
            if node is not None:
                sub.add_node(node)
    sub.add_node(model.services[service_id])
    sub.finalize()
    sub.stats["focus"] = service_id
    return sub


def iter_nodes(model: GraphModel) -> Iterator[Node]:
    for node in model.services.values():
        yield node
    for node in model.topics.values():
        yield node
    for node in model.external_systems.values():
        yield node


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def validate(model: GraphModel) -> List[str]:
    """Return human-readable problems. An empty list means the model is sound."""
    problems = []  # type: List[str]
    known = model.nodes

    for node in iter_nodes(model):
        if node.kind not in NODE_KINDS:
            problems.append("node {0}: unknown kind {1!r}".format(node.id, node.kind))
        if not node.source_evidence:
            problems.append("node {0}: no source_evidence".format(node.id))
        for citation in node.source_evidence:
            if not SOURCE_RE.match(citation):
                problems.append(
                    "node {0}: source_evidence {1!r} is not path/to/file:LINE".format(
                        node.id, citation))

    for edge in model.edges:
        where = "edge {0} -{1}-> {2}".format(edge.src, edge.type, edge.dst)
        if edge.src not in known:
            problems.append("{0}: source node is not declared".format(where))
        if edge.dst not in known:
            problems.append("{0}: target node is not declared".format(where))
        if edge.type not in EDGE_TYPES:
            problems.append("{0}: unknown type {1!r}".format(where, edge.type))
        if edge.evidence_tag not in EVIDENCE_TAGS:
            problems.append("{0}: bad evidence tag {1!r}".format(where, edge.evidence_tag))
        if not edge.source:
            problems.append("{0}: missing source citation".format(where))
        for citation in edge.citations:
            if citation and not SOURCE_RE.match(citation):
                problems.append(
                    "{0}: source {1!r} is not path/to/file:LINE".format(where, citation))
        if not edge.confirmed and not edge.note:
            problems.append(
                "{0}: tagged {1} without a note explaining why".format(
                    where, edge.evidence_tag))
        if edge.type == EDGE_PRODUCES and edge.dst not in model.topics:
            problems.append("{0}: `produces` must point at a topic".format(where))
        if edge.type == EDGE_CONSUMES and edge.src not in model.topics:
            problems.append("{0}: `consumes` must start at a topic".format(where))

    return sorted(set(problems))


# --------------------------------------------------------------------------- #
# Write containment
# --------------------------------------------------------------------------- #

def user_path(path: str) -> str:
    """Interpret a path the user typed as relative to their shell, not the root.

    `SafeWriter` resolves a bare relative path against its output root, which is
    what callers like the MCP server want when they ask for "graph-model.json".
    A path typed on a command line means something different - `-o
    run-a/graph-model.json` is relative to the working directory - and taking it
    the other way silently writes `run-a/run-a/graph-model.json`.
    """
    return str(Path(path).expanduser().absolute())


class OutsideOutputRoot(RuntimeError):
    """Raised when something tries to write outside the allowed output root."""


class SafeWriter:
    """Every byte this tool writes goes through here.

    The analysed repository is read-only: no source, no tests, no config, not
    even its `.gitignore`. Anything resolving outside the output root raises
    instead of writing, so a path-traversal bug cannot become a stray file.
    """

    def __init__(self, output_root: str) -> None:
        self.root = Path(output_root).expanduser().resolve()
        self.written = []  # type: List[Path]

    def resolve(self, path: str) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        # normpath collapses `..` before the comparison, so `../../etc` is caught;
        # resolve() then follows symlinks, so a link pointing out of the root is
        # caught too - and both sides of the comparison are resolved the same
        # way, which matters wherever /tmp is itself a symlink.
        resolved = Path(os.path.normpath(str(candidate)))
        try:
            resolved = resolved.resolve()
        except OSError:
            pass
        try:
            resolved.relative_to(self.root)
        except ValueError:
            raise OutsideOutputRoot(
                "refusing to write {0} - outside the output root {1}".format(
                    resolved, self.root))
        return resolved

    def write_text(self, path: str, text: str) -> Path:
        target = self.resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # newline="" so the bytes we built are the bytes on disk, on every OS.
        with open(str(target), "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        self.written.append(target)
        return target
