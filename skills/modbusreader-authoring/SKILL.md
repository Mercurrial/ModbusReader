---
name: modbusreader-authoring
description: Create and validate ModbusReader register maps, projects, dashboards and Python macros from device specifications. Use for ModbusReader file generation or macro authoring, including Russian requests. Does not connect to devices or execute macros.
---

# ModbusReader authoring

Turn the user's specification into files that ModbusReader can load. Preserve the
requested scope; a register-map request does not require a dashboard or macro.
Respond in the user's language. Work offline; this skill does not authorize
device writes or uploading files to external services.

## Sources and decisions

Read [the contract reference](references/authoring.md) for fields, types, macro
semantics and examples. For exact JSON Schemas, permitted builtins, ports and
API signatures consult [contract.json](references/contract.json), selectively
by section. These are generated snapshots of the application, not a generic
Modbus format. If the target application has a newer contract, use its exported
contract and validator rather than guessing compatibility.

Extract a small evidence table from the specification: source page/section,
area, address convention, offset, type/signedness, length, access, scale, unit
and byte/word order. Ask only for consequential missing facts. Never invent
addresses, signedness or byte order. A reference such as 40001 is not a raw
zero-based offset; confirm the vendor's convention before converting. Keep
unresolved entries outside the loadable artifact and list them separately.

## Create the requested artifact

- Use current envelopes and integer zero-based `addr`; omit unsupported fields.
- Choose actual type IDs from the contract. Do not substitute `uint16` or `USHORT` for `UINT16`.
- `area` defaults to `holding`; `input` and `discrete` are read-only. Bit tables
  use `BOOL`, length 1. Keep names and their translations unambiguous.
- Byte orders are project connection settings, not per-register fields. If the
  device needs mixed orders in one type family, disclose the limitation instead
  of inventing a field. Standalone maps do not carry connection settings.
- Macro values are decoded device values **before scale/offset**. Convert units
  explicitly. Do not import modules, use unavailable builtins, or assume
  exception classes exist in the restricted namespace.
- Use named registers where possible. `read("IR 0x0010")` is a macro key;
  `reg_id: "0x10010"` is the dashboard's composite binding for the same address.
- Respect read-only fields even where the runtime may not enforce map access.
  Generate bounded loops and sensible waits for measurement scripts.
- Do not run generated macros to validate them. Their API writes to equipment.

## Validate without the application

The included validator uses Python 3.10+ standard library only. Resolve paths
relative to this skill directory; use the platform's Python command:

```text
python scripts/validate.py describe
python scripts/validate.py validate /absolute/path/map.json
python scripts/validate.py validate /absolute/path/project.mbproj
python scripts/validate.py validate /absolute/path/panel.mbdash --profile /absolute/path/map.json
python scripts/validate.py check-macro /absolute/path/sample.py --profile /absolute/path/map.json
```

Read JSON diagnostics and fix errors; review warnings individually. Exit 0 means
no errors, 1 means validation failed, 2 means unreadable/malformed input or CLI
usage error. `--warnings-as-errors` also returns 1 for warnings. `valid` describes
errors only. Existing legacy files may load in the app yet fail this strict
creation contract; do not silently rewrite them or claim they are corrupt.

Static validation cannot prove device compatibility, algorithm correctness or
runtime safety. Dynamic register expressions and indirect calls need manual
review; passing AST checks is not a security guarantee. If Python/tools are
unavailable, inspect against the reference and explicitly state validation was
not run. Do not fabricate a successful validator result.

Deliver the requested files, relevant source assumptions/unresolved entries,
and actual validation results. Include raw/engineering-unit conversions and
required connection byte orders when they matter to operating the artifact.
