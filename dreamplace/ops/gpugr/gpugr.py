"""Standalone GPUGR op facade."""


def build_gpugr_backend(params=None, backend=None, placedb=None, data_collections=None):
    name = (backend or getattr(params, "ruplace_router_backend", "xplace") or "xplace").lower()
    if name == "xplace":
        from dreamplace.ops.gpugr.xplace_backend import XplaceGGRAdapter

        if params is None or placedb is None or data_collections is None:
            raise ValueError("Xplace GPUGR backend requires params, placedb, and data_collections")
        return XplaceGGRAdapter(params, placedb, data_collections)
    if name == "instantgr":
        from dreamplace.ops.gpugr.instantgr_backend import InstantGRBackend

        return InstantGRBackend(params)
    raise ValueError("Unknown GPUGR backend: %s" % name)


class GPUGROp(object):
    """Callable wrapper around a backend; usable without enabling RUPlace."""

    def __init__(self, backend):
        self.backend = backend

    def __call__(self, *args, **kwargs):
        if hasattr(self.backend, "run_route"):
            return self.backend.run_route(*args, **kwargs)
        return self.backend.route(*args, **kwargs)
