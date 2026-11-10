# -*- coding: utf-8 -*-
r"""
S1000D Data Module Containerization and Reference Update Script.

Purpose:
This script automates the process of identifying related S1000D data modules (DMs),
grouping them into a new container DM, updating references in the source DMs,
and validating the data for issues like broken links.

Execution Procedure:
Run the script using Python from the command line:
    python S1000DContainerizationScript_v2-2-6.py <input_dir> <output_dir> [flags]

Common examples:
1. Run input data validation only (no files generated or modified):
    python S1000DContainerizationScript_v2-2-6.py "F:\path\to\input" "F:\path\to\output" --validate-input
2. Run grouping, container generation, reference updating, and output validation:
    python S1000DContainerizationScript_v2-2-6.py "F:\path\to\input" "F:\path\to\output"
3. Run container generation for single-member groups too:
    python S1000DContainerizationScript_v2-2-6.py "F:\path\to\input" "F:\path\to\output" --create-single-dm-containers
4. Enable verbose debug logging:
    python S1000DContainerizationScript_v2-2-6.py "F:\path\to\input" "F:\path\to\output" --debug

Version History:
- v2.2.7 (2026-11-02):
  - Fixed logging initialization: setup_logging is now called before ScriptConfig.load_from_file
    and basicConfig uses force=True, resolving 0-byte log files and missing console output.
  - Runtime configuration schema validation: ScriptConfig validates property names, value types,
    and normalizes DMC codes to uppercase with clear warnings/errors.
  - Fixed universal applicability ("All"): prevented fallback overwrite by primary member restrictions
    when any group member has universal applicability.
  - Fixed boolean absorption in applicability factoring: factoring common AND conditions correctly
    handles empty remainder sets and avoids single-child <evaluate> wrappers.
  - Clean C14N deduplication and uniform container indentation: isolated applicability logic from
    editor PIs/whitespace for exact structural matching and applied clean 2-space indentation.
  - Complete BREX BRDP-S1-00547 compliance: verified non-empty displayText in container <applic>
    and <referencedApplicGroup> member copies.
  - Fixed reasonForUpdate retention: when use_fixed_reason_for_update is false, source reasonForUpdate
    elements are preserved instead of omitted.
  - Fixed validation false positives and error reporting:
    - Resolved widespread false BROKEN_LINK errors on DMs where issueInfo/language was stripped
      under BREX rules by adding DMC-core matching and language inheritance.
    - Fixed INCORRECT_REFERENCE false warnings: references already pointing to the container,
      references in container DMs to child DMs, and references in identAndStatusSection are
      now correctly handled.
    - Reported XML parsing failures as XML_PARSE_ERROR in validation reports.
    - Included learnCode/learnEventCode check in is_already_container.
  - Safe root element detection in read_xml_file: correctly skips prolog comments and internal DOCTYPE subsets.
  - Output directory safety: prevented nested input/output collisions and cleared stale output XML files.
  - infoCodeVariant: included in get_grouping_key() and reference updating to prevent
    collision between different info variants (e.g., 251A vs 251B).
  - Dynamic schema detection: containers derive their schema location from the source DM.
  - Prevent duplicate container output: existing containers that are being regenerated in
    04_new_container are no longer duplicated into 01_unchanged.
- v2.2.6:
  - Added JSON schema validation and structured configuration guide.
- v2.2.5 (2025-09-24):
  - Improved logging to provide a status line for every file processed during
    the reference update phase, indicating whether it was changed or not.
- v2.2.4 (2025-09-24):
  - Validation report now includes an "OK" status for every file that passes
    all checks, ensuring the report is never empty and provides a complete status
    overview.
- v2.2.3 (2025-09-24):
  - Fixed a critical bug in the reference update logic where the language of the
    referenced DM was not being correctly determined, causing all key lookups
    to fail. The script now correctly inherits the language from the source DM
    if it's not specified in the <dmRef>.
- v2.2.2 (2025-09-24):
  - Fixed a critical bug where the container map key was created with the original
    infoCode, but lookups were performed with the container infoCode, causing
    the reference update step to always fail.
- v2.2.1 (2025-09-24):
  - Corrected applicability aggregation to ensure multiple conditions are always
    wrapped in a single <evaluate> block, preventing invalid XML structures.
- v2.2.0 (2025-09-24):
  - Changed the main workflow to generate/update files first, then run validation
    on the output and create a report.
"""

# --- Standard Library Imports ---
import argparse
import html
import json
import logging
import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from copy import deepcopy

# --- Third-Party Library Imports ---
try:
    from lxml import etree
except ImportError:
    print("Error: The 'lxml' library is required. Please install it using 'pip install lxml'")
    sys.exit(1)

# --- Configuration ---
class ScriptConfig:
    # Explicit schema definition: property_name -> (default_value, expected_type)
    _DEFAULTS = {
        "container_info_code": ("914", str),
        "use_config_info_code": (False, bool),
        "container_default_dcv": ("Z", str),
        "container_default_sdc": ("A000", str),
        "create_container_for_single_dms": (True, bool),
        "create_referenced_applic_group": (False, bool),
        "excluded_info_codes": ([
            "000", "001", "002", "003", "004", "005", "006", "007", "008", "009",
            "00A", "00B", "00C", "00D", "00E", "00F", "00G", "00H", "00J", "00K",
            "00L", "00M", "00N", "00P", "00Q", "00R", "00S", "00T", "00U", "00V",
            "00W", "00X", "00Y", "00Z"
        ], list),
        "override_rpc_enterprise_code": (None, (str, type(None))),
        "override_originator_enterprise_code": (None, (str, type(None))),
        "container_issue_number": ("001", str),
        "container_inwork_number": ("00", str),
        "container_issue_year": ("2025", str),
        "container_issue_month": ("09", str),
        "container_issue_day": ("19", str),
        "use_fixed_reason_for_update": (True, bool),
        "fixed_reason_for_update_text": ("Container data module automatically generated to group variants.", str),
        "remove_issue_info_from_content_refs": (True, bool),
        "remove_language_from_content_refs": (True, bool),
        "remove_ident_extension_from_content_refs": (True, bool),
        "remove_applic_ref_id_from_content_refs": (True, bool),
        "generate_applic_display_text": (True, bool),
    }

    def __init__(self, config_dict=None):
        config_dict = config_dict or {}
        
        # 1. Warn on unknown keys
        for key in config_dict:
            if key != "$schema" and key not in self._DEFAULTS:
                logging.warning(f"Unknown configuration property '{key}' in configuration file will be ignored.")

        # 2. Validate types and assign values or defaults
        validated = {}
        for prop, (default_val, expected_type) in self._DEFAULTS.items():
            if prop in config_dict:
                val = config_dict[prop]
                is_valid = False
                if expected_type == bool:
                    is_valid = isinstance(val, bool)
                elif expected_type == str:
                    is_valid = not isinstance(val, bool) and isinstance(val, str) and len(val.strip()) > 0
                elif expected_type == list:
                    is_valid = isinstance(val, list) and all(isinstance(x, str) for x in val)
                elif isinstance(expected_type, tuple):
                    is_valid = (val is None) or (not isinstance(val, bool) and isinstance(val, str))

                if is_valid:
                    validated[prop] = val
                else:
                    logging.error(f"Invalid value for '{prop}': {val!r} (expected {expected_type}). Using default: {default_val!r}.")
                    validated[prop] = default_val
            else:
                validated[prop] = default_val

        self.container_info_code = str(validated["container_info_code"]).strip().upper()
        self.use_config_info_code = bool(validated["use_config_info_code"])
        self.container_default_dcv = str(validated["container_default_dcv"]).strip().upper()
        self.container_default_sdc = str(validated["container_default_sdc"]).strip().upper()
        self.create_container_for_single_dms = bool(validated["create_container_for_single_dms"])
        self.create_referenced_applic_group = bool(validated["create_referenced_applic_group"])
        
        self.excluded_info_codes = [str(c).strip().upper() for c in validated["excluded_info_codes"]]
        
        self.override_rpc_enterprise_code = validated["override_rpc_enterprise_code"]
        if self.override_rpc_enterprise_code is not None:
            self.override_rpc_enterprise_code = str(self.override_rpc_enterprise_code).strip()
            
        self.override_originator_enterprise_code = validated["override_originator_enterprise_code"]
        if self.override_originator_enterprise_code is not None:
            self.override_originator_enterprise_code = str(self.override_originator_enterprise_code).strip()
        
        self.container_issue_number = str(validated["container_issue_number"]).strip()
        self.container_inwork_number = str(validated["container_inwork_number"]).strip()
        self.container_issue_year = str(validated["container_issue_year"]).strip()
        self.container_issue_month = str(validated["container_issue_month"]).strip()
        self.container_issue_day = str(validated["container_issue_day"]).strip()
        
        self.use_fixed_reason_for_update = bool(validated["use_fixed_reason_for_update"])
        self.fixed_reason_for_update_text = str(validated["fixed_reason_for_update_text"])
            
        self.remove_issue_info_from_content_refs = bool(validated["remove_issue_info_from_content_refs"])
        self.remove_language_from_content_refs = bool(validated["remove_language_from_content_refs"])
        self.remove_ident_extension_from_content_refs = bool(validated["remove_ident_extension_from_content_refs"])
        self.remove_applic_ref_id_from_content_refs = bool(validated["remove_applic_ref_id_from_content_refs"])
        self.generate_applic_display_text = bool(validated["generate_applic_display_text"])
        
        # Cross-checks
        if self.remove_applic_ref_id_from_content_refs and self.create_referenced_applic_group:
            logging.warning("remove_applic_ref_id_from_content_refs is enabled. "
                            "Disabling create_referenced_applic_group to comply with BREX rules.")
            self.create_referenced_applic_group = False

    @classmethod
    def load_from_file(cls, config_path: Path) -> 'ScriptConfig':
        if not config_path.is_file():
            logging.warning(f"Configuration file not found at {config_path}. Using default configuration settings.")
            return cls()
        try:
            with config_path.open('r', encoding='utf-8') as f:
                data = json.load(f)
            logging.info(f"Loaded configuration from {config_path}")
            return cls(data)
        except Exception as e:
            logging.error(f"Failed to load configuration file {config_path}: {e}. Using default configuration settings.")
            return cls()

