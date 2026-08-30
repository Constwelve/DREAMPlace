cmake_minimum_required(VERSION 3.24)

if (NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
  set(CMAKE_CUDA_ARCHITECTURES 80 86 CACHE STRING "CUDA architectures" FORCE)
endif()

project(xplace LANGUAGES C CXX CUDA)

option(XPLACE_BUILD_GPUGR_ONLY "Build only the GPUGR/IOParser backend needed by RUPlace" ON)
option(XPLACE_EMBEDDED_IN_DREAMPLACE "Build as a DREAMPlace third-party subdirectory" OFF)
set(XPLACE_INSTALL_PY_DEST "" CACHE STRING "Install destination for the XplaceGPUGR Python root; empty means install prefix root")
set(XPLACE_INSTALL_LIB_DEST "" CACHE STRING "Install destination for GPUGR Python extensions; defaults under XPLACE_INSTALL_PY_DEST")

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
message(STATUS "CMAKE_BUILD_TYPE: ${CMAKE_BUILD_TYPE}")

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

message(STATUS PROJECT_SOURCE_DIR=${PROJECT_SOURCE_DIR})
set(PATH_THIRDPARTY_ROOT ${PROJECT_SOURCE_DIR}/thirdparty)
if(NOT XPLACE_LIB_DIR)
  set(XPLACE_LIB_DIR ${PROJECT_BINARY_DIR}/cpp_to_py/cpybin CACHE PATH "Directory for Xplace/GPUGR Python extension build outputs" FORCE)
endif()
if(NOT XPLACE_INSTALL_LIB_DEST)
  if(XPLACE_INSTALL_PY_DEST)
    set(XPLACE_INSTALL_LIB_DEST "${XPLACE_INSTALL_PY_DEST}/cpp_to_py/cpybin" CACHE STRING "Install destination for GPUGR Python extensions" FORCE)
  else()
    set(XPLACE_INSTALL_LIB_DEST "cpp_to_py/cpybin" CACHE STRING "Install destination for GPUGR Python extensions" FORCE)
  endif()
endif()
if(XPLACE_INSTALL_PY_DEST)
  set(XPLACE_INSTALL_CPP_DEST "${XPLACE_INSTALL_PY_DEST}/cpp_to_py")
  set(XPLACE_INSTALL_UTILS_DEST "${XPLACE_INSTALL_PY_DEST}/utils")
  set(XPLACE_INSTALL_FLUTE_DEST "${XPLACE_INSTALL_PY_DEST}/thirdparty/flute")
else()
  set(XPLACE_INSTALL_CPP_DEST "cpp_to_py")
  set(XPLACE_INSTALL_UTILS_DEST "utils")
  set(XPLACE_INSTALL_FLUTE_DEST "thirdparty/flute")
endif()
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${XPLACE_LIB_DIR})
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${XPLACE_LIB_DIR})

