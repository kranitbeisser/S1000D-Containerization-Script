# S1000D Containerization Script

> High-performance Python utility to bundle and containerize modular S1000D Issue 4.1/4.2 XML Data Modules. Aggregates member modules into validated container DMs with normalized applicability factoring, C14N deduplication, BREX compliance checks, and configurable enterprise metadata overrides.

---

## Overview

In technical publication suites following the **S1000D standard** (specifically Issue 4.1 and Issue 4.2), complex assemblies often have numerous variant data modules (DMs) sharing the same Standard Numbering System (SNS) address. 

The **S1000D Containerization Script** automates the aggregation of these related variant modules into consolidated **Container Data Modules** (infoCode `914` or inherited infoCode). It handles the full lifecycle:
1. **Grouping & Discovery**: Identifies variant DMs by system code, subsystem, sub-subsystem, assembly, and disassembly code.
2. **Applicability Synthesis**: Extracts `<applic>` annotations from all member modules, applies C14N whitespace normalization and boolean logic factoring (e.g. factoring out common product assertions), and generates human-readable display text compliant with `BRDP-S1-00547`.
3. **Reference Updates**: Rewrites internal and external `<dmRef>` references across the entire publication set so cross-references point to the new container.
4. **BREX Compliance**: Enforces Business Rules Exchange checks (e.g. stripping inline `<issueInfo>` per `BRDP-S1-00573`, removing language/identExtension from content references).
5. **Quality Validation**: Performs end-to-end verification of output data, detecting broken links, XML parsing errors, and reference anomalies.

---

## Features

- **Standard S1000D 4.1 & 4.2 Compatibility**: Preserves DOCTYPE declarations, entity references, namespaces, and schema locations.
- **Smart Applicability Factoring**: Extracts member applicability, deduplicates identical clauses, preserves universal (`All`) assertions, and factors common boolean terms cleanly without invalid empty clauses or redundant evaluate wrappers.
- **Configurable Grouping**: Group by inherited `infoCode`/`infoCodeVariant` or collapse into single container modules (`infoCode="914"`).
- **Automated Reference Retargeting**: Updates both source DMs and third-party referencing DMs to point to new container DMs, including language inheritance and DMC-core matching.
- **Multi-Category Output Organization**:
  - `01_unchanged`: Modules requiring no modifications.
  - `02_modified_source`: Containerized member modules with updated headers or references.
  - `03_modified_other`: External modules whose references were updated to point to the new container.
  - `04_new_container`: Newly created container Data Modules.
- **Strict Configuration Schema**: Validated via JSON Schema (`container_config.schema.json`) with editor autocompletion.

---

## Requirements

- **Python 3.8+**
- **lxml**: Fast XML processing library
  ```sh
  pip install lxml
  ```

---

## Quick Start

### Basic Execution

Run the script by pointing it to an input directory of S1000D XML files and an output directory:

```sh
python S1000DContainerizationScript_v2-2-6.py "path/to/input_dms" "path/to/output_dms"
```

### Input Validation Only

Verify input modules for broken links, syntax errors, and missing targets without creating or altering any files:

```sh
python S1000DContainerizationScript_v2-2-6.py "path/to/input_dms" "path/to/output_dms" --validate-input
```

### Custom Configuration

Pass a custom JSON configuration file:

```sh
python S1000DContainerizationScript_v2-2-6.py "path/to/input_dms" "path/to/output_dms" --config "./container_config.json"
```

### Single-DM Containers

To generate container DMs even for single-member groups:

```sh
python S1000DContainerizationScript_v2-2-6.py "path/to/input_dms" "path/to/output_dms" --create-single-dm-containers
```

---

## Configuration

The script is driven by `container_config.json` (documented in detail in [CONFIG_GUIDE.md](CONFIG_GUIDE.md)).

Key options include:

| Option | Type | Default | Purpose |
| :--- | :--- | :--- | :--- |
| `container_info_code` | `string` | `"914"` | Info code assigned to new container DMs. |
| `use_config_info_code` | `boolean` | `false` | When `false`, container inherits member infoCode. When `true`, forces `container_info_code`. |
| `container_default_dcv` | `string` | `"Z"` | Disassembly code variant for containers. |
| `container_default_sdc` | `string` | `"A000"` | System difference code for containers. |
| `override_rpc_enterprise_code` | `string|null` | `null` | Overrides responsible partner company CAGE/enterprise code. |
| `remove_issue_info_from_content_refs` | `boolean` | `true` | Enforces BRDP-S1-00573 compliance (removes issueInfo from content refs). |
| `generate_applic_display_text` | `boolean` | `true` | Generates human-readable displayText per BRDP-S1-00547. |

For the complete specification of all configuration parameters and their default values, see [`CONFIG_GUIDE.md`](CONFIG_GUIDE.md).

---

## License

This project is licensed under the [MIT License](LICENSE).
