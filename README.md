# FormatValidation

Shared C/C++ formatting tools for MetaHookSv, inspired by DiligentCore's
`BuildTools/FormatValidation`. The style is derived from DiligentCore's
`.clang-format`, interpreted by clang-format **23.1.3**.

## Requirements and direct use

Python 3.9 or newer (CI uses 3.12), Git, and the pinned formatter:

```sh
python -m pip install -r requirements.txt
python clang-format-validate.py --root /path/to/component
python clang-format-validate.py --root /path/to/component --fix
```

The formatter installed for the Python interpreter takes precedence over PATH.
Use `--clang-format-executable` or `FORMAT_VALIDATION_CLANG_FORMAT_EXECUTABLE`
to select an executable explicitly; its version must still be 23.1.3.

Checks print a unified diff without writing sources. Exit codes are 0 (success),
1 (format differences), and 2 (tool or input errors). Fix mode writes only files
with format differences, preserving UTF-8 BOMs and the predominant newline
convention. Comparison ignores CRLF versus LF, not changes inside C++ strings.

Only tracked and non-ignored untracked C/C++ files under `src/`, `include/`, and
`tests/` are considered. Gitlinks and symbolic links are never traversed. The
component's `.clang-format-ignore` accepts repository-relative glob patterns,
directory prefixes ending in `/`, blank lines, and `#` comments. It does not
support negation patterns. An empty source selection is an error.

## CMake consumers

Consumers resolve `FORMAT_VALIDATION_SOURCE_PATH` before using a fixed
FetchContent commit, then include `cmake/FormatValidation.cmake` and call:

```cmake
format_validation_add_component(ComponentName "${CMAKE_CURRENT_SOURCE_DIR}")
```

The module creates `ComponentName-format-check` and `ComponentName-format`.
At the component's top level it also creates `format-check` and `format` aliases.
It copies the shared style into the component root for editor use; consumers
must gitignore that generated `.clang-format`. Only formatting targets require
Python and clang-format, and none are part of the normal build.

MetaHookSv consumers support a compiler-free setup:

```sh
cmake -S . -B build/format -DFORMAT_VALIDATION_ONLY=ON
cmake --build build/format --target format-check
cmake --build build/format --target format
```

Explicit relative source paths are resolved against the consumer repository
root. External source trees are read-only. Consumers pin complete commits;
`v1.0.0` retains the initial release and must not be moved.

## Verification

```sh
python -m unittest discover -s tests -v
cmake -S . -B build
ctest --test-dir build --output-on-failure
```

The wrapper's provenance and MIT terms are recorded in `LICENSE`. Formatting
settings follow [DiligentCore](https://github.com/DiligentGraphics/DiligentCore).
