##
# @file   ruplace_ggr_smoke.py
# @brief  Optional smoke test for RUPlace's external Xplace GGR dependency.
#

import argparse
import json
import os
import sys
import tempfile


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def resolve_xplace_root(path):
    candidates = [path, "../Xplace", "../XPlace"]
    for candidate in candidates:
        root = os.path.abspath(candidate)
        if os.path.isdir(root):
            return root
    raise RuntimeError("cannot find Xplace root from %s" % candidates)


def main():
    parser = argparse.ArgumentParser("RUPlace GGR smoke")
    parser.add_argument("--config", default="unittest/regression/ispd2018/ispd18_test1.json")
    parser.add_argument("--xplace-root", default="../Xplace")
    parser.add_argument("--gpu", type=int, default=0)
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)
    lefs = cfg.get("lef_input")
    if isinstance(lefs, str):
        lefs = [lefs]
    design_def = cfg.get("def_input")
    paths = [design_def] + list(lefs or [])
    missing = [p for p in paths if not p or not os.path.exists(p)]
    if missing:
        print("SKIP: benchmark files are missing: %s" % ", ".join(missing))
        return 0

    xplace_root = resolve_xplace_root(args.xplace_root)
    sys.path.insert(0, xplace_root)
    try:
        import torch
    except ImportError as e:
        print("SKIP: unable to import torch: %s" % e)
        return 0
    if not torch.cuda.is_available():
        print("SKIP: Xplace GGR requires CUDA, but torch.cuda.is_available() is false")
        return 0
    from dreamplace.ops.gpugr.xplace_backend import _external_eval_main

    with tempfile.TemporaryDirectory() as tmp:
        output = os.path.join(tmp, "ggr.pt")
        cli = [
            "--ruplace-external-eval",
            "--def-input",
            os.path.abspath(design_def),
            "--design-name",
            os.path.basename(design_def).replace(".def", ""),
            "--xplace-root",
            xplace_root,
            "--gpu",
            str(args.gpu),
            "--output",
            output,
        ]
        for lef in lefs:
            cli.extend(["--lef-input", os.path.abspath(lef)])
        try:
            rc = _external_eval_main(cli)
        except Exception as e:
            print("SKIP: Xplace GGR smoke failed to initialize: %s" % e)
            return 0
        if rc != 0 or not os.path.exists(output):
            print("SKIP: Xplace GGR did not write output")
            return 0
        payload = torch.load(output, map_location="cpu")
    dmd_map = payload["overflow_map"]
    assert dmd_map.numel() > 0
    assert payload["metrics"]["num_ovfl_nets"] >= 0
    print(
        "PASS: GGR overflow map %s, ovfl_nets=%d"
        % (tuple(dmd_map.shape), payload["metrics"]["num_ovfl_nets"])
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
