"""Cross-process serialization for the single GPU used by RUPlace."""

import contextlib
import fcntl
import logging
import os
from pathlib import Path
import threading
import time


# Granularity of the RUPlace GPU lock (params: ruplace_gpu_lock_mode):
#   call -- lock around each GPU router entry point (default; two campaign
#           workers can then overlap everything that is not a router call)
#   run  -- hold the lock from adapter construction to close(), i.e. for the
#           whole global placement (serializes entire placements)
#   none -- never lock, including in the standalone evaluator subprocesses
LOCK_MODES = ("call", "run", "none")
DEFAULT_LOCK_MODE = "call"
LOCK_MODE_ENV = "RUPLACE_GPU_LOCK_MODE"

# Thread-local nesting depth, keyed by lock file.  A wrapped router entry point
# may call another one (every gradient method can call run_route), and flock()
# on a second fd of the same file blocks even inside a single process, so only
# the outermost serialized_gpu() may touch the lock.
_LOCAL = threading.local()


def _default_lock_path(device_id):
    configured = os.environ.get("RUPLACE_GPU_LOCK", "").strip()
    if configured:
        return Path(configured)
    for parent in Path(__file__).resolve().parents:
        if (parent / "tools" / "ruplace_quality.py").is_file():
            return parent / "results" / "locks" / ("ruplace_gpu%d.lock" % device_id)
    return Path.cwd() / "results" / "locks" / ("ruplace_gpu%d.lock" % device_id)


def normalize_lock_mode(mode, default=DEFAULT_LOCK_MODE):
    """Return a valid member of LOCK_MODES; unknown values warn and fall back."""
    if mode is None:
        return default
    text = str(mode).strip().lower()
    if not text:
        return default
    if text not in LOCK_MODES:
        logging.warning("RUPlace: unrecognized GPU lock mode %r, using %r", mode, default)
        return default
    return text


def resolve_lock_mode(configured=None, default=DEFAULT_LOCK_MODE):
    """Resolve the lock mode: an explicit value (params/CLI) wins.

    ``RUPLACE_GPU_LOCK_MODE`` is the fallback for the code paths that have no
    params object -- the external/standalone evaluator subprocesses, which the
    parent launches with that variable exported.
    """
    if configured is not None and str(configured).strip():
        return normalize_lock_mode(configured, default)
    return normalize_lock_mode(os.environ.get(LOCK_MODE_ENV), default)


def _depths():
    depths = getattr(_LOCAL, "depths", None)
    if depths is None:
        depths = {}
        _LOCAL.depths = depths
    return depths


def lock_depth(device_id=0):
    """Current thread's serialized_gpu() nesting depth for this device."""
    return _depths().get(str(_default_lock_path(int(device_id))), 0)


def acquire_gpu_lock(device_id=0, label="RUPlace"):
    path = _default_lock_path(int(device_id))
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    start = time.time()
    # call mode acquires once per router call, so keep the common (uncontended)
    # case out of the placement log and report only real queueing.
    logging.debug("%s waiting for exclusive GPU%d lock %s", label, device_id, path)
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    waited = time.time() - start
    handle.seek(0)
    handle.truncate()
    handle.write("pid=%d label=%s acquired=%s\n" % (os.getpid(), label, time.time()))
    handle.flush()
    if waited > 0.5:
        logging.info("%s acquired GPU%d lock after %.2fs", label, device_id, waited)
    else:
        logging.debug("%s acquired GPU%d lock after %.2fs", label, device_id, waited)
    return handle


def release_gpu_lock(handle):
    if handle is None or handle.closed:
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    handle.close()


@contextlib.contextmanager
def serialized_gpu(device_id=0, label="RUPlace"):
    """Hold the GPU lock for the block.  Re-entrant within one thread."""
    key = str(_default_lock_path(int(device_id)))
    depths = _depths()
    if depths.get(key, 0) > 0:
        # Already held by an outer section in this thread: re-acquiring on a
        # second fd would deadlock against ourselves.
        depths[key] += 1
        try:
            yield
        finally:
            depths[key] -= 1
        return
    handle = acquire_gpu_lock(device_id, label)
    depths[key] = 1
    try:
        yield
    finally:
        depths[key] = max(depths.get(key, 1) - 1, 0)
        release_gpu_lock(handle)


@contextlib.contextmanager
def maybe_serialized_gpu(mode, device_id=0, label="RUPlace"):
    """serialized_gpu() unless ``mode`` is 'none' (then a plain no-op)."""
    if normalize_lock_mode(mode) == "none":
        yield
        return
    with serialized_gpu(device_id, label):
        yield
