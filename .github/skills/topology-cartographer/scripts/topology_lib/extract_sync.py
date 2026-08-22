"""Synchronous calls and external systems.

    OpenAPI      the declared, provider side of a REST API
    gRPC         .proto services, server registrations, generated-stub usage
    HTTP         requests/httpx, axios/fetch, RestTemplate/WebClient/Feign,
                 net/http, resty
    Datastores   connection strings, drawn as leaf nodes

The resolution ladder for an HTTP call, best evidence first:

    1. literal URL whose host is a service we found       -> [CODE]
    2. symbol -> config or env value -> host              -> [CODE]
    3. path only, matched against an OpenAPI spec         -> [INFERENCE]
    4. anything else                                       -> dropped

Step 4 is the important one. A call we cannot resolve is left out of the
diagram entirely rather than drawn against a guessed target.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from .configindex import parse_yaml, parse_yaml_documents
from .discovery import FileRecord
from .extract import Context, known_host
from .model import (
    CODE,
    INFERENCE,
    KIND_CACHE,
    KIND_DATASTORE,
    KIND_EXTERNAL_API,
    KIND_SERVICE,
    Node,
)
from .textutil import (
    balanced_call_args,
    line_of,
    paren_after,
    slugify,
    split_args,
    strip_comment,
    window,
)

# --------------------------------------------------------------------------- #
# OpenAPI - phase 1
# --------------------------------------------------------------------------- #

OPENAPI_NAME = "openapi"

_OPENAPI_GATE = re.compile(r"^\s*[\"']?(?:openapi|swagger)[\"']?\s*:", re.MULTILINE)
_HTTP_METHODS = ("get", "put", "post", "delete", "patch", "head", "options", "trace")


def applies_openapi(record: FileRecord) -> bool:
    return record.suffix in (".yml", ".yaml", ".json")


def extract_openapi(context: Context, record: FileRecord) -> None:
    """Register the paths a service serves. A spec never creates an edge itself."""
    text = context.scan.read_text(record)
    if not _OPENAPI_GATE.search(text):
        return
    try:
        document = json.loads(text) if record.suffix == ".json" else parse_yaml(text)
    except (ValueError, TypeError):
        return
    if not isinstance(document, dict):
        return
    if not (document.get("openapi") or document.get("swagger")):
        return
    paths = document.get("paths")
    if not isinstance(paths, dict):
        return

    lines = context.scan.read_lines(record)
    service = context.owner(record)
    entries = []  # type: List[Tuple[str, str, str]]

    for path in sorted(paths):
        operations = paths[path]
        source = "{0}:{1}".format(record.rel, line_of(lines, str(path)))
        methods = sorted(
            str(key).upper() for key in (operations if isinstance(operations, dict) else {})
            if str(key).lower() in _HTTP_METHODS
        )
        for method in methods or [""]:
            entries.append((str(path), source, method))

    if not entries:
        return
    known = context.api_paths.setdefault(service, [])
    known.extend(entries)
    context.api_paths[service] = sorted(set(known))

    context.ensure_service(service)
    context.model.add_node(Node(
        id=service, kind=KIND_SERVICE, label="",
        source_evidence=("{0}:1".format(record.rel),),
        attributes=(("openapi", record.rel), ("api_operations", str(len(entries)))),
    ))

    # `servers: [{url: http://orders-svc:8080}]` makes that host an alias.
    for server in document.get("servers") or []:
        url = server.get("url") if isinstance(server, dict) else None
        if not url:
            continue
        host = re.sub(r"^[a-z]+://", "", str(url)).split("/")[0].split(":")[0]
        if host and host not in ("localhost", "127.0.0.1"):
            context.config.register_service_host(
                host, service, "{0}:{1}".format(record.rel, line_of(lines, str(url))))

    info = document.get("info")
    if isinstance(info, dict) and info.get("title"):
        context.config.register_service_host(
            slugify(str(info["title"]), keep_dots=False), service,
            "{0}:1".format(record.rel))


# --------------------------------------------------------------------------- #
# gRPC
# --------------------------------------------------------------------------- #

GRPC_NAME = "grpc"
GRPC_SUFFIXES = (".go", ".py", ".java", ".kt", ".ts", ".js", ".cs", ".rb")

_PROTO_SERVICE = re.compile(r"^\s*service\s+([A-Za-z_]\w*)\s*\{", re.MULTILINE)
_PROTO_RPC = re.compile(r"^\s*rpc\s+([A-Za-z_]\w*)\s*\(", re.MULTILINE)

_REGISTRATIONS = (
    re.compile(r"\bRegister([A-Za-z_]\w*?)Server\s*\("),                 # Go
    re.compile(r"\badd_([A-Za-z_]\w*?)Servicer_to_server\s*\("),         # Python
    re.compile(r"\bextends\s+([A-Za-z_]\w*?)Grpc\."),                    # Java
    re.compile(r"\b([A-Za-z_]\w*?)Grpc\s*\.\s*\w*ImplBase\b"),           # Java
)

_STUBS = (
    re.compile(r"\b(?:[\w.]*?)New([A-Za-z_]\w*?)Client\s*\("),           # Go
    re.compile(r"\b(?:[\w.]*?)([A-Za-z_]\w*?)Stub\s*\("),                # Python
    re.compile(r"\b([A-Za-z_]\w*?)Grpc\s*\.\s*new\w*Stub\s*\("),         # Java
    re.compile(r"\bnew\s+[\w.]*?([A-Za-z_]\w*?)Client\s*\("),            # C#, Node
)

_NOT_A_SERVICE = frozenset(("http", "grpc", "kafka", "redis", "api", "web", "db"))


def applies_grpc(record: FileRecord) -> bool:
    return record.suffix == ".proto" or record.suffix in GRPC_SUFFIXES


def extract_grpc_providers(context: Context, record: FileRecord) -> None:
    """Phase 1: read .proto declarations and server registrations."""
    if record.suffix == ".proto":
        _read_proto(context, record)
    else:
        _read_registrations(context, record)


def _read_proto(context: Context, record: FileRecord) -> None:
    text = context.scan.read_text(record)
    owner = context.owner(record)
    for match in _PROTO_SERVICE.finditer(text):
        name = match.group(1)
        body = _brace_block(text, match.end() - 1)
        methods = tuple(sorted(set(rpc.group(1) for rpc in _PROTO_RPC.finditer(body))))
        line = text[:match.start()].count("\n") + 1
        key = name.lower()
        existing = context.grpc_services.get(key)
        # A .proto proves the contract exists; it does not prove who serves it.
        # The owner stays provisional until a server registration confirms it.
        if existing is not None and key in context.grpc_impl_source:
            continue
        context.grpc_services[key] = (
            owner, "{0}:{1}".format(record.rel, line), methods)


def _read_registrations(context: Context, record: FileRecord) -> None:
    text = context.scan.read_text(record)
    if "grpc" not in text.lower() and "Grpc" not in text:
        return
    owner = context.owner(record)
    for index, raw in enumerate(context.scan.read_lines(record)):
        line = strip_comment(raw, record.suffix)
        for pattern in _REGISTRATIONS:
            match = pattern.search(line)
            if match is None:
                continue
            key = match.group(1).lower()
            if not key or key in _NOT_A_SERVICE:
                continue
            source = "{0}:{1}".format(record.rel, index + 1)
            known = context.grpc_services.get(key)
            methods = known[2] if known is not None else ()
            proto_source = known[1] if known is not None else source
            # A confirmed implementer overrides the provisional .proto owner.
            context.grpc_services[key] = (owner, proto_source, methods)
            context.grpc_impl_source[key] = source


def extract_grpc_clients(context: Context, record: FileRecord) -> None:
    """Phase 2: generated-stub usage becomes a call edge."""
    if record.suffix not in GRPC_SUFFIXES:
        return
    text = context.scan.read_text(record)
    if "grpc" not in text.lower() and "Grpc" not in text and "_pb2" not in text:
        return
    caller = context.owner(record)
    lines = context.scan.read_lines(record)

    for index, raw in enumerate(lines):
        line = strip_comment(raw, record.suffix)
        for pattern in _STUBS:
            match = pattern.search(line)
            if match is None:
                continue
            name = match.group(1)
            if not name or name.lower() in _NOT_A_SERVICE:
                continue
            key = name.lower()
            declaration = context.grpc_services.get(key)

            if declaration is not None and declaration[0] == caller:
                continue  # our own generated server code, not a call out
            if declaration is not None:
                target, proto_source, methods = declaration
                if key in context.grpc_impl_source:
                    tag, note = CODE, ""
                else:
                    tag = INFERENCE
                    note = ("`{0}` is declared in {1} but no server registration was "
                            "found; the target service is inferred from where the "
                            ".proto lives".format(name, proto_source))
                _emit_grpc(context, caller, target, name, methods,
                           record, index + 1, tag, note, lines)
            else:
                _emit_grpc(
                    context, caller, slugify(_strip_service_suffix(name), keep_dots=False),
                    name, (), record, index + 1, INFERENCE,
                    "a generated gRPC client stub for `{0}` is used here, but no "
                    ".proto declaring that service was found in scope".format(name),
                    lines)


def _emit_grpc(context: Context, caller: str, target: str, service_name: str,
               methods: Tuple[str, ...], record: FileRecord, line: int,
               tag: str, note: str, lines: List[str]) -> None:
    called = _called_methods(lines, methods)
    for method in (called or [""])[:8]:
        context.add_call(
            caller=caller, target_id=target, target_kind=KIND_SERVICE,
            target_label=_strip_service_suffix(service_name), protocol="grpc",
            method=method or service_name, record=record, line=line, tag=tag,
            note=note, detail=service_name if method else "", extractor=GRPC_NAME)


def _called_methods(lines: List[str], methods: Tuple[str, ...]) -> List[str]:
    if not methods:
        return []
    text = "\n".join(lines)
    found = []  # type: List[str]
    for method in methods:
        snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", method).lower()
        if (re.search(r"\.\s*" + re.escape(method) + r"\s*\(", text)
                or re.search(r"\.\s*" + re.escape(snake) + r"\s*\(", text)):
            found.append(method)
    return sorted(found)


def _strip_service_suffix(name: str) -> str:
    return re.sub(r"(?:Service|Svc)$", "", name) or name


def _brace_block(text: str, brace_index: int) -> str:
    depth = 0
    for index in range(brace_index, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[brace_index:index]
    return text[brace_index:]


# --------------------------------------------------------------------------- #
# HTTP clients
# --------------------------------------------------------------------------- #

HTTP_NAME = "http-client"
HTTP_SUFFIXES = (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
                 ".java", ".kt", ".go", ".rb", ".cs")

_VERBS = "get|post|put|patch|delete|head|options"

_PY_CALL = re.compile(
    r"\b(?:requests|httpx|session|client|http|aiohttp)\w*\s*\.\s*"
    r"(?P<verb>" + _VERBS + r"|request)\s*\(", re.IGNORECASE)
_JS_AXIOS = re.compile(r"\baxios\s*\.\s*(?P<verb>" + _VERBS + r")\s*\(", re.IGNORECASE)
_JS_AXIOS_CONFIG = re.compile(r"\baxios\s*\(")
_JS_FETCH = re.compile(r"\bfetch\s*\(")
_JS_LIB = re.compile(
    r"\b(?:got|superagent|ky)\s*\.\s*(?P<verb>" + _VERBS + r")\s*\(", re.IGNORECASE)
_JAVA_REST = re.compile(
    r"\b\w*[Rr]estTemplate\s*\.\s*(?P<op>getForObject|getForEntity|postForObject"
    r"|postForEntity|put|delete|patchForObject|exchange)\s*\(")
_JAVA_WEBCLIENT = re.compile(
    r"\b\w*[Ww]ebClient\s*\.\s*(?P<verb>" + _VERBS + r")\s*\(\s*\)\s*\.\s*uri\s*\(")
_JAVA_OKHTTP = re.compile(r"\bnew\s+Request\.Builder\s*\(\s*\)\s*\.\s*url\s*\(")
_GO_HTTP = re.compile(r"\b(?:http|client|c)\s*\.\s*(?P<verb>Get|Post|Head|PostForm)\s*\(")
_GO_NEW_REQUEST = re.compile(r"\bhttp\.NewRequest(?:WithContext)?\s*\(")
_GO_RESTY = re.compile(r"\.\s*R\s*\(\s*\)[^\n]*?\.\s*(?P<verb>Get|Post|Put|Delete|Patch)\s*\(")

_FEIGN = re.compile(r"@FeignClient\s*\(")
_SPRING_MAPPING = re.compile(
    r"@(?P<verb>Get|Post|Put|Delete|Patch|Request)Mapping\s*\(\s*(?P<args>[^)]*)\)")
_ANNOTATION_PATH = re.compile(r"(?:value|path)\s*=\s*[\"']([^\"']+)[\"']")

_ASSIGNMENT = re.compile(
    r"(?:const|let|var|final|String|static)?\s*(?P<name>[A-Za-z_$][\w$]*)\s*(?::\s*\w+)?"
    r"\s*[:=]\s*(?P<value>[\"'`][^\"'`]*[\"'`]|os\.environ[^\n]*|os\.getenv[^\n]*"
    r"|process\.env[^\n;,]*|os\.Getenv[^\n]*)")
_VALUE_ANNOTATION = re.compile(
    r"@Value\s*\(\s*[\"']\$\{(?P<key>[^:}]+)(?::(?P<default>[^}]*))?\}[\"']\s*\)\s*"
    r"(?:private|public|protected)?\s*(?:final\s+)?String\s+(?P<name>\w+)")
_ENV_LOOKUP = re.compile(
    r"(?:os\.environ(?:\.get)?\s*[\[(]\s*|os\.getenv\s*\(\s*|process\.env\.|"
    r"process\.env\[\s*|os\.Getenv\s*\(\s*|System\.getenv\s*\(\s*)"
    r"[\"']?(?P<key>[A-Za-z_]\w*)[\"']?")
_LITERAL = re.compile(r"[\"'`](?P<value>[^\"'`]*)[\"'`]")
_HAS_SCHEME = re.compile(r"https?://", re.IGNORECASE)

_SKIP_HOSTS = frozenset((
    "localhost", "127.0.0.1", "0.0.0.0", "::1", "host.docker.internal",
    "example.com", "www.example.com", "test",
))


def applies_http(record: FileRecord) -> bool:
    return record.suffix in HTTP_SUFFIXES


def extract_http(context: Context, record: FileRecord) -> None:
    service = context.owner(record)
    if not service:
        return
    lines = context.scan.read_lines(record)
    symbols = _symbol_table(lines)

    _feign_clients(context, record, lines, service)

    for index, raw_line in enumerate(lines):
        raw = strip_comment(raw_line, record.suffix)
        line_no = index + 1
        chunk = window(lines, index, 4, record.suffix)

        for verb, expression in _call_sites(raw, chunk, record.suffix):
            if not expression:
                continue
            target = _resolve_target(context, expression, symbols)
            if target is None:
                continue
            target_id, kind, label, tag, note, path = target
            method = "{0} {1}".format(verb, path).strip() if path else verb
            context.add_call(
                caller=service, target_id=target_id, target_kind=kind,
                target_label=label, protocol="http", method=method,
                record=record, line=line_no, tag=tag, note=note,
                extractor=HTTP_NAME)


def _call_sites(raw: str, chunk: str, suffix: str) -> List[Tuple[str, str]]:
    """-> [(verb, url expression)] for every HTTP call anchored on this line."""
    found = []  # type: List[Tuple[str, str]]

    def args_of(pattern) -> List[str]:
        return split_args(balanced_call_args(chunk, paren_after(chunk, pattern)))

    if suffix == ".py":
        match = _PY_CALL.search(raw)
        if match is not None:
            args = args_of(_PY_CALL)
            verb = match.group("verb").upper()
            if verb == "REQUEST" and len(args) >= 2:
                found.append((_literal_or(args[0], "REQUEST"), args[1]))
            elif args:
                found.append((verb, args[0]))

    elif suffix in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"):
        for pattern in (_JS_AXIOS, _JS_LIB):
            match = pattern.search(raw)
            if match is not None:
                args = args_of(pattern)
                if args:
                    found.append((match.group("verb").upper(), args[0]))
        if _JS_FETCH.search(raw):
            args = args_of(_JS_FETCH)
            if args:
                verb = "GET"
                if len(args) > 1:
                    method = re.search(r"method\s*:\s*[\"'`](\w+)[\"'`]", args[1])
                    if method is not None:
                        verb = method.group(1).upper()
                found.append((verb, args[0]))
        if _JS_AXIOS_CONFIG.search(raw) and _JS_AXIOS.search(raw) is None:
            body = balanced_call_args(chunk, paren_after(chunk, _JS_AXIOS_CONFIG))
            url = re.search(r"\burl\s*:\s*(?P<value>[\"'`][^\"'`]*[\"'`]|[\w.$\[\]'\"+ ]+)", body)
            if url is not None:
                method = re.search(r"method\s*:\s*[\"'`](\w+)[\"'`]", body)
                found.append((method.group(1).upper() if method else "GET",
                              url.group("value")))

    elif suffix in (".java", ".kt"):
        match = _JAVA_REST.search(raw)
        if match is not None:
            args = args_of(_JAVA_REST)
            if args:
                found.append((_java_verb(match.group("op"), args), args[0]))
        match = _JAVA_WEBCLIENT.search(raw)
        if match is not None:
            uri_at = chunk.find("uri(", match.start())
            if uri_at >= 0:
                args = split_args(balanced_call_args(chunk, chunk.find("(", uri_at)))
                if args:
                    found.append((match.group("verb").upper(), args[0]))
        if _JAVA_OKHTTP.search(raw):
            args = args_of(_JAVA_OKHTTP)
            if args:
                found.append(("GET", args[0]))

    elif suffix == ".go":
        match = _GO_HTTP.search(raw)
        if match is not None:
            args = args_of(_GO_HTTP)
            if args:
                verb = match.group("verb").upper().replace("POSTFORM", "POST")
                found.append((verb, args[0]))
        if _GO_NEW_REQUEST.search(raw):
            args = args_of(_GO_NEW_REQUEST)
            # NewRequest(method, url, body) | NewRequestWithContext(ctx, method, url, body)
            if len(args) >= 3 and args[0].startswith(("ctx", "context")):
                found.append((_literal_or(args[1], "GET"), args[2]))
            elif len(args) >= 2:
                found.append((_literal_or(args[0], "GET"), args[1]))
        match = _GO_RESTY.search(raw)
        if match is not None:
            args = args_of(_GO_RESTY)
            if args:
                found.append((match.group("verb").upper(), args[0]))

    return found


def _java_verb(operation: str, args: List[str]) -> str:
    for prefix, verb in (("get", "GET"), ("post", "POST"), ("put", "PUT"),
                         ("delete", "DELETE"), ("patch", "PATCH")):
        if operation.startswith(prefix):
            return verb
    if operation == "exchange" and len(args) >= 2:
        match = re.search(r"HttpMethod\.(\w+)", args[1])
        if match is not None:
            return match.group(1).upper()
    return "HTTP"


def _literal_or(expression: str, fallback: str) -> str:
    match = _LITERAL.search(expression)
    return match.group("value").upper() if match is not None else fallback


# -- symbol table and resolution -------------------------------------------- #

def _symbol_table(lines: List[str]) -> Dict[str, str]:
    """symbol -> URL or environment key. File-local only, deliberately."""
    table = {}  # type: Dict[str, str]
    for line in lines:
        annotation = _VALUE_ANNOTATION.search(line)
        if annotation is not None:
            table.setdefault(annotation.group("name"),
                             annotation.group("default") or annotation.group("key"))
            continue
        match = _ASSIGNMENT.search(line)
        if match is None:
            continue
        name, value = match.group("name"), match.group("value").strip()
        if name in table:
            continue
        literal = _LITERAL.match(value)
        if literal is not None:
            table[name] = literal.group("value")
        else:
            env = _ENV_LOOKUP.search(value)
            if env is not None:
                table[name] = env.group("key")
    return table


def _resolve_target(context: Context, expression: str, symbols: Dict[str, str]
                    ) -> Optional[Tuple[str, str, str, str, str, str]]:
    """-> (target id, node kind, label, evidence tag, note, path) or None."""
    url, notes = _expand(context, expression, symbols)
    if not url:
        return None

    if url.startswith("{id}"):
        return None
    if _HAS_SCHEME.search(url):
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        path = parts.path or ""
    else:
        host, path = "", url if url.startswith("/") else ""

    if host and host not in _SKIP_HOSTS:
        note = "; ".join(notes)
        known = known_host(context, host)
        if known is not None:
            return known[0], KIND_SERVICE, known[0], CODE, note, _clean_path(path)
        if "." in host:
            # A real external domain, read as a literal - the identity is certain.
            return (_external_id(host), KIND_EXTERNAL_API, host, CODE, note,
                    _clean_path(path))
        return (_external_id(host), KIND_EXTERNAL_API, host, INFERENCE,
                "; ".join(notes + ["host `{0}` did not match any service found in "
                                   "this repository".format(host)]),
                _clean_path(path))

    if path:
        match = _match_openapi(context, path)
        if match is not None:
            service_id, spec_source, spec_path = match
            return (service_id, KIND_SERVICE, service_id, INFERENCE,
                    "path `{0}` matches `{1}` declared in {2}; no base URL was "
                    "resolvable at the call site".format(
                        _clean_path(path), spec_path, spec_source),
                    _clean_path(path))
    return None


def _expand(context: Context, expression: str, symbols: Dict[str, str]
            ) -> Tuple[str, List[str]]:
    """Turn a URL expression into a concrete URL wherever we can."""
    notes = []  # type: List[str]
    expression = expression.strip()
    literals = [match.group("value") for match in _LITERAL.finditer(expression)]

    absolute = next((value for value in literals if _HAS_SCHEME.search(value)), "")
    if absolute:
        return _strip_placeholders(absolute), notes

    # `base + "/orders/1"`, f"{BASE}/orders", `${BASE}/orders`
    candidate = None
    identifier = re.match(r"([A-Za-z_$][\w$.]*)", expression)
    interpolated = re.search(r"[{$]\{?\s*([A-Za-z_$][\w$.]*)\s*\}?", expression)
    if identifier is not None and identifier.group(1) not in ("f", "self", "this"):
        candidate = identifier.group(1)
    elif interpolated is not None:
        candidate = interpolated.group(1)

    if candidate is not None:
        head, note = _resolve_symbol(context, candidate, symbols)
        if note:
            notes.append(note)
        if head:
            tail = next((value for value in literals if value.startswith("/")), "")
            if not tail:
                tail = _template_tail(literals, candidate)
            return _strip_placeholders(head.rstrip("/") + tail), notes

    path_only = next((value for value in literals if value.startswith("/")), "")
    return (_strip_placeholders(path_only), notes) if path_only else ("", notes)


def _resolve_symbol(context: Context, name: str, symbols: Dict[str, str]
                    ) -> Tuple[str, str]:
    seen = set()  # type: set
    current = name
    for _ in range(4):
        if current in seen:
            break
        seen.add(current)
        local = symbols.get(current) or symbols.get(current.split(".")[-1])
        if local is not None:
            if _HAS_SCHEME.search(local) or local.startswith("/"):
                return local, ""
            current = local
            continue
        hit = context.config.resolve(current)
        if hit is not None:
            return hit.value, "base URL read from {0} via `{1}`".format(hit.source, current)
        break
    return "", ""


def _template_tail(literals: List[str], candidate: str) -> str:
    """Pull the path out of a template literal: `${BASE}/orders/${id}` -> /orders/{id}.

    Without this a template-literal call resolves to a bare host and the edge
    loses the one detail that makes it reviewable - which endpoint was called.
    """
    for value in literals:
        if candidate not in value:
            continue
        closing = value.find("}", value.find(candidate))
        if closing < 0:
            continue
        tail = value[closing + 1:]
        if tail.startswith("/"):
            return tail
    return ""


def _strip_placeholders(url: str) -> str:
    """`/orders/${orderId}` -> `/orders/{id}`.

    Deleting the placeholder outright would throw away the fact that the path
    is parameterised, which is exactly the detail a reviewer wants to see.
    """
    url = re.sub(r"\$\{[^}]*\}", "{id}", url)
    url = re.sub(r"%[svd]", "{id}", url)
    return url.strip()


def _clean_path(path: str) -> str:
    """Collapse ids so `/orders/42` and `/orders/7` are one edge, not two."""
    if not path:
        return ""
    parts = []  # type: List[str]
    for part in path.split("/"):
        if (re.match(r"^\d+$", part)
                or re.match(r"^[0-9a-f]{8}-[0-9a-f-]{20,}$", part, re.IGNORECASE)
                or (part[:1] in "{%$:" and part)):
            parts.append("{id}")
        else:
            parts.append(part)
    cleaned = "/".join(parts)
    if len(cleaned) > 1 and cleaned.endswith("/"):
        cleaned = cleaned[:-1]
    return cleaned if len(cleaned) <= 48 else cleaned[:47] + "..."


def _external_id(host: str) -> str:
    return slugify(host, keep_dots=False)


def _match_openapi(context: Context, path: str) -> Optional[Tuple[str, str, str]]:
    target = _normalise_path(path)
    if not target or target == "/":
        return None
    for service_id in sorted(context.api_paths):
        for spec_path, source, _method in context.api_paths[service_id]:
            if _normalise_path(spec_path) == target:
                return service_id, source, spec_path
    return None


def _normalise_path(path: str) -> str:
    parts = []  # type: List[str]
    for part in path.split("?")[0].split("/"):
        if not part:
            continue
        if part.startswith("{") or part.startswith(":") or re.match(r"^\d+$", part):
            parts.append("*")
        else:
            parts.append(part.lower())
    return "/" + "/".join(parts)


# -- Feign ------------------------------------------------------------------ #

def _feign_clients(context: Context, record: FileRecord, lines: List[str],
                   service: str) -> None:
    """`@FeignClient(name = "orders-svc")` names its target outright."""
    if record.suffix not in (".java", ".kt"):
        return
    for index, line in enumerate(lines):
        if not _FEIGN.search(line):
            continue
        header = "\n".join(lines[index:index + 4])
        name_match = re.search(r"(?:name|value)\s*=\s*[\"']([^\"']+)[\"']", header)
        url_match = re.search(r"\burl\s*=\s*[\"']([^\"']+)[\"']", header)
        raw_target = name_match.group(1) if name_match is not None else ""
        if not raw_target and url_match is not None:
            raw_target = urlsplit(url_match.group(1)).hostname or ""
        if not raw_target:
            continue
        raw_target = re.sub(r"\$\{([^:}]+)(?::([^}]*))?\}",
                            lambda m: m.group(2) or m.group(1), raw_target)

        known = known_host(context, raw_target)
        target_id = known[0] if known is not None else slugify(raw_target, keep_dots=False)
        tag = CODE if known is not None else INFERENCE
        note = "" if known is not None else (
            "@FeignClient names `{0}`, which does not match any service found in "
            "this repository".format(raw_target))

        body = "\n".join(lines[index:index + 200])
        methods = [(match.group("verb").upper(), _mapping_path(match.group("args")))
                   for match in _SPRING_MAPPING.finditer(body)]
        for verb, path in (methods or [("HTTP", "")])[:12]:
            context.add_call(
                caller=service, target_id=target_id, target_kind=KIND_SERVICE,
                target_label=raw_target, protocol="http",
                method="{0} {1}".format(verb, path).strip(), record=record,
                line=index + 1, tag=tag, note=note, detail="feign",
                extractor=HTTP_NAME)


def _mapping_path(args: str) -> str:
    match = _ANNOTATION_PATH.search(args)
    if match is not None:
        return _clean_path(match.group(1))
    literal = _LITERAL.search(args)
    return _clean_path(literal.group("value")) if literal is not None else ""


# --------------------------------------------------------------------------- #
# Datastores and caches
# --------------------------------------------------------------------------- #

DATASTORE_NAME = "datastore"

_SCHEMES = {
    "postgres": (KIND_DATASTORE, "PostgreSQL", "sql"),
    "postgresql": (KIND_DATASTORE, "PostgreSQL", "sql"),
    "mysql": (KIND_DATASTORE, "MySQL", "sql"),
    "mariadb": (KIND_DATASTORE, "MariaDB", "sql"),
    "sqlserver": (KIND_DATASTORE, "SQL Server", "sql"),
    "oracle": (KIND_DATASTORE, "Oracle", "sql"),
    "mongodb": (KIND_DATASTORE, "MongoDB", "mongo"),
    "mongodb+srv": (KIND_DATASTORE, "MongoDB", "mongo"),
    "cassandra": (KIND_DATASTORE, "Cassandra", "cql"),
    "clickhouse": (KIND_DATASTORE, "ClickHouse", "sql"),
    "elasticsearch": (KIND_DATASTORE, "Elasticsearch", "http"),
    "opensearch": (KIND_DATASTORE, "OpenSearch", "http"),
    "redis": (KIND_CACHE, "Redis", "redis"),
    "rediss": (KIND_CACHE, "Redis", "redis"),
    "valkey": (KIND_CACHE, "Valkey", "redis"),
    "memcached": (KIND_CACHE, "Memcached", "memcached"),
    "amqp": (KIND_EXTERNAL_API, "RabbitMQ", "amqp"),
    "amqps": (KIND_EXTERNAL_API, "RabbitMQ", "amqp"),
}

_CONNECTION_URI = re.compile(
    r"(?:jdbc:)?(?P<scheme>" + "|".join(sorted(_SCHEMES, key=len, reverse=True))
    + r")://(?P<rest>[^\s\"'`,)\]}]*)", re.IGNORECASE)

_DATASTORE_SUFFIXES = (
    ".py", ".java", ".kt", ".go", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs",
    ".cs", ".rb", ".rs", ".yml", ".yaml", ".properties", ".tf",
)


def applies_datastore(record: FileRecord) -> bool:
    return record.suffix in _DATASTORE_SUFFIXES or record.name.startswith(".env")


_COMPOSE_PREFIXES = ("docker-compose", "compose.yml", "compose.yaml")


def extract_datastores(context: Context, record: FileRecord) -> None:
    if record.name.lower().startswith(_COMPOSE_PREFIXES):
        # A compose file belongs to no single service, so a connection string
        # in it must be attributed to the container whose environment holds it,
        # never to whichever service happens to own the file.
        _compose_datastores(context, record)
        return
    service = context.owner(record)
    if not service:
        return
    for index, raw in enumerate(context.scan.read_lines(record)):
        line = strip_comment(raw, record.suffix) if record.suffix else raw
        for match in _CONNECTION_URI.finditer(line):
            _emit_datastore(context, service, match, record, index + 1)


def _compose_datastores(context: Context, record: FileRecord) -> None:
    text = context.scan.read_text(record)
    lines = context.scan.read_lines(record)
    for document in parse_yaml_documents(text):
        if not isinstance(document, dict):
            continue
        services = document.get("services")
        if not isinstance(services, dict):
            continue
        for name in sorted(services):
            spec = services[name]
            if not isinstance(spec, dict):
                continue
            caller = slugify(str(name), keep_dots=False)
            if caller not in context.scan.services:
                continue
            environment = spec.get("environment")
            if isinstance(environment, dict):
                values = [str(value) for value in environment.values()]
            elif isinstance(environment, list):
                values = [str(entry) for entry in environment or []]
            else:
                continue
            for value in values:
                for match in _CONNECTION_URI.finditer(value):
                    _emit_datastore(context, caller, match, record,
                                    line_of(lines, value.split("=")[-1][:60]))


def _emit_datastore(context: Context, service: str, match, record: FileRecord,
                    line: int) -> None:
    scheme = match.group("scheme").lower()
    kind, label, protocol = _SCHEMES[scheme]
    host, database = _split_connection(match.group("rest"))
    if not host:
        return

    # If the host names a container docker-compose already described, reuse
    # that node - otherwise the same database is drawn twice, once per source.
    container = context.scan.config.compose_systems.get(slugify(host, keep_dots=False))
    if container is not None:
        node_id = slugify(host, keep_dots=False)
        node_label = container[1]
    else:
        node_id = slugify("{0}-{1}".format(scheme, database or host), keep_dots=False)
        node_label = "{0}\n{1}".format(label, database or host)

    context.add_call(
        caller=service, target_id=node_id, target_kind=kind,
        target_label=node_label, protocol=protocol, method="", record=record,
        line=line, tag=CODE, detail=database or host, extractor=DATASTORE_NAME)


def _split_connection(rest: str) -> Tuple[str, str]:
    """`user:pw@db-host:5432/orders?x=1` -> ("db-host", "orders")."""
    try:
        parts = urlsplit("//" + rest)
        host = (parts.hostname or "").lower()
        database = parts.path.lstrip("/").split("?")[0].split(";")[0].strip()
    except ValueError:
        return "", ""
    if host.startswith(("$", "{", "%")) or "{" in host:
        host = ""       # a templated host tells us nothing; the db name might
    if database and not re.match(r"^[A-Za-z0-9_\-.]+$", database):
        database = ""
    if re.match(r"^\d+$", database or ""):
        database = ""   # `redis://cache:6379/0` - that is a db index, not a name
    if not host and not database:
        return "", ""
    return host or database, database
