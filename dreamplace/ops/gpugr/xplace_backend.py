##
# @file   xplace_backend.py
# @brief  Xplace GPU-router backend for RUPlace/standalone GPUGR.
#

import ctypes
import logging
import os
import argparse
import importlib
import importlib.util
import math
import re
import subprocess
import sys
import time
import types

import torch
import torch.nn.functional as F

try:
    from dreamplace.ops.gpugr import gr_metrics
except ImportError:  # standalone / bundled invocation (run_gpugr.py runs this file directly)
    import gr_metrics


class RUPlaceRouteResult(object):
    def __init__(self, routeforce, overflow_map, utilization_map, hv_overflow_map,
                 metrics, hv_utilization_map=None, route_maps=None):
        self.routeforce = routeforce
        self.overflow_map = overflow_map
        self.utilization_map = utilization_map
        self.hv_overflow_map = hv_overflow_map
        self.hv_utilization_map = hv_utilization_map
        self.route_maps = route_maps
        self.metrics = metrics


# Roots whose native libraries have already been preloaded (dlopen/log once).
_PRELOADED_LIB_ROOTS = set()


def _preload_xplace_shared_libs(xplace_root):
    """Preload <root>/cpp_to_py/cpybin/libxplace_*.so with RTLD_GLOBAL.

    The gpugr/io_parser extension modules link libxplace_common.so with
    RUNPATH=$ORIGIN.  ld.so searches LD_LIBRARY_PATH *before* DT_RUNPATH, so a
    campaign script that puts another Xplace checkout on LD_LIBRARY_PATH makes
    the extension bind to that checkout's libxplace_common.so instead of the one
    shipped next to it -- which segfaults in GRDatabase::addMovObs/addCellObs
    when the two disagree about the LEF parser.  Loading the correct files first
    with RTLD_GLOBAL makes them win: they are already in the link map under the
    right SONAME by the time the extension's DT_NEEDED entries are resolved.
    """
    root = os.path.abspath(xplace_root)
    if root in _PRELOADED_LIB_ROOTS:
        return []
    _PRELOADED_LIB_ROOTS.add(root)
    cpybin = os.path.join(root, "cpp_to_py", "cpybin")
    loaded = []
    for name in ("libxplace_flute.so", "libxplace_common.so"):
        path = os.path.join(cpybin, name)
        if not os.path.exists(path):
            continue
        try:
            ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
            loaded.append(path)
        except OSError as e:
            logging.warning("RUPlace could not preload %s: %s", path, e)
    if loaded:
        logging.info("RUPlace preloaded Xplace shared libs (RTLD_GLOBAL): %s",
                     ", ".join(loaded))
    else:
        logging.info("RUPlace found no libxplace_*.so to preload under %s", cpybin)
    return loaded


def _load_xplace_extension(xplace_root, name):
    cpybin = os.path.join(xplace_root, "cpp_to_py", "cpybin")
    if cpybin not in sys.path:
        sys.path.insert(0, cpybin)
    return importlib.import_module(name)


def _install_minimal_cpp_to_py(xplace_root):
    # Must run before the extension modules are imported (see docstring).
    _preload_xplace_shared_libs(xplace_root)
    module = sys.modules.get("cpp_to_py")
    if module is None or not hasattr(module, "gpugr") or not hasattr(module, "io_parser"):
        module = types.ModuleType("cpp_to_py")
        module.gpugr = _load_xplace_extension(xplace_root, "gpugr")
        module.io_parser = _load_xplace_extension(xplace_root, "io_parser")
        sys.modules["cpp_to_py"] = module
    return module


def _load_xplace_gpugr(xplace_root):
    # Import the required extension directly.  Xplace's package __init__ imports
    # optional modules as well, which can fail when only GGR is needed.
    return _install_minimal_cpp_to_py(xplace_root).gpugr


