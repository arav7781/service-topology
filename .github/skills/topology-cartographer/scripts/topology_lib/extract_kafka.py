"""Kafka producer and consumer bindings.

Five sources, one per ecosystem plus config:

    JVM      Spring Kafka (@KafkaListener, KafkaTemplate), Kafka Streams,
             the plain Java client, @SendTo, @StreamListener
    Python   kafka-python, confluent-kafka-python, aiokafka, faust
    Node     kafkajs, node-rdkafka, @nestjs/microservices Kafka transport
    Go       segmentio/kafka-go, Shopify|IBM/sarama
    Config   Spring Cloud Stream bindings, Terraform topic declarations,
             docker-compose depends_on

Every extractor is gated on the file actually referencing Kafka. Without that
gate a bare `producer.send(...)` in an unrelated file becomes a phantom topic,
and a diagram with phantom topics is worse than no diagram.
"""

from __future__ import annotations

import re
from typing import Iterator, List, Optional

from .configindex import (
    flatten,
    parse_properties,
    parse_terraform_topics,
    parse_yaml_documents,
)
from .discovery import FileRecord
from .extract import Context, ResolvedTopic
from .model import (
    CODE,
    EDGE_CONSUMES,
    EDGE_PRODUCES,
    KIND_CACHE,
    KIND_DATASTORE,
    KIND_EXTERNAL_API,
    KIND_TOPIC,
    Node,
)
from .textutil import (
    all_string_literals,
    balanced_call_args,
    extract_argument,
    line_of,
    paren_after,
    slugify,
    split_args,
    strip_comment,
    topic_id,
    window,
)

# --------------------------------------------------------------------------- #
# JVM - Spring Kafka, Kafka Streams, plain client
# --------------------------------------------------------------------------- #

JVM_NAME = "kafka-jvm"
JVM_SUFFIXES = (".java", ".kt", ".kts", ".scala")

_JVM_GATE = re.compile(
    r"org\.apache\.kafka|springframework\.kafka|KafkaTemplate|KafkaListener"
    r"|ProducerRecord|StreamsBuilder|spring\.cloud\.stream|KafkaProducer|KafkaConsumer",
    re.IGNORECASE)

_LISTENER = re.compile(r"@KafkaListener\s*\(")
_STREAM_LISTENER = re.compile(r"@StreamListener\s*\(")
_SEND_TO = re.compile(r"@SendTo\s*\(")
_TEMPLATE_SEND = re.compile(r"\b([A-Za-z_]\w*)\s*\.\s*(?:send|sendDefault)\s*\(")
_PRODUCER_RECORD = re.compile(r"\bnew\s+ProducerRecord\s*(?:<[^>]*>)?\s*\(")
_JVM_SUBSCRIBE = re.compile(r"\.\s*(?:subscribe|assign)\s*\(")
_STREAMS_SOURCE = re.compile(r"\b\w*[Bb]uilder\s*\.\s*(?:stream|table|globalTable)\s*\(")
_STREAMS_SINK = re.compile(r"\.\s*(?:to|through|repartition)\s*\(\s*[\"']")

