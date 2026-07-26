file(GLOB INSTALL_SRCS "${CMAKE_CURRENT_SOURCE_DIR}/*.py")
install(FILES ${INSTALL_SRCS} DESTINATION dreamplace/ops/routability_opt)

file(GLOB PLUGIN_INSTALL_SRCS "${CMAKE_CURRENT_SOURCE_DIR}/plugins/*.py")
install(FILES ${PLUGIN_INSTALL_SRCS} DESTINATION dreamplace/ops/routability_opt/plugins)