def _load_xplace_ioparser(xplace_root):
    _install_minimal_cpp_to_py(xplace_root)
    try:
        from utils import IOParser
        return IOParser
    except Exception as e:
        logging.warning("RUPlace falling back to direct Xplace IOParser load: %s", e)
    path = os.path.join(xplace_root, "utils", "io_parser.py")
    spec = importlib.util.spec_from_file_location("xplace_ioparser", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.IOParser


class XplaceGGRAdapter(object):
    """
    Adapter around Xplace's gpugr module. DREAMPlace remains the owner of
    placement state; Xplace is used only for route evaluation and gradients.
    """

    def __init__(self, params, placedb, data_collections):
        self.params = params
        self.placedb = placedb
        self.data_collections = data_collections
        self.device = data_collections.pos[0].device
        self.xplace_root = self._resolve_xplace_root(params.ruplace_xplace_root)

        self._import_xplace()
        self.rawdb = None
        self.gpdb = None
        self.parser = None
        self.design_info = None
        self.base_lpos = None
        self.base_size = None
        self.dp_to_x = {}
        self.x_to_dp = {}
        self.dp_movable_ids = None
        self.x_movable_ids = None
        self.x_num_nodes = 0
        self.x_movable_end = 0
        self.node2pin_list = None
        self.node2pin_list_end = None
        self.last_route = None
        self.anchor_pos = None
        self.original_node_size_x = data_collections.node_size_x.clone()
        self.original_node_size_y = data_collections.node_size_y.clone()
        self.original_pin_offset_x = data_collections.pin_offset_x.clone()
        self.original_pin_offset_y = data_collections.pin_offset_y.clone()
        self.external_route_eval = bool(int(getattr(params, "ruplace_external_route_eval", 1)))
        self.external_route_id = 0

        self._load_design()

    def _resolve_xplace_root(self, configured):
        candidates = []
        if configured:
            candidates.append(configured)
        candidates.extend(["../Xplace", "../XPlace"])
        for candidate in candidates:
            path = os.path.abspath(candidate)
            if os.path.isdir(path):
                return path
        raise RuntimeError(
            "RUPlace requires an Xplace repository. Tried: %s"
            % ", ".join(os.path.abspath(c) for c in candidates)
        )

    def _import_xplace(self):
        if not torch.cuda.is_available():
            raise RuntimeError("RUPlace requires a CUDA-enabled PyTorch runtime for Xplace GGR")
        if self.xplace_root not in sys.path:
            sys.path.insert(0, self.xplace_root)
        try:
            gpugr = _load_xplace_gpugr(self.xplace_root)
            IOParser = _load_xplace_ioparser(self.xplace_root)
        except Exception as e:
            raise RuntimeError(
                "Unable to import Xplace GPU router from %s: %s"
                % (self.xplace_root, e)
            )
        self.IOParser = IOParser
        self.gpugr = gpugr
        self.connection_dct_ops = {}
        try:
            self.gpugr.read_flute(
                os.path.join(self.xplace_root, "thirdparty", "flute", "POWV9.dat"),
                os.path.join(self.xplace_root, "thirdparty", "flute", "POST9.dat"),
            )
        except Exception as e:
            logging.warning("RUPlace could not initialize Xplace Flute LUTs: %s", e)

    def _load_design(self):
        if not self.params.def_input or not self.params.lef_input:
            raise RuntimeError("RUPlace currently supports LEF/DEF inputs only")

        lefs = self.params.lef_input if isinstance(self.params.lef_input, list) else [self.params.lef_input]
        io_params = {
            "benchmark": "dreamplace",
            "lefs": [os.path.abspath(lef) for lef in lefs],
            "def": os.path.abspath(self.params.def_input),
            "design_name": self.params.design_name(),
        }
        eval_verilog = getattr(self.params, "ruplace_eval_verilog_input", "")
        if not eval_verilog:
            eval_verilog = getattr(self.params, "verilog_input", "")
        if eval_verilog:
            io_params["verilog"] = os.path.abspath(eval_verilog)
        self.parser = self.IOParser()
        self.rawdb, self.gpdb = self.parser.read(
            io_params,
            verbose_log=False,
            lite_mode=True,
            random_place=False,
            num_threads=self.params.num_threads,
        )
        self.design_info = self.parser.preprocess_design_info(self.gpdb)
        self.base_lpos = self.design_info["node_lpos"].float().cpu()
        self.base_size = self.design_info["node_size"].float().cpu()
        self.x_num_nodes = int(self.base_lpos.shape[0])
        self.x_movable_end = int(self.design_info["movable_index"][1])
        self.node2pin_list = self.design_info["node2pin_list"].to(self.device).long().contiguous()
        self.node2pin_list_end = self.design_info["node2pin_list_end"].to(self.device).long().contiguous()
        self._build_node_maps(self.design_info["node_names"])
        self._validate_node_maps()

    @staticmethod
    def _norm_name(name):
        if isinstance(name, bytes):
            name = name.decode("utf8", errors="ignore")
        name = str(name)
        # Xplace node names contain no backslash at all, so drop every DEF escape
        # backslash, not just the bracket ones: SMIC14 DEFs also escape the hierarchy
        # separator inside a leaf name (DEF DP_OP_4591\\/U28 vs Xplace DP_OP_4591/U28).
        return re.sub(r"\\(.)", r"\1", name)

    def _build_node_maps(self, x_node_names):
        x_name2id = {self._norm_name(name): i for i, name in enumerate(x_node_names)}
        for dp_id, name in enumerate(self.placedb.node_names[: self.placedb.num_physical_nodes]):
            x_id = x_name2id.get(self._norm_name(name))
            if x_id is not None:
                self.dp_to_x[dp_id] = x_id
                self.x_to_dp[x_id] = dp_id

        if len(self.dp_to_x) < min(self.placedb.num_physical_nodes, self.x_num_nodes):
            logging.warning(
                "RUPlace mapped %d/%d DREAMPlace physical nodes to Xplace nodes by name",
                len(self.dp_to_x),
                self.placedb.num_physical_nodes,
            )

    def _validate_node_maps(self):
        missing_movable = [
            self._norm_name(self.placedb.node_names[i])
            for i in range(self.placedb.num_movable_nodes)
            if i not in self.dp_to_x
        ]
        if missing_movable:
            raise RuntimeError(
                "RUPlace/Xplace node mapping missed %d movable nodes, e.g. %s"
                % (len(missing_movable), ", ".join(missing_movable[:5]))
            )

        scale = float(self.params.scale_factor)
        if scale == 0:
            return
        max_size_err = 0.0
        for dp_id, x_id in self.dp_to_x.items():
            if dp_id >= self.placedb.num_physical_nodes:
                continue
            dp_w = float(self.placedb.node_size_x[dp_id]) / scale
            dp_h = float(self.placedb.node_size_y[dp_id]) / scale
            x_w = float(self.base_size[x_id, 0].item())
            x_h = float(self.base_size[x_id, 1].item())
            max_size_err = max(max_size_err, abs(dp_w - x_w), abs(dp_h - x_h))
        if max_size_err > 1e-3:
            logging.warning(
                "RUPlace/Xplace mapped-node size mismatch: max raw-coordinate error %.6g",
                max_size_err,
            )
        dp_ids = []
        x_ids = []
        for dp_id in range(self.placedb.num_movable_nodes):
            x_id = self.dp_to_x.get(dp_id)
            if x_id is not None and x_id < self.x_movable_end:
                dp_ids.append(dp_id)
                x_ids.append(x_id)
        self.dp_movable_ids = torch.tensor(dp_ids, dtype=torch.long)
        self.x_movable_ids = torch.tensor(x_ids, dtype=torch.long)
        logging.info(
            "RUPlace mapped %d DREAMPlace physical nodes to %d Xplace nodes",
            len(self.dp_to_x),
            self.x_num_nodes,
        )

    def _scaled_to_raw_lpos(self, pos):
        num_nodes = self.placedb.num_nodes
        shift_x, shift_y = self.params.shift_factor
        scale = self.params.scale_factor
        x = pos[:num_nodes].detach().cpu().numpy() / scale + shift_x
        y = pos[num_nodes:].detach().cpu().numpy() / scale + shift_y
        raw_lpos = self.base_lpos.clone()
        for dp_id, x_id in self.dp_to_x.items():
            raw_lpos[x_id, 0] = float(x[dp_id])
            raw_lpos[x_id, 1] = float(y[dp_id])
        if not getattr(self, "_lpos_diag_logged", False):
            # One-shot sanity check: DREAMPlace never moves fixed cells, so the round-trip
            # through pos/scale+shift must reproduce the parser positions exactly for them.
            # A non-zero drift here means the scale/shift inversion or the name map is wrong,
            # which shows up downstream as garbage obstruction boxes in GRDatabase.
            self._lpos_diag_logged = True
            nmov = int(self.placedb.num_movable_nodes)
            worst, worst_id, nbad = 0.0, -1, 0
            for dp_id, x_id in self.dp_to_x.items():
                if dp_id < nmov:
                    continue
                d = max(abs(float(raw_lpos[x_id, 0]) - float(self.base_lpos[x_id, 0])),
                        abs(float(raw_lpos[x_id, 1]) - float(self.base_lpos[x_id, 1])))
                if d > 0.5:
                    nbad += 1
                if d > worst:
                    worst, worst_id = d, dp_id
            logging.info(
                "RUPlace lpos round-trip: scale=%r shift=%r, fixed-node drift max %.3f dbu "
                "(%d of %d fixed nodes off by >0.5 dbu, worst dp_id %d %s)",
                scale, (shift_x, shift_y), worst, nbad,
                self.placedb.num_physical_nodes - nmov, worst_id,
                self.placedb.node_names[worst_id] if worst_id >= 0 else "",
            )
            mov_x = raw_lpos[self.x_movable_ids, 0]
            mov_y = raw_lpos[self.x_movable_ids, 1]
            mw = self.base_size[self.x_movable_ids, 0]
            mh = self.base_size[self.x_movable_ids, 1]
            die = self.gpdb.dieInfo()
            oob = int(((mov_x < die[0]) | (mov_x + mw > die[1])
                       | (mov_y < die[2]) | (mov_y + mh > die[3])).sum())
            logging.info(
                "RUPlace movable raw lpos: x [%.1f, %.1f] y [%.1f, %.1f], die %s, "
                "%d of %d movable nodes with a bbox outside the die",
                float(mov_x.min()), float(mov_x.max()), float(mov_y.min()), float(mov_y.max()),
                die, oob, int(mov_x.numel()),
            )
        return raw_lpos.contiguous()

    def _scaled_xplace_centers(self, pos):
        shift = torch.tensor(self.params.shift_factor, dtype=pos.dtype, device=self.device)
        scale = float(self.params.scale_factor)
        base_lpos = self.base_lpos.to(self.device, dtype=pos.dtype)
        base_size = self.base_size.to(self.device, dtype=pos.dtype)
        node_pos = (base_lpos - shift) * scale + base_size * scale * 0.5
        num_nodes = self.placedb.num_nodes
        for dp_id, x_id in self.dp_to_x.items():
            node_pos[x_id, 0] = pos[dp_id] + self.data_collections.node_size_x[dp_id] * 0.5
            node_pos[x_id, 1] = pos[num_nodes + dp_id] + self.data_collections.node_size_y[dp_id] * 0.5
        return node_pos.contiguous()

    def _gr_grid_size(self):
        """Resolve ``ruplace_gr_grid`` into the (route_xSize, route_ySize) pair.

        ``bins``  -- legacy: the DEF routing grid if the parser found one, else
                     ``route_num_bins_{x,y}``.
        ``def``   -- pass 0/0 so GRDatabase falls back to the DEF GCELLGRID.
        ``NxM``   -- an explicit uniform grid, e.g. ``625x650``.
        ``step:D``-- a target gcell pitch in DEF dbu; the grid is derived from the die
                     box as ``max(1, round(die_w / D)) x max(1, round(die_h / D))``.
        """
        grid = str(getattr(self.params, "ruplace_gr_grid", "bins") or "bins").strip().lower()
        if grid in ("", "bins", "legacy"):
            return (int(self.placedb.num_routing_grids_x or self.params.route_num_bins_x),
                    int(self.placedb.num_routing_grids_y or self.params.route_num_bins_y))
        if grid == "def":
            return 0, 0
        if grid.startswith("step:"):
            try:
                step = float(grid.split(":", 1)[1])
            except ValueError:
                step = 0.0
            if step > 0:
                # gpdb.dieInfo() -> (dieLX, dieHX, dieLY, dieHY) in raw DEF dbu.
                die_lx, die_hx, die_ly, die_hy = self.gpdb.dieInfo()
                nx = max(1, int(round((float(die_hx) - float(die_lx)) / step)))
                ny = max(1, int(round((float(die_hy) - float(die_ly)) / step)))
                logging.info(
                    "RUPlace GR grid: step %g dbu over die (%g, %g)-(%g, %g) -> %d x %d gcells "
                    "(actual pitch %.1f x %.1f dbu)",
                    step, die_lx, die_ly, die_hx, die_hy, nx, ny,
                    (float(die_hx) - float(die_lx)) / nx, (float(die_hy) - float(die_ly)) / ny,
                )
                return nx, ny
            logging.warning("RUPlace: bad ruplace_gr_grid %r, falling back to bins", grid)
        if "x" in grid:
            a, _, b = grid.partition("x")
            try:
                return int(a), int(b)
            except ValueError:
                pass
        logging.warning("RUPlace: unrecognized ruplace_gr_grid %r, falling back to 'bins'", grid)
        return (int(self.placedb.num_routing_grids_x or self.params.route_num_bins_x),
                int(self.placedb.num_routing_grids_y or self.params.route_num_bins_y))

    def _route_params(self):
        route_guide = ""
        if int(getattr(self.params, "ruplace_write_guides", 1)):
            try:
                out_dir = os.path.join(self.params.result_dir, self.params.design_name(), "ruplace")
                os.makedirs(out_dir, exist_ok=True)
                route_guide = os.path.join(out_dir, "latest.guide")
            except Exception:
                pass
        route_gpu = getattr(self.params, "ruplace_route_gpu", None)
        if route_gpu is None:
            route_gpu = 0
        route_x, route_y = self._gr_grid_size()
        return {
            "device_id": int(route_gpu),
            "route_xSize": int(route_x),
            "route_ySize": int(route_y),
            "rrrIters": int(self.params.ruplace_gr_rrr_iters),
            "route_guide": route_guide,
            "wire_cost_sat": int(getattr(self.params, "ruplace_gr_wire_cost_sat", 0)),
            # NB: plain getattr, never `x or default` -- 0 is a meaningful value for all
            # three of these and `or` would silently restore the ISPD18 defaults.
            "via_usage_scale": float(getattr(self.params, "ruplace_gr_via_usage_scale", 1.5)),
            "m1_routable": int(getattr(self.params, "ruplace_gr_m1_routable", 1)),
            "max_route_len_per_pin": int(
                getattr(self.params, "ruplace_gr_max_route_len_per_pin", 130)
            ),
        }

    def _gr_util_mode(self):
        mode = str(getattr(self.params, "ruplace_gr_util_mode", "legacy") or "legacy").strip().lower()
        if mode not in gr_metrics.UTIL_MODES:
            logging.warning("RUPlace: unrecognized ruplace_gr_util_mode %r, using 'legacy'", mode)
            mode = "legacy"
        return mode

    def run_route(self, pos):
        if self.external_route_eval:
            return self._run_route_external(pos)
        tt = time.time()
        self.gpdb.apply_node_lpos(self._scaled_to_raw_lpos(pos))
        route_params = self._route_params()
        if not getattr(self, "_route_params_logged", False):
            # Log the fully resolved router settings once: a mis-synced install/ tree or a
            # mistyped key is otherwise a silent no-op (load_gr_params ignores unknown keys).
            logging.info("RUPlace GR settings (resolved): %s | util_mode=%s",
                         ", ".join("%s=%s" % kv for kv in sorted(route_params.items())),
                         self._gr_util_mode())
            self._route_params_logged = True
        self.gpugr.load_gr_params(route_params)
        t_build = time.time()
        grdb = self.gpugr.create_grdatabase(self.rawdb, self.gpdb)
        routeforce = self.gpugr.create_routeforce(grdb)
        t_ggr = time.time()
        routeforce.run_ggr()
        ggr_sec = time.time() - t_ggr
        build_sec = t_ggr - t_build

        dmd_map, wire_dmd_map, via_dmd_map = routeforce.dmd_map()
        cap_map = routeforce.cap_map()
        try:
            fixed_map = routeforce.fixed_map()
        except AttributeError:
            fixed_map = None

        m1direction = self.gpdb.m1direction()
        all_start = 1
        util_mode = self._gr_util_mode()
        if util_mode == "avail" and fixed_map is None:
            logging.warning("RUPlace: ruplace_gr_util_mode='avail' but the router exposes no "
                            "fixed_map(); falling back to 'legacy'")
            util_mode = "legacy"

        demand_map_2d = dmd_map[all_start:].sum(dim=0).contiguous()
        wire_demand_map_2d = wire_dmd_map[all_start:].sum(dim=0).contiguous()
        via_demand_map_2d = via_dmd_map[all_start:].sum(dim=0).contiguous()
        capacity_map_2d = cap_map[all_start:].sum(dim=0).contiguous()
        util_map, overflow_map, hv_utilization, hv_overflow = gr_metrics.hv_maps(
            dmd_map, wire_dmd_map, via_dmd_map, cap_map,
            fixed=fixed_map, m1direction=m1direction, util_mode=util_mode,
        )

        try:
            gr_wirelength, gr_vias = grdb.report_gr_stat()
        except Exception:
            gr_wirelength, gr_vias = 0, 0
        _sx, _sy, _um = _gcell_geometry(routeforce)
        metrics = gr_metrics.route_metrics(
            num_ovfl_nets=int(routeforce.num_ovfl_nets()),
            hv_overflow=hv_overflow,
            dmd_map=dmd_map, wire_dmd_map=wire_dmd_map, via_dmd_map=via_dmd_map, cap_map=cap_map,
            wl_steps=gr_wirelength, gr_vias=gr_vias,
            step_x=_sx, step_y=_sy, microns=_um,
        )
        metrics["time"] = time.time() - tt
        metrics["ggr_time"] = ggr_sec
        metrics["build_time"] = build_sec
        self._route_call_count = getattr(self, "_route_call_count", 0) + 1
        logging.info(
            "RUPlace GR: call %d, #OvflNets %d, GR WL %.3f, vias %.3f, estShorts %.3f, "
            "RC(H/V) %.4f/%.4f, %.2fs (grdb+routeforce %.2fs, run_ggr %.2fs)",
            self._route_call_count,
            metrics["num_ovfl_nets"],
            metrics["gr_wirelength"],
            metrics["gr_vias"],
            metrics["est_shorts"],
            metrics["rc_hor"],
            metrics["rc_ver"],
            metrics["time"],
            build_sec,
            ggr_sec,
        )
        self.last_route = RUPlaceRouteResult(
            routeforce, overflow_map, util_map.contiguous(), hv_overflow,
            metrics, hv_utilization,
            {
                "demand": demand_map_2d,
                "wire_demand": wire_demand_map_2d,
                "via_demand": via_demand_map_2d,
                "capacity": capacity_map_2d,
                "layer_demand": dmd_map[all_start:].contiguous(),
                "layer_wire_demand": wire_dmd_map[all_start:].contiguous(),
                "layer_via_demand": via_dmd_map[all_start:].contiguous(),
                "layer_capacity": cap_map[all_start:].contiguous(),
                # GPUGR's estimated-short formula includes every routing
                # layer, including M1.  Keep these maps separate because the
                # legacy layer fields intentionally skip M1.
                "short_layer_wire_demand": wire_dmd_map.contiguous(),
                "short_layer_via_demand": via_dmd_map.contiguous(),
                "short_layer_capacity": cap_map.contiguous(),
            },
        )
        return self.last_route

    def _run_route_external(self, pos):
        tt = time.time()
        self.external_route_id += 1
        out_dir = os.path.join(self.params.result_dir, self.params.design_name(), "ruplace", "external")
        os.makedirs(out_dir, exist_ok=True)
        prefix = os.path.join(out_dir, "route_%04d" % self.external_route_id)
        def_path = prefix + ".def"
        result_path = prefix + ".pt"
        log_path = prefix + ".log"

        self.gpdb.apply_node_lpos(self._scaled_to_raw_lpos(pos))
        self.gpdb.write_placement(prefix)

        lefs = self.params.lef_input if isinstance(self.params.lef_input, list) else [self.params.lef_input]
        route_params = self._route_params()
        cmd = [
            sys.executable,
            os.path.abspath(__file__),
            "--ruplace-external-eval",
            "--def-input",
            os.path.abspath(def_path),
            "--design-name",
            self.params.design_name(),
            "--xplace-root",
            self.xplace_root,
            "--route-x-size",
            str(route_params["route_xSize"]),
            "--route-y-size",
            str(route_params["route_ySize"]),
            "--rrr-iters",
            str(route_params["rrrIters"]),
            "--gpu",
            str(route_params["device_id"]),
            "--num-threads",
            str(self.params.num_threads),
            "--output",
            result_path,
            "--util-mode",
            self._gr_util_mode(),
            "--wire-cost-sat",
            str(route_params.get("wire_cost_sat", 0)),
        ]
        for lef in lefs:
            cmd.extend(["--lef-input", os.path.abspath(lef)])
        eval_verilog = getattr(self.params, "ruplace_eval_verilog_input", "")
        if not eval_verilog:
            eval_verilog = getattr(self.params, "verilog_input", "")
        if eval_verilog:
            cmd.extend(["--verilog-input", os.path.abspath(eval_verilog)])
        with open(log_path, "w") as log:
            log.write("$ %s\n\n" % " ".join(cmd))
            log.flush()
            proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, text=True)
        if proc.returncode != 0 and not os.path.exists(result_path):
            raise RuntimeError("RUPlace external GGR failed with code %d; see %s" % (proc.returncode, log_path))
        if proc.returncode != 0:
            logging.warning("RUPlace external GGR returned %d after writing metrics; see %s", proc.returncode, log_path)

        payload = torch.load(result_path, map_location="cpu")
        overflow_map = torch.nan_to_num(
            payload["overflow_map"], nan=0.0, posinf=0.0, neginf=0.0
        ).contiguous()
        util_map = torch.nan_to_num(
            payload["utilization_map"], nan=0.0, posinf=0.0, neginf=0.0
        ).contiguous()
        hv_overflow = torch.nan_to_num(
            payload["hv_overflow_map"], nan=0.0, posinf=0.0, neginf=0.0
        ).contiguous()
        hv_utilization = payload.get("hv_utilization_map")
        if hv_utilization is not None:
            hv_utilization = torch.nan_to_num(
                hv_utilization, nan=0.0, posinf=0.0, neginf=0.0
            ).contiguous()
        metrics = payload["metrics"]
        metrics["time"] = time.time() - tt
        logging.info(
            "RUPlace external GR: #OvflNets %d, GR WL %.3f, vias %.3f, estShorts %.3f, RC(H/V) %.4f/%.4f, %.2fs",
            metrics["num_ovfl_nets"],
            metrics["gr_wirelength"],
            metrics["gr_vias"],
            metrics["est_shorts"],
            metrics["rc_hor"],
            metrics["rc_ver"],
            metrics["time"],
        )
        self.last_route = RUPlaceRouteResult(
            None, overflow_map, util_map, hv_overflow, metrics,
            hv_utilization, None,
        )
        return self.last_route

    @staticmethod
    def _connection_fft_scale(shape, device, dtype):
        """Match Xplace's pure-Torch DCT route-field scaling."""
        num_bin_x, num_bin_y = shape
        wj = torch.arange(num_bin_x, device=device, dtype=dtype)
        wk = torch.arange(num_bin_y, device=device, dtype=dtype)
        wj = wj.mul(2.0 * torch.pi / num_bin_x).reshape(num_bin_x, 1)
        wk = wk.mul(2.0 * torch.pi / num_bin_y).reshape(1, num_bin_y)
        wk = wk * (num_bin_y / num_bin_x)
        denom = wj.square() + wk.square()
        denom[0, 0] = 1.0
        potential_scale = denom.reciprocal()
        potential_scale[0, 0] = 0.0
        force_x_scale = wj * potential_scale * 0.5
        force_y_scale = wk * potential_scale * 0.5
        force_x_coeff = torch.where(
            torch.arange(num_bin_x, device=device) % 2 == 0,
            torch.ones(num_bin_x, device=device, dtype=dtype),
            -torch.ones(num_bin_x, device=device, dtype=dtype),
        ).unsqueeze(1)
        force_y_coeff = torch.where(
            torch.arange(num_bin_y, device=device) % 2 == 0,
            torch.ones(num_bin_y, device=device, dtype=dtype),
            -torch.ones(num_bin_y, device=device, dtype=dtype),
        ).unsqueeze(0)
        return (
            potential_scale, 1.0, force_x_scale, force_y_scale,
            force_x_coeff, force_y_coeff,
        )

    def connection_route_gradient(self, pos, refresh=False,
                                  overflow_threshold=0.0,
                                  max_wire_span=19,
                                  distance_weighting="uniform",
                                  field_mode="aggregate",
                                  segment_reduction="last",
                                  segment_blend=0.0,
                                  utilization_threshold=1.0,
                                  pressure_exponent=1.0,
                                  via_utilization_threshold=0.0,
                                  dilation_radius=0,
                                  unit_wire_cost=1.0,
                                  unit_via_cost=1.0):
        """Return Xplace's routed-segment overflow gradient in DREAMPlace order."""
        if self.external_route_eval:
            raise RuntimeError(
                "connection routeforce requires in-process gpugr feedback"
            )
        if refresh or self.last_route is None:
            self.run_route(pos)
        route = self.last_route
        if route.routeforce is None or not route.route_maps:
            raise RuntimeError("connection routeforce requires native route maps")

        threshold = float(overflow_threshold)
        utilization_threshold = float(utilization_threshold)
        pressure_exponent = float(pressure_exponent)
        via_utilization_threshold = float(via_utilization_threshold)
        dilation_radius = int(dilation_radius)
        max_wire_span = int(max_wire_span)
        if threshold < 0.0:
            raise ValueError("connection routeforce threshold must be nonnegative")
        if utilization_threshold < 0.0:
            raise ValueError(
                "connection routeforce utilization threshold must be nonnegative"
            )
        if not math.isfinite(pressure_exponent) or pressure_exponent <= 0.0:
            raise ValueError(
                "connection routeforce pressure exponent must be finite and positive"
            )
        if via_utilization_threshold < 0.0:
            raise ValueError(
                "connection routeforce via utilization threshold must be "
                "nonnegative"
            )
        if dilation_radius < 0:
            raise ValueError(
                "connection routeforce dilation radius must be nonnegative"
            )
        if max_wire_span < 0:
            raise ValueError("connection routeforce max wire span must be nonnegative")
        mode = str(distance_weighting).lower()
        if mode not in ("uniform", "inverse_sqrt"):
            raise ValueError(
                "unsupported connection routeforce distance weighting: %s" % mode
            )
        field_mode = str(field_mode).lower()
        field_mode_ids = {
            "aggregate": 0,
            "max_hv": 1,
            "directional_hv": 2,
            "max_layer": 3,
            "directional_hv_pressure": 4,
            "directional_hv_pressure_via": 5,
            "directional_hv_pressure_via_short": 6,
        }
        if field_mode not in field_mode_ids:
            raise ValueError(
                "unsupported connection routeforce field mode: %s" % field_mode
            )
        segment_reduction = str(segment_reduction).lower()
        segment_reduction_ids = {"last": 0, "sum": 1, "mean": 2, "blend": 3}
        if segment_reduction not in segment_reduction_ids:
            raise ValueError(
                "unsupported connection routeforce segment reduction: %s"
                % segment_reduction
            )
        segment_blend = float(segment_blend)
        if not math.isfinite(segment_blend) or not 0.0 <= segment_blend <= 1.0:
            raise ValueError(
                "connection routeforce segment blend must be finite and in [0, 1]"
            )

        overflow = route.overflow_map.to(self.device).float().contiguous()
        maps = route.route_maps
        raw_capacity = maps["capacity"].to(self.device).float().contiguous()
        wire_demand = maps["wire_demand"].to(
            self.device
        ).float().contiguous()
        via_demand = maps["via_demand"].to(
            self.device
        ).float().contiguous()

        def tensor_stats(name, value):
            finite = torch.isfinite(value)
            finite_values = value[finite]
            return {
                "%s_nonfinite_count" % name: int((~finite).sum().item()),
                "%s_finite_max" % name: (
                    float(finite_values.abs().max().item())
                    if finite_values.numel() else 0.0
                ),
            }

        diagnostics = {}
        for name, value in (
            ("overflow", overflow),
            ("capacity", raw_capacity),
            ("wire_demand", wire_demand),
            ("via_demand", via_demand),
        ):
            diagnostics.update(tensor_stats(name, value))
            if diagnostics["%s_nonfinite_count" % name]:
                raise RuntimeError(
                    "connection routeforce received non-finite %s: %s"
                    % (name, diagnostics)
                )

        positive_capacity = raw_capacity > 0.0
        # Zero-capacity boundary bins have no routable resource. run_route uses
        # an epsilon denominator for reporting, so their apparent overflow can
        # be extremely large even though they must not drive the global DCT
        # field. Masking only inside route_grad is too late: an extreme field
        # can overflow first and the CUDA kernel then evaluates inf * 0.
        zero_field = torch.zeros_like(overflow)
        aggregate_field = torch.where(
            positive_capacity, overflow, zero_field
        ).contiguous()
        if field_mode == "aggregate":
            field_x_source = aggregate_field
            field_y_source = aggregate_field
        elif field_mode in (
            "max_hv", "directional_hv", "directional_hv_pressure",
            "directional_hv_pressure_via",
            "directional_hv_pressure_via_short",
        ):
            use_pressure = field_mode in (
                "directional_hv_pressure", "directional_hv_pressure_via",
                "directional_hv_pressure_via_short",
            )
            use_via_pressure = field_mode in (
                "directional_hv_pressure_via",
                "directional_hv_pressure_via_short",
            )
            use_short_via_pressure = (
                field_mode == "directional_hv_pressure_via_short"
            )
            directional_map = (
                route.hv_utilization_map if use_pressure
                else route.hv_overflow_map
            )
            if directional_map is None:
                raise RuntimeError(
                    "%s connection routeforce requires directional %s"
                    % (field_mode, "utilization" if use_pressure else "overflow")
                )
            directional_map = directional_map.to(
                self.device
            ).float().contiguous()
            map_name = "hv_utilization" if use_pressure else "hv_overflow"
            diagnostics.update(tensor_stats(map_name, directional_map))
            if diagnostics[map_name + "_nonfinite_count"]:
                raise RuntimeError(
                    "connection routeforce received non-finite directional "
                    "%s: %s" % (
                        "utilization" if use_pressure else "overflow",
                        diagnostics,
                    )
                )
            if use_pressure:
                directional_map = (
                    directional_map - utilization_threshold
                ).clamp_min(0.0)
                # Preserve the established linear field exactly by bypassing
                # pow at the default. Larger exponents focus the normalized
                # route force on peak H/V utilization without changing the
                # independently weighted short-aware via term.
                if pressure_exponent != 1.0:
                    directional_map = directional_map.pow(pressure_exponent)
                if dilation_radius:
                    kernel = dilation_radius * 2 + 1
                    directional_map = F.max_pool2d(
                        directional_map.unsqueeze(0),
                        kernel_size=kernel,
                        stride=1,
                        padding=dilation_radius,
                    ).squeeze(0)
            horizontal_field = torch.where(
                positive_capacity, directional_map[0], zero_field
            ).contiguous()
            vertical_field = torch.where(
                positive_capacity, directional_map[1], zero_field
            ).contiguous()
            if field_mode == "max_hv":
                field_x_source = torch.maximum(
                    horizontal_field, vertical_field
                ).contiguous()
                field_y_source = field_x_source
            else:
                # Vertical routes need an x force; horizontal routes need a y
                # force. Preserve those cross-track axes independently.
                field_x_source = vertical_field
                field_y_source = horizontal_field
                if use_via_pressure:
                    via_pressure_demand = via_demand
                    if use_short_via_pressure:
                        layer_wire_demand = maps.get(
                            "short_layer_wire_demand",
                            maps.get("layer_wire_demand"),
                        )
                        layer_via_demand = maps.get(
                            "short_layer_via_demand",
                            maps.get("layer_via_demand"),
                        )
                        layer_capacity = maps.get(
                            "short_layer_capacity",
                            maps.get("layer_capacity"),
                        )
                        if (layer_wire_demand is None or
                                layer_via_demand is None or
                                layer_capacity is None):
                            raise RuntimeError(
                                "directional_hv_pressure_via_short requires "
                                "per-layer wire, via, and capacity maps"
                            )
                        layer_wire_demand = layer_wire_demand.to(
                            self.device
                        ).float().contiguous()
                        layer_via_demand = layer_via_demand.to(
                            self.device
                        ).float().contiguous()
                        layer_capacity = layer_capacity.to(
                            self.device
                        ).float().contiguous()
                        for name, value in (
                            ("layer_wire_demand", layer_wire_demand),
                            ("layer_via_demand", layer_via_demand),
                            ("layer_capacity", layer_capacity),
                        ):
                            diagnostics.update(tensor_stats(name, value))
                            if diagnostics[name + "_nonfinite_count"]:
                                raise RuntimeError(
                                    "connection routeforce received "
                                    "non-finite %s: %s" % (name, diagnostics)
                                )
                        # Match the pinned evaluator at run_route(): its via
                        # short term is active where total routed demand has
                        # utilization above one, not only where wire demand
                        # alone exceeds capacity.
                        short_via_mask = (
                            layer_wire_demand + layer_via_demand
                            > layer_capacity
                        )
                        via_pressure_demand = torch.where(
                            short_via_mask,
                            layer_via_demand,
                            torch.zeros_like(layer_via_demand),
                        ).sum(dim=0).contiguous()
                        diagnostics.update(tensor_stats(
                            "short_via_demand", via_pressure_demand
                        ))
                        diagnostics["short_via_active_layer_bins"] = int(
                            short_via_mask.sum().item()
                        )
                    via_utilization = torch.where(
                        positive_capacity,
                        via_pressure_demand / raw_capacity.clamp_min(
                            torch.finfo(raw_capacity.dtype).eps
                        ),
                        zero_field,
                    ).contiguous()
                    via_pressure = (
                        via_utilization - via_utilization_threshold
                    ).clamp_min(0.0)
                    if dilation_radius:
                        kernel = dilation_radius * 2 + 1
                        via_pressure = F.max_pool2d(
                            via_pressure.unsqueeze(0).unsqueeze(0),
                            kernel_size=kernel,
                            stride=1,
                            padding=dilation_radius,
                        ).squeeze(0).squeeze(0)
                    via_pressure = torch.where(
                        positive_capacity, via_pressure, zero_field
                    ).contiguous()
                    diagnostics.update(tensor_stats(
                        "via_utilization", via_utilization
                    ))
                    diagnostics.update(tensor_stats(
                        "via_pressure", via_pressure
                    ))
                    field_x_source = (
                        field_x_source + float(unit_via_cost) * via_pressure
                    ).contiguous()
                    field_y_source = (
                        field_y_source + float(unit_via_cost) * via_pressure
                    ).contiguous()
        else:
            layer_demand = maps.get("layer_demand")
            layer_capacity = maps.get("layer_capacity")
            if layer_demand is None or layer_capacity is None:
                raise RuntimeError(
                    "max_layer connection routeforce requires per-layer maps"
                )
            layer_demand = layer_demand.to(
                self.device
            ).float().contiguous()
            layer_capacity = layer_capacity.to(
                self.device
            ).float().contiguous()
            diagnostics.update(tensor_stats("layer_demand", layer_demand))
            diagnostics.update(tensor_stats("layer_capacity", layer_capacity))
            if (diagnostics["layer_demand_nonfinite_count"] or
                    diagnostics["layer_capacity_nonfinite_count"]):
                raise RuntimeError(
                    "connection routeforce received non-finite per-layer maps: %s"
                    % diagnostics
                )
            positive_layer_capacity = layer_capacity > 0.0
            layer_utilization = torch.where(
                positive_layer_capacity,
                layer_demand / layer_capacity.clamp_min(
                    torch.finfo(layer_capacity.dtype).eps
                ),
                torch.zeros_like(layer_demand),
            )
            max_layer_field = (layer_utilization - 1.0).clamp_min(0.0).max(
                dim=0
            ).values
            max_layer_field = torch.where(
                positive_capacity, max_layer_field, zero_field
            ).contiguous()
            field_x_source = max_layer_field
            field_y_source = max_layer_field

        field_overflow = torch.maximum(
            field_x_source, field_y_source
        ).contiguous()
        mask_map = (
            (field_overflow > threshold) & positive_capacity
        ).float().contiguous()
        diagnostics.update(tensor_stats("field_overflow", field_overflow))
        fft_scale = self._connection_fft_scale(
            field_overflow.shape, field_overflow.device, field_overflow.dtype
        )
        cache_key = (
            tuple(field_overflow.shape), field_overflow.device,
            field_overflow.dtype,
        )
        operators = self.connection_dct_ops.get(cache_key)
        if operators is None:
            import dreamplace.ops.dct.dct2_fft2 as dct
            operators = (dct.DCT2(), dct.IDXST_IDCT(), dct.IDCT_IDXST())
            self.connection_dct_ops[cache_key] = operators
        dct2, idxst_idct, idct_idxst = operators
        def field_gradient(value, name):
            coefficients = dct2(value)
            diagnostics.update(tensor_stats(name + "_dct", coefficients))
            if diagnostics[name + "_dct_nonfinite_count"]:
                raise RuntimeError(
                    "connection routeforce DCT produced non-finite %s "
                    "coefficients: %s" % (name, diagnostics)
                )
            return (
                idxst_idct(coefficients * fft_scale[2]),
                idct_idxst(coefficients * fft_scale[3]),
            )

        if field_mode in (
            "directional_hv", "directional_hv_pressure",
            "directional_hv_pressure_via",
            "directional_hv_pressure_via_short",
        ):
            field_x, _ = field_gradient(field_x_source, "vertical_field")
            _, field_y = field_gradient(field_y_source, "horizontal_field")
        else:
            field_x, field_y = field_gradient(field_overflow, "field")
        route_gradmat = torch.stack((field_x, field_y)).contiguous()
        route_gradmat = route_gradmat.float().contiguous()
        diagnostics.update(tensor_stats("route_field", route_gradmat))
        if diagnostics["route_field_nonfinite_count"]:
            raise RuntimeError(
                "connection routeforce DCT produced a non-finite route field: %s"
                % diagnostics
            )

        max_n_grid = max(overflow.shape)
        dist_weights = torch.ones(
            max_n_grid + 2, dtype=torch.float32, device=self.device
        )
        if mode == "inverse_sqrt":
            dist_weights[1:] = 1.0 / torch.sqrt(torch.arange(
                1, max_n_grid + 2, dtype=torch.float32, device=self.device
            ))
        wirelength_weights = torch.ones_like(dist_weights)
        if max_wire_span + 1 < wirelength_weights.numel():
            wirelength_weights[max_wire_span + 1:] = 0.0

        # Xplace's kernel divides by min(capacity, 0.2). A zero-capacity
        # boundary bin would otherwise produce inf*0 and poison the gradient.
        safe_capacity = raw_capacity.clamp_min(0.2).contiguous()
        active_bins = int(mask_map.sum().item())
        if active_bins:
            route_grad = route.routeforce.route_grad
            route_grad_args = (
                mask_map,
                wire_demand,
                via_demand,
                safe_capacity,
                dist_weights,
                wirelength_weights,
                route_gradmat,
                self.node2pin_list,
                self.node2pin_list_end,
                -1.0,
                float(unit_wire_cost),
                float(unit_via_cost),
                self.x_num_nodes,
            )
            if segment_reduction == "last" or (
                segment_reduction == "blend" and segment_blend == 0.0
            ):
                x_grad = route_grad(*route_grad_args)
            else:
                route_grad_reduce = getattr(
                    route.routeforce, "route_grad_reduce", None
                )
                if route_grad_reduce is None:
                    raise RuntimeError(
                        "multisegment connection routeforce requires the bundled "
                        "route_grad_reduce extension"
                    )
                reduce_mode = 1 if segment_reduction == "blend" else (
                    segment_reduction_ids[segment_reduction]
                )
                reduced_grad = route_grad_reduce(
                    *route_grad_args, reduce_mode,
                )
                if segment_reduction != "blend" or segment_blend == 1.0:
                    x_grad = reduced_grad
                else:
                    reference_grad = route_grad(*route_grad_args)
                    x_grad = torch.lerp(
                        reference_grad, reduced_grad, segment_blend
                    )
        else:
            # Xplace's connection kernel can emit NaNs for empty masks because
            # it still traverses every routed segment. There is no force to
            # compute in this case, so avoid the kernel entirely.
            x_grad = torch.zeros(
                (self.x_num_nodes, 2), dtype=torch.float32,
                device=self.device,
            )
        diagnostics.update(tensor_stats("raw_route_gradient", x_grad))
        if diagnostics["raw_route_gradient_nonfinite_count"]:
            raise RuntimeError(
                "Xplace connection routeforce kernel produced a non-finite "
                "gradient: %s" % diagnostics
            )

        grad = torch.zeros_like(pos)
        num_nodes = self.placedb.num_nodes
        if self.dp_movable_ids is not None and self.dp_movable_ids.numel():
            dp_ids = self.dp_movable_ids.to(grad.device)
            x_ids = self.x_movable_ids.to(x_grad.device)
            grad[dp_ids] = x_grad[x_ids, 0].to(
                device=grad.device, dtype=grad.dtype
            )
            grad[num_nodes + dp_ids] = x_grad[x_ids, 1].to(
                device=grad.device, dtype=grad.dtype
            )
        metrics = {
            "overflow_active_bins": active_bins,
            "overflow_max": float(overflow.max().item()),
            "field_overflow_max": float(field_overflow.max().item()),
            "zero_capacity_bins": int((~positive_capacity).sum().item()),
            "max_wire_span": max_wire_span,
            "distance_weighting_id": 0 if mode == "uniform" else 1,
            "field_mode_id": field_mode_ids[field_mode],
            "segment_reduction_id": segment_reduction_ids[segment_reduction],
            "segment_blend": segment_blend,
            "utilization_threshold": utilization_threshold,
            "pressure_exponent": pressure_exponent,
            "via_utilization_threshold": via_utilization_threshold,
            "dilation_radius": dilation_radius,
            "kernel_skipped_empty_mask": int(active_bins == 0),
        }
        metrics.update(diagnostics)
        return grad, metrics

    def admm_gradient(self, pos, refresh=False):
        """Return Xplace's ADMM objective gradient in DREAMPlace node order.

        Xplace adds this tensor to its placement gradient before optimizer
        descent. Preserve that sign here: the route term contracts congested
        segments, while the anchor term pulls nodes toward their route anchor.
        """
        if self.external_route_eval:
            return torch.zeros_like(pos)
        if refresh or self.last_route is None:
            self.run_route(pos)
        route = self.last_route
        node_pos = self._scaled_xplace_centers(pos)
        movable_pos = node_pos[: self.x_movable_end].contiguous()
        self._update_admm_anchor(movable_pos, refresh)

        max_n_grid = max(route.overflow_map.shape[0], route.overflow_map.shape[1])
        dist_weights = torch.ones(max_n_grid + 2, dtype=torch.float32, device=self.device)
        dist_weights[1:] = 1.0 / torch.sqrt(torch.arange(1, max_n_grid + 2, dtype=torch.float32, device=self.device))
        wirelength_weights = torch.ones(max_n_grid + 2, dtype=torch.float32, device=self.device)
        x_grad = route.routeforce.admm_route_grad(
            route.overflow_map.to(self.device).float().contiguous(),
            dist_weights,
            wirelength_weights,
            self.node2pin_list,
            self.node2pin_list_end,
            movable_pos.float().contiguous(),
            self.anchor_pos.float().contiguous(),
            1.0,
            float(self.params.ruplace_admm_anchor_weight),
            self.x_num_nodes,
            self.x_movable_end,
        )

        grad = torch.zeros_like(pos)
        num_nodes = self.placedb.num_nodes
        if self.dp_movable_ids is not None and self.dp_movable_ids.numel():
            dp_ids = self.dp_movable_ids.to(grad.device)
            x_ids = self.x_movable_ids.to(x_grad.device)
            grad[dp_ids] = x_grad[x_ids, 0].to(device=grad.device, dtype=grad.dtype)
            grad[num_nodes + dp_ids] = x_grad[x_ids, 1].to(device=grad.device, dtype=grad.dtype)
        return grad

    def routed_overflow_contraction_gradient(
            self, pos, refresh=False, mode="directional",
            overflow_threshold=0.0, overflow_exponent=1.0,
            max_wire_span=19, distance_weighting="uniform",
            matching_contraction_scale=1.0, orthogonal_spread_scale=0.0,
            smoothing_radius=0,
            smoothing_padding="replicate", utilization_pressure_scale=0.0,
            utilization_threshold=1.0, utilization_exponent=1.0):
        """Contract routed segments that traverse overflowing resources."""
        if self.external_route_eval:
            raise RuntimeError(
                "routed overflow contraction requires in-process gpugr feedback"
            )
        mode = str(mode).lower()
        distance_weighting = str(distance_weighting).lower()
        overflow_threshold = float(overflow_threshold)
        overflow_exponent = float(overflow_exponent)
        max_wire_span = int(max_wire_span)
        matching_contraction_scale = float(matching_contraction_scale)
        orthogonal_spread_scale = float(orthogonal_spread_scale)
        smoothing_radius = int(smoothing_radius)
        smoothing_padding = str(smoothing_padding).lower()
        utilization_pressure_scale = float(utilization_pressure_scale)
        utilization_threshold = float(utilization_threshold)
        utilization_exponent = float(utilization_exponent)
        if mode not in ("aggregate", "directional"):
            raise ValueError(
                "unsupported routed overflow contraction mode: %s" % mode
            )
        if not math.isfinite(overflow_threshold) or overflow_threshold < 0.0:
            raise ValueError(
                "routed overflow contraction threshold must be finite and nonnegative"
            )
        if not math.isfinite(overflow_exponent) or overflow_exponent <= 0.0:
            raise ValueError(
                "routed overflow contraction exponent must be finite and positive"
            )
        if max_wire_span < 0:
            raise ValueError(
                "routed overflow contraction max wire span must be nonnegative"
            )
        if distance_weighting not in ("uniform", "inverse_sqrt"):
            raise ValueError(
                "unsupported routed overflow contraction distance weighting: %s"
                % distance_weighting
            )
        if (not math.isfinite(matching_contraction_scale)
                or matching_contraction_scale < 0.0):
            raise ValueError(
                "routed overflow contraction matching scale must be finite "
                "and nonnegative"
            )
        if (not math.isfinite(orthogonal_spread_scale)
                or orthogonal_spread_scale < 0.0):
            raise ValueError(
                "routed overflow contraction orthogonal spread scale must be "
                "finite and nonnegative"
            )
        if smoothing_radius < 0:
            raise ValueError(
                "routed overflow contraction smoothing radius must be "
                "nonnegative"
            )
        if smoothing_padding not in ("zero", "replicate"):
            raise ValueError(
                "unsupported routed overflow contraction smoothing padding: %s"
                % smoothing_padding
            )
        if (not math.isfinite(utilization_pressure_scale)
                or utilization_pressure_scale < 0.0):
            raise ValueError(
                "routed overflow contraction utilization pressure scale must "
                "be finite and nonnegative"
            )
        if (not math.isfinite(utilization_threshold)
                or utilization_threshold < 0.0):
            raise ValueError(
                "routed overflow contraction utilization threshold must be "
                "finite and nonnegative"
            )
        if (not math.isfinite(utilization_exponent)
                or utilization_exponent <= 0.0):
            raise ValueError(
                "routed overflow contraction utilization exponent must be "
                "finite and positive"
            )
        if refresh or self.last_route is None:
            self.run_route(pos)
        route = self.last_route
        if route.routeforce is None:
            raise RuntimeError(
                "routed overflow contraction requires native route data"
            )

        def prepare_overflow(value):
            value = value.to(self.device).float().contiguous()
            if not torch.isfinite(value).all():
                raise RuntimeError(
                    "routed overflow contraction received a non-finite overflow map"
                )
            value = (value - overflow_threshold).clamp_min(0.0)
            if overflow_exponent != 1.0:
                value = value.pow(overflow_exponent)
            return value.contiguous()

        def smooth_overflow(value):
            if smoothing_radius == 0:
                return value
            kernel = 2 * smoothing_radius + 1
            batched = value[None, None]
            if smoothing_padding == "replicate":
                batched = F.pad(
                    batched,
                    (
                        smoothing_radius,
                        smoothing_radius,
                        smoothing_radius,
                        smoothing_radius,
                    ),
                    mode="replicate",
                )
                return F.avg_pool2d(
                    batched, kernel_size=kernel, stride=1
                )[0, 0].contiguous()
            return F.avg_pool2d(
                batched,
                kernel_size=kernel,
                stride=1,
                padding=smoothing_radius,
            )[0, 0].contiguous()

        def utilization_pressure(value):
            value = value.to(self.device).float().contiguous()
            if not torch.isfinite(value).all():
                raise RuntimeError(
                    "routed overflow contraction received a non-finite "
                    "utilization map"
                )
            value = (value - utilization_threshold).clamp_min(0.0)
            if utilization_exponent != 1.0:
                value = value.pow(utilization_exponent)
            return value.contiguous()

        aggregate = prepare_overflow(route.overflow_map)
        aggregate_pressure_active_bins = 0
        if utilization_pressure_scale != 0.0:
            pressure = utilization_pressure(route.utilization_map)
            aggregate_pressure_active_bins = int((pressure > 0.0).sum().item())
            aggregate = aggregate + utilization_pressure_scale * pressure
        aggregate = smooth_overflow(aggregate)
        max_n_grid = max(aggregate.shape)
        dist_weights = torch.ones(
            max_n_grid + 2, dtype=torch.float32, device=self.device
        )
        if distance_weighting == "inverse_sqrt":
            dist_weights[1:] = 1.0 / torch.sqrt(torch.arange(
                1, max_n_grid + 2, dtype=torch.float32, device=self.device
            ))
        wirelength_weights = torch.ones_like(dist_weights)
        if max_wire_span + 1 < wirelength_weights.numel():
            wirelength_weights[max_wire_span + 1:] = 0.0

        node_pos = self._scaled_xplace_centers(pos)
        movable_pos = node_pos[: self.x_movable_end].float().contiguous()

        def native_gradient(overflow):
            return route.routeforce.admm_route_grad(
                overflow,
                dist_weights,
                wirelength_weights,
                self.node2pin_list,
                self.node2pin_list_end,
                movable_pos,
                movable_pos,
                1.0,
                0.0,
                self.x_num_nodes,
                self.x_movable_end,
            )

        horizontal_active_bins = 0
        vertical_active_bins = 0
        horizontal_pressure_active_bins = 0
        vertical_pressure_active_bins = 0
        if mode == "directional":
            if route.hv_overflow_map is None:
                raise RuntimeError(
                    "directional routed overflow contraction requires H/V overflow maps"
                )
            directional = route.hv_overflow_map
            if directional.ndim != 3 or directional.shape[0] != 2:
                raise RuntimeError(
                    "directional routed overflow contraction requires a [2, X, Y] map"
                )
            horizontal = prepare_overflow(directional[0])
            vertical = prepare_overflow(directional[1])
            if utilization_pressure_scale != 0.0:
                directional_utilization = route.hv_utilization_map
                if directional_utilization is None:
                    raise RuntimeError(
                        "routed overflow contraction utilization pressure "
                        "requires H/V utilization maps"
                    )
                if (directional_utilization.ndim != 3
                        or directional_utilization.shape[0] != 2):
                    raise RuntimeError(
                        "routed overflow contraction utilization pressure "
                        "requires a [2, X, Y] map"
                    )
                horizontal_pressure = utilization_pressure(
                    directional_utilization[0]
                )
                vertical_pressure = utilization_pressure(
                    directional_utilization[1]
                )
                horizontal_pressure_active_bins = int(
                    (horizontal_pressure > 0.0).sum().item()
                )
                vertical_pressure_active_bins = int(
                    (vertical_pressure > 0.0).sum().item()
                )
                horizontal = (
                    horizontal
                    + utilization_pressure_scale * horizontal_pressure
                )
                vertical = (
                    vertical
                    + utilization_pressure_scale * vertical_pressure
                )
            horizontal = smooth_overflow(horizontal)
            vertical = smooth_overflow(vertical)
            horizontal_grad = native_gradient(horizontal)
            vertical_grad = native_gradient(vertical)
            x_grad = torch.zeros_like(horizontal_grad)
            # Blend matching-axis contraction with reversed cross response.
            # A zero matching scale and nonzero spread is pure orthogonal relief.
            x_grad[:, 0] = (
                matching_contraction_scale * horizontal_grad[:, 0]
                - orthogonal_spread_scale * vertical_grad[:, 0]
            )
            x_grad[:, 1] = (
                matching_contraction_scale * vertical_grad[:, 1]
                - orthogonal_spread_scale * horizontal_grad[:, 1]
            )
            horizontal_active_bins = int((horizontal > 0.0).sum().item())
            vertical_active_bins = int((vertical > 0.0).sum().item())
        else:
            x_grad = native_gradient(aggregate)

        if not torch.isfinite(x_grad).all():
            raise RuntimeError(
                "routed overflow contraction produced a non-finite native gradient"
            )
        grad = torch.zeros_like(pos)
        num_nodes = self.placedb.num_nodes
        if self.dp_movable_ids is not None and self.dp_movable_ids.numel():
            dp_ids = self.dp_movable_ids.to(grad.device)
            x_ids = self.x_movable_ids.to(x_grad.device)
            grad[dp_ids] = x_grad[x_ids, 0].to(
                device=grad.device, dtype=grad.dtype
            )
            grad[num_nodes + dp_ids] = x_grad[x_ids, 1].to(
                device=grad.device, dtype=grad.dtype
            )
        metrics = {
            "route_refreshed": int(bool(refresh)),
            "overflow_net_count": int(route.metrics.get("num_ovfl_nets", 0)),
            "aggregate_active_bins": int((aggregate > 0.0).sum().item()),
            "aggregate_pressure_active_bins": aggregate_pressure_active_bins,
            "horizontal_active_bins": horizontal_active_bins,
            "vertical_active_bins": vertical_active_bins,
            "horizontal_pressure_active_bins": horizontal_pressure_active_bins,
            "vertical_pressure_active_bins": vertical_pressure_active_bins,
            "overflow_threshold": overflow_threshold,
            "overflow_exponent": overflow_exponent,
            "max_wire_span": max_wire_span,
            "raw_gradient_norm": float(torch.linalg.vector_norm(grad).item()),
            "contraction_mode": mode,
            "distance_weighting": distance_weighting,
            "matching_contraction_scale": matching_contraction_scale,
            "orthogonal_spread_scale": orthogonal_spread_scale,
            "smoothing_radius": smoothing_radius,
            "smoothing_padding": smoothing_padding,
            "smoothing_padding_id": {
                "zero": 0,
                "replicate": 1,
            }[smoothing_padding],
            "utilization_pressure_scale": utilization_pressure_scale,
            "utilization_threshold": utilization_threshold,
            "utilization_exponent": utilization_exponent,
        }
        return grad, metrics

    def _update_admm_anchor(self, movable_pos, refresh):
        mode = str(getattr(self.params, "ruplace_admm_anchor_update", "refresh")).lower()
        if self.anchor_pos is None or self.anchor_pos.shape != movable_pos.shape:
            self.anchor_pos = movable_pos.detach().clone()
            return
        if not refresh:
            return
        if mode in ("static", "fixed", "none"):
            return
        if mode == "ema":
            decay = float(getattr(self.params, "ruplace_admm_anchor_decay", 0.9))
            decay = min(max(decay, 0.0), 1.0)
            self.anchor_pos.mul_(decay).add_(movable_pos.detach(), alpha=1.0 - decay)
            return
        self.anchor_pos = movable_pos.detach().clone()