# Global config instance that will be set in main()
config = ScriptConfig()


# --- Data Classes for Structure ---
@dataclass
class Dmc:
    """A data class to hold the components of a Data Module Code."""
    model_ident_code: str
    system_diff_code: str
    system_code: str
    sub_system_code: str
    sub_sub_system_code: str
    assy_code: str
    disassy_code: str
    disassy_code_variant: str
    info_code: str
    info_code_variant: str
    item_location_code: str
    language: str
    issue: str
    inwork: str
    learn_code: Optional[str] = None
    learn_event_code: Optional[str] = None
    
    def get_grouping_key(self, use_container_info_code=False) -> Tuple:
        """
        Returns the tuple of attributes used for grouping DMs into containers.
        Includes infoCodeVariant to avoid collisions between variants of the same infoCode.
        """
        if use_container_info_code and config.use_config_info_code:
            info_code_to_use = config.container_info_code
            info_variant_to_use = "A"
        else:
            info_code_to_use = self.info_code
            info_variant_to_use = self.info_code_variant

        return (
            self.model_ident_code,
            self.system_code,
            self.sub_system_code,
            self.sub_sub_system_code,
            self.assy_code,
            self.disassy_code,
            info_code_to_use,
            info_variant_to_use,
            self.item_location_code,
            self.language.upper()
        )

    def to_filename(self, is_container=False) -> str:
        """Constructs the S1000D filename from the DMC components."""
        info_code = self.info_code
        info_code_variant = self.info_code_variant
        dcv = config.container_default_dcv if is_container else self.disassy_code_variant
        sdc = config.container_default_sdc if is_container else self.system_diff_code
        
        # Format language code to xx-XX
        lang_parts = self.language.split('-')
        if len(lang_parts) != 2:
            lang_parts = self.language.split('_')
        formatted_lang = f"{lang_parts[0].lower()}-{lang_parts[1].upper()}" if len(lang_parts) == 2 else self.language
        
        lc_suffix = ""
        if not is_container:
            if self.learn_code:
                lc_suffix += f"-{self.learn_code}"
                if self.learn_event_code:
                    lc_suffix += self.learn_event_code
            
        return (f"DMC-{self.model_ident_code}-{sdc}-"
                f"{self.system_code}-{self.sub_system_code}{self.sub_sub_system_code}-"
                f"{self.assy_code}-{self.disassy_code}{dcv}-{info_code}"
                f"{info_code_variant}-{self.item_location_code}{lc_suffix}_"
                f"{self.issue}-{self.inwork}_{formatted_lang}.xml")

@dataclass
class ValidationIssue:
    """A data class to hold information about a single validation issue."""
    source_file: str
    line_number: int
    severity: str  # ERROR, WARNING, OK
    problem_type: str  # BROKEN_LINK, INCORRECT_REFERENCE, VALIDATION_PASSED
    details: str

# --- Core Functions ---
def setup_logging(log_dir: Path, debug: bool):
    """
    Configures the logging for the script, directing output to both the console and a file.
    Uses force=True to ensure handlers take effect even if logging was touched earlier.
    """
    global DEBUG_MODE
    DEBUG_MODE = debug
    
    log_level = logging.DEBUG if DEBUG_MODE else logging.INFO
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"container_script_{datetime.now():%Y%m%d_%H%M%S}.log"
    
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)-7s] [%(threadName)-10s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ],
        force=True
    )
    logging.info("Logging initialized.")
    if DEBUG_MODE:
        logging.debug("Debug mode enabled.")

def remove_element_preserve_whitespace(parent: etree._Element, child: etree._Element):
    """
    Removes a child element while preserving any trailing whitespace/newlines
    so that XML formatting and indentation are not corrupted.
    """
    if child.tail:
        prev = child.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + child.tail
        else:
            parent.text = (parent.text or "") + child.tail
    parent.remove(child)

def clean_applic_logic_node(elem: etree._Element) -> Optional[etree._Element]:
    """
    Recursively constructs a clean, namespace-free copy of an <evaluate>, <assert>,
    or <assign> node, stripping whitespace-only text/tail so C14N comparison
    is purely structural and independent of source formatting or editor PIs.
    """
    if not isinstance(elem.tag, str) or callable(elem.tag):
        return None
    tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
    if tag not in ('assert', 'evaluate', 'assign'):
        return None

    clean_elem = etree.Element(tag, attrib=dict(elem.attrib))
    if elem.text and elem.text.strip():
        clean_elem.text = elem.text.strip()

    for child in elem:
        clean_child = clean_applic_logic_node(child)
        if clean_child is not None:
            clean_elem.append(clean_child)

    return clean_elem

def strip_structural_whitespace(elem: etree._Element):
    """
    Recursively strips editor processing instructions and comments, clears blank formatting
    whitespace on parent elements, and trims text on leaf elements.
    """
    for child in list(elem):
        if not isinstance(child.tag, str) or callable(child.tag):
            elem.remove(child)
        else:
            strip_structural_whitespace(child)

    if len(elem) > 0:
        if elem.text and not elem.text.strip():
            elem.text = None
    elif elem.text and elem.text.strip():
        elem.text = elem.text.strip()

    if elem.tail and not elem.tail.strip():
        elem.tail = None

def read_xml_file(file_path: Path) -> Tuple[Optional[str], Optional[etree._Element]]:
    """
    Reads an XML file, carefully preserving the header (including multi-line
    DOCTYPE declarations and comments) and parsing the rest of the content without stripping blank text.
    """
    try:
        with file_path.open('r', encoding='utf-8') as f:
            content_str = f.read()

        # Safely find the root element start tag by skipping XML declarations/PIs, comments, and DOCTYPE declarations
        prolog_pattern = re.compile(
            r'^\s*(?:<\?.*?\?>\s*|<!--.*?-->\s*|<!DOCTYPE\s+[^>\[<\s]+(?:\s+[^>\[\s]+)*(?:\s*\[.*?\])?\s*>\s*)*',
            re.DOTALL | re.IGNORECASE
        )
        prolog_match = prolog_pattern.match(content_str)
        root_start = prolog_match.end() if prolog_match else 0
        if root_start < len(content_str) and content_str[root_start] == '<':
            header = content_str[:root_start]
            body = content_str[root_start:]
        else:
            header = '<?xml version="1.0" encoding="UTF-8"?>\n'
            body = content_str

        # If header does not contain an XML declaration, add one to ensure UTF-8 parsing
        parse_header = header
        if '<?xml' not in header:
            parse_header = '<?xml version="1.0" encoding="UTF-8"?>\n' + header

        parser = etree.XMLParser(remove_blank_text=False, recover=False, resolve_entities=False)
        tree = etree.fromstring((parse_header + body).encode('utf-8'), parser)
        
        return header, tree
    except Exception as e:
        logging.error(f"Failed to read or parse file {file_path}: {e}")
    return None, None

