"""Command-line entrypoint for standalone GPUGR evaluation."""

import argparse
import json
import sys

from dreamplace.ops.gpugr.base import GPUGRRequest
from dreamplace.ops.gpugr.instantgr_backend import InstantGRBackend


def main(argv=None):
    parser = argparse.ArgumentParser("Standalone DREAMPlace GPUGR frontend")
    parser.add_argument("--backend", default="xplace", choices=["xplace", "instantgr"])
    parser.add_argument("--design-name", required=True)
    parser.add_argument("--lef-input", action="append", default=[])
    parser.add_argument("--def-input", default="")
    parser.add_argument("--verilog-input", default="")
    parser.add_argument("--xplace-root", default="../Xplace")
    parser.add_argument("--cap-input", default="")
    parser.add_argument("--net-input", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--route-x-size", type=int, default=0)
    parser.add_argument("--route-y-size", type=int, default=0)
    parser.add_argument("--rrr-iters", type=int, default=1)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--num-threads", type=int, default=8)
    args = parser.parse_args(argv)
    if args.backend == "xplace":
        from dreamplace.ops.gpugr.xplace_backend import _external_eval_main

        output = args.output or GPUGRRequest(design_name=args.design_name, output_dir=args.output_dir).output_path(
            args.design_name + ".xplace_ggr.pt"
        )
        if not args.lef_input or not args.def_input:
            raise RuntimeError("xplace backend requires --lef-input and --def-input")
        cli = [
            "--ruplace-external-eval",
            "--def-input",
            args.def_input,
            "--design-name",
            args.design_name,
            "--xplace-root",
            args.xplace_root,
            "--route-x-size",
            str(args.route_x_size),
            "--route-y-size",
            str(args.route_y_size),
            "--rrr-iters",
            str(args.rrr_iters),
            "--gpu",
            str(args.gpu),
            "--num-threads",
            str(args.num_threads),
            "--output",
            str(output),
        ]
        for lef in args.lef_input:
            cli.extend(["--lef-input", lef])
        if args.verilog_input:
            cli.extend(["--verilog-input", args.verilog_input])
        return _external_eval_main(cli)

    req = GPUGRRequest(
        design_name=args.design_name,
        backend=args.backend,
        cap_input=args.cap_input,
        net_input=args.net_input,
        output_dir=args.output_dir,
    )
    result = InstantGRBackend().route(req)
    print(json.dumps({"metrics": result.metrics, "artifacts": result.artifacts}, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