def _grdb_attr(grdb, name, default=None):
    """Read an optional GRDatabase pybind attribute (older builds lack the A0 bindings)."""
    try:
        return getattr(grdb, name)
    except Exception:
        return default


def _dump_raw_gr_maps(
    path,
    grdb,
    gpdb,
    dmd_map,
    wire_dmd_map,
    via_dmd_map,
    cap_map,
    fixed_map,
    m1direction,
    h_id,
    v_id,
    all_start,
    gr_wirelength,
    gr_vias,
    num_ovfl_nets,
    args,
    timings,
):
    """torch.save the per-layer GR maps plus the grid geometry needed to align them
    with an external router's gcell grid (RUPlace calibration harness, item A0)."""
    gridlines = _grdb_attr(grdb, "gridlines", [[], []]) or [[], []]
    payload = {
        "dmd_map": dmd_map.detach().float().cpu(),
        "wire_dmd_map": wire_dmd_map.detach().float().cpu(),
        "via_dmd_map": via_dmd_map.detach().float().cpu(),
        "cap_map": cap_map.detach().float().cpu(),
        # RUPlace (batch 1, item 6): per-gcell blocked ("fixed") tracks, same [L, X, Y]
        # layout as cap_map, so the harness can form wire/(cap - fixed).
        "fixed_map": (None if fixed_map is None else fixed_map.detach().float().cpu()),
        "gridlines_x": [int(v) for v in gridlines[0]],
        "gridlines_y": [int(v) for v in gridlines[1]],
        "m1direction": int(m1direction),
        "h_id": int(h_id),
        "v_id": int(v_id),
        "all_start": int(all_start),
        "x_size": _grdb_attr(grdb, "x_size"),
        "y_size": _grdb_attr(grdb, "y_size"),
        "n_layers": _grdb_attr(grdb, "n_layers"),
        "microns": _grdb_attr(grdb, "microns"),
        "main_gcell_step_x": _grdb_attr(grdb, "main_gcell_step_x"),
        "main_gcell_step_y": _grdb_attr(grdb, "main_gcell_step_y"),
        "layer_width": list(_grdb_attr(grdb, "layer_width", []) or []),
        "layer_pitch": list(_grdb_attr(grdb, "layer_pitch", []) or []),
        "report_gr_stat": {"wl_steps": float(gr_wirelength), "vias": float(gr_vias)},
        "num_ovfl_nets": int(num_ovfl_nets),
        "route_x_size": int(args.route_x_size),
        "route_y_size": int(args.route_y_size),
        "rrr_iters": int(args.rrr_iters),
        "design_name": args.design_name,
        "def_input": os.path.abspath(args.def_input),
        "timings": dict(timings),
    }
    out = os.path.abspath(path)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    torch.save(payload, out)
    logging.info(
        "RUPlace dumped GR maps to %s (dmd %s, cap %s, grid %sx%s)",
        out,
        tuple(payload["dmd_map"].shape),
        tuple(payload["cap_map"].shape),
        payload["x_size"],
        payload["y_size"],
    )
    print("RUPlace dump-maps: %s" % out)