_TOPICS_ATTR = re.compile(r"\btopics\s*=\s*", re.IGNORECASE)
_PATTERN_ATTR = re.compile(r"\btopicPattern\s*=\s*", re.IGNORECASE)
_GROUP_ATTR = re.compile(r"\bgroupId\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)


def applies_jvm(record: FileRecord) -> bool:
    return record.suffix in JVM_SUFFIXES


def extract_jvm(context: Context, record: FileRecord) -> None:
    lines = context.scan.read_lines(record)
    text = "\n".join(lines)
    if not _JVM_GATE.search(text):
        return
    service = context.owner(record)
    if not service:
        return

    for index, raw in enumerate(lines):
        line_no = index + 1
        chunk = window(lines, index, 6, record.suffix)

        for pattern in (_LISTENER, _STREAM_LISTENER):
            if not pattern.search(raw):
                continue
            args = balanced_call_args(chunk, paren_after(chunk, pattern))
            group = _GROUP_ATTR.search(args)
            detail = "group={0}".format(group.group(1)) if group else ""
            for literal in _annotation_topics(args):
                resolved = context.resolve_topic(literal, record, line_no)
                if resolved is not None:
                    context.add_topic_edge(service, resolved, EDGE_CONSUMES,
                                           record, line_no, detail, JVM_NAME)

        if _SEND_TO.search(raw):
            args = balanced_call_args(chunk, paren_after(chunk, _SEND_TO))
            for literal in _annotation_topics(args):
                resolved = context.resolve_topic(literal, record, line_no)
                if resolved is not None:
                    context.add_topic_edge(service, resolved, EDGE_PRODUCES,
                                           record, line_no, "@SendTo", JVM_NAME)

        for pattern in (_TEMPLATE_SEND, _PRODUCER_RECORD):
            match = pattern.search(raw)
            if match is None:
                continue
            if pattern is _TEMPLATE_SEND and not _is_kafka_sender(match.group(1), text):
                continue
            args = split_args(balanced_call_args(chunk, paren_after(chunk, pattern)))
            if not args:
                continue
            resolved = context.resolve_topic(extract_argument(args[0]), record, line_no)
            if resolved is None:
                continue
            # send(topic, key, value) - the middle argument is the message key.
            detail = "key={0}".format(_expression(args[1])) if len(args) >= 3 else ""
            context.add_topic_edge(service, resolved, EDGE_PRODUCES,
                                   record, line_no, detail, JVM_NAME)

        if _JVM_SUBSCRIBE.search(raw):
            args = balanced_call_args(chunk, paren_after(chunk, _JVM_SUBSCRIBE))
            for value in all_string_literals(args):
                resolved = context.resolve_topic(
                    extract_argument('"{0}"'.format(value)), record, line_no)
                if resolved is not None:
                    context.add_topic_edge(service, resolved, EDGE_CONSUMES,
                                           record, line_no, "", JVM_NAME)

        for pattern, direction in ((_STREAMS_SOURCE, EDGE_CONSUMES),
                                   (_STREAMS_SINK, EDGE_PRODUCES)):
            if not pattern.search(raw):
                continue
            args = split_args(balanced_call_args(chunk, paren_after(chunk, pattern)))
            if not args:
                continue
            resolved = context.resolve_topic(extract_argument(args[0]), record, line_no)
            if resolved is not None:
                context.add_topic_edge(service, resolved, direction, record,
                                       line_no, "Kafka Streams", JVM_NAME)


def _annotation_topics(args: str) -> Iterator:
    """Topics from `topics = ...` / `topicPattern = ...`, or positional."""
    for attribute in (_TOPICS_ATTR, _PATTERN_ATTR):
        match = attribute.search(args)
        if match is None:
            continue
        tail = args[match.end():]
        if tail.lstrip().startswith("{"):
            # topics = {"orders.created", "orders.updated"}
            brace = tail.find("{")
            closing = tail.find("}", brace)
            tail = tail[brace + 1:closing if closing > 0 else len(tail)]
        else:
            pieces = split_args(tail)
            tail = pieces[0] if pieces else tail
        literals = all_string_literals(tail)
        if literals:
            for value in literals:
                yield extract_argument('"{0}"'.format(value))
        else:
            argument = extract_argument(tail)
            if argument is not None:
                yield argument
        return
    # @KafkaListener("orders.created") with no named attribute.
    for value in all_string_literals(args):
        yield extract_argument('"{0}"'.format(value))


def _is_kafka_sender(identifier: str, text: str) -> bool:
    lowered = identifier.lower()
    if "kafka" in lowered or "producer" in lowered or "template" in lowered:
        return True
    # `private final KafkaTemplate<String, Order> events;` -> events.send(...)
    return bool(re.search(
        r"Kafka(?:Template|Producer)\s*(?:<[^>]*>)?\s+" + re.escape(identifier) + r"\b",
        text))


def _expression(argument: str) -> str:
    return re.sub(r"\s+", " ", argument.strip().strip("\"'"))[:40]


# --------------------------------------------------------------------------- #
# Python - kafka-python, confluent-kafka, aiokafka, faust
# --------------------------------------------------------------------------- #

PY_NAME = "kafka-python"

_PY_GATE = re.compile(r"\bkafka\b|confluent_kafka|aiokafka|\bfaust\b", re.IGNORECASE)
_PY_CONSUMER_CTOR = re.compile(r"\b(?:AIO)?KafkaConsumer\s*\(")
_PY_SEND = re.compile(r"\b([A-Za-z_]\w*)\s*\.\s*(send|send_and_wait|produce)\s*\(")
_PY_SUBSCRIBE = re.compile(r"\b[A-Za-z_]\w*\s*\.\s*(?:subscribe|assign)\s*\(")
_PY_FAUST_TOPIC = re.compile(r"\b[A-Za-z_]\w*\s*\.\s*topic\s*\(")
_PY_FAUST_AGENT = re.compile(r"@\s*[A-Za-z_]\w*\s*\.\s*agent\s*\(")
_PY_GROUP = re.compile(r"group_id\s*=\s*[\"']([^\"']+)[\"']")
_PY_KEY = re.compile(r"\bkey\s*=\s*([^,)]+)")


def applies_python(record: FileRecord) -> bool:
    return record.suffix == ".py"


def extract_python(context: Context, record: FileRecord) -> None:
    lines = context.scan.read_lines(record)
    text = "\n".join(lines)
    if not _PY_GATE.search(text):
        return
    service = context.owner(record)
    if not service:
        return
    group = _PY_GROUP.search(text)
    group_detail = "group={0}".format(group.group(1)) if group else ""
    faust_topics = {}  # type: dict

    for index, raw_line in enumerate(lines):
        raw = strip_comment(raw_line, ".py")
        line_no = index + 1
        chunk = window(lines, index, 5, ".py")

        if _PY_CONSUMER_CTOR.search(raw):
            args_text = balanced_call_args(chunk, paren_after(chunk, _PY_CONSUMER_CTOR))
            for argument in split_args(args_text):
                if _is_keyword_argument(argument):
                    continue
                resolved = context.resolve_topic(
                    extract_argument(argument), record, line_no)
                if resolved is not None:
                    context.add_topic_edge(service, resolved, EDGE_CONSUMES,
                                           record, line_no, group_detail, PY_NAME)

        match = _PY_SEND.search(raw)
        if match is not None and _is_py_producer(match.group(1), match.group(2), text):
            args_text = balanced_call_args(chunk, paren_after(chunk, _PY_SEND))
            args = split_args(args_text)
            if args:
                resolved = context.resolve_topic(extract_argument(args[0]), record, line_no)
                if resolved is not None:
                    key = _PY_KEY.search(args_text)
                    detail = "key={0}".format(key.group(1).strip()[:40]) if key else ""
                    context.add_topic_edge(service, resolved, EDGE_PRODUCES,
                                           record, line_no, detail, PY_NAME)

        if _PY_SUBSCRIBE.search(raw):
            args_text = balanced_call_args(chunk, paren_after(chunk, _PY_SUBSCRIBE))
            literals = all_string_literals(args_text)
            candidates = ['"{0}"'.format(value) for value in literals] or [args_text]
            for candidate in candidates:
                resolved = context.resolve_topic(
                    extract_argument(candidate), record, line_no)
                if resolved is not None:
                    context.add_topic_edge(service, resolved, EDGE_CONSUMES,
                                           record, line_no, group_detail, PY_NAME)

        if "faust" in text.lower():
            assignment = re.match(r"\s*([A-Za-z_]\w*)\s*=", raw)
            if _PY_FAUST_TOPIC.search(raw) and assignment is not None:
                args = split_args(balanced_call_args(
                    chunk, paren_after(chunk, _PY_FAUST_TOPIC)))
                if args:
                    literal = extract_argument(args[0])
                    if literal is not None:
                        faust_topics[assignment.group(1)] = literal.value
            if _PY_FAUST_AGENT.search(raw):
                args = split_args(balanced_call_args(
                    chunk, paren_after(chunk, _PY_FAUST_AGENT)))
                value = faust_topics.get(args[0].strip()) if args else None
                if value:
                    resolved = context.resolve_topic(
                        extract_argument('"{0}"'.format(value)), record, line_no)
                    if resolved is not None:
                        context.add_topic_edge(service, resolved, EDGE_CONSUMES,
                                               record, line_no, "faust agent", PY_NAME)


def _is_keyword_argument(argument: str) -> bool:
    head = argument.split("(")[0]
    return "=" in head and not argument.strip().startswith(("\"", "'"))


def _is_py_producer(identifier: str, method: str, text: str) -> bool:
    if method == "produce":                     # confluent-kafka only has produce()
        return True
    lowered = identifier.lower()
    if "produc" in lowered or "kafka" in lowered:
        return True
    return bool(re.search(
        r"\b" + re.escape(identifier) + r"\s*=\s*(?:AIO)?KafkaProducer\s*\(", text))


# --------------------------------------------------------------------------- #
# Node - kafkajs, node-rdkafka, NestJS
# --------------------------------------------------------------------------- #

NODE_NAME = "kafka-node"
NODE_SUFFIXES = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")

# A team that wraps kafkajs in its own PubSubService never mentions kafkajs at
# the call site - the file imports `IPubSubService` and nothing else. Gating on
# the vendor name alone silently skips every such repository, so accept the
# vocabulary a wrapper uses too, case-insensitively.
_NODE_GATE = re.compile(
    r"kafkajs|node-rdkafka|kafkaclient|@nestjs/microservices|\bkafka\b"
    r"|pubsub|pub-sub|\bproducer\b|\bconsumer\b|\btopic\b",
    re.IGNORECASE)
_NODE_TOPIC_PROP = re.compile(
    r"\btopic\s*:\s*(?P<value>[\"'`][^\"'`]+[\"'`]|[A-Za-z_$][\w.$\[\]'\"]*)")
_NODE_TOPICS_PROP = re.compile(r"\btopics\s*:\s*\[(?P<value>[^\]]*)\]")
_NODE_SEND = re.compile(r"\b[A-Za-z_$][\w$]*\s*\.\s*(?:send|sendBatch)\s*\(")
_NODE_SUBSCRIBE = re.compile(r"\b[A-Za-z_$][\w$]*\s*\.\s*subscribe\s*\(")
_NODE_EMIT = re.compile(r"\b[A-Za-z_$][\w$]*\s*\.\s*(?:emit|publish)\s*\(\s*(?P<first>[^,)]+)")
_NODE_PATTERN = re.compile(r"@(?:MessagePattern|EventPattern)\s*\(\s*(?P<first>[^)]+)\)")
_NODE_GROUP = re.compile(r"groupId\s*:\s*[\"'`]([^\"'`]+)[\"'`]")
_NODE_KEY = re.compile(r"\bkey\s*:\s*([^,}\n]+)")


# `const refundTopic = this.configService.get<string>(INFRA.KAFKA.TOPICS.X)`
# `private readonly refundTopic = configService.get("X")`
# `const refundTopic = "orders.created"`
_NODE_TOPIC_CONST = re.compile(
    r"(?:const|let|var|readonly)\s+(?P<name>[A-Za-z_$][\w$]*)"
    r"\s*(?::\s*[\w<>\[\]|\s]+?)?\s*=\s*(?P<value>[^;]{0,300})",
    re.DOTALL)
_CONFIG_GET = re.compile(
    r"(?:configService|config|conf)\s*\.\s*get(?:OrThrow)?\s*(?:<[^>]*>)?\s*\("
    r"\s*(?P<key>[^,)]+)", re.DOTALL)


def _node_topic_constants(lines: List[str]) -> dict:
    """symbol -> the literal or config key it resolves to, within one file.

    Topic names in a wrapped-client codebase are almost never literal at the
    call site; they are a `const` two screens up that reads a config key. The
    HTTP extractor already resolves base URLs this way - Kafka needs the same,
    or every such binding degrades to an unresolved inference.

    Scans the joined text rather than line by line: a prettier-formatted
    declaration puts the name, the getter and the key on three separate lines,
    and a per-line scan sees only `= this.configService.get<string>(`.
    """
    table = {}  # type: dict
    text = "\n".join(lines)
    for match in _NODE_TOPIC_CONST.finditer(text):
        name = match.group("name")
        if name in table:
            continue
        # Everything up to the statement terminator, newlines included.
        value = match.group("value")
        literal = _LITERAL_VALUE.match(value.strip())
        if literal is not None:
            table[name] = literal.group("value")
            continue
        getter = _CONFIG_GET.search(value)
        if getter is not None:
            # `INFRA.KAFKA.TOPICS.REFUND_REQUEST_TOPIC` -> the last segment is
            # the key the config index will actually have.
            key = getter.group("key").strip().strip("\"'`").strip()
            table[name] = key.rsplit(".", 1)[-1]
            continue
        env = _ENV_VALUE.search(value)
        if env is not None:
            table[name] = env.group("key")
    return table


_LITERAL_VALUE = re.compile(r"^[\"'`](?P<value>[^\"'`]+)[\"'`]")
_ENV_VALUE = re.compile(r"process\.env\.(?P<key>[A-Za-z_]\w*)")


def applies_node(record: FileRecord) -> bool:
    return record.suffix in NODE_SUFFIXES


def extract_node(context: Context, record: FileRecord) -> None:
    lines = context.scan.read_lines(record)
    text = "\n".join(lines)
    if not _NODE_GATE.search(text):
        return
    service = context.owner(record)
    if not service:
        return
    group = _NODE_GROUP.search(text)
    group_detail = "group={0}".format(group.group(1)) if group else ""
    constants = _node_topic_constants(lines)

    for index, raw_line in enumerate(lines):
        raw = strip_comment(raw_line, record.suffix)
        line_no = index + 1
        chunk = window(lines, index, 6, record.suffix)

        direction, pattern = None, None
        if _NODE_SEND.search(raw):
            direction, pattern = EDGE_PRODUCES, _NODE_SEND
        elif _NODE_SUBSCRIBE.search(raw):
            direction, pattern = EDGE_CONSUMES, _NODE_SUBSCRIBE

        if direction is not None:
            args = balanced_call_args(chunk, paren_after(chunk, pattern))
            detail = group_detail if direction == EDGE_CONSUMES else _node_key(args)
            for value in _node_topics(args):
                resolved = _resolve_node_topic(context, value, constants,
                                               record, line_no)
                if resolved is not None:
                    context.add_topic_edge(service, resolved, direction,
                                           record, line_no, detail, NODE_NAME)

        if "microservices" in text:
            emit = _NODE_EMIT.search(raw)
            if emit is not None:
                resolved = context.resolve_topic(
                    extract_argument(emit.group("first")), record, line_no)
                if resolved is not None:
                    context.add_topic_edge(service, resolved, EDGE_PRODUCES,
                                           record, line_no, "nest emit", NODE_NAME)
        pattern_match = _NODE_PATTERN.search(raw)
        if pattern_match is not None:
            resolved = context.resolve_topic(
                extract_argument(pattern_match.group("first")), record, line_no)
            if resolved is not None:
                context.add_topic_edge(service, resolved, EDGE_CONSUMES,
                                       record, line_no, "nest pattern", NODE_NAME)


def _resolve_node_topic(context: Context, value: str, constants: dict,
                        record: FileRecord, line_no: int):
    """Resolve a topic argument, following a file-local constant if it is one."""
    bare = value.strip().strip("\"'`")
    target = constants.get(bare, value)
    resolved = context.resolve_topic(extract_argument(target), record, line_no)
    if resolved is not None and resolved.tag == CODE and bare in constants:
        resolved.note = (resolved.note or
                         "topic name read via the file-local constant `{0}`".format(bare))
    return resolved


def _node_topics(args: str) -> List[str]:
    found = [match.group("value") for match in _NODE_TOPIC_PROP.finditer(args)]
    for match in _NODE_TOPICS_PROP.finditer(args):
        found.extend(part.strip() for part in match.group("value").split(",") if part.strip())
    if not found:
        stripped = args.strip()
        if stripped[:1] in "\"'`":
            found.append(stripped)
    return found


def _node_key(args: str) -> str:
    match = _NODE_KEY.search(args)
    if match is None:
        return ""
    value = match.group(1).strip().strip("\"'`")[:40]
    return "key={0}".format(value) if value else ""


# --------------------------------------------------------------------------- #
# Go - segmentio/kafka-go, sarama
# --------------------------------------------------------------------------- #

GO_NAME = "kafka-go"

_GO_GATE = re.compile(
    r"segmentio/kafka-go|Shopify/sarama|IBM/sarama|confluent-kafka-go|\bsarama\b|\bkafka\b")
# The brace must hug the type name: `*kafka.Writer {` is a function's return
# type, not a composite literal, and matching it invents a topic-less producer.
_GO_WRITER = re.compile(r"kafka\.(?:NewWriter\s*\(|WriterConfig\s*\{|Writer\{)")
_GO_READER = re.compile(r"kafka\.(?:NewReader\s*\(|ReaderConfig\s*\{|Reader\{)")
_GO_MESSAGE = re.compile(r"kafka\.Message\s*\{")
_GO_SARAMA_MSG = re.compile(r"sarama\.ProducerMessage\s*\{")
_GO_CONSUME = re.compile(r"\.\s*(?:Consume|ConsumePartition)\s*\(")
_GO_TOPIC_FIELD = re.compile(r"\bTopic\s*:\s*(?P<value>\"[^\"]*\"|`[^`]*`|[A-Za-z_][\w.]*)")
_GO_TOPICS_FIELD = re.compile(r"\bTopics?\s*:\s*\[\]string\{(?P<value>[^}]*)\}")
_GO_GROUP_FIELD = re.compile(r"\bGroupID\s*:\s*\"([^\"]+)\"")
_GO_KEY_FIELD = re.compile(r"\bKey\s*:\s*([^,}\n]+)")
_GO_STRING_SLICE = re.compile(r"\[\]string\{(?P<value>[^}]*)\}")


def applies_go(record: FileRecord) -> bool:
    return record.suffix == ".go"


def extract_go(context: Context, record: FileRecord) -> None:
    lines = context.scan.read_lines(record)
    text = "\n".join(lines)
    if not _GO_GATE.search(text):
        return
    service = context.owner(record)
    if not service:
        return

    for index, raw_line in enumerate(lines):
        raw = strip_comment(raw_line, ".go")
        line_no = index + 1
        chunk = window(lines, index, 8, ".go")

        producer = (_GO_WRITER.search(raw) or _GO_MESSAGE.search(raw)
                    or _GO_SARAMA_MSG.search(raw))
        consumer = _GO_READER.search(raw)
        anchor = producer or consumer
        if anchor is not None:
            direction = EDGE_PRODUCES if producer is not None else EDGE_CONSUMES
            body = _go_struct_body(chunk, anchor.start())
            group = _GO_GROUP_FIELD.search(body)
            if group is not None:
                detail = "group={0}".format(group.group(1))
            elif producer is not None:
                detail = _go_key(body)
            else:
                detail = ""
            for value in _go_topics(body):
                resolved = context.resolve_topic(extract_argument(value), record, line_no)
                if resolved is not None:
                    context.add_topic_edge(service, resolved, direction,
                                           record, line_no, detail, GO_NAME)

        if _GO_CONSUME.search(raw):
            args = balanced_call_args(chunk, paren_after(chunk, _GO_CONSUME))
            values = []  # type: List[str]
            slice_match = _GO_STRING_SLICE.search(args)
            if slice_match is not None:
                values = [part.strip() for part in slice_match.group("value").split(",")
                          if part.strip()]
            elif '"' in args:
                values = [split_args(args)[0]] if split_args(args) else []
            for value in values:
                resolved = context.resolve_topic(extract_argument(value), record, line_no)
                if resolved is not None:
                    context.add_topic_edge(service, resolved, EDGE_CONSUMES,
                                           record, line_no, "", GO_NAME)


def _go_struct_body(chunk: str, start: int) -> str:
    brace = chunk.find("{", start)
    if brace < 0:
        return balanced_call_args(chunk, chunk.find("(", start))
    depth = 0
    for index in range(brace, len(chunk)):
        if chunk[index] == "{":
            depth += 1
        elif chunk[index] == "}":
            depth -= 1
            if depth == 0:
                return chunk[brace + 1:index]
    return chunk[brace + 1:]


def _go_topics(body: str) -> List[str]:
    values = [match.group("value") for match in _GO_TOPIC_FIELD.finditer(body)]
    for match in _GO_TOPICS_FIELD.finditer(body):
        values.extend(part.strip() for part in match.group("value").split(",")
                      if part.strip())
    return values


def _go_key(body: str) -> str:
    match = _GO_KEY_FIELD.search(body)
    if match is None:
        return ""
    value = match.group(1).strip()
    # `Key: []byte(orderID)` - the conversion is noise on a diagram label.
    value = re.sub(r"^\[\]byte\((.*)\)$", r"\1", value)
    value = value.strip().strip("\"'`")[:40]
    return "key={0}".format(value) if value else ""


# --------------------------------------------------------------------------- #
# Config - Spring Cloud Stream, Terraform, docker-compose
# --------------------------------------------------------------------------- #

CONFIG_NAME = "config"

_BINDING = re.compile(
    r"^spring\.cloud\.stream\.bindings\.(?P<binding>[^.]+)\.destination$", re.IGNORECASE)
_DEFAULT_TOPIC = re.compile(
    r"^(?:spring\.kafka\.template\.default-topic|kafka\.default-?topic)$", re.IGNORECASE)
_OUTPUT_BINDING = re.compile(r"(^|[-_.])(out|output|producer|supplier|source)([-_.\d]|$)", re.I)
_INPUT_BINDING = re.compile(r"(^|[-_.])(in|input|consumer|sink|listener)([-_.\d]|$)", re.I)

_COMPOSE_PREFIXES = ("docker-compose", "compose.yml", "compose.yaml")
_KIND_FOR_IMAGE = {
    "datastore": KIND_DATASTORE,
    "cache": KIND_CACHE,
    "external_api": KIND_EXTERNAL_API,
}
_PROTOCOL_FOR_IMAGE = {"datastore": "sql", "cache": "cache", "external_api": "http"}


def applies_config(record: FileRecord) -> bool:
    return (record.suffix in (".yml", ".yaml", ".properties", ".tf", ".tfvars")
            or record.name.startswith(("application.", "bootstrap.")))


def extract_config(context: Context, record: FileRecord) -> None:
    lower = record.name.lower()
    if lower.startswith(_COMPOSE_PREFIXES):
        _compose(context, record)
    if record.suffix in (".tf", ".tfvars"):
        _terraform_topics(context, record)
        return
    _stream_bindings(context, record)


def _flat_config(context: Context, record: FileRecord) -> dict:
    text = context.scan.read_text(record)
    if record.suffix == ".properties":
        return parse_properties(text)
    flat = {}  # type: dict
    for document in parse_yaml_documents(text):
        if isinstance(document, (dict, list)):
            flat.update(flatten(document))
    return flat


def _stream_bindings(context: Context, record: FileRecord) -> None:
    flat = _flat_config(context, record)
    if not flat:
        return
    lines = context.scan.read_lines(record)
    service = context.owner(record)
    if not service:
        return

    for key in sorted(flat):
        value = flat[key]
        binding = _BINDING.match(key)
        if binding is not None:
            name = binding.group("binding")
            if _OUTPUT_BINDING.search(name):
                direction = EDGE_PRODUCES
            elif _INPUT_BINDING.search(name):
                direction = EDGE_CONSUMES
            else:
                continue  # an ambiguous binding name is not worth guessing at
            group = flat.get(key.rsplit(".", 1)[0] + ".group", "")
            detail = "binding {0}".format(name)
            if group:
                detail += ", group={0}".format(group)
            context.add_topic_edge(
                service, ResolvedTopic(topic_id(value), value, CODE), direction,
                record, line_of(lines, str(value)), detail, CONFIG_NAME)
        elif _DEFAULT_TOPIC.match(key):
            context.add_topic_edge(
                service, ResolvedTopic(topic_id(value), value, CODE), EDGE_PRODUCES,
                record, line_of(lines, str(value)), "default-topic", CONFIG_NAME)


def _terraform_topics(context: Context, record: FileRecord) -> None:
    """A topic declared in Terraform but not yet referenced by any code.

    It belongs on the master topology - an unconsumed topic is a finding, not
    an omission - so the node is created even though no edge touches it.
    """
    text = context.scan.read_text(record)
    lines = context.scan.read_lines(record)
    for topic, resource_type in parse_terraform_topics(text):
        context.model.add_node(Node(
            id=topic_id(topic),
            kind=KIND_TOPIC,
            label=topic,
            source_evidence=("{0}:{1}".format(record.rel, line_of(lines, topic)),),
            attributes=(("declared_in", resource_type),),
        ))


def _compose(context: Context, record: FileRecord) -> None:
    text = context.scan.read_text(record)
    lines = context.scan.read_lines(record)
    for document in parse_yaml_documents(text):
        if not isinstance(document, dict):
            continue
        services = document.get("services")
        if not isinstance(services, dict):
            continue
        for raw_name in sorted(services):
            spec = services[raw_name]
            if not isinstance(spec, dict):
                continue
            caller = _compose_service_id(context, str(raw_name))
            # Only draw from containers we can tie back to code in this repo.
            if caller not in context.scan.services:
                continue
            line = line_of(lines, str(raw_name))
            depends = spec.get("depends_on")
            if isinstance(depends, list):
                targets = [str(item) for item in depends if isinstance(item, str)]
            elif isinstance(depends, dict):
                targets = [str(key) for key in depends]
            else:
                continue
            for target in sorted(targets):
                _compose_edge(context, caller, target, record, line)


def _compose_edge(context: Context, caller: str, target: str,
                  record: FileRecord, line: int) -> None:
    slug = slugify(target, keep_dots=False)
    infrastructure = context.scan.config.compose_systems.get(slug)
    if infrastructure is not None:
        kind, label, _source = infrastructure
        if kind == "broker":
            return  # the broker is drawn as its topics, not as a box
        context.add_call(
            caller=caller, target_id=slug, target_kind=_KIND_FOR_IMAGE[kind],
            target_label=label, protocol=_PROTOCOL_FOR_IMAGE.get(kind, ""),
            method="", record=record, line=line, tag=CODE,
            detail="", extractor=CONFIG_NAME)
        return
    target_id = _compose_service_id(context, target)
    if target_id in context.scan.services:
        context.add_call(
            caller=caller, target_id=target_id, target_kind="service",
            target_label=target, protocol="", method="", record=record,
            line=line, tag=CODE, detail="depends_on", extractor=CONFIG_NAME)


def _compose_service_id(context: Context, name: str) -> str:
    slug = slugify(name, keep_dots=False)
    if slug in context.scan.services:
        return slug
    mapped = context.scan.config.host_to_service(name)
    return mapped[0] if mapped is not None else slug
