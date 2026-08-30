#pragma once
#include "common/common.h"
#include "gpugr/db/GrNet.h"

namespace gr {

int prepare(double &count,
            gr::GrNet &grNet,
            int *points,
            int routesOffset,
            int *gbpoints,
            int &gbPinOffset,
            int X,
            int Y,
            int N,
            int LAYER,
            int DIRECTION);

void prepareSingeNet(gr::GrNet &grNet, int routesOffset, int X, int Y, int N, int LAYER, int DIRECTION);

void prepareGrNets(std::vector<gr::GrNet> &grNets,
                   std::vector<int> &netsToRoute,
                   std::vector<int> &batchSizes,
                   std::vector<std::vector<int>> &points_cpu_vec,
                   std::vector<std::tuple<int, int, int>> &batchId2vec_info,
                   int *routesOffsetCPU,
                   int X,
                   int Y,
                   int N,
                   int LAYER,
                   int DIRECTION);

void patternRoute(int *points,
                  int batchSize,
                  int64_t *wireCostSum,
                  int *viaCost,
                  int *map,
                  int *prev,
                  int *wires,
                  int *vias,
                  int *routes,
                  int *gbpoints,
                  int *gbpinRoutes,
                  int X,
                  int Y,
                  int N,
                  int LAYER,
                  int DIRECTION,
                  // RUPlace (batch 1, item 7): failed-net diagnostics, enabled by
                  // RUPLACE_GR_DEBUG_FAILED=N.  All four are ignored when dbgLimit == 0.
                  const float *capacity = nullptr,
                  const int *dbgNetIds = nullptr,
                  int *dbgCounter = nullptr,
                  int dbgLimit = 0,
                  // RUPlace (batch 2): 1 = saturate the int64->int wire-cost difference and the
                  // distance accumulations at INF (grSetting.wireCostSat).  0 = legacy truncation.
                  int wireCostSat = 0);
}  // namespace gr