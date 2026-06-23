# RUPlace GPUGR Integration

This branch integrates RUPlace routability optimization with a bundled
GPUGR-only fork of Xplace. The submodule lives at `thirdparty/XplaceGPUGR`
and is built by DREAMPlace when `RUPLACE_ENABLE_GPUGR=ON` (default).

## Build

```bash
git submodule update --init --recursive
mkdir -p build
cd build
cmake .. \
  -DCMAKE_INSTALL_PREFIX=../install \
  -DPython_EXECUTABLE="$(which python)" \
  -DRUPLACE_ENABLE_GPUGR=ON \
  -DRUPLACE_GPUGR_CUDA_ARCHITECTURES="75;86"
make -j"$(nproc)"
make install
```

Use CUDA 11.8+ with a CUDA-enabled PyTorch. The bundled backend installs into
`install/dreamplace/ops/gpugr/xplace_gpugr`, so normal runs do not need an
external Xplace checkout or manual `LD_LIBRARY_PATH`.

## Run RUPlace

Enable RUPlace in a JSON config:

```json
{
  "routability_opt_flag": 1,
  "ruplace_flag": 1,
  "ruplace_router_backend": "gpugr"
}
```

Then run from the installed tree:

```bash
cd install
python dreamplace/Placer.py test/ruplace/ispd18_test1_gpugr.json
```

The legacy external Xplace backend remains available for reproducibility:

```json
{
  "ruplace_router_backend": "xplace",
  "ruplace_xplace_root": "../Xplace"
}
```

## Standalone GPUGR

The router can be called without enabling RUPlace:

```bash
python -m dreamplace.ops.gpugr.run_gpugr \
  --backend gpugr \
  --design-name ispd18_test1 \
  --lef-input ../Xplace/data/ispd18_test1.input.lef \
  --def-input ../Xplace/data/ispd18_test1.input.def \
  --output /tmp/ispd18_test1.gpugr.pt
```

For development without `make install`, set `DREAMPLACE_GPUGR_ROOT` or
`ruplace_gpugr_root` to a built GPUGR root containing `cpp_to_py/cpybin`.
