import importlib
import torch

_EXTENSIONS = [
    "dct_cuda",
    "flute_cpp",
    "hpwl_cuda",
    "io_parser",
    "density_map_cuda",
    "draw_placement",
    "wa_wirelength_hpwl_cuda",
    "gpugr",
    "gpudp",
    "routedp",
    "gputimer",
    "wirelength_timing_cuda",
]

__all__ = []

for _name in _EXTENSIONS:
    try:
        globals()[_name] = importlib.import_module(f".cpybin.{_name}", __name__)
        __all__.append(_name)
    except ImportError:
        globals()[_name] = None
