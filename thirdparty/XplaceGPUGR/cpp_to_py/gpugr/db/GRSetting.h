#pragma once
#include <string>

namespace gr {

class GRSetting {
public:
    // 1. SystemSetting
    int deviceId = 0;

    // 2. Gridgraph setting
    int routeXSize = 0;
    int routeYSize = 0;
    int csrnScale = 0;

    // 3. The number of Rip-up and Reroute iterations (if 0, only PR is invoked)
    int rrrIters = 0;

    std::string routeGuideFile = "";

    // ---- RUPlace s14 fidelity knobs (defaults = legacy Xplace behavior) ----
    // Max number of route-array entries reserved per pin (legacy hard-coded 130).
    int maxRouteLenPerPin = 130;
    // 1 = legacy (M1 carries wire capacity); 0 = zero out routing layer 0 capacity so
    // that wires are forbidden on M1 while vias down to M1 pins stay legal.
    int m1Routable = 1;
    // Scale on the sqrt(via count) in-gcell via-usage model (legacy literal 1.5).
    float viaUsageScale = 1.5f;
    // 0 = legacy: the int64 wireCostSum difference is truncated into an `int`, so a span that
    // crosses >= 3 blocked gcells (cost INF each) wraps and yields a negative "distance" that
    // wins the final min, making the net report `failed`.  1 = saturate the difference and the
    // distance accumulations at INF so a blocked layer simply loses the min instead.
    int wireCostSat = 0;

    void reset();
};

extern GRSetting grSetting;
}  //   namespace gr
