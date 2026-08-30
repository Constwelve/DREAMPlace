#include "common/common.h"
#include "common/db/Database.h"
#include "io_parser/gp/GPDatabase.h"
#include "gpugr/db/GRDatabase.h"
#include "gpugr/gr/RouteForce.h"
#include "flute.h"
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/stl_bind.h>

namespace Xplace {

bool loadGRParams(const pybind11::dict& kwargs) {
    gr::grSetting.reset();
    // ----- design related options -----

    if (kwargs.contains("device_id")) {
        gr::grSetting.deviceId = kwargs["device_id"].cast<int>();
    }

    if (kwargs.contains("route_xSize")) {
        gr::grSetting.routeXSize = kwargs["route_xSize"].cast<int>();
    }

    if (kwargs.contains("route_ySize")) {
        gr::grSetting.routeYSize = kwargs["route_ySize"].cast<int>();
    }

    if (kwargs.contains("csrn_scale")) {
        gr::grSetting.csrnScale = kwargs["csrn_scale"].cast<int>();
    }

    if (kwargs.contains("rrrIters")) {
        gr::grSetting.rrrIters = kwargs["rrrIters"].cast<int>();
    }

    if (kwargs.contains("route_guide")) {
        gr::grSetting.routeGuideFile = kwargs["route_guide"].cast<std::string>();
    }

    // ----- RUPlace s14 fidelity knobs (defaults = legacy behavior) -----

    if (kwargs.contains("max_route_len_per_pin")) {
        gr::grSetting.maxRouteLenPerPin = kwargs["max_route_len_per_pin"].cast<int>();
    }

    if (kwargs.contains("m1_routable")) {
        gr::grSetting.m1Routable = kwargs["m1_routable"].cast<int>();
    }

    if (kwargs.contains("via_usage_scale")) {
        gr::grSetting.viaUsageScale = kwargs["via_usage_scale"].cast<float>();
    }

    if (kwargs.contains("wire_cost_sat")) {
        gr::grSetting.wireCostSat = kwargs["wire_cost_sat"].cast<int>();
    }

    return true;
}

PYBIND11_MODULE(TORCH_EXTENSION_NAME, m) {
    pybind11::class_<gr::GRDatabase, std::shared_ptr<gr::GRDatabase>>(m, "GRDatabase")
        .def(pybind11::init<std::shared_ptr<db::Database>, std::shared_ptr<gp::GPDatabase>>())
        .def("report_gr_stat", &gr::GRDatabase::reportGRStat)
        .def("setup_capacity", &gr::GRDatabase::setupCapacity)
        .def("setup_wiredist", &gr::GRDatabase::setupWireDist)
        .def("setup_obs", &gr::GRDatabase::setupObs)
        .def("setup_grnets", &gr::GRDatabase::setupGrNets)
        // ---- RUPlace calibration harness (A0): read-only geometry introspection ----
        .def_readonly("gridlines", &gr::GRDatabase::gridlines)
        .def_readonly("grid_centers", &gr::GRDatabase::gridCenters)
        .def_readonly("x_size", &gr::GRDatabase::xSize)
        .def_readonly("y_size", &gr::GRDatabase::ySize)
        .def_readonly("n_layers", &gr::GRDatabase::nLayers)
        .def_readonly("m1direction", &gr::GRDatabase::m1direction)
        .def_readonly("microns", &gr::GRDatabase::microns)
        .def_readonly("main_gcell_step_x", &gr::GRDatabase::mainGcellStepX)
        .def_readonly("main_gcell_step_y", &gr::GRDatabase::mainGcellStepY)
        .def_readonly("layer_width", &gr::GRDatabase::layerWidth)
        .def_readonly("layer_pitch", &gr::GRDatabase::layerPitch);
    pybind11::class_<gr::RouteForce, std::shared_ptr<gr::RouteForce>>(m, "RouteForce")
        .def(pybind11::init<std::shared_ptr<gr::GRDatabase>>())
        .def("run_ggr", &gr::RouteForce::run_ggr)
        .def("num_ovfl_nets", &gr::RouteForce::getNumOvflNets)
        .def("gcell_steps", &gr::RouteForce::getGcellStep)
        .def("microns", &gr::RouteForce::getMicrons)
        .def("layer_pitch", &gr::RouteForce::getLayerPitch)
        .def("layer_width", &gr::RouteForce::getLayerWidth)
        .def("dmd_map", &gr::RouteForce::getDemandMap, py::return_value_policy::move)
        .def("cap_map", &gr::RouteForce::getCapacityMap, py::return_value_policy::move)
        .def("route_grad", &gr::RouteForce::calcRouteGrad, py::return_value_policy::move)
        .def("route_grad_reduce", &gr::RouteForce::calcRouteGradReduce, py::return_value_policy::move)
        .def("admm_route_grad", &gr::RouteForce::calcAdmmRouteGrad, py::return_value_policy::move)
        .def("filler_route_grad", &gr::RouteForce::calcFillerRouteGrad, py::return_value_policy::move)
        .def("pseudo_grad", &gr::RouteForce::calcPseudoPinGrad, py::return_value_policy::move)
        .def("inflate_ratio", &gr::RouteForce::calcNodeInflateRatio, py::return_value_policy::move)
        .def("inflate_pin_rel_cpos", &gr::RouteForce::calcInflatedPinRelCpos, py::return_value_policy::move)
        // RUPlace (batch 1, item 6): per-gcell blocked-track map, same layout as cap_map.
        .def("fixed_map", &gr::RouteForce::getFixedMap, py::return_value_policy::move);
    
    m.def("create_grdatabase", [](std::shared_ptr<db::Database> rawdb, std::shared_ptr<gp::GPDatabase> gpdb) {
        logger.enable_logger();
        std::shared_ptr<gr::GRDatabase> grdb = std::make_shared<gr::GRDatabase>(rawdb, gpdb);
        logger.reset_logger();
        return grdb;
    });
    m.def("create_routeforce", [](std::shared_ptr<gr::GRDatabase> grdb) {
        logger.enable_logger();
        std::shared_ptr<gr::RouteForce> routeforce = std::make_shared<gr::RouteForce>(grdb);
        logger.reset_logger();
        return routeforce;
    });
    m.def("load_gr_params", &loadGRParams, "Parse input args to DB and return graph information");
    m.def("read_flute", &Flute::readLUT, "Read Flute LUT");
}

}  // namespace Xplace
