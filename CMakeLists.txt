cmake_minimum_required(VERSION 3.21)
project(FormatValidation VERSION 1.0.0 LANGUAGES NONE)
enable_testing()
find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
add_test(NAME format-validation.behavior
    COMMAND "${Python3_EXECUTABLE}" -m unittest discover -s "${CMAKE_CURRENT_SOURCE_DIR}/tests" -v)