set(CMAKE_MODULE_PATH ${CMAKE_MODULE_PATH} "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
set(CMAKE_BUILD_RPATH ${XPLACE_LIB_DIR})
set(CMAKE_INSTALL_RPATH "$ORIGIN")

# set _GLIBCXX_USE_CXX11_ABI for torch
if(NOT CMAKE_CXX_ABI)
    set(CMAKE_CXX_ABI 0 CACHE STRING
        "Choose the value for _GLIBCXX_USE_CXX11_ABI, options are: 0|1."
        FORCE)
endif(NOT CMAKE_CXX_ABI)
message(STATUS "CMAKE_CXX_ABI: _GLIBCXX_USE_CXX11_ABI=${CMAKE_CXX_ABI}")
add_definitions(-D_GLIBCXX_USE_CXX11_ABI=${CMAKE_CXX_ABI})

# PyBind11
if(NOT TARGET pybind11::module)
  add_subdirectory(${PATH_THIRDPARTY_ROOT}/pybind11)
endif()
message(STATUS "PYTHON_INCLUDE_DIRS: ${PYTHON_INCLUDE_DIRS}")

# Flute
add_subdirectory(${PATH_THIRDPARTY_ROOT}/flute)
message(STATUS "FLUTE_INCLUDE_DIR: ${FLUTE_INCLUDE_DIR}")

# Lemon
set(LEMON_INCLUDE_DIR "${PATH_THIRDPARTY_ROOT}/lemon/include")
set(LEMON_INCLUDE_DIRS "${LEMON_INCLUDE_DIR}")
find_library(LEMON_LIBRARY emon ${PATH_THIRDPARTY_ROOT}/lemon/lib)
set(LEMON_LIBRARIES "${LEMON_LIBRARY}")
message(STATUS "LEMON_INCLUDE_DIRS: ${LEMON_INCLUDE_DIRS}")
message(STATUS "LEMON_LIBRARIES: ${LEMON_LIBRARIES}")

# Cairo
find_package(Cairo)
message(STATUS "CAIRO_INCLUDE_DIRS: ${CAIRO_INCLUDE_DIRS}")
message(STATUS "CAIRO_LIBRARIES: ${CAIRO_LIBRARIES}")

# CUDA
message(STATUS "CMAKE_CUDA_ARCHITECTURES: ${CMAKE_CUDA_ARCHITECTURES}")
find_package(CUDAToolkit)

# set nvcc flags
set(CUDA_USE_STATIC_CUDA_RUNTIME OFF)
set(CMAKE_CUDA17_EXTENSION_COMPILE_OPTION "-std=c++17")
list(APPEND BASIC_CUDA_FLAGS --compiler-options;-fPIC;-std=c++17)
list(APPEND BASIC_CUDA_FLAGS --expt-relaxed-constexpr) # suppress warning from pytorch
message(STATUS "BASIC_CUDA_FLAGS: ${BASIC_CUDA_FLAGS}")
add_compile_options(
  "$<$<COMPILE_LANGUAGE:CUDA>:${BASIC_CUDA_FLAGS}>"
)

# Torch
if(NOT PYTHON_EXECUTABLE AND Python_EXECUTABLE)
  set(PYTHON_EXECUTABLE ${Python_EXECUTABLE})
endif()
if(NOT PYTHON_EXECUTABLE)
  find_package(Python COMPONENTS Interpreter Development REQUIRED)
  set(PYTHON_EXECUTABLE ${Python_EXECUTABLE})
endif()
if(NOT PYTHON_INCLUDE_DIRS)
  find_package(Python COMPONENTS Interpreter Development REQUIRED)
  set(PYTHON_INCLUDE_DIRS ${Python_INCLUDE_DIRS})
endif()
if(TARGET torch AND PYTHON_INCLUDE_DIRS)
  list(APPEND TORCH_INCLUDE_DIRS ${PYTHON_INCLUDE_DIRS})
endif()

if(NOT TARGET torch)
  execute_process(COMMAND ${PYTHON_EXECUTABLE} -c 
    "import torch; print(torch.__path__[0]); print(int(torch.cuda.is_available())); print(torch.__version__);" 
    OUTPUT_VARIABLE TORCH_OUTPUT OUTPUT_STRIP_TRAILING_WHITESPACE)
  string(REPLACE "\n" ";" TORCH_OUTPUT_LIST ${TORCH_OUTPUT})
  list(GET TORCH_OUTPUT_LIST 0 TORCH_INSTALL_PREFIX)
  list(GET TORCH_OUTPUT_LIST 1 TORCH_ENABLE_CUDA)
  list(GET TORCH_OUTPUT_LIST 2 TORCH_VERSION)
  string(REPLACE "." ";" TORCH_VERSION_LIST ${TORCH_VERSION})
  list(GET TORCH_VERSION_LIST 0 TORCH_VERSION_MAJOR)
  list(GET TORCH_VERSION_LIST 1 TORCH_VERSION_MINOR)
  message(STATUS TORCH_INSTALL_PREFIX=${TORCH_INSTALL_PREFIX})
  message(STATUS TORCH_VERSION=${TORCH_VERSION_MAJOR}.${TORCH_VERSION_MINOR})
  message(STATUS TORCH_ENABLE_CUDA=${TORCH_ENABLE_CUDA})
  if (NOT TORCH_ENABLE_CUDA)
    message(FATAL_ERROR "GPUGR requires Torch-CUDA mode, exit CMAKE." )
  endif()
endif()

# set torch lib
if(NOT TARGET torch)
  add_library(torch STATIC IMPORTED)
  find_library(TORCH_PYTHON_LIBRARY torch_python PATHS "${TORCH_INSTALL_PREFIX}/lib" REQUIRED)
  find_library(TORCH_LIBRARY torch PATHS "${TORCH_INSTALL_PREFIX}/lib" REQUIRED)
  find_library(C10_LIBRARY c10 PATHS "${TORCH_INSTALL_PREFIX}/lib" REQUIRED)
  find_library(C10_CUDA_LIBRARY c10_cuda PATHS "${TORCH_INSTALL_PREFIX}/lib")
  find_library(TORCH_CPU_LIBRARY torch_cpu PATHS "${TORCH_INSTALL_PREFIX}/lib" REQUIRED)
  find_library(TORCH_CUDA_LIBRARY torch_cuda PATHS "${TORCH_INSTALL_PREFIX}/lib")

  set(LINK_LIBS ${C10_LIBRARY} ${TORCH_CPU_LIBRARY})
  if (TORCH_ENABLE_CUDA)
    set(LINK_LIBS ${LINK_LIBS}
      ${C10_CUDA_LIBRARY}
      ${TORCH_CUDA_LIBRARY})
  endif()

  if (EXISTS ${TORCH_INSTALL_PREFIX}/include)
    set(TORCH_HEADER_PREFIX ${TORCH_INSTALL_PREFIX}/include)
  endif()
  set(TORCH_INCLUDE_DIRS
    ${PYTHON_INCLUDE_DIRS} ${TORCH_HEADER_PREFIX} ${TORCH_HEADER_PREFIX}/torch/csrc/api/include)
  message(STATUS TORCH_INCLUDE_DIRS=${TORCH_INCLUDE_DIRS})

  set_target_properties(torch PROPERTIES
    IMPORTED_LOCATION "${TORCH_LIBRARY}"
    INTERFACE_INCLUDE_DIRECTORIES "${TORCH_INCLUDE_DIRS}"
    INTERFACE_LINK_LIBRARIES "${LINK_LIBS}"
    INTERFACE_COMPILE_OPTIONS "-D_GLIBCXX_USE_CXX11_ABI=${CMAKE_CXX_ABI}"
    )
endif()

if(NOT XPLACE_EMBEDDED_IN_DREAMPLACE)
function(add_pytorch_extension target_name)
  set(multiValueArgs EXTRA_INCLUDE_DIRS EXTRA_LINK_LIBRARIES EXTRA_DEFINITIONS)
  cmake_parse_arguments(ARG "" "" "${multiValueArgs}" ${ARGN})
  if (TORCH_ENABLE_CUDA)
    set(CUDA_SRCS "${ARG_UNPARSED_ARGUMENTS}")
    list(FILTER CUDA_SRCS INCLUDE REGEX ".*cu$")
    if (CUDA_SRCS)
      add_library(${target_name}_cuda_tmp STATIC ${CUDA_SRCS})
      target_include_directories(${target_name}_cuda_tmp PRIVATE ${ARG_EXTRA_INCLUDE_DIRS} ${TORCH_INCLUDE_DIRS})
      target_link_libraries(${target_name}_cuda_tmp ${ARG_EXTRA_LINK_LIBRARIES} ${TORCH_LIBRARY})
      target_compile_definitions(${target_name}_cuda_tmp PRIVATE 
        TORCH_EXTENSION_NAME=${target_name}
        TORCH_VERSION_MAJOR=${TORCH_VERSION_MAJOR}
        TORCH_VERSION_MINOR=${TORCH_VERSION_MINOR}
        ENABLE_CUDA=${TORCH_ENABLE_CUDA}
        ${ARG_EXTRA_DEFINITIONS})
      set_target_properties(${target_name}_cuda_tmp PROPERTIES 
        POSITION_INDEPENDENT_CODE ON
        CXX_VISIBILITY_PRESET "hidden"
        CUDA_VISIBILITY_PRESET "hidden"
        )
    endif()
  endif()
  list(FILTER ARG_UNPARSED_ARGUMENTS EXCLUDE REGEX ".*cu$")
  pybind11_add_module(${target_name} MODULE ${ARG_UNPARSED_ARGUMENTS})
  target_include_directories(${target_name} PRIVATE ${ARG_EXTRA_INCLUDE_DIRS} ${TORCH_INCLUDE_DIRS})
  if (TORCH_ENABLE_CUDA AND CUDA_SRCS)
    target_link_libraries(${target_name} PRIVATE ${target_name}_cuda_tmp ${ARG_EXTRA_LINK_LIBRARIES} torch ${TORCH_PYTHON_LIBRARY})
  else()
    target_link_libraries(${target_name} PRIVATE ${ARG_EXTRA_LINK_LIBRARIES} torch ${TORCH_PYTHON_LIBRARY})
  endif()
  target_compile_definitions(${target_name} PRIVATE 
    TORCH_EXTENSION_NAME=${target_name}
    TORCH_VERSION_MAJOR=${TORCH_VERSION_MAJOR}
    TORCH_VERSION_MINOR=${TORCH_VERSION_MINOR}
    ENABLE_CUDA=${TORCH_ENABLE_CUDA}
    ${ARG_EXTRA_DEFINITIONS})
endfunction()
endif()

# add targets
add_subdirectory(cpp_to_py)

# Install the lightweight Python tree expected by DREAMPlace's bundled GPUGR backend.
install(FILES ${PROJECT_SOURCE_DIR}/cpp_to_py/__init__.py
        DESTINATION ${XPLACE_INSTALL_CPP_DEST})
install(FILES ${PROJECT_SOURCE_DIR}/utils/io_parser.py
        DESTINATION ${XPLACE_INSTALL_UTILS_DEST})
install(FILES ${PROJECT_SOURCE_DIR}/utils/gpugr_only_init.py
        DESTINATION ${XPLACE_INSTALL_UTILS_DEST}
        RENAME __init__.py)
install(FILES ${PATH_THIRDPARTY_ROOT}/flute/POWV9.dat ${PATH_THIRDPARTY_ROOT}/flute/POST9.dat
        DESTINATION ${XPLACE_INSTALL_FLUTE_DEST})
