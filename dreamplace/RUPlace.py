"""Compatibility shim for the moved RUPlace implementation.

New code should import from ``dreamplace.ops.gpugr`` or
``dreamplace.ops.routability_opt`` instead of this module.
"""

from dreamplace.ops.gpugr.xplace_backend import (  # noqa: F401
    GPUGRResult,
    RUPlaceRouteResult,
    XplaceBackend,
    XplaceGGRAdapter,
    _external_eval_main,
)
from dreamplace.ops.routability_opt.ruplace_op import (  # noqa: F401
    RUPlaceController,
    RUPlaceInflation,
    RoutabilityOptOp,
)


if __name__ == "__main__":
    import sys

    if "--ruplace-external-eval" in sys.argv:
        raise SystemExit(_external_eval_main(sys.argv[1:]))
