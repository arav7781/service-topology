# Online Boutique - a third-party test

[GoogleCloudPlatform/microservices-demo](https://github.com/GoogleCloudPlatform/microservices-demo)
is a public demo of twelve services in Go, C#, Node.js, Python and Java,
wired over gRPC, with Kubernetes manifests. Nobody on this project wrote it,
and its README documents the architecture, so it's an honest test.

This directory holds only what the skill produced: the
[ledger](topology.ledger) and an [overview](views/overview.md). The code isn't
copied. Every receipt points into the upstream repository at commit
[`38e7348`](https://github.com/GoogleCloudPlatform/microservices-demo/tree/38e7348eb289eb5b87c0c6e8cb19ced0449dc389)
(2026-09-18). CI clones that commit and checks that every receipt still
resolves:

```bash
git clone https://github.com/GoogleCloudPlatform/microservices-demo /tmp/boutique
git -C /tmp/boutique checkout 38e7348eb289eb5b87c0c6e8cb19ced0449dc389
bash tools/check-ledger.sh /tmp/boutique examples/third-party/online-boutique/topology.ledger
```

What was found, and what it took to find it, is written up in
[docs/evaluation.md](../../../docs/evaluation.md).
