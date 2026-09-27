"""``app.platform`` - the primitives every module may import, and which may import
no module back (``03-ARCHITECTURE.md`` §5, rules 1 and 4).

This package is the v2 shape landing inside the running v1 tree: it is ADDITIVE, so
nothing in ``app/services`` or ``app/modules`` changes because it exists. The first
resident is :mod:`app.platform.ai` - the model router, the graph runtime and the
tracing seam that ``06-AI-STACK.md`` makes the single door to every model call.

Note the name: ``app.platform`` never shadows the stdlib ``platform`` module, because
Python 3 resolves ``import platform`` absolutely. A module inside this package that
genuinely wants the stdlib one still writes ``import platform`` and gets it.
"""
