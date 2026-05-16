#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate a package_tuya_open_index.json file.

Checks:
    1. JSON is parseable.
    2. At least one platform entry exists.
    3. The specified version is in platforms[0].
    4. Every toolsDependencies entry has a matching tool in the tools array.
    5. If a manifest is provided, checksum/size values for new artifacts match.
    6. All URLs are well-formed GitHub release download URLs.

Usage:
    python validate_index.py --index package_tuya_open_index.json --version 1.2.5
    python validate_index.py --index package_tuya_open_index.json --version 1.2.5 --manifest manifest.json
"""

import argparse
import json
import logging
import re
import sys


def validate_index(index_path, version, manifest_path=None):
    errors = []
    warnings = []

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        errors.append(f"JSON parse error: {e}")
        return errors, warnings

    if "packages" not in data or not data["packages"]:
        errors.append("Missing 'packages' array")
        return errors, warnings

    package = data["packages"][0]
    platforms = package.get("platforms", [])
    tools = package.get("tools", [])

    if not platforms:
        errors.append("No platform entries found")
        return errors, warnings

    if platforms[0]["version"] != version:
        errors.append(
            f"Expected version {version} at platforms[0], found {platforms[0]['version']}"
        )

    target_platform = None
    for p in platforms:
        if p["version"] == version:
            target_platform = p
            break

    if target_platform is None:
        errors.append(f"Version {version} not found in platforms list")
        return errors, warnings

    url = target_platform.get("url", "")
    if not url.startswith("https://github.com/"):
        errors.append(f"Platform URL does not start with https://github.com/: {url}")

    if not target_platform.get("size"):
        warnings.append("Platform size is empty")
    if not target_platform.get("checksum"):
        warnings.append("Platform checksum is empty")

    tool_index = {}
    for tool in tools:
        key = (tool["name"].lower(), tool["version"])
        tool_index[key] = tool

    for dep in target_platform.get("toolsDependencies", []):
        dep_key = (dep["name"].lower(), dep["version"])
        if dep_key not in tool_index:
            errors.append(
                f"toolsDependency '{dep['name']}' version '{dep['version']}' "
                f"not found in tools array"
            )

    for tool in tools:
        for system in tool.get("systems", []):
            tool_url = system.get("url", "")
            if tool_url and not tool_url.startswith("https://github.com/"):
                warnings.append(f"Tool {tool['name']} {tool['version']} URL not on GitHub: {tool_url}")

    if manifest_path:
        try:
            with open(manifest_path, "r") as f:
                manifest = json.load(f)

            manifest_artifacts = {a["name"]: a for a in manifest.get("artifacts", [])}

            arduino_name = target_platform.get("archiveFileName", "")
            if arduino_name in manifest_artifacts:
                art = manifest_artifacts[arduino_name]
                if target_platform.get("size") != art["size"]:
                    errors.append(
                        f"Arduino size mismatch: index={target_platform.get('size')}, "
                        f"manifest={art['size']}"
                    )
                if target_platform.get("checksum") != art["checksum"]:
                    errors.append(
                        f"Arduino checksum mismatch: index={target_platform.get('checksum')}, "
                        f"manifest={art['checksum']}"
                    )

            for tool in tools:
                for system in tool.get("systems", []):
                    archive_name = system.get("archiveFileName", "")
                    if archive_name in manifest_artifacts:
                        art = manifest_artifacts[archive_name]
                        if system.get("size") != art["size"]:
                            errors.append(
                                f"Tool {tool['name']} size mismatch: "
                                f"index={system.get('size')}, manifest={art['size']}"
                            )
                        if system.get("checksum") != art["checksum"]:
                            errors.append(
                                f"Tool {tool['name']} checksum mismatch: "
                                f"index={system.get('checksum')}, manifest={art['checksum']}"
                            )
                        break

        except Exception as e:
            warnings.append(f"Could not validate against manifest: {e}")

    for tool in tools:
        for system in tool.get("systems", []):
            if system.get("size") == "0" or system.get("checksum") == "SHA-256:0":
                errors.append(
                    f"Tool {tool['name']} {tool['version']} has placeholder "
                    f"size/checksum (size={system.get('size')}, checksum={system.get('checksum')})"
                )

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description="Validate package index JSON")
    parser.add_argument("--index", required=True, help="Path to index JSON")
    parser.add_argument("--version", required=True, help="Expected version at platforms[0]")
    parser.add_argument("--manifest", default=None, help="Path to manifest JSON for cross-check")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(levelname)-8s] %(message)s")

    errors, warnings = validate_index(args.index, args.version, args.manifest)

    for w in warnings:
        logging.warning(w)
    for e in errors:
        logging.error(e)

    if errors:
        logging.error(f"Validation FAILED with {len(errors)} error(s)")
        sys.exit(1)
    else:
        logging.info(f"Validation PASSED ({len(warnings)} warning(s))")


if __name__ == "__main__":
    main()
