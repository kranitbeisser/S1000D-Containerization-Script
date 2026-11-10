# Configuration Guide for S1000D Containerization Script

This guide details all configuration properties available in `container_config.json`. These options customize the container generation and reference updating processes, ensuring that generated and modified XML modules comply with your project's Business Rules Exchange (BREX) rules.

---

## Configuration Discovery & Validation

* **Default Discovery**: By default, the script looks for `./container_config.json` in the current working directory.
* **CLI Override**: Pass `-c <path>` or `--config <path>` to specify an alternative configuration file location:
  ```sh
  python S1000DContainerizationScript_v2-2-6.py "input_dir" "output_dir" --config "path/to/custom_config.json"
  ```
* **Single-DM Containers**: The `--create-single-dm-containers` CLI flag overrides `create_container_for_single_dms` to `true` for a single run without altering the JSON file.
* **Schema Validation & Autocompletion**: A companion JSON schema is provided at [`container_config.schema.json`](container_config.schema.json). Include `"$schema": "./container_config.schema.json"` at the root of your configuration file to enable real-time validation and autocompletion in supported editors (such as VS Code).

---

## 1. General S1000D Options

| Property | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `container_info_code` | `string` | `"914"` | The infoCode assigned to newly generated container data modules. S1000D specifies `"914"` as the standard code for Container modules. |
| `use_config_info_code` | `boolean` | `false` | When `true`, all generated container DMs use `container_info_code` (with `infoCodeVariant` `"A"`), and all non-excluded DMs sharing the same SNS, disassemblyCode, itemLocationCode, and language collapse into a single container per assembly. When `false`, DMs are partitioned and grouped separately by their original `infoCode` and `infoCodeVariant`, which the generated container inherits. |
| `container_default_dcv` | `string` | `"Z"` | The disassemblyCodeVariant character used to denote a container module. S1000D standard specifies `"Z"`. |
| `container_default_sdc` | `string` | `"A000"` | The default System Difference Code (SDC) assigned to container modules. |
| `create_container_for_single_dms` | `boolean` | `true` | When `true`, container modules are generated even for groups that contain only one member module. When `false`, single-member groups are skipped during container generation. |
| `create_referenced_applic_group` | `boolean` | `false` | When `true`, generates a `<referencedApplicGroup>` element within the container `<content>` section containing cross-referenced applicability statements (`<applic id="applic-NNN">`) for each member module, referenced by `applicRefId` on each member `<dmRef>`. Automatically disabled if `remove_applic_ref_id_from_content_refs` is `true`. |
| `excluded_info_codes` | `array of strings` | `["000" ... "00Z"]` | A list of exact 3-character infoCode strings (case-insensitive) to exclude from container grouping. The default list includes standard management and table-of-contents codes: `"000"`, `"001"`, `"002"`, `"003"`, `"004"`, `"005"`, `"006"`, `"007"`, `"008"`, `"009"`, `"00A"`, `"00B"`, `"00C"`, `"00D"`, `"00E"`, `"00F"`, `"00G"`, `"00H"`, `"00J"`, `"00K"`, `"00L"`, `"00M"`, `"00N"`, `"00P"`, `"00Q"`, `"00R"`, `"00S"`, `"00T"`, `"00U"`, `"00V"`, `"00W"`, `"00X"`, `"00Y"`, `"00Z"`. |

---

## 2. Status & Metadata Options

| Property | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `override_rpc_enterprise_code` | `string` or `null` | `null` | If set (e.g. `"CAGE1"`), overrides the `enterpriseCode` attribute on `<responsiblePartnerCompany>` in generated containers. If `null`, retains the `enterpriseCode` from the primary (alphabetically first) member DM in the group. |
| `override_originator_enterprise_code` | `string` or `null` | `null` | If set (e.g. `"CAGE2"`), overrides the `enterpriseCode` attribute on `<originator>` in generated containers. If `null`, retains the `enterpriseCode` from the primary (alphabetically first) member DM in the group. |
| `container_issue_number` | `string` | `"001"` | The initial issue number assigned to new containers. When set to `"001"`, `<dmStatus>` is assigned `issueType="new"` and `<reasonForUpdate>` uses `updateReasonType="urt52"`. For higher numbers (e.g. `"002"`), `issueType="revised"` and `updateReasonType="urt62"` are used. |
| `container_inwork_number` | `string` | `"00"` | The initial in-work number assigned to new containers. |
| `container_issue_year` | `string` | `"2025"` | Year of container issue date (`<issueDate year="...">`). |
| `container_issue_month` | `string` | `"09"` | Month of container issue date (`<issueDate month="...">`). |
| `container_issue_day` | `string` | `"19"` | Day of container issue date (`<issueDate day="...">`). |
| `use_fixed_reason_for_update` | `boolean` | `true` | When `true`, replaces any `<reasonForUpdate>` element in new containers with a single block containing `fixed_reason_for_update_text`. When `false`, retains the existing `<reasonForUpdate>` elements from the primary member DM. |
| `fixed_reason_for_update_text` | `string` | `"Container data module automatically generated to group variants."` | The exact text placed inside the `<simplePara>` tag of `<reasonForUpdate>`. |

---

## 3. BREX Compliance Flags

These settings ensure compliance with project-specific Business Rules Exchange (BREX) and Schematron validation rules (such as S1000D default business rules).

| Property | Type | Default | BREX Rule / Relevance | Description |
| :--- | :--- | :--- | :--- | :--- |
| `remove_issue_info_from_content_refs` | `boolean` | `true` | **BRDP-S1-00573** | When `true`, completely removes `<issueInfo>` child elements from all `<dmRefIdent>` and `<pmRefIdent>` structures inside the `<content>` section of both container files and updated source data modules. Ensures issue numbers are not presented in inline references or tables. |
| `remove_language_from_content_refs` | `boolean` | `true` | Project BREX (Referencing) | When `true`, strips the `<language>` child element from all `<dmRefIdent>` structures under the `<content>` section. |
| `remove_ident_extension_from_content_refs` | `boolean` | `true` | Project BREX (Referencing) | When `true`, strips the `<identExtension>` child element from all `<dmRefIdent>` structures under the `<content>` section. |
| `remove_applic_ref_id_from_content_refs` | `boolean` | `true` | Project BREX (Referencing) | When `true`, strips the `applicRefId` attribute from all `<dmRef>` elements within the `<content>` section. Because references cannot be linked to `<referencedApplicGroup>` without this attribute, enabling this flag **automatically disables** `create_referenced_applic_group`. |
| `generate_applic_display_text` | `boolean` | `true` | **BRDP-S1-00547** | When `true`, generates human-readable applicability annotations (e.g. `type: Mountain bicycle and (model: Mountain storm or model: Brook trekker)`) and populates a `<displayText>` element with `<simplePara>` as the first child of every `<applic>` element in generated containers and `<referencedApplicGroup>` members. |
