"""NCTUgr Bookshelf evaluator adapter."""

from pathlib import Path
import re
import tempfile
import time

from .base import EvaluationResult, RoutabilityEvaluator


def parse_nctugr_overflow(path):
    text = Path(path).read_text()
    values = [int(value) for value in re.findall(r"^\([^\n]+\)\s+\([^\n]+\)\s+(\d+)\s*$", text, re.MULTILINE)]
    return {
        "overflow": float(sum(values)),
        "overflow_edges": len(values),
        "overflow_max": float(max(values)) if values else 0.0,
    }


class NCTUgrEvaluator(RoutabilityEvaluator):
    name = "nctugr"

    def evaluate(self, request):
        start = time.time()
        pl_input = request.options.get("pl_input", "")
        if not request.aux_input or not pl_input:
            return EvaluationResult(
                backend=self.name, design_name=request.design_name, status="unsupported",
                error="NCTUgr requires aux_input and options.pl_input Bookshelf files",
            )
        root = Path(request.options.get(
            "nctugr_root", Path(__file__).resolve().parents[3] / "thirdparty/NCTUgr.ICCAD2012"
        )).resolve()
        output_base = request.artifact("nctugr.route")
        with tempfile.TemporaryDirectory(prefix="nctugr_eval_", dir=request.output_dir or None) as tmp:
            work = Path(tmp)
            for name in ("PORT9.dat", "POST9.dat", "POWV9.dat", "DAC12.set"):
                (work / name).symlink_to(root / name)
            command = [
                str(root / "NCTUgr"), "DAC", str(Path(request.aux_input).resolve()),
                str(Path(pl_input).resolve()), str(work / "DAC12.set"), str(output_base),
            ]
            output, failure = self.run(request, command, cwd=work)
        if failure:
            return failure
        overflow_file = Path(str(output_base) + ".ofinfo")
        if not overflow_file.exists():
            return EvaluationResult(
                backend=self.name,
                design_name=request.design_name,
                status="failed",
                runtime_sec=time.time() - start,
                artifacts={"route": str(output_base),
                           "log": str(request.artifact("nctugr.log"))},
                error="NCTUgr completed without an overflow-info artifact",
            )
        metrics = parse_nctugr_overflow(overflow_file)
        return EvaluationResult(
            backend=self.name,
            design_name=request.design_name,
            runtime_sec=time.time() - start,
            metrics=metrics,
            artifacts={"route": str(output_base), "overflow": str(overflow_file),
                       "log": str(request.artifact("nctugr.log"))},
        )
