# Repository Guidelines

## Project Structure & Module Organization

DREAMPlace is a Python-led VLSI placer with C++/CUDA PyTorch operators. Core placement logic lives in `dreamplace/` (`Placer.py`, `PlaceDB.py`, optimization classes, and `params.json`). Native operators are organized under `dreamplace/ops/<op_name>/` with Python wrappers, `src/` kernels, and per-op `CMakeLists.txt` files. Regression configurations and runnable examples are under `test/`, while unit and regression test drivers live in `unittest/`. Build helpers are in `cmake/`, benchmark download scripts in `benchmarks/`, documentation images in `images/`, and external dependencies in `thirdparty/`.

## Build, Test, and Development Commands

- `git submodule init && git submodule update`: fetch integrated dependencies such as Limbo, CUB, OpenTimer, and munkres-cpp.
- `pip install -r requirements.txt`: install Python runtime dependencies.
- `mkdir -p build && cd build && cmake .. -DCMAKE_INSTALL_PREFIX=../install -DPython_EXECUTABLE=$(which python)`: configure an out-of-tree build.
- `make -C build -j$(nproc) && make -C build install`: compile native extensions and install the Python package plus tests into `install/`.
- `python benchmarks/ispd2005_2015.py`: download common public benchmarks.
- `cd install && python dreamplace/Placer.py test/ispd2005/adaptec1.json`: run a small placement example after installation.

## Coding Style & Naming Conventions

Python code uses 4-space indentation, module-level imports, `snake_case` variables/functions, and `CamelCase` classes. Keep JSON configuration keys consistent with `dreamplace/params.json`. C++/CUDA code uses C++17, two-space indentation in operator sources, `camelCase` helper names, and DREAMPlace namespace/macros from existing utilities. Follow neighboring files before introducing formatting-only churn.

## Testing Guidelines

Use Python `unittest` for operator tests. Test files follow `*_unittest.py` and are discovered by `python unittest/unittests.py` from an installed tree or compatible build environment. Run targeted tests with commands such as `python unittest/ops/hpwl_unittest.py`. For placement changes, add or update JSON regression cases in `unittest/regression/<suite>/` and sanity-check at least one small `test/ispd2005/*.json` run.

## Commit & Pull Request Guidelines

History uses short imperative or descriptive subjects, often with merge commits (for example, `support multi-liberty input` or `fix bug in readme`). Keep commits focused and mention affected modules or benchmarks. Pull requests should include the motivation, key implementation changes, build/test commands run, benchmark/config files used, and any runtime or HPWL impact. Attach logs or plots when behavior changes.

## Security & Configuration Tips

Do not commit downloaded benchmark payloads, local `build/` or `install/` artifacts, CUDA/toolchain paths, or license/server settings. Keep machine-specific scripts separate from portable CMake and Python configuration.

## Long-Running Experiment Token Policy

For long benchmark, thermal, ATSim, routing, or placement runs:
- Do not babysit runs with repeated sleep or polling loops inside Codex.
- Prefer detached runners (`tmux`, `nohup`, or supervisor scripts) that write compact status files.
- Create or maintain a `HANDOFF_STATUS.md` in each long-experiment directory with repo path, artifact root, completed/total counts, active row, key commands, and pending final reports.
- For progress reports, read status CSV/JSON/Markdown artifacts and log tails only.
- Avoid dumping full logs; use `tail`, `rg`, and structured parsers.
- Keep progress reports concise: completed/total, active case, latest artifact, and blocker.
- If a run is still active, report once and stop; do not wait unless explicitly asked.

