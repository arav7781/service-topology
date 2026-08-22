# Service Boundary Heuristics

Phase 0. Everything downstream is a statement about services, so if the service
list is wrong, the diagram is confidently wrong - which is worse than absent.

---

## What counts as a service

A directory containing a **declared deployable name**. In precedence order:

| Signal | Name taken from | Language |
|---|---|---|
| `application.yml` / `.properties` | `spring.application.name` | java |
| `pom.xml` | `<artifactId>`, ignoring the `<parent>` block | java |
| `build.gradle[.kts]` | `rootProject.name` | java |
| `package.json` | `name`, scope stripped: `@acme/orders-svc` -> `orders-svc` | javascript |
| `go.mod` | last segment of the module path | go |
| `pyproject.toml` / `setup.py` | `name` | python |
| `Cargo.toml` | `name` | rust |
| `Chart.yaml` | `name` | - |
| `Dockerfile` alone | the directory name | - |
| Nothing at all | the repository directory name | - |

`spring.application.name` outranks `artifactId` deliberately: it is the name the
service answers to at runtime, which is the name other services use to reach it.

An `application.yml` sits in `src/main/resources`, so the module root is found by
walking up past `/src/main/resources`, `/src/main/java`, `/src`, `/config` and
`/resources` before the directory is claimed.

---

## Attribution

Each file belongs to the **deepest** service root above it. A file under no
service root belongs to **no service** - and extractors skip it.

That last rule matters more than it looks. A root `docker-compose.yml` in a
three-service monorepo is owned by nobody; attributing it to whichever service
sorts first would hang every connection string in the file off an unrelated
service. The compose reader handles those files specially, resolving each fact
to the compose service that declares it.

---

## Dropping workspace wrappers

A root `package.json` above `packages/*/package.json`, or a parent `pom.xml`
above `modules/*/pom.xml`, declares a name but owns no code of its own. Any
candidate root with zero code files attributed to it is dropped, unless it is
the only candidate.

---

## Ambiguous cases - ask, do not guess

Emit `BOUNDARIES_UNCLEAR` and show the user the detected list when:

- **A modular monolith.** Internal modules each have a manifest but ship as one
  deployable. The topology between them is real but it is not a service
  topology, and drawing it as one implies a network boundary that is not there.
- **Services named only in Kubernetes manifests.** The code has no per-service
  manifests; the deployables are defined in Helm or Kustomize. Ask which
  directories map to which workload.
- **One repository, one service, many directories.** Discovery finds one
  service; confirm that is intended before rendering a diagram with a single box.
- **More than 25 services.** Ask which subsystems matter before generating a
  micro topology for each.

---

## Referenced-only services

A service can enter the model without a manifest - a Feign client naming it, a
gRPC stub implying it, a resolved hostname pointing at it. Those nodes carry
`origin: referenced-only`, are drawn hollow with a dashed border, and get **no
micro topology**: there is no inside to draw. They are usually one of three
things, and the summary should say which you think it is:

1. a real service in another repository;
2. a service in this repository whose boundary was missed;
3. a stale reference to something that no longer exists.
