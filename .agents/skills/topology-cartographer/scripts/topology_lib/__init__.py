"""Shared library for the Topology Cartographer scripts.

The six command-line scripts in the parent directory are thin argument-parsing
shells; the extraction, layout, and rendering logic lives here so the skill,
the subagents, and the MCP server all execute the same code path. Nothing in
this package imports anything outside the Python standard library.

Modules
-------
    model       graph model, evidence tags, containment-checked writer
    discovery   repository walk, service detection, config index
    extract     Kafka, HTTP, gRPC, OpenAPI and config extractors
    textutil    identifiers, literals, and the label wrapping both of the below
    theme       shapes, sizes, spacing and label widths - read by layout *and*
                render, because a theme decides how big a thing is drawn as
                well as how it looks
    layout      deterministic layered placement
    render      mxGraph (.drawio), Mermaid, and evidence-report renderers

Python 3.8+, standard library only - the same constraint as every other script
in this repository.
"""

__all__ = ["model", "discovery", "extract", "textutil", "theme",
           "layout", "render"]

VERSION = "1.1.0"