def write_xml_file(tree: etree._Element, header: str, output_path: Path, pretty_print: bool = False):
    """
    Writes the lxml tree to the specified output path, prepending the preserved header.
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        xml_bytes = etree.tostring(tree, pretty_print=pretty_print, xml_declaration=False, encoding='utf-8')
        with output_path.open('wb') as f:
            f.write(header.encode('utf-8'))
            f.write(xml_bytes)
        logging.debug(f"Successfully wrote XML file to {output_path}")
    except Exception as e:
        logging.error(f"Failed to write XML file to {output_path}: {e}")
        
def parse_dmc_from_filename(filename: str) -> Optional[Dmc]:
    """
    Parses an S1000D filename to extract its DMC components.
    """
    if not filename.upper().startswith("DMC-"):
        logging.debug(f"Skipping non-DM filename '{filename}' from pattern matching.")
        return None

    pattern = re.compile(
        r"DMC-(?P<mic>[A-Z0-9]{2,14})-(?P<sdc>[A-Z0-9]{1,4})-"
        r"(?P<sys>[A-Z0-9]{2,3})-(?P<ssys>[A-Z0-9]{1})(?P<sssys>[A-Z0-9]{1})-"
        r"(?P<asy>[A-Z0-9]{2,4})-(?P<dc>[A-Z0-9]{2})(?P<dcv>[A-Z0-9]{1,3})-"
        r"(?P<ic>[A-Z0-9]{3})(?P<icv>[A-Z0-9]{1})-(?P<ilc>[A-Z0-9]{1})"
        r"(?:-(?P<lc>[A-Z0-9]{4}))?_"
        r"(?P<iss>\d{3})-(?P<inw>\d{2})_(?P<lang>[a-zA-Z]{2}[-_][a-zA-Z]{2})\.xml", re.IGNORECASE
    )
    match = pattern.match(filename)
    if not match:
        logging.warning(f"Filename '{filename}' does not match S1000D DMC pattern.")
        return None
    
    parts = match.groupdict()
    lc = parts.get('lc')
    learn_code = None
    learn_event_code = None
    if lc:
        lc = lc.upper()
        if len(lc) == 4:
            learn_code = lc[:3]
            learn_event_code = lc[3]
        else:
            learn_code = lc

    return Dmc(
        model_ident_code=parts['mic'].upper(), system_diff_code=parts['sdc'].upper(),
        system_code=parts['sys'].upper(), sub_system_code=parts['ssys'].upper(),
        sub_sub_system_code=parts['sssys'].upper(), assy_code=parts['asy'].upper(),
        disassy_code=parts['dc'].upper(), disassy_code_variant=parts['dcv'].upper(),
        info_code=parts['ic'].upper(), info_code_variant=parts['icv'].upper(),
        item_location_code=parts['ilc'].upper(), issue=parts['iss'],
        inwork=parts['inw'], language=parts['lang'].replace('_', '-'),
        learn_code=learn_code,
        learn_event_code=learn_event_code
    )
    
def find_and_group_modules(input_dir: Path, create_single_dm_containers: bool) -> Dict[Tuple, List[Path]]:
    """
    Scans the input directory for XML files, parses their DMCs, filters out containers and excluded infoCodes,
    deduplicates multiple issues of the same DM, and groups them deterministically.
    """
    logging.info(f"Scanning for data modules in '{input_dir}'...")
    all_xml_files = list(input_dir.rglob("*.xml"))
    if not all_xml_files:
        logging.warning("No XML files found in the input directory.")
        return {}
        
    dm_code_to_best: Dict[Tuple, Tuple[Tuple[int, int], Path, Dmc]] = {}

    with ThreadPoolExecutor(max_workers=os.cpu_count(), thread_name_prefix="DMC_Parser") as executor:
        future_to_file = {executor.submit(parse_dmc_from_filename, f.name): f for f in all_xml_files}
        for future in as_completed(future_to_file):
            dmc = future.result()
            if dmc is None:
                continue
            
            # 1. Filter out existing containers
            if dmc.disassy_code_variant.upper() == config.container_default_dcv:
                logging.debug(f"Skipping {dmc.to_filename()}: it is a container.")
                continue

            # 2. Filter out DMs with excluded infoCodes
            if dmc.info_code in config.excluded_info_codes:
                logging.info(f"Skipping {dmc.to_filename()}: infoCode '{dmc.info_code}' is in the exclusion list.")
                continue

            file_path = future_to_file[future]
            # Key representing the specific DM across different issues
            core_key = (
                dmc.model_ident_code, dmc.system_diff_code, dmc.system_code,
                dmc.sub_system_code, dmc.sub_sub_system_code, dmc.assy_code,
                dmc.disassy_code, dmc.disassy_code_variant, dmc.info_code,
                dmc.info_code_variant, dmc.item_location_code, dmc.learn_code,
                dmc.learn_event_code, dmc.language.upper()
            )
            try:
                issue_val = (int(dmc.issue), int(dmc.inwork))
            except (ValueError, TypeError):
                issue_val = (0, 0)

            # If multiple issues of the same DM are present, keep the highest issue
            if core_key not in dm_code_to_best or issue_val > dm_code_to_best[core_key][0]:
                dm_code_to_best[core_key] = (issue_val, file_path, dmc)

    dm_map = {path: dmc for _, path, dmc in dm_code_to_best.values()}
    
    groups = {}
    for path, dmc in dm_map.items():
        key = dmc.get_grouping_key(use_container_info_code=True)
        if key not in groups:
            groups[key] = []
        groups[key].append(path)

    # Sort files in each group deterministically
    for key in groups:
        groups[key].sort(key=lambda p: p.name)
        
    if create_single_dm_containers:
        logging.info("Container generation for single DMs is enabled. All groups will be processed.")
        final_groups = groups
    else:
        logging.info("Container generation for single DMs is disabled. Filtering groups with only one member.")
        final_groups = {k: v for k, v in groups.items() if len(v) > 1}
        
    logging.info(f"Found {len(all_xml_files)} total XML files, processed {len(dm_map)} valid DMs for grouping.")
    logging.info(f"Identified {len(final_groups)} groups for containerization.")
    return final_groups

def extract_applic_logic(applic_elem: Optional[etree._Element]) -> Tuple[bool, Optional[etree._Element]]:
    """
    Extracts the core logic element from an <applic> element.
    Returns (has_restrictions, logic_element).
    If has_restrictions is False, the DM applies universally ('All').
    """
    if applic_elem is None:
        return False, None
        
    logic_children = [clean_applic_logic_node(c) for c in applic_elem if isinstance(c.tag, str) and c.tag in ('assert', 'evaluate', 'assign')]
    logic_children = [c for c in logic_children if c is not None]
    if not logic_children:
        return False, None
        
    if len(logic_children) == 1:
        return True, logic_children[0]
    
    # Multiple logic children at root of applic imply an implicit 'and'
    and_eval = etree.Element("evaluate", andOr="and")
    for c in logic_children:
        and_eval.append(c)
    return True, and_eval

def aggregate_applicability(group_files: List[Path]) -> etree._Element:
    """
    Merges applicability statements from multiple DMs.
    The applicability of the container is the logical OR of all member DMs.
    If any member applies universally ('All'), the container applies universally ('All').
    Common AND conditions across variants are factored out cleanly.
    Returns an <applic> element (empty <applic/> if universal).
    """
    dm_logics: List[etree._Element] = []
    
    for dm_path in sorted(group_files):
        _, tree = read_xml_file(dm_path)
        if tree is not None:
            applic_elem = tree.find(".//dmStatus/applic")
            has_restrictions, logic = extract_applic_logic(applic_elem)
            if not has_restrictions or logic is None:
                # If any variant has no restrictions, the container as a whole applies to 'All'
                logging.debug(f"DM {dm_path.name} applies to All; container applicability is universal.")
                return etree.Element("applic")
            dm_logics.append(logic)

    if not dm_logics:
        return etree.Element("applic")

    # Case 1: Single DM or all DMs have identical applicability
    first_c14n = etree.tostring(dm_logics[0], method="c14n")
    if all(etree.tostring(l, method="c14n") == first_c14n for l in dm_logics):
        agg_applic = etree.Element("applic")
        agg_applic.append(deepcopy(dm_logics[0]))
        return agg_applic

    # Case 2: Check if all DMs have evaluate andOr="and" with factorable common assertions
    all_are_and = all(l.tag == 'evaluate' and l.get('andOr') == 'and' for l in dm_logics)
    if all_are_and:
        common_candidates = []
        for child in dm_logics[0]:
            child_c14n = etree.tostring(child, method="c14n")
            if all(any(etree.tostring(other_child, method="c14n") == child_c14n for other_child in other_logic) for other_logic in dm_logics[1:]):
                common_candidates.append(deepcopy(child))
                
        if common_candidates:
            common_c14n_set = {etree.tostring(c, method="c14n") for c in common_candidates}
            has_unrestricted_common = False
            unique_per_dm = []
            for logic in dm_logics:
                remaining = [c for c in logic if etree.tostring(c, method="c14n") not in common_c14n_set]
                if len(remaining) == 0:
                    has_unrestricted_common = True
                elif len(remaining) == 1:
                    unique_per_dm.append(deepcopy(remaining[0]))
                elif len(remaining) > 1:
                    sub_and = etree.Element("evaluate", andOr="and")
                    for r in remaining:
                        sub_and.append(deepcopy(r))
                    unique_per_dm.append(sub_and)

            agg_applic = etree.Element("applic")
            # If any DM had no remaining restrictions beyond common_candidates,
            # Common OR (Common AND X) simplifies to Common.
            if has_unrestricted_common or not unique_per_dm:
                if len(common_candidates) == 1:
                    agg_applic.append(common_candidates[0])
                else:
                    and_eval = etree.SubElement(agg_applic, "evaluate", andOr="and")
                    for c in common_candidates:
                        and_eval.append(c)
                return agg_applic

            # Otherwise, factor out common and append the OR of unique per DM
            seen_unique = set()
            dedup_unique = []
            for u in unique_per_dm:
                u_c14n = etree.tostring(u, method="c14n")
                if u_c14n not in seen_unique:
                    seen_unique.add(u_c14n)
                    dedup_unique.append(u)

            if len(dedup_unique) == 1:
                combined_children = common_candidates + [dedup_unique[0]]
            else:
                or_eval = etree.Element("evaluate", andOr="or")
                for u in dedup_unique:
                    or_eval.append(u)
                combined_children = common_candidates + [or_eval]

            if len(combined_children) == 1:
                agg_applic.append(combined_children[0])
            else:
                and_eval = etree.SubElement(agg_applic, "evaluate", andOr="and")
                for c in combined_children:
                    and_eval.append(c)
            return agg_applic

    # Case 3: Combine all DMs' logics under an OR evaluation, flattening nested ORs
    or_children = []
    seen_c14n = set()
    for logic in dm_logics:
        if logic.tag == 'evaluate' and logic.get('andOr') == 'or':
            for child in logic:
                c_c14n = etree.tostring(child, method="c14n")
                if c_c14n not in seen_c14n:
                    seen_c14n.add(c_c14n)
                    or_children.append(deepcopy(child))
        else:
            l_c14n = etree.tostring(logic, method="c14n")
            if l_c14n not in seen_c14n:
                seen_c14n.add(l_c14n)
                or_children.append(deepcopy(logic))

    agg_applic = etree.Element("applic")
    if len(or_children) == 1:
        agg_applic.append(or_children[0])
    else:
        or_eval = etree.SubElement(agg_applic, "evaluate", andOr="or")
        for child in or_children:
            or_eval.append(child)

    return agg_applic

def generate_applicability_text(element) -> str:
    """
    Recursively generates a human-readable string from a nested
    <evaluate>, <assert>, and <assign> structure.
    """
    if not isinstance(element.tag, str) or callable(element.tag):
        return ''

    tag = element.tag
    attrib = element.attrib

    if tag == 'assert':
        prop_ident = attrib.get('applicPropertyIdent', '')
        prop_value = attrib.get('applicPropertyValues', '')
        if not prop_value and element.text:
            prop_value = element.text.strip()

        if prop_ident and prop_value:
            return f"{prop_ident}: {prop_value}"
        return prop_ident or prop_value or ''
            
    elif tag == 'assign':
        prop_ident = attrib.get('applicPropertyIdent', '')
        prop_value = attrib.get('applicPropertyValue', '')
        if prop_ident and prop_value:
            return f"{prop_ident}: {prop_value}"
        return prop_ident or prop_value or ''

    elif tag == 'evaluate':
        operator = attrib.get('andOr', 'and')
        parts = []
        for child in element:
            child_text = generate_applicability_text(child)
            if child_text:
                parts.append(child_text)
        
        joined_text = f" {operator} ".join(parts)
        if len(parts) > 1:
            return f"({joined_text})"
        return joined_text
    
    return ''

def generate_container_display_text(applic_element) -> str:
    """
    Finds the logic child within an <applic> element and generates its human-readable text.
    """
    logic_element = None
    for child in applic_element:
        if isinstance(child.tag, str) and child.tag in ('evaluate', 'assert', 'assign'):
            logic_element = child
            break
    if logic_element is not None:
        new_text = generate_applicability_text(logic_element)
        if new_text.startswith('(') and new_text.endswith(')'):
            # Only strip outer parentheses if they enclose the entire expression
            depth = 0
            enclosed = True
            for i, ch in enumerate(new_text[:-1]):
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                    if depth == 0 and i < len(new_text) - 1:
                        enclosed = False
                        break
            if enclosed and depth == 1:
                new_text = new_text[1:-1]
        return new_text or "All"
    return "All"

def ensure_applic_display_text(applic_elem: etree._Element):
    """
    Ensures that an <applic> element has a non-empty <displayText><simplePara>
    as its first child, satisfying BRDP-S1-00547.
    """
    dp_elem = applic_elem.find("displayText")
    if dp_elem is not None:
        sp_elem = dp_elem.find("simplePara")
        if sp_elem is not None and sp_elem.text and sp_elem.text.strip():
            return

    display_text = generate_container_display_text(applic_elem)
    if display_text:
        if dp_elem is None:
            dp_elem = etree.Element("displayText")
            applic_elem.insert(0, dp_elem)
        sp_elem = dp_elem.find("simplePara")
        if sp_elem is None:
            sp_elem = etree.SubElement(dp_elem, "simplePara")
        sp_elem.text = display_text

def create_container_dm(group_files: List[Path], container_dmc: Dmc, output_dir: Path):
    """
    Creates a new container data module XML structure.
    """
    logging.info(f"Generating new container: {container_dmc.to_filename(is_container=True)}")
    
    sorted_files = sorted(group_files, key=lambda p: p.name)
    primary_target_path = sorted_files[0]
        
    _, primary_tree = read_xml_file(primary_target_path)
    if primary_tree is None:
        logging.error(f"Cannot create container, failed to parse primary target {primary_target_path}")
        return

    XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
    nsmap = {k: v for k, v in primary_tree.nsmap.items() if k}
    nsmap['xsi'] = XSI_NS
    
    dmodule = etree.Element("dmodule", nsmap=nsmap)
    # Dynamically detect schema location from primary source DM
    orig_schema = primary_tree.get(f"{{{XSI_NS}}}noNamespaceSchemaLocation") or primary_tree.get("noNamespaceSchemaLocation")
    if orig_schema and "/" in orig_schema:
        container_schema = re.sub(r'/[^/]+\.xsd$', '/container.xsd', orig_schema)
    else:
        container_schema = "http://www.s1000d.org/S1000D_4-1/xml_schema_flat/container.xsd"
    dmodule.set(f"{{{XSI_NS}}}noNamespaceSchemaLocation", container_schema)

    ident_section = etree.SubElement(dmodule, "identAndStatusSection")
    content_section = etree.SubElement(dmodule, "content")
    
    original_ident = primary_tree.find(".//identAndStatusSection")
    if original_ident is not None:
        ident_section[:] = deepcopy(original_ident[:])
        
        # Remove identExtension from container dmIdent if present
        dm_ident_elem = ident_section.find(".//dmIdent")
        if dm_ident_elem is not None:
            ident_ext = dm_ident_elem.find("identExtension")
            if ident_ext is not None:
                dm_ident_elem.remove(ident_ext)

        old_dm_status = ident_section.find(".//dmStatus")
        if old_dm_status is not None:
            new_dm_status = etree.Element("dmStatus")
            issue_type = "new" if config.container_issue_number == "001" else "revised"
            new_dm_status.set("issueType", issue_type)
            
            # --- Handle RPC and Originator overrides before copying ---
            rpc_elem = old_dm_status.find(".//responsiblePartnerCompany")
            if rpc_elem is not None and config.override_rpc_enterprise_code:
                rpc_elem.set("enterpriseCode", config.override_rpc_enterprise_code)

            orig_elem = old_dm_status.find(".//originator")
            if orig_elem is not None and config.override_originator_enterprise_code:
                orig_elem.set("enterpriseCode", config.override_originator_enterprise_code)

            elements_to_keep = {
                "security": old_dm_status.find(".//security"), "logo": old_dm_status.find(".//logo"),
                "responsiblePartnerCompany": rpc_elem,
                "originator": orig_elem, "applicCrossRefTableRef": old_dm_status.find(".//applicCrossRefTableRef"),
                "brexDmRef": old_dm_status.find(".//brexDmRef"), "qualityAssurance": old_dm_status.findall(".//qualityAssurance"),
                "skillLevel": old_dm_status.find(".//skillLevel")
            }
            aggregated_applic = aggregate_applicability(sorted_files)
            dr_elem = etree.Element("dataRestrictions")
            ri_elem = etree.SubElement(dr_elem, "restrictionInstructions")
            etree.SubElement(ri_elem, "dataDistribution")
            ec_elem = etree.SubElement(ri_elem, "exportControl", exportRegulationType="exp00")
            ers_elem = etree.SubElement(ec_elem, "exportRegistrationStmt")
            etree.SubElement(ers_elem, "simplePara")
            rfu_elems = []
            if config.use_fixed_reason_for_update:
                rfu_elem = etree.Element("reasonForUpdate")
                rfu_elem.set("updateHighlight", "0")
                rfu_elem.set("updateReasonType", "urt52" if config.container_issue_number == "001" else "urt62")
                sp_elem = etree.SubElement(rfu_elem, "simplePara")
                sp_elem.text = config.fixed_reason_for_update_text
                rfu_elems.append(rfu_elem)
            else:
                for old_rfu in old_dm_status.findall(".//reasonForUpdate"):
                    rfu_elems.append(deepcopy(old_rfu))
            
            if elements_to_keep["security"] is not None: new_dm_status.append(elements_to_keep["security"])
            new_dm_status.append(dr_elem)
            if elements_to_keep["logo"] is not None: new_dm_status.append(elements_to_keep["logo"])
            if elements_to_keep["responsiblePartnerCompany"] is not None: new_dm_status.append(elements_to_keep["responsiblePartnerCompany"])
            if elements_to_keep["originator"] is not None: new_dm_status.append(elements_to_keep["originator"])
            if elements_to_keep["applicCrossRefTableRef"] is not None: new_dm_status.append(elements_to_keep["applicCrossRefTableRef"])
            
            # Handle aggregated applicability and human-readable text generation
            if config.generate_applic_display_text:
                ensure_applic_display_text(aggregated_applic)
            new_dm_status.append(aggregated_applic)
                
            if elements_to_keep["brexDmRef"] is not None: new_dm_status.append(elements_to_keep["brexDmRef"])
            for qa in elements_to_keep["qualityAssurance"]:
                first_ver = qa.find(".//firstVerification")
                if first_ver is not None:
                    first_ver.set("verificationType", "tabtop")
                new_dm_status.append(qa)
            if elements_to_keep["skillLevel"] is not None: new_dm_status.append(elements_to_keep["skillLevel"])
            for rfu_elem in rfu_elems:
                new_dm_status.append(rfu_elem)
            
            old_dm_status.getparent().replace(old_dm_status, new_dm_status)

        issue_info_elem = ident_section.find(".//issueInfo")
        if issue_info_elem is not None:
            issue_info_elem.set("issueNumber", config.container_issue_number)
            issue_info_elem.set("inWork", config.container_inwork_number)
        issue_date_elem = ident_section.find(".//issueDate")
        if issue_date_elem is not None:
            issue_date_elem.set("year", config.container_issue_year)
            issue_date_elem.set("month", config.container_issue_month)
            issue_date_elem.set("day", config.container_issue_day)
        dm_code_elem = ident_section.find(".//dmCode")
        if dm_code_elem is not None:
            for field in fields(container_dmc):
                attr_name = "".join(word.capitalize() for word in field.name.split('_'))
                attr_name = attr_name[0].lower() + attr_name[1:]
                if dm_code_elem.get(attr_name) is not None:
                    val = getattr(container_dmc, field.name)
                    if val is not None:
                        dm_code_elem.set(attr_name, val)
                    else:
                        dm_code_elem.attrib.pop(attr_name, None)

    # --- Build Content Section ---
    refs_block = etree.Element("refs")
    DMC_FIELD_TO_ATTR_MAP = {f.name:(''.join(word.capitalize() for word in f.name.split('_'))) for f in fields(Dmc)}
    for f, n in DMC_FIELD_TO_ATTR_MAP.items(): DMC_FIELD_TO_ATTR_MAP[f] = n[0].lower() + n[1:]
    
    applic_id_counter = 1
    referenced_applic_group = etree.Element("referencedApplicGroup")
    
    for dm_path in sorted_files:
        dmc_target = parse_dmc_from_filename(dm_path.name)
        if dmc_target:
            dm_ref = etree.SubElement(refs_block, "dmRef")
            
            target_applic_elem = None
            if config.create_referenced_applic_group and not config.remove_applic_ref_id_from_content_refs:
                _, target_tree = read_xml_file(dm_path)
                if target_tree is not None:
                    target_applic_elem = target_tree.find(".//dmStatus/applic")

            # Only add applicRefId if an applic element is actually available to reference
            if target_applic_elem is not None:
                applic_id = f"applic-{applic_id_counter:03}"
                dm_ref.set("applicRefId", applic_id)
                applic_copy = deepcopy(target_applic_elem)
                applic_copy.set("id", applic_id)
                if config.generate_applic_display_text:
                    ensure_applic_display_text(applic_copy)
                referenced_applic_group.append(applic_copy)
                applic_id_counter += 1
            
            dm_ref_ident = etree.SubElement(dm_ref, "dmRefIdent")
            dm_code = etree.SubElement(dm_ref_ident, "dmCode")
            for field_name, attr_name in DMC_FIELD_TO_ATTR_MAP.items():
                value = getattr(dmc_target, field_name, None)
                if value is not None and attr_name not in ["language", "issue", "inwork"]:
                    dm_code.set(attr_name, value)
            
            if not config.remove_issue_info_from_content_refs:
                issue_info = etree.SubElement(dm_ref_ident, "issueInfo")
                issue_info.set("issueNumber", dmc_target.issue)
                issue_info.set("inWork", dmc_target.inwork)

            if not config.remove_language_from_content_refs:
                lang_parts = dmc_target.language.split('-')
                if len(lang_parts) != 2:
                    lang_parts = dmc_target.language.split('_')
                if len(lang_parts) == 2:
                    language_element = etree.SubElement(dm_ref_ident, "language")
                    language_element.set("languageIsoCode", lang_parts[0].lower())
                    language_element.set("countryIsoCode", lang_parts[1].upper())

    content_section.append(refs_block)
    if config.create_referenced_applic_group and not config.remove_applic_ref_id_from_content_refs and len(referenced_applic_group) > 0:
        content_section.append(referenced_applic_group)
    
    container_element = etree.SubElement(content_section, "container")
    container_element.append(deepcopy(refs_block))
    
    strip_structural_whitespace(dmodule)
    etree.indent(dmodule, space="  ")
    header = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE dmodule []>\n'
    output_path = output_dir / container_dmc.to_filename(is_container=True)
    write_xml_file(dmodule, header, output_path, pretty_print=False)

def update_dm_references(source_path: Path, container_map: Dict[Tuple, Dmc], output_dirs: Dict[str, Path]):
    """
    Processes a single source DM, updates its references, cleans up elements based on compliance settings,
    and saves it to the correct output folder without destroying mixed-content formatting.
    """
    header, tree = read_xml_file(source_path)
    if tree is None:
        return

    source_dmc = parse_dmc_from_filename(source_path.name)
    if source_dmc is None:
        shutil.copy(source_path, output_dirs["unchanged"] / source_path.name)
        return
    source_language = source_dmc.language

    is_file_changed = False

    content_elem = tree.find(".//content")
    if content_elem is not None:
        # 1. Process all dmRefs under content
        dm_refs = content_elem.findall(".//dmRef")
        for dm_ref in dm_refs:
            # Check for applicRefId removal
            if config.remove_applic_ref_id_from_content_refs:
                if dm_ref.get("applicRefId") is not None:
                    dm_ref.attrib.pop("applicRefId")
                    is_file_changed = True

            # Process dmRefIdent
            dm_ref_ident = dm_ref.find("dmRefIdent")
            if dm_ref_ident is not None:
                dm_code = dm_ref_ident.find("dmCode")
                if dm_code is not None:
                    try:
                        # Extract reference language to build the mapping key
                        lang_elem = dm_ref_ident.find("language")
                        language = source_language
                        if lang_elem is not None and lang_elem.get("languageIsoCode") and lang_elem.get("countryIsoCode"):
                            language = f"{lang_elem.get('languageIsoCode')}-{lang_elem.get('countryIsoCode')}"

                        def _attr_upper(elem, attr):
                            val = elem.get(attr)
                            return val.upper() if isinstance(val, str) else val

                        ref_dmc = Dmc(
                            model_ident_code=_attr_upper(dm_code, "modelIdentCode"),
                            system_diff_code=_attr_upper(dm_code, "systemDiffCode"),
                            system_code=_attr_upper(dm_code, "systemCode"),
                            sub_system_code=_attr_upper(dm_code, "subSystemCode"),
                            sub_sub_system_code=_attr_upper(dm_code, "subSubSystemCode"),
                            assy_code=_attr_upper(dm_code, "assyCode"),
                            disassy_code=_attr_upper(dm_code, "disassyCode"),
                            disassy_code_variant=_attr_upper(dm_code, "disassyCodeVariant"),
                            info_code=_attr_upper(dm_code, "infoCode"),
                            info_code_variant=_attr_upper(dm_code, "infoCodeVariant"),
                            item_location_code=_attr_upper(dm_code, "itemLocationCode"),
                            language=language, issue="", inwork="",
                            learn_code=_attr_upper(dm_code, "learnCode"),
                            learn_event_code=_attr_upper(dm_code, "learnEventCode")
                        )

                        ref_grouping_key = ref_dmc.get_grouping_key(use_container_info_code=True)
                        points_to_container = ref_grouping_key in container_map

                        if points_to_container:
                            container_dmc = container_map[ref_grouping_key]
                            
                            new_sdc = container_dmc.system_diff_code
                            new_dcv = container_dmc.disassy_code_variant
                            new_ic = container_dmc.info_code
                            new_icv = container_dmc.info_code_variant

                            if (dm_code.get("systemDiffCode") != new_sdc or 
                                dm_code.get("disassyCodeVariant") != new_dcv or 
                                (config.use_config_info_code and dm_code.get("infoCode") != new_ic) or
                                (config.use_config_info_code and dm_code.get("infoCodeVariant") != new_icv) or
                                dm_code.get("learnCode") is not None or
                                dm_code.get("learnEventCode") is not None):
                                
                                dm_code.set("systemDiffCode", new_sdc)
                                dm_code.set("disassyCodeVariant", new_dcv)
                                if config.use_config_info_code:
                                    dm_code.set("infoCode", new_ic)
                                    dm_code.set("infoCodeVariant", new_icv)
                                if dm_code.get("learnCode") is not None:
                                    dm_code.attrib.pop("learnCode")
                                if dm_code.get("learnEventCode") is not None:
                                    dm_code.attrib.pop("learnEventCode")
                                is_file_changed = True

                        # Handle element removals using whitespace-preserving helper
                        if config.remove_issue_info_from_content_refs:
                            issue_info = dm_ref_ident.find("issueInfo")
                            if issue_info is not None:
                                remove_element_preserve_whitespace(dm_ref_ident, issue_info)
                                is_file_changed = True
                        elif points_to_container:
                            container_dmc = container_map[ref_grouping_key]
                            issue_info = dm_ref_ident.find("issueInfo")
                            if issue_info is not None:
                                if (issue_info.get("issueNumber") != container_dmc.issue or 
                                    issue_info.get("inWork") != container_dmc.inwork):
                                    issue_info.set("issueNumber", container_dmc.issue)
                                    issue_info.set("inWork", container_dmc.inwork)
                                    is_file_changed = True

                        if config.remove_language_from_content_refs:
                            language_elem = dm_ref_ident.find("language")
                            if language_elem is not None:
                                remove_element_preserve_whitespace(dm_ref_ident, language_elem)
                                is_file_changed = True

                        if config.remove_ident_extension_from_content_refs:
                            ident_ext = dm_ref_ident.find("identExtension")
                            if ident_ext is not None:
                                remove_element_preserve_whitespace(dm_ref_ident, ident_ext)
                                is_file_changed = True

                    except (TypeError, AttributeError) as e:
                        logging.debug(f"Skipping dmCode ref processing in {source_path.name} due to missing attributes: {e}")

        # 2. Process all pmRefs under content for issueInfo removal
        if config.remove_issue_info_from_content_refs:
            pm_ref_idents = content_elem.findall(".//pmRefIdent")
            for pm_ref_ident in pm_ref_idents:
                issue_info = pm_ref_ident.find("issueInfo")
                if issue_info is not None:
                    remove_element_preserve_whitespace(pm_ref_ident, issue_info)
                    is_file_changed = True

    if is_file_changed:
        logging.info(f"Processed {source_path.name}: references/attributes updated/cleaned.")
        write_xml_file(tree, header, output_dirs["changed"] / source_path.name, pretty_print=False)
    else:
        logging.info(f"Processed {source_path.name}: no changes needed.")
        shutil.copy(source_path, output_dirs["unchanged"] / source_path.name)

# --- Validation Functions ---

def run_validation(all_files: List[Path], group_key_to_container: Dict[Tuple, Dmc]) -> List[ValidationIssue]:
    """
    Runs all validation checks in parallel and returns a list of issues.
    Builds lookup caches for both exact filenames and core DMC attributes.
    """
    issues = []
    all_filenames = {f.name.lower() for f in all_files}
    
    # Cache available DMC core signatures for references where issueInfo is omitted
    available_dmcs: Set[Tuple] = set()
    for f in all_files:
        dmc = parse_dmc_from_filename(f.name)
        if dmc:
            # Lang-specific signature
            available_dmcs.add((
                dmc.model_ident_code, dmc.system_diff_code, dmc.system_code,
                dmc.sub_system_code, dmc.sub_sub_system_code, dmc.assy_code,
                dmc.disassy_code, dmc.disassy_code_variant, dmc.info_code,
                dmc.info_code_variant, dmc.item_location_code, dmc.learn_code,
                dmc.learn_event_code, dmc.language.upper()
            ))
            # Generic signature
            available_dmcs.add((
                dmc.model_ident_code, dmc.system_diff_code, dmc.system_code,
                dmc.sub_system_code, dmc.sub_sub_system_code, dmc.assy_code,
                dmc.disassy_code, dmc.disassy_code_variant, dmc.info_code,
                dmc.info_code_variant, dmc.item_location_code, dmc.learn_code,
                dmc.learn_event_code, "*"
            ))
    
    with ThreadPoolExecutor(max_workers=os.cpu_count(), thread_name_prefix="Validator") as executor:
        future_to_file = {executor.submit(validate_single_dm, f, all_filenames, available_dmcs, group_key_to_container): f for f in all_files}
        for future in as_completed(future_to_file):
            try:
                file_issues = future.result()
                if file_issues:
                    issues.extend(file_issues)
            except Exception as e:
                logging.error(f"Error during validation of {future_to_file[future].name}: {e}")
    
    return issues

def validate_single_dm(file_path: Path, all_filenames: Set[str], available_dmcs: Set[Tuple], group_key_to_container: Dict[Tuple, Dmc]) -> List[ValidationIssue]:
    """Performs all validation checks for a single data module."""
    issues = []
    _, tree = read_xml_file(file_path)
    if tree is None:
        return [ValidationIssue(
            source_file=file_path.name, line_number=0, severity="ERROR",
            problem_type="XML_PARSE_ERROR", details="Failed to read or parse XML file."
        )]

    file_dmc = parse_dmc_from_filename(file_path.name)
    is_container = (file_dmc is not None and file_dmc.disassy_code_variant.upper() == config.container_default_dcv)
    source_language = file_dmc.language if file_dmc else "en-US"
        
    dm_refs = tree.findall(".//dmRef")
    for dm_ref in dm_refs:
        dm_code = dm_ref.find(".//dmRefIdent/dmCode")
        if dm_code is None:
            continue

        try:
            # Check whether reference is in content vs identAndStatusSection
            is_in_content = False
            curr = dm_ref.getparent()
            while curr is not None:
                if curr.tag == 'content':
                    is_in_content = True
                    break
                curr = curr.getparent()

            issue_info_elem = dm_ref.find(".//issueInfo")
            has_issue_info = (issue_info_elem is not None and issue_info_elem.get("issueNumber") is not None)
            issue = issue_info_elem.get("issueNumber", "000") if has_issue_info else None
            inwork = issue_info_elem.get("inWork", "00") if has_issue_info else None

            lang_elem = dm_ref.find(".//language")
            if lang_elem is not None and lang_elem.get("languageIsoCode") and lang_elem.get("countryIsoCode"):
                language = f"{lang_elem.get('languageIsoCode')}-{lang_elem.get('countryIsoCode')}"
            else:
                language = source_language
            
            def _attr_upper(elem, attr):
                val = elem.get(attr)
                return val.upper() if isinstance(val, str) else val

            ref_dmc = Dmc(
                model_ident_code=_attr_upper(dm_code, "modelIdentCode"),
                system_diff_code=_attr_upper(dm_code, "systemDiffCode"),
                system_code=_attr_upper(dm_code, "systemCode"),
                sub_system_code=_attr_upper(dm_code, "subSystemCode"),
                sub_sub_system_code=_attr_upper(dm_code, "subSubSystemCode"),
                assy_code=_attr_upper(dm_code, "assyCode"),
                disassy_code=_attr_upper(dm_code, "disassyCode"),
                disassy_code_variant=_attr_upper(dm_code, "disassyCodeVariant"),
                info_code=_attr_upper(dm_code, "infoCode"),
                info_code_variant=_attr_upper(dm_code, "infoCodeVariant"),
                item_location_code=_attr_upper(dm_code, "itemLocationCode"), 
                issue=issue or "000", inwork=inwork or "00", language=language,
                learn_code=_attr_upper(dm_code, "learnCode"),
                learn_event_code=_attr_upper(dm_code, "learnEventCode")
            )
            
            # 1. Check for Broken Links
            link_exists = False
            if has_issue_info:
                target_filename = ref_dmc.to_filename()
                link_exists = (target_filename.lower() in all_filenames)
            else:
                dmc_sig = (
                    ref_dmc.model_ident_code, ref_dmc.system_diff_code, ref_dmc.system_code,
                    ref_dmc.sub_system_code, ref_dmc.sub_sub_system_code, ref_dmc.assy_code,
                    ref_dmc.disassy_code, ref_dmc.disassy_code_variant, ref_dmc.info_code,
                    ref_dmc.info_code_variant, ref_dmc.item_location_code, ref_dmc.learn_code,
                    ref_dmc.learn_event_code, language.upper()
                )
                link_exists = (dmc_sig in available_dmcs or (dmc_sig[:-1] + ("*",)) in available_dmcs)

            if not link_exists:
                ref_label = ref_dmc.to_filename() if has_issue_info else (
                    f"DMC-{ref_dmc.model_ident_code}-{ref_dmc.system_diff_code}-"
                    f"{ref_dmc.system_code}-{ref_dmc.sub_system_code}{ref_dmc.sub_sub_system_code}-"
                    f"{ref_dmc.assy_code}-{ref_dmc.disassy_code}{ref_dmc.disassy_code_variant}-"
                    f"{ref_dmc.info_code}{ref_dmc.info_code_variant}-{ref_dmc.item_location_code}"
                )
                issues.append(ValidationIssue(
                    source_file=file_path.name, line_number=dm_ref.sourceline or 0,
                    severity="ERROR", problem_type="BROKEN_LINK",
                    details=f"Reference to '{ref_label}' not found in file set."
                ))
                continue

            # 2. Check for Incorrect References (points to child instead of container)
            # Only checked for regular (non-container) Data Modules within the content section
            if file_dmc is not None and not is_container and is_in_content:
                ref_grouping_key = ref_dmc.get_grouping_key(use_container_info_code=True)
                if ref_grouping_key in group_key_to_container:
                    container_dmc = group_key_to_container[ref_grouping_key]
                    # Check if reference is ALREADY pointing to the container
                    is_already_container = (
                        ref_dmc.system_diff_code == container_dmc.system_diff_code and
                        ref_dmc.disassy_code_variant == container_dmc.disassy_code_variant and
                        ref_dmc.learn_code is None and
                        ref_dmc.learn_event_code is None and
                        (not config.use_config_info_code or (
                            ref_dmc.info_code == container_dmc.info_code and
                            ref_dmc.info_code_variant == container_dmc.info_code_variant
                        ))
                    )
                    if not is_already_container:
                        issues.append(ValidationIssue(
                            source_file=file_path.name, line_number=dm_ref.sourceline or 0,
                            severity="WARNING", problem_type="INCORRECT_REFERENCE",
                            details=f"Reference should point to container '{container_dmc.to_filename(True)}'."
                        ))

        except (TypeError, AttributeError) as e:
            logging.debug(f"Could not validate a dmRef in {file_path.name} due to missing attributes: {e}")
    
    if not issues:
        issues.append(ValidationIssue(
            source_file=file_path.name, line_number=0, severity="OK",
            problem_type="VALIDATION_PASSED", details="No issues found."
        ))

    return issues

def generate_html_report(issues: List[ValidationIssue], log_dir: Path, scanned_files_count: int):
    """Generates a self-contained, filterable HTML report from the list of issues."""
    report_path = log_dir / "validation_report.html"
    logging.info(f"Generating HTML validation report at: {report_path}")

    issues_json = json.dumps([asdict(issue) for issue in issues])

    html_template = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>S1000D Validation Report</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{ font-family: sans-serif; }}
        .severity-error {{ background-color: #fecaca; }}
        .severity-warning {{ background-color: #fef08a; }}
        .severity-ok {{ background-color: #dcfce7; }}
        th {{ position: sticky; top: 0; background-color: #f3f4f6; }}
    </style>
</head>
<body class="bg-gray-100 text-gray-800 p-4 md:p-8">

    <div class="max-w-7xl mx-auto bg-white p-6 rounded-lg shadow-lg">
        <h1 class="text-3xl font-bold mb-2 text-gray-700">S1000D Validation Report</h1>
        <p class="text-gray-500 mb-6">Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

        <!-- Summary -->
        <div id="summary" class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div class="bg-green-100 p-4 rounded-lg text-center">
                <p class="text-2xl font-bold" id="total-passed">0</p>
                <p class="text-green-800">Passed</p>
            </div>
            <div class="bg-red-200 p-4 rounded-lg text-center">
                <p class="text-2xl font-bold" id="total-errors">0</p>
                <p class="text-red-800">Errors</p>
            </div>
            <div class="bg-yellow-100 p-4 rounded-lg text-center">
                <p class="text-2xl font-bold" id="total-warnings">0</p>
                <p class="text-yellow-800">Warnings</p>
            </div>
             <div class="bg-blue-100 p-4 rounded-lg text-center">
                <p class="text-2xl font-bold" id="total-files">{scanned_files_count}</p>
                <p class="text-blue-800">Total Files Scanned</p>
            </div>
        </div>

        <!-- Filters -->
        <div class="flex flex-wrap gap-4 mb-4 items-center bg-gray-50 p-4 rounded-lg">
            <h3 class="text-lg font-semibold mr-4">Filters:</h3>
            <div>
                <label for="severity-filter" class="block text-sm font-medium text-gray-700">Severity</label>
                <select id="severity-filter" class="mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm rounded-md">
                    <option value="all">All</option>
                    <option value="OK">OK</option>
                    <option value="ERROR">Error</option>
                    <option value="WARNING">Warning</option>
                </select>
            </div>
            <div>
                <label for="type-filter" class="block text-sm font-medium text-gray-700">Problem Type</label>
                <select id="type-filter" class="mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm rounded-md">
                    <option value="all">All</option>
                </select>
            </div>
             <div class="flex-grow">
                <label for="search-filter" class="block text-sm font-medium text-gray-700">Search Details / File</label>
                <input type="text" id="search-filter" placeholder="Search..." class="mt-1 block w-full pl-3 pr-4 py-2 text-base border-gray-300 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm rounded-md">
            </div>
        </div>

        <!-- Results Table -->
        <div class="overflow-y-auto" style="max-height: 60vh;">
            <table class="min-w-full divide-y divide-gray-200">
                <thead class="bg-gray-50">
                    <tr>
                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Source File</th>
                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Line</th>
                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Severity</th>
                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Problem Type</th>
                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Details</th>
                    </tr>
                </thead>
                <tbody id="results-table" class="bg-white divide-y divide-gray-200">
                    <!-- Rows will be injected by JavaScript -->
                </tbody>
            </table>
        </div>
    </div>

    <script>
        const issues = {issues_json};
        
        const tableBody = document.getElementById('results-table');
        const severityFilter = document.getElementById('severity-filter');
        const typeFilter = document.getElementById('type-filter');
        const searchFilter = document.getElementById('search-filter');

        function escapeHtml(text) {{
            if (!text && text !== 0) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }}

        function populateTypeFilter() {{
            const types = [...new Set(issues.map(issue => issue.problem_type))];
            types.sort().forEach(type => {{
                const option = document.createElement('option');
                option.value = type;
                option.textContent = type.replace(/_/g, ' ').replace(/\\b\\w/g, l => l.toUpperCase());
                typeFilter.appendChild(option);
            }});
        }}

        function updateSummary(filteredIssues) {{
            document.getElementById('total-passed').textContent = issues.filter(i => i.severity === 'OK').length;
            document.getElementById('total-errors').textContent = issues.filter(i => i.severity === 'ERROR').length;
            document.getElementById('total-warnings').textContent = issues.filter(i => i.severity === 'WARNING').length;
        }}

        function renderTable(data) {{
            tableBody.innerHTML = '';
            if (data.length === 0) {{
                tableBody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-gray-500">No issues found matching the criteria.</td></tr>';
                return;
            }}
            data.forEach(issue => {{
                const row = document.createElement('tr');
                row.className = `severity-${{issue.severity.toLowerCase()}}`;
                row.innerHTML = `
                    <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">${{escapeHtml(issue.source_file)}}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${{issue.line_number || '-'}}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm font-bold text-gray-700">${{escapeHtml(issue.severity)}}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${{escapeHtml(issue.problem_type)}}</td>
                    <td class="px-6 py-4 text-sm text-gray-600">${{escapeHtml(issue.details)}}</td>
                `;
                tableBody.appendChild(row);
            }});
        }}

        function applyFilters() {{
            const severity = severityFilter.value;
            const type = typeFilter.value;
            const search = searchFilter.value.toLowerCase();

            const filtered = issues.filter(issue => {{
                const severityMatch = severity === 'all' || issue.severity === severity;
                const typeMatch = type === 'all' || issue.problem_type === type;
                const searchMatch = search === '' || 
                                    issue.details.toLowerCase().includes(search) ||
                                    issue.source_file.toLowerCase().includes(search);
                return severityMatch && typeMatch && searchMatch;
            }});

            renderTable(filtered);
            updateSummary(issues);
        }}

        severityFilter.addEventListener('change', applyFilters);
        typeFilter.addEventListener('change', applyFilters);
        searchFilter.addEventListener('input', applyFilters);

        populateTypeFilter();
        applyFilters();
    </script>

</body>
</html>
    """
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html_template)
    logging.info("HTML report generation complete.")


