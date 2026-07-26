"""CUGR LEF/DEF evaluator adapter."""

from pathlib import Path
import re
import tempfile
import time

from .base import EvaluationResult, RoutabilityEvaluator


DEFAULT_RRR_ITERS = 1


def merge_lefs(sources, destination):
    """Create one LEF library for routers that accept a single input file."""
    if not sources:
        raise ValueError("at least one LEF input is required")
    chunks = []
    for index, source in enumerate(sources):
        text = Path(source).read_text()
        text = re.sub(r"^\s*END\s+LIBRARY\s*$", "", text,
                      flags=re.IGNORECASE | re.MULTILINE)
        if index:
            text = re.sub(r"^\s*(?:VERSION|BUSBITCHARS|DIVIDERCHAR)\b.*?;\s*$", "", text,
                          flags=re.IGNORECASE | re.MULTILINE)
            text = re.sub(r"^\s*UNITS\b.*?^\s*END\s+UNITS\s*$", "", text,
                          flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)
        chunks.append(text.rstrip())
    Path(destination).write_text("\n\n".join(chunks) + "\nEND LIBRARY\n")


def add_gcell_grid(source, destination, route_size=512):
    text = Path(source).read_text()
    if re.search(r"^\s*GCELLGRID\s", text, re.MULTILINE):
        Path(destination).write_text(text)
        return
    match = re.search(
        r"DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*;",
        text,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError("DEF does not contain a rectangular DIEAREA")
    xl, yl, xh, yh = map(int, match.groups())
    ratio = (xh - xl) / float(yh - yl)
    nx = route_size if ratio <= 1 else max(2, round(route_size / ratio))
    ny = route_size if ratio >= 1 else max(2, round(route_size * ratio))
    sx = max(1, (xh - xl) // nx)
    sy = max(1, (yh - yl) // ny)
    grid = (
        "GCELLGRID X %d DO %d STEP %d ;\n" % (xl, nx, sx)
        + "GCELLGRID Y %d DO %d STEP %d ;\n" % (yl, ny, sy)
    )
    updated, count = re.subn(r"(^\s*END\s+DESIGN\s*$)", grid + r"\1", text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise ValueError("DEF does not contain END DESIGN")
    Path(destination).write_text(updated)


def filter_duplicate_special_nets(source, destination):
    """Remove regular NETS records whose names also occur in SPECIALNETS."""
    lines = Path(source).read_text().splitlines(keepends=True)
    special_names = set()
    section = None
    for line in lines:
        if re.match(r"^\s*SPECIALNETS\b", line, re.IGNORECASE):
            section = "special"
            continue
        if re.match(r"^\s*END\s+SPECIALNETS\b", line, re.IGNORECASE):
            section = None
            continue
        if section == "special":
            match = re.match(r"^\s*-\s+(\S+)", line)
            if match:
                special_names.add(match.group(1))

    output = []
    in_nets = False
    record = []
    removed = []
    net_count_index = None
    for line in lines:
        if re.match(r"^\s*NETS\b", line, re.IGNORECASE):
            in_nets = True
            net_count_index = len(output)
            output.append(line)
            continue
        if in_nets and re.match(r"^\s*END\s+NETS\b", line, re.IGNORECASE):
            if record:
                output.extend(record)
                record = []
            in_nets = False
            output.append(line)
            continue
        if in_nets and (record or re.match(r"^\s*-\s+", line)):
            record.append(line)
            if ";" in line:
                match = re.match(r"^\s*-\s+(\S+)", record[0])
                name = match.group(1) if match else ""
                if name in special_names:
                    removed.append(name)
                else:
                    output.extend(record)
                record = []
            continue
        output.append(line)

    if removed and net_count_index is not None:
        output[net_count_index] = re.sub(
            r"(^\s*NETS\s+)(\d+)(\s*;)",
            lambda match: "%s%d%s" % (
                match.group(1), int(match.group(2)) - len(removed), match.group(3)
            ),
            output[net_count_index],
            count=1,
            flags=re.IGNORECASE,
        )
    Path(destination).write_text("".join(output))
    return removed


def parse_cugr_log(text):
    patterns = {
        "wirelength": r"wirelength\s*\|\s*([0-9.eE+-]+)",
        "vias": r"#\s*vias\s*\|\s*([0-9.eE+-]+)",
        "estimated_shorts": r"short\s*\|\s*([0-9.eE+-]+)",
        "score": r"total score\s*=\s*([0-9.eE+-]+)",
    }
    metrics = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            metrics[key] = float(match.group(1))
    return metrics


class CUGREvaluator(RoutabilityEvaluator):
    name = "cugr"

    def evaluate(self, request):
        start = time.time()
        if not request.lef_input:
            return EvaluationResult(
                backend=self.name, design_name=request.design_name, status="unsupported",
                error="CUGR evaluation requires at least one LEF input",
            )
        root = Path(request.options.get(
            "cugr_root", "/mnt/nvme0n1/yifan/projs/Xplace/tool/cugr_ispd2015_fix/CUGR"
        )).resolve()
        # The available public ICCAD19 build raises SIGFPE when it enters the
        # second RRR pass, even with one thread. One pass still emits a complete
        # nonempty route and is the only validated portable default.
        rrr_iters = int(request.options.get("rrr_iters", DEFAULT_RRR_ITERS))
        if rrr_iters < 1:
            return EvaluationResult(
                backend=self.name, design_name=request.design_name, status="unsupported",
                error="CUGR requires rrr_iters >= 1; zero iterations emits an empty route",
            )
        binary = root / "iccad19gr"
        with tempfile.TemporaryDirectory(prefix="cugr_eval_", dir=request.output_dir or None) as tmp:
            work = Path(tmp)
            merged_lef = work / "input.merged.lef"
            merge_lefs(request.lef_input, merged_lef)
            filtered_def = work / "input.filtered.def"
            removed_special_nets = filter_duplicate_special_nets(
                request.def_input, filtered_def
            )
            routed_def = work / "input.gcell.def"
            add_gcell_grid(
                filtered_def, routed_def, int(request.options.get("route_size", 512))
            )
            for lut in ("PORT9.dat", "POST9.dat", "POWV9.dat"):
                (work / lut).symlink_to(root / lut)
            guide = request.artifact("cugr.guide")
            command = [
                str(binary), "-lef", str(merged_lef),
                "-def", str(routed_def), "-output", str(guide),
                # This public CUGR build can raise SIGFPE in multithreaded RRR.
                "-threads", str(request.options.get("cugr_threads", 1)),
                "-rrrIters", str(rrr_iters),
            ]
            output, failure = self.run(request, command, cwd=work)
        if failure:
            return failure
        metrics = parse_cugr_log(output)
        if not metrics:
            return EvaluationResult(
                backend=self.name, design_name=request.design_name, status="failed",
                runtime_sec=time.time() - start,
                artifacts={"log": str(request.artifact("cugr.log"))},
                error="CUGR completed but no score block was found",
            )
        metrics["filtered_duplicate_special_nets"] = len(removed_special_nets)
        return EvaluationResult(
            backend=self.name,
            design_name=request.design_name,
            runtime_sec=time.time() - start,
            metrics=metrics,
            artifacts={"guide": str(guide), "log": str(request.artifact("cugr.log"))},
        )
