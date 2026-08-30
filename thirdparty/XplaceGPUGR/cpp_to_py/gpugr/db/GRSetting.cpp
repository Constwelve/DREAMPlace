#include "GRSetting.h"

namespace gr {

void GRSetting::reset() {
    deviceId = 0;

    routeXSize = 0;
    routeYSize = 0;
    csrnScale = 0;

    rrrIters = 0;

    routeGuideFile = ""; 

    maxRouteLenPerPin = 130;
    m1Routable = 1;
    viaUsageScale = 1.5f;
    wireCostSat = 0;
}

GRSetting grSetting;

}  //   namespace gr