#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Manage platform data archives stored in the global GitHub Release.

Usage:
    python manage_data.py download --platform t2
    python manage_data.py download --all
    python manage_data.py upload --platform t2
    python manage_data.py upload --all
    python manage_data.py init --all
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import tarfile

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "package-config.json")
DATA_DIR = os.path.join(SCRIPT_DIR, "data")


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def get_global_release_info(config):
    pkg = config["package"]
    return pkg["githubOwner"], pkg["githubRepo"], pkg["globalReleaseTag"]


def get_platform_keys(config, platform_arg):
    if platform_arg == "all":
        return list(config["platforms"].keys())
    if platform_arg in config["platforms"]:
        return [platform_arg]
    logging.error(f"Unknown platform: {platform_arg}")
    sys.exit(1)


def download_platform(config, platform_key):
    owner, repo, tag = get_global_release_info(config)
    plat = config["platforms"][platform_key]
    asset_name = plat.get("dataAsset", f"ci-data-{platform_key}.tar.gz")
    data_path = os.path.join(DATA_DIR, platform_key)

    logging.info(f"Downloading {asset_name} from {owner}/{repo} release {tag}...")

    result = subprocess.run(
        [
            "gh", "release", "download", tag,
            "--repo", f"{owner}/{repo}",
            "--pattern", asset_name,
            "--output", asset_name,
            "--clobber",
        ],
        capture_output=True,
        text=True,
        cwd=SCRIPT_DIR,
    )
    if result.returncode != 0:
        logging.error(f"Download failed: {result.stderr.strip()}")
        return False

    archive_path = os.path.join(SCRIPT_DIR, asset_name)
    os.makedirs(data_path, exist_ok=True)

    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(path=data_path)

    os.remove(archive_path)
    logging.info(f"Extracted {asset_name} to {data_path}")
    return True


def upload_platform(config, platform_key):
    owner, repo, tag = get_global_release_info(config)
    plat = config["platforms"][platform_key]
    asset_name = plat.get("dataAsset", f"ci-data-{platform_key}.tar.gz")
    data_path = os.path.join(DATA_DIR, platform_key)

    if not os.path.exists(data_path):
        logging.error(f"Data path not found: {data_path}")
        return False

    archive_path = os.path.join(SCRIPT_DIR, asset_name)
    logging.info(f"Packing {data_path} -> {asset_name}...")

    with tarfile.open(archive_path, "w:gz") as tar:
        for entry in sorted(os.listdir(data_path)):
            tar.add(os.path.join(data_path, entry), arcname=entry)

    size_mb = os.path.getsize(archive_path) / (1024 * 1024)
    logging.info(f"Archive size: {size_mb:.2f} MB")

    logging.info(f"Uploading {asset_name} to {owner}/{repo} release {tag}...")
    result = subprocess.run(
        [
            "gh", "release", "upload", tag,
            archive_path,
            "--repo", f"{owner}/{repo}",
            "--clobber",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logging.error(f"Upload failed: {result.stderr.strip()}")
        os.remove(archive_path)
        return False

    os.remove(archive_path)
    logging.info(f"Uploaded {asset_name}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Manage CI data archives")
    parser.add_argument(
        "action",
        choices=["download", "upload", "init"],
        help="download: fetch from release; upload: pack and push; init: upload all platforms",
    )
    parser.add_argument("--platform", default=None, help="Platform key (e.g. t2) or 'all'")
    parser.add_argument("--all", action="store_true", help="Apply to all platforms")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="[%(levelname)-8s] %(message)s",
    )

    config = load_config()

    if args.action == "init":
        platforms = list(config["platforms"].keys())
    elif args.all or args.platform == "all":
        platforms = list(config["platforms"].keys())
    elif args.platform:
        platforms = get_platform_keys(config, args.platform)
    else:
        logging.error("Specify --platform <name> or --all")
        sys.exit(1)

    failed = False
    for plat in platforms:
        if args.action in ("download",):
            if not download_platform(config, plat):
                failed = True
        elif args.action in ("upload", "init"):
            if not upload_platform(config, plat):
                failed = True

    if failed:
        logging.error("Some operations failed")
        sys.exit(1)

    logging.info("Done")


if __name__ == "__main__":
    main()