def _gcell_geometry(routeforce):
    """(step_x, step_y, microns) if the router exposes them, else (None, None, None).

    Only used to add the purely additive ``gr_wirelength_um`` metric; every legacy metric
    is unaffected when this returns Nones.
    """
    try:
        step_x, step_y = routeforce.gcell_steps()
        return step_x, step_y, float(routeforce.microns())
    except Exception:
        return None, None, None


def _external_eval_main(argv):
    parser = argparse.ArgumentParser("RUPlace external Xplace GGR evaluator")
    parser.add_argument("--ruplace-external-eval", action="store_true")
    parser.add_argument("--lef-input", action="append", required=True)
    parser.add_argument("--def-input", required=True)
    parser.add_argument("--verilog-input", default="")
    parser.add_argument("--design-name", required=True)
    parser.add_argument("--xplace-root", required=True)
    parser.add_argument("--route-x-size", type=int, default=0)
    parser.add_argument("--route-y-size", type=int, default=0)
    parser.add_argument("--rrr-iters", type=int, default=1)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--num-threads", type=int, default=8)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dump-maps", default="", help="torch.save raw per-layer GR maps + grid geometry here")
    # ---- RUPlace s14 fidelity knobs (defaults = legacy GPUGR behavior) ----
    parser.add_argument("--max_route_len_per_pin", "--max-route-len-per-pin",
                        dest="max_route_len_per_pin", type=int, default=130)
    parser.add_argument("--m1_routable", "--m1-routable",
                        dest="m1_routable", type=int, default=1)
    parser.add_argument("--via_usage_scale", "--via-usage-scale",
                        dest="via_usage_scale", type=float, default=1.5)
    parser.add_argument("--wire_cost_sat", "--wire-cost-sat",
                        dest="wire_cost_sat", type=int, default=0)
    parser.add_argument("--util_mode", "--util-mode", dest="util_mode",
                        choices=list(gr_metrics.UTIL_MODES), default="legacy")
    args = parser.parse_args(argv)

    timings = {}
    xplace_root = os.path.abspath(args.xplace_root)
    if xplace_root not in sys.path:
        sys.path.insert(0, xplace_root)
    gpugr = _load_xplace_gpugr(xplace_root)
    IOParser = _load_xplace_ioparser(xplace_root)

    gpugr.read_flute(
        os.path.join(xplace_root, "thirdparty", "flute", "POWV9.dat"),
        os.path.join(xplace_root, "thirdparty", "flute", "POST9.dat"),
    )
    io_params = {
        "benchmark": "dreamplace",
        "lefs": [os.path.abspath(lef) for lef in args.lef_input],
        "def": os.path.abspath(args.def_input),
        "design_name": args.design_name,
    }
    if args.verilog_input:
        io_params["verilog"] = os.path.abspath(args.verilog_input)
    _t0 = time.time()
    rawdb, gpdb = IOParser().read(
        io_params,
        verbose_log=False,
        lite_mode=True,
        random_place=False,
        num_threads=args.num_threads,
    )
    timings["parse_sec"] = time.time() - _t0
    gpugr.load_gr_params(
        {
            "device_id": args.gpu,
            "route_xSize": args.route_x_size,
            "route_ySize": args.route_y_size,
            "rrrIters": args.rrr_iters,
            "max_route_len_per_pin": int(args.max_route_len_per_pin),
            "m1_routable": int(args.m1_routable),
            "via_usage_scale": float(args.via_usage_scale),
            "wire_cost_sat": int(args.wire_cost_sat),
        }
    )
    _t0 = time.time()
    grdb = gpugr.create_grdatabase(rawdb, gpdb)
    timings["create_grdatabase_sec"] = time.time() - _t0
    _t0 = time.time()
    routeforce = gpugr.create_routeforce(grdb)
    timings["create_routeforce_sec"] = time.time() - _t0
    _t0 = time.time()
    routeforce.run_ggr()
    timings["run_ggr_sec"] = time.time() - _t0

    dmd_map, wire_dmd_map, via_dmd_map = routeforce.dmd_map()
    cap_map = routeforce.cap_map()
    try:
        fixed_map = routeforce.fixed_map()
    except AttributeError:
        fixed_map = None
    m1direction = gpdb.m1direction()
    h_id, v_id = gr_metrics.hv_layer_ids(m1direction)
    all_start = 1

    util_mode = args.util_mode
    if util_mode == "avail" and fixed_map is None:
        print("WARNING: --util-mode avail requested but the router exposes no fixed_map(); "
              "falling back to legacy")
        util_mode = "legacy"
    util_map, overflow_map, hv_utilization, hv_overflow = gr_metrics.hv_maps(
        dmd_map, wire_dmd_map, via_dmd_map, cap_map,
        fixed=fixed_map, m1direction=m1direction, util_mode=util_mode,
    )
    overflow_map = overflow_map.cpu()
    hv_utilization = hv_utilization.cpu()
    hv_overflow = hv_overflow.cpu()
    try:
        gr_wirelength, gr_vias = grdb.report_gr_stat()
    except Exception:
        gr_wirelength, gr_vias = 0, 0
    _sx, _sy, _um = _gcell_geometry(routeforce)
    metrics = gr_metrics.route_metrics(
        num_ovfl_nets=int(routeforce.num_ovfl_nets()),
        hv_overflow=hv_overflow,
        dmd_map=dmd_map, wire_dmd_map=wire_dmd_map, via_dmd_map=via_dmd_map, cap_map=cap_map,
        wl_steps=gr_wirelength, gr_vias=gr_vias,
        step_x=_sx, step_y=_sy, microns=_um,
    )
    metrics["time"] = 0.0
    metrics.update(timings)
    if args.dump_maps:
        _dump_raw_gr_maps(
            args.dump_maps,
            grdb=grdb,
            gpdb=gpdb,
            dmd_map=dmd_map,
            wire_dmd_map=wire_dmd_map,
            via_dmd_map=via_dmd_map,
            cap_map=cap_map,
            fixed_map=fixed_map,
            m1direction=m1direction,
            h_id=h_id,
            v_id=v_id,
            all_start=all_start,
            gr_wirelength=gr_wirelength,
            gr_vias=gr_vias,
            num_ovfl_nets=int(routeforce.num_ovfl_nets()),
            args=args,
            timings=timings,
        )
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    torch.save(
        {
            "overflow_map": overflow_map,
            "utilization_map": util_map.cpu(),
            "hv_overflow_map": hv_overflow,
            "hv_utilization_map": hv_utilization,
            "metrics": metrics,
        },
        args.output,
    )
    print("RUPlace external metrics: %s" % metrics)
    return 0


if __name__ == "__main__":
    if "--ruplace-external-eval" in sys.argv:
        raise SystemExit(_external_eval_main(sys.argv[1:]))


# Backward/neutral aliases used by the standalone GPUGR facade.
GPUGRResult = RUPlaceRouteResult
XplaceBackend = XplaceGGRAdapter
