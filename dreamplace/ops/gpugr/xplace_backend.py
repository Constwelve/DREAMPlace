##
# @file   xplace_backend.py
# @brief  Xplace GPU-router backend for RUPlace/standalone GPUGR.
#

import logging
import os
import argparse
import importlib
import importlib.util
import subprocess
import sys
import time
import types

import torch
import torch.nn.functional as F


class RUPlaceRouteResult(object):
    def __init__(self, routeforce, overflow_map, utilization_map, hv_overflow_map, metrics):
        self.routeforce = routeforce
        self.overflow_map = overflow_map
        self.utilization_map = utilization_map
        self.hv_overflow_map = hv_overflow_map
        self.metrics = metrics


def _load_xplace_extension(xplace_root, name):
    cpybin = os.path.join(xplace_root, "cpp_to_py", "cpybin")
    if cpybin not in sys.path:
        sys.path.insert(0, cpybin)
    return importlib.import_module(name)


def _install_minimal_cpp_to_py(xplace_root):
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
        # DREAMPlace preserves DEF escaping for bus-indexed instance names
        # (e.g. reg\[0\]) while Xplace reports the logical Verilog name
        # (reg[0]). Normalize only those DEF escape markers for name matching.
        return name.replace("\\[", "[").replace("\\]", "]")

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

    def _route_params(self):
        route_guide = ""
        try:
            out_dir = os.path.join(self.params.result_dir, self.params.design_name(), "ruplace")
            os.makedirs(out_dir, exist_ok=True)
            route_guide = os.path.join(out_dir, "latest.guide")
        except Exception:
            pass
        route_gpu = getattr(self.params, "ruplace_route_gpu", None)
        if route_gpu is None:
            route_gpu = 0
        return {
            "device_id": int(route_gpu),
            "route_xSize": int(self.placedb.num_routing_grids_x or self.params.route_num_bins_x),
            "route_ySize": int(self.placedb.num_routing_grids_y or self.params.route_num_bins_y),
            "rrrIters": int(self.params.ruplace_gr_rrr_iters),
            "route_guide": route_guide,
        }

    def run_route(self, pos):
        if self.external_route_eval:
            return self._run_route_external(pos)
        tt = time.time()
        self.gpdb.apply_node_lpos(self._scaled_to_raw_lpos(pos))
        self.gpugr.load_gr_params(self._route_params())
        grdb = self.gpugr.create_grdatabase(self.rawdb, self.gpdb)
        routeforce = self.gpugr.create_routeforce(grdb)
        routeforce.run_ggr()

        dmd_map, wire_dmd_map, via_dmd_map = routeforce.dmd_map()
        cap_map = routeforce.cap_map()
        eps = torch.finfo(dmd_map.dtype).eps
        util_by_layer = dmd_map / cap_map.clamp_min(eps)

        m1direction = self.gpdb.m1direction()
        h_id = 1 if m1direction else 0
        v_id = 0 if m1direction else 1
        h_id = h_id + 2 if h_id == 0 else h_id
        v_id = v_id + 2 if v_id == 0 else v_id
        all_start = 1

        util_map = dmd_map[all_start:].sum(dim=0) / cap_map[all_start:].sum(dim=0).clamp_min(eps)
        util_map = torch.nan_to_num(util_map, nan=0.0, posinf=0.0, neginf=0.0)
        overflow_map = (util_map - 1).clamp_min(0).contiguous()
        cg_h = dmd_map[h_id::2].sum(dim=0) / cap_map[h_id::2].sum(dim=0).clamp_min(eps)
        cg_v = dmd_map[v_id::2].sum(dim=0) / cap_map[v_id::2].sum(dim=0).clamp_min(eps)
        cg_h = torch.nan_to_num(cg_h, nan=0.0, posinf=0.0, neginf=0.0)
        cg_v = torch.nan_to_num(cg_v, nan=0.0, posinf=0.0, neginf=0.0)
        hv_overflow = torch.stack(((cg_h - 1).clamp_min(0), (cg_v - 1).clamp_min(0))).contiguous()

        try:
            gr_wirelength, gr_vias = grdb.report_gr_stat()
        except Exception:
            gr_wirelength, gr_vias = 0, 0
        est_shorts = (wire_dmd_map - cap_map).clamp_min(0).sum().item() + via_dmd_map[util_by_layer > 1].sum().item()
        metrics = {
            "num_ovfl_nets": int(routeforce.num_ovfl_nets()),
            "gr_wirelength": float(gr_wirelength),
            "gr_vias": float(gr_vias),
            "est_shorts": float(est_shorts),
            "rc_hor": float(hv_overflow[0].mean().item()),
            "rc_ver": float(hv_overflow[1].mean().item()),
            "time": time.time() - tt,
        }
        logging.info(
            "RUPlace GR: #OvflNets %d, GR WL %.3f, vias %.3f, estShorts %.3f, RC(H/V) %.4f/%.4f, %.2fs",
            metrics["num_ovfl_nets"],
            metrics["gr_wirelength"],
            metrics["gr_vias"],
            metrics["est_shorts"],
            metrics["rc_hor"],
            metrics["rc_ver"],
            metrics["time"],
        )
        self.last_route = RUPlaceRouteResult(routeforce, overflow_map, util_map.contiguous(), hv_overflow, metrics)
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
        self.last_route = RUPlaceRouteResult(None, overflow_map, util_map, hv_overflow, metrics)
        return self.last_route

    def admm_gradient(self, pos, refresh=False):
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
    args = parser.parse_args(argv)

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
    rawdb, gpdb = IOParser().read(
        io_params,
        verbose_log=False,
        lite_mode=True,
        random_place=False,
        num_threads=args.num_threads,
    )
    gpugr.load_gr_params(
        {
            "device_id": args.gpu,
            "route_xSize": args.route_x_size,
            "route_ySize": args.route_y_size,
            "rrrIters": args.rrr_iters,
        }
    )
    grdb = gpugr.create_grdatabase(rawdb, gpdb)
    routeforce = gpugr.create_routeforce(grdb)
    routeforce.run_ggr()

    dmd_map, wire_dmd_map, via_dmd_map = routeforce.dmd_map()
    cap_map = routeforce.cap_map()
    eps = torch.finfo(dmd_map.dtype).eps
    util_by_layer = dmd_map / cap_map.clamp_min(eps)

    m1direction = gpdb.m1direction()
    h_id = 1 if m1direction else 0
    v_id = 0 if m1direction else 1
    h_id = h_id + 2 if h_id == 0 else h_id
    v_id = v_id + 2 if v_id == 0 else v_id
    all_start = 1

    util_map = dmd_map[all_start:].sum(dim=0) / cap_map[all_start:].sum(dim=0).clamp_min(eps)
    util_map = torch.nan_to_num(util_map, nan=0.0, posinf=0.0, neginf=0.0)
    overflow_map = (util_map - 1).clamp_min(0).cpu()
    cg_h = dmd_map[h_id::2].sum(dim=0) / cap_map[h_id::2].sum(dim=0).clamp_min(eps)
    cg_v = dmd_map[v_id::2].sum(dim=0) / cap_map[v_id::2].sum(dim=0).clamp_min(eps)
    cg_h = torch.nan_to_num(cg_h, nan=0.0, posinf=0.0, neginf=0.0)
    cg_v = torch.nan_to_num(cg_v, nan=0.0, posinf=0.0, neginf=0.0)
    hv_overflow = torch.stack(((cg_h - 1).clamp_min(0), (cg_v - 1).clamp_min(0))).cpu()
    try:
        gr_wirelength, gr_vias = grdb.report_gr_stat()
    except Exception:
        gr_wirelength, gr_vias = 0, 0
    est_shorts = (wire_dmd_map - cap_map).clamp_min(0).sum().item() + via_dmd_map[util_by_layer > 1].sum().item()
    metrics = {
        "num_ovfl_nets": int(routeforce.num_ovfl_nets()),
        "gr_wirelength": float(gr_wirelength),
        "gr_vias": float(gr_vias),
        "est_shorts": float(est_shorts),
        "rc_hor": float(hv_overflow[0].mean().item()),
        "rc_ver": float(hv_overflow[1].mean().item()),
        "time": 0.0,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    torch.save(
        {
            "overflow_map": overflow_map,
            "utilization_map": util_map.cpu(),
            "hv_overflow_map": hv_overflow,
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
