cmake_minimum_required(VERSION 3.20)

if(NOT DEFINED SKBUILD_PROJECT_VERSION)
  set(SKBUILD_PROJECT_VERSION "0.0.0+local")
endif()

project(blipsmith_core LANGUAGES CXX VERSION 0.1.0)

# --- Determinism contract -----------------------------------------------------
# blipsmith's product invariant is that the same SoundSpec plus the same seed
# yields byte-identical audio on every supported platform. That survives only if
# the compiler is forbidden from reassociating, contracting, or approximating
# floating-point arithmetic. These settings are pinned; weakening any of them
# breaks the invariant rather than merely degrading quality.
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_INTERPROCEDURAL_OPTIMIZATION OFF)

# Patterns are written with character classes so the literal enabling spellings
# never appear in this file; tests assert those spellings are absent.
set(BLIPSMITH_FORBIDDEN_FLAGS "fast-math" "[-]Ofast" "unsafe-math" "ffp-contract=fast")

foreach(_flag_var
    CMAKE_CXX_FLAGS
    CMAKE_CXX_FLAGS_DEBUG
    CMAKE_CXX_FLAGS_RELEASE
    CMAKE_CXX_FLAGS_RELWITHDEBINFO
    CMAKE_CXX_FLAGS_MINSIZEREL)
  foreach(_pattern IN LISTS BLIPSMITH_FORBIDDEN_FLAGS)
    if("${${_flag_var}}" MATCHES "${_pattern}")
      message(FATAL_ERROR
        "${_flag_var} contains a flag matching '${_pattern}'. blipsmith requires "
        "strict IEEE-754 arithmetic for bit-identical renders across platforms.")
    endif()
  endforeach()
endforeach()

find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)
find_package(pybind11 CONFIG REQUIRED)

# NO_EXTRAS drops pybind11's default link-time optimization. LTO is another
# cross-toolchain variable in the audio path, and the core is small enough that
# the lost inlining does not matter.
pybind11_add_module(_core NO_EXTRAS
  core/src/bus.cpp
  core/src/core.cpp
  core/src/env.cpp
  core/src/features.cpp
  core/src/filter.cpp
  core/src/fx.cpp
  core/src/lofi.cpp
  core/src/mod.cpp
  core/src/noise.cpp
  core/src/osc.cpp
  core/src/render.cpp
  core/src/seq.cpp
  core/src/spec_parse.cpp
  core/src/tables.cpp
  core/src/wav.cpp
)

target_compile_features(_core PRIVATE cxx_std_17)
target_compile_definitions(_core PRIVATE BLIPSMITH_CORE_VERSION="${SKBUILD_PROJECT_VERSION}")

if(MSVC)
  target_compile_options(_core PRIVATE /fp:precise)
else()
  target_compile_options(_core PRIVATE -ffp-contract=off)
endif()

install(TARGETS _core DESTINATION blipsmith)
