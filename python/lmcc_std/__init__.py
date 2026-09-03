"""lmcc_std — the standard vocabulary pack.

This package is deliberately *outside* the kernel. It registers through the
same sockets your own formats and strategies use, and it earns its standing
the same way: by passing the contract corpus. Nothing here is privileged.

Install into a registry explicitly::

    import lmcc, lmcc_std
    lmcc_std.install()                      # default registry
    lmcc_std.install(my_registry)           # or an explicit one
"""

from . import formats, lenses, strategies

VERSION = "0.1.0"


def install(registry=None, *, exist_ok: bool = True) -> None:
    from lmcc.registry import default_registry
    registry = registry if registry is not None else default_registry
    formats.install(registry, exist_ok=exist_ok)
    strategies.install(registry, exist_ok=exist_ok)
    lenses.install(registry, exist_ok=exist_ok)


__all__ = ["VERSION", "formats", "install", "lenses", "strategies"]
