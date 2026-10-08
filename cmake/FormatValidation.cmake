include_guard(GLOBAL)

function(format_validation_add_component name source_root)
    if(TARGET "${name}-format-check")
        return()
    endif()
    get_filename_component(tool_root "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/.." ABSOLUTE)
    get_filename_component(source_root "${source_root}" ABSOLUTE)
    if(NOT EXISTS "${source_root}/CMakeLists.txt")
        message(FATAL_ERROR "FormatValidation component is missing: ${source_root}")
    endif()
    configure_file("${tool_root}/.clang-format" "${source_root}/.clang-format" COPYONLY)
    foreach(mode check fix)
        if(mode STREQUAL "check")
            set(target_name "${name}-format-check")
        else()
            set(target_name "${name}-format")
        endif()
        add_custom_target("${target_name}"
            COMMAND "${CMAKE_COMMAND}"
                "-DFORMAT_VALIDATION_REPOSITORY_ROOT=${source_root}"
                "-DFORMAT_VALIDATION_MODE=${mode}"
                "-DFORMAT_VALIDATION_CLANG_FORMAT_EXECUTABLE=${FORMAT_VALIDATION_CLANG_FORMAT_EXECUTABLE}"
                -P "${tool_root}/cmake/RunFormatValidation.cmake"
            COMMENT "clang-format ${mode}: ${name}"
            VERBATIM)
        set_target_properties("${target_name}" PROPERTIES FOLDER "FormatValidation")
    endforeach()
    if(CMAKE_SOURCE_DIR STREQUAL source_root)
        add_custom_target(format-check)
        add_dependencies(format-check "${name}-format-check")
        add_custom_target(format)
        add_dependencies(format "${name}-format")
    endif()
endfunction()