def main():
    """Main function to drive the script execution."""
    parser = argparse.ArgumentParser(description="S1000D Container Generation and Reference Update Script.")
    parser.add_argument("input_dir", type=Path, help="Path to the input directory containing source data modules.")
    parser.add_argument("output_dir", type=Path, help="Path to the output directory where new and modified files will be saved.")
    parser.add_argument("-c", "--config", type=Path, default=Path("./container_config.json"), help="Path to the JSON configuration file.")
    parser.add_argument("--logs_dir", type=Path, default=Path("./logs"), help="Path to the directory for log files.")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging.")
    parser.add_argument("--validate-input", action="store_true", help="Run in validation-only mode on the input data. No files will be created or modified.")
    parser.add_argument("--create-single-dm-containers", action="store_true", help="Create a container even for single, non-grouped data modules. Overrides the config variable.")
    
    args = parser.parse_args()

    # 1. Setup logging first so all subsequent operations (including config loading) are logged properly
    setup_logging(args.logs_dir, args.debug)

    # 2. Load configuration from file
    global config
    config = ScriptConfig.load_from_file(args.config)

    should_create_for_single = config.create_container_for_single_dms or args.create_single_dm_containers
    
    if not args.input_dir.is_dir():
        logging.error(f"Input directory not found: {args.input_dir}")
        sys.exit(1)
        
    try:
        resolved_input = args.input_dir.resolve()
        resolved_output = args.output_dir.resolve()
        if resolved_input == resolved_output:
            logging.error(f"Output directory cannot be identical to input directory: {args.output_dir}")
            sys.exit(1)
        if resolved_input in resolved_output.parents:
            logging.error(f"Output directory cannot be inside input directory: {args.output_dir}")
            sys.exit(1)
    except Exception as e:
        logging.debug(f"Path resolution check warning: {e}")

    output_dirs = {
        "unchanged": args.output_dir / "01_unchanged",
        "changed": args.output_dir / "02_changed_reference",
        "new_container": args.output_dir / "04_new_container"
    }
    
    logging.info(f"Input directory: {args.input_dir}")
    
    dm_groups = find_and_group_modules(args.input_dir, should_create_for_single)
    group_key_to_container_dmc = {}

    for key, files in dm_groups.items():
        sorted_group_files = sorted(files, key=lambda p: p.name)
        base_dmc = parse_dmc_from_filename(sorted_group_files[0].name)
        if base_dmc:
            container_ic = config.container_info_code if config.use_config_info_code else base_dmc.info_code
            container_icv = "A" if config.use_config_info_code else base_dmc.info_code_variant
            group_key_to_container_dmc[key] = Dmc(
                model_ident_code=base_dmc.model_ident_code, system_diff_code=config.container_default_sdc,
                system_code=base_dmc.system_code, sub_system_code=base_dmc.sub_system_code,
                sub_sub_system_code=base_dmc.sub_sub_system_code, assy_code=base_dmc.assy_code,
                disassy_code=base_dmc.disassy_code, disassy_code_variant=config.container_default_dcv,
                info_code=container_ic, info_code_variant=container_icv,
                item_location_code=base_dmc.item_location_code, language=base_dmc.language,
                issue=config.container_issue_number, inwork=config.container_inwork_number
            )
            
    # --- Validation-Only Mode for Input ---
    if args.validate_input:
        logging.info("Input-only validation mode enabled. Running checks...")
        all_source_files = list(args.input_dir.rglob("*.xml"))
        issues = run_validation(all_source_files, group_key_to_container_dmc)
        generate_html_report(issues, args.logs_dir, len(all_source_files))
        logging.info("Input validation complete. Report generated. Exiting.")
        sys.exit(0)

    # --- Generation and Update Mode ---
    logging.info(f"Output directory: {args.output_dir}")
    for d in output_dirs.values():
        d.mkdir(parents=True, exist_ok=True)
        for stale_file in d.glob("*.xml"):
            try:
                stale_file.unlink()
            except Exception as e:
                logging.warning(f"Failed to remove stale output file {stale_file}: {e}")
    
    if not dm_groups:
        logging.info("No groups found for containerization. Proceeding to reference update scan.")
    
    try:
        with ThreadPoolExecutor(max_workers=os.cpu_count(), thread_name_prefix="Container-Gen") as executor:
            futures = {executor.submit(create_container_dm, files, group_key_to_container_dmc[key], output_dirs["new_container"]) for key, files in dm_groups.items()}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logging.error(f"An error occurred during container generation: {e}")
    except KeyboardInterrupt:
        logging.warning("Container generation interrupted by user. Shutting down...")
        executor.shutdown(wait=False, cancel_futures=True)
        sys.exit(1)

    logging.info("Starting reference update process...")
    all_source_files = list(args.input_dir.rglob("*.xml"))
    
    non_container_source_files = []
    for f in all_source_files:
        dmc = parse_dmc_from_filename(f.name)
        if dmc is None or dmc.disassy_code_variant.upper() != config.container_default_dcv:
            non_container_source_files.append(f)
        else:
            # Check if this existing container is being regenerated in 04_new_container
            cont_key = dmc.get_grouping_key(use_container_info_code=True)
            if cont_key in group_key_to_container_dmc:
                logging.debug(f"Skipping {f.name} from unchanged folder: it is regenerated in new_container.")
            else:
                logging.debug(f"Preserving existing un-grouped container {f.name} in unchanged folder.")
                try:
                    shutil.copy(f, output_dirs["unchanged"] / f.name)
                except Exception as e:
                    logging.error(f"Failed to copy existing container {f.name} to unchanged directory: {e}")

    try:
        with ThreadPoolExecutor(max_workers=os.cpu_count(), thread_name_prefix="Ref-Update") as executor:
            futures = {executor.submit(update_dm_references, f, group_key_to_container_dmc, output_dirs) for f in non_container_source_files}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logging.error(f"An error occurred during reference update: {e}")
    except KeyboardInterrupt:
        logging.warning("Reference updates interrupted by user. Shutting down...")
        executor.shutdown(wait=False, cancel_futures=True)
        sys.exit(1)

    # --- Final Validation of Output ---
    logging.info("Starting final validation of the output directory...")
    all_output_files = list(args.output_dir.rglob("*.xml"))
    output_issues = run_validation(all_output_files, group_key_to_container_dmc)
    generate_html_report(output_issues, args.logs_dir, len(all_output_files))
    logging.info("Script execution and final validation complete.")


if __name__ == "__main__":
    main()
