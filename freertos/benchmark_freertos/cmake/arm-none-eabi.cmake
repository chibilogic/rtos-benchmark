# CMake toolchain file: arm-none-eabi-gcc from project-local tools/.
#
# Used by:
#   cmake -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi.cmake -B build/<profile>

set(CMAKE_SYSTEM_NAME      Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)

# Resolve the project-local toolchain. Assumes env.bat has been run
# (PATH already contains tools/gcc-arm/bin), but also works if not.
find_program(ARM_GCC arm-none-eabi-gcc)
if(NOT ARM_GCC)
    message(FATAL_ERROR
        "arm-none-eabi-gcc not in PATH. Run env.bat from the repo root first.")
endif()

set(CMAKE_C_COMPILER   arm-none-eabi-gcc)
set(CMAKE_ASM_COMPILER arm-none-eabi-gcc)
set(CMAKE_CXX_COMPILER arm-none-eabi-g++)

# CMake tries to build a test executable to validate the compiler;
# disable that since we have no startup/linker yet.
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

# Do NOT search host paths for libraries / includes / programs.
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
