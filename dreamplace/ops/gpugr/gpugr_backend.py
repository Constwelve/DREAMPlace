##
# @file   gpugr_backend.py
# @brief  Bundled XplaceGPUGR backend for RUPlace.
#

import os

from dreamplace.ops.gpugr.xplace_backend import XplaceGGRAdapter


class BundledGPUGRBackend(XplaceGGRAdapter):
    """Use the XplaceGPUGR submodule installed inside DREAMPlace."""

    @staticmethod
    def resolve_bundle_root(configured=""):
        candidates = []
        if configured:
            candidates.append(configured)
        env_root = os.environ.get("DREAMPLACE_GPUGR_ROOT")
        if env_root:
            candidates.append(env_root)

        op_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(op_dir, "xplace_gpugr"))

        # Source-tree fallback for developers running without `make install`.
        repo_root = os.path.abspath(os.path.join(op_dir, "..", "..", ".."))
        candidates.append(os.path.join(repo_root, "thirdparty", "XplaceGPUGR"))

        for candidate in candidates:
            root = os.path.abspath(candidate)
            cpybin = os.path.join(root, "cpp_to_py", "cpybin")
            ioparser = os.path.join(root, "utils", "io_parser.py")
            if os.path.isdir(cpybin) and os.path.exists(ioparser):
                return root
        tried = ", ".join(os.path.abspath(c) for c in candidates)
        raise RuntimeError(
            "Bundled GPUGR backend is not built or installed. Tried: %s. "
            "Run CMake with -DRUPLACE_ENABLE_GPUGR=ON and install DREAMPlace, "
            "or set DREAMPLACE_GPUGR_ROOT/ruplace_gpugr_root to a built GPUGR root."
            % tried
        )

    def _resolve_xplace_root(self, configured):
        return self.resolve_bundle_root(getattr(self.params, "ruplace_gpugr_root", ""))
