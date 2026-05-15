# -*- coding: utf-8 -*-

import os
import shutil
import logging

from .package_handler import PackageHandler

TUYA_ARDUINO_VERSION_H_PREFIX = """#ifndef __TUYA_ARDUINO_VERSION_H__
#define __TUYA_ARDUINO_VERSION_H__

#ifdef __cplusplus
extern "C" {
#endif
"""

TUYA_ARDUINO_VERSION_H_SUFFIX = """
// Version number (in numeric form)
#define VERSION_ARDUINO_TUYA ((VERSION_ARDUINO_TUYA_MAJOR << 16) | (VERSION_ARDUINO_TUYA_MINOR << 8) | VERSION_ARDUINO_TUYA_PATCH)

// Version string (in string form)
#define df2str(x) #x
#define d2str(x) df2str(x)
#define VERSION_ARDUINO_TUYA_STR d2str(VERSION_ARDUINO_TUYA_MAJOR) "." d2str(VERSION_ARDUINO_TUYA_MINOR) "." d2str(VERSION_ARDUINO_TUYA_PATCH)

#ifdef __cplusplus
}
#endif

#endif // __TUYA_ARDUINO_VERSION_H__
"""


def _version_update(arduino_path, version):
    major, minor, patch = version.split(".")

    version_h_path = os.path.join(arduino_path, "cores", "tuya_open", "tuya_arduino_version.h")
    version_h_str = (
        TUYA_ARDUINO_VERSION_H_PREFIX
        + f"// Major version number (X.x.x)\n"
        + f"#define VERSION_ARDUINO_TUYA_MAJOR {major}\n"
        + f"// Minor version number (x.X.x)\n"
        + f"#define VERSION_ARDUINO_TUYA_MINOR {minor}\n"
        + f"// Patch version number (x.x.X)\n"
        + f"#define VERSION_ARDUINO_TUYA_PATCH {patch}\n"
        + TUYA_ARDUINO_VERSION_H_SUFFIX
    )

    with open(version_h_path, "w") as f:
        f.write(version_h_str)
    logging.info(f"Updated tuya_arduino_version.h to {version}")

    platform_txt_path = os.path.join(arduino_path, "platform.txt")
    with open(platform_txt_path, "r") as f:
        lines = f.readlines()
    with open(platform_txt_path, "w") as f:
        for line in lines:
            if line.startswith("version="):
                f.write(f"version={version}\n")
            else:
                f.write(line)
    logging.info(f"Updated platform.txt version to {version}")


def _ignore_patterns(checkout_path):
    base_ignore = shutil.ignore_patterns(".git", "output")
    ci_data_path = os.path.normpath(os.path.join(checkout_path, "tools", "ci", "data"))

    def _ignore(directory, contents):
        ignored = base_ignore(directory, contents)
        if os.path.normpath(directory) == ci_data_path:
            ignored = set(contents)
        return ignored

    return _ignore


def package_arduino(checkout_path, version, output_path):
    """Package the Arduino core from a checked-out repository.

    Args:
        checkout_path: Path to the checked-out arduino-TuyaOpen repository.
        version: Version string (e.g. "1.2.5").
        output_path: Directory to write the output zip.

    Returns:
        Tuple of (output_file_path, size, sha256) on success, or None on failure.
    """
    import tempfile

    handler = PackageHandler()

    work_dir = tempfile.mkdtemp(prefix="arduino-pack-")
    try:
        compress_path = os.path.join(work_dir, "arduino_tuya_open")
        tmp_output_path = os.path.join(compress_path, "tuya_open")

        shutil.copytree(checkout_path, tmp_output_path,
                        ignore=_ignore_patterns(checkout_path))

        _version_update(tmp_output_path, version)

        remove_list = [
            ".github/",
            ".gitignore",
            ".gitmodules",
            ".codespellrc",
            "script/",
            "package.json",
            "package_cn.json",
            "CMakeLists.txt",
            "ArduinoCore-API/.github/",
            "ArduinoCore-API/test/",
            "ArduinoCore-API/.codespellrc",
            "ArduinoCore-API/.gitignore",
            "ArduinoCore-API/README.md",
        ]
        handler.remove_unused_files(tmp_output_path, remove_list)

        os.makedirs(output_path, exist_ok=True)
        package_name = f"arduino_tuya_open-{version}.zip"
        output_file = os.path.join(output_path, package_name)
        handler.compress_package(compress_path, output_file, "zip")

        size = os.path.getsize(output_file)
        sha256 = handler.calculate_sha256(output_file)

        logging.info(f"Arduino core packaged: {output_file} (size={size}, sha256={sha256})")
        return output_file, size, sha256
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
