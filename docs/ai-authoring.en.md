# Authoring maps and macros with AI

The portable **modbusreader-authoring** skill helps Claude and ChatGPT/Codex
produce ModbusReader maps, projects, dashboards and macros from device specifications.
It includes an offline validator using Python 3.10+ standard library only.

```text
python tools/build_authoring.py --zip dist/modbusreader-authoring.zip
```

Upload the ZIP to custom Skills in Claude.ai with code execution enabled, or copy
its skill folder to `.claude/skills/` (Claude Code). For local Codex, copy it to
`.agents/skills/` in the project or user home. ChatGPT skill import availability
depends on the client/workspace. If a chat has no Skills support, the instructions
and reference can be attached as context; this is not an installed skill, and
the model must not claim it ran validation without a Python tool.

See [OpenAI's skill guide](https://learn.chatgpt.com/docs/build-skills) and
[Claude's guide](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview).
The build does not install anything into accounts. Rebuild when the application
contract changes. Never infer missing address conventions or byte orders from a
device specification; ask or explicitly leave those entries unresolved.

## CLI

```text
python -m core.authoring_cli describe
python -m core.authoring_cli schema profile
python -m core.authoring_cli validate map.json
python -m core.authoring_cli validate project.mbproj
python -m core.authoring_cli validate panel.mbdash --profile map.json
python -m core.authoring_cli check-macro measurement.py --profile map.json
python -m core.authoring_cli completions --profile map.json --language en
```

`--profile` also accepts a current project. Output is JSON; diagnostic paths are
JSON Pointers and Python locations are 1-based. Exit codes: 0 no errors, 1 validation
errors, 2 input/usage errors. `--warnings-as-errors` returns 1 for warnings too;
`valid` still reflects errors only. Command usage errors go to stderr; file
diagnostics go to stdout as JSON. Input limit: 8 MiB. No file changes, hardware
access or script execution occurs.

Strict validation covers current document envelopes, fields, addresses/spans,
area/type compatibility, ambiguous names, bindings/ports, macro syntax and AST
policy, API arity and literal register references. Overlaps are warnings because
intentional aliases exist. Legacy loader compatibility is unchanged; an old file
may still load in the app while failing this creation contract.

Run `python tools/check_project.py project.mbproj` to check an existing project
through the application loader along with macros in its project folder.
See `AI_GUIDE.md` in the repository root for project structure and examples.

Dynamic references, handle methods and custom functions are not fully analyzed.
Validation does not prove termination, device compatibility or runtime safety.
Macro I/O bypasses engineering scale/offset; convert explicitly.

## Shared contract

The runtime namespace, editor help and Ctrl+Space suggestions use `core.macro_api`.
Inside the first quoted argument to `reg`, `read` or `write`, suggestions come from
the current map. This is not a full language server.

`core.authoring` builds the schemas and performs semantic validation. Generated
JSON Schemas live in `schemas/`, editor-only declarations in `schemas/macro-api.pyi`,
and the [reference](reference/authoring.md) is bundled with the skill.

```text
python tools/build_authoring.py
python tools/build_authoring.py --check
python -m pytest tests/test_authoring.py tests/test_macro_engine.py tests/test_macro_safety.py
```

The drift check and ZIP extraction test keep generated artifacts synchronized;
the extracted validator is tested without installed site-packages.
