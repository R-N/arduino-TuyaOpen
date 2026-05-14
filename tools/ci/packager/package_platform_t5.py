# -*- coding: utf-8 -*-

import logging
import os
import re
import subprocess
import shutil
import json
import hashlib

from .package_platform import PackagePlatform


class PackagePlatformT5(PackagePlatform):
    def copy_from_string(self, input_str, output_lib_path, base_path=None):
        input_str = input_str.strip()
        tmp_list = [x for x in input_str.split(" ") if x]
        lib_list = list(set(lib for lib in tmp_list if lib.endswith(".a")))

        remove_lib_list = ["libtuyaapp.a"]
        rename_lib_dict = {"/bk7258/libs/libbk_phy.a": "libbk7258_bk_phy.a"}

        output_lib_dict = {}
        for lib in lib_list:
            if os.path.basename(lib) in remove_lib_list:
                continue
            if not os.path.isabs(lib):
                if base_path:
                    lib = os.path.join(base_path, lib)
                elif lib.startswith("armino/"):
                    lib = os.path.join(self.vendor_path, "t5_os", "build", "bk7258", lib)
                lib = os.path.normpath(lib)
            output_lib_dict[lib] = os.path.basename(lib)
            for rename_key, new_name in rename_lib_dict.items():
                if rename_key in lib:
                    output_lib_dict[lib] = new_name
                    break

        for lib, out_name in output_lib_dict.items():
            output_lib_file = os.path.join(output_lib_path, out_name)
            shutil.copy2(lib, output_lib_file)
            logging.debug(f"Copy {lib} to {output_lib_file} success")
        return True

    def get_libs_flags(self, input_str, output_file):
        link_txt_lists = [x for x in input_str.split(" ") if x]

        remove_lib_list = ["libtuyaapp.a"]
        for remove_lib in remove_lib_list:
            link_txt_lists = [x for x in link_txt_lists if remove_lib not in x]

        lib_list = [x for x in link_txt_lists if x.startswith("-l") or x.endswith(".a")]

        rename_lib_dict = {"/bk7258/libs/libbk_phy.a": "libbk7258_bk_phy.a"}
        write_lib_list = []
        for lib in lib_list:
            tmp_name = os.path.basename(lib)
            for rename_key, new_name in rename_lib_dict.items():
                if rename_key in lib:
                    tmp_name = new_name
                    break
            if tmp_name.endswith(".a"):
                write_lib_list.append(f"-l{tmp_name[3:-2]}")
            else:
                write_lib_list.append(tmp_name)

        for i in range(min(9, len(write_lib_list) - 1), -1, -1):
            if write_lib_list[i] in ["-lm", "-lgcc", "-lc", "-lnosys"]:
                write_lib_list.pop(i)

        with open(output_file, "w") as f:
            for lib in write_lib_list:
                lib_stripped = lib.strip()
                if lib_stripped:
                    f.write(f"{lib_stripped}\n")
        return True

    def get_include_flags(self, compile_commands_file, output_path):
        with open(compile_commands_file, "r") as f:
            compile_json = json.load(f)
            compile_commands = compile_json[0]["command"]

        compile_list = [x for x in compile_commands.split(" ") if x]
        include_list = list(set(
            item[2:].replace(self.clone_path + "/", "")
            for item in compile_list if item.startswith("-I")
        ))

        tuya_open_include_list = [x for x in include_list if x.startswith("src/")]
        with open(os.path.join(output_path, "include_tuya_open.txt"), "w") as f:
            f.write("\n".join(tuya_open_include_list) + "\n")

        tuyaos_adapter_include_list = [
            x for x in include_list if x.startswith("platform/T5AI/tuyaos/tuyaos_adapter/")
        ]
        with open(os.path.join(output_path, "include_tkl.txt"), "w") as f:
            f.write("platform/T5AI/tuyaos/tuyaos_adapter/include\n")
            f.write("platform/T5AI/tuyaos/tuyaos_adapter/include/security\n")
            for item in tuyaos_adapter_include_list:
                f.write(f"{item}\n")

        vendor_include_list = [x for x in include_list if x.startswith("platform/T5AI/")]
        with open(os.path.join(output_path, "include_vendor.txt"), "w") as f:
            f.write("\n".join(vendor_include_list) + "\n")
        return True

    def copy_ai_components_libs(self, output_lib_path):
        build_app_rel = self.package_info.build_app
        ai_components_rel = os.path.join(os.path.dirname(build_app_rel), "ai_components")
        ai_components_build_path = os.path.join(
            self.build_app_path,
            ".build", "CMakeFiles", "tuyaapp.dir", ai_components_rel,
        )
        if not os.path.exists(ai_components_build_path):
            logging.warning(f"ai_components build path not exists: {ai_components_build_path}")
            return True

        libtuyaos_path = os.path.join(output_lib_path, "libtuyaos.a")
        if not os.path.exists(libtuyaos_path):
            logging.error(f"libtuyaos.a not found at {libtuyaos_path}")
            return False

        ai_obj_files = []
        for root, _, files in os.walk(ai_components_build_path):
            for f in files:
                if f.endswith(".o"):
                    ai_obj_files.append(os.path.join(root, f))

        if not ai_obj_files:
            logging.warning(f"No .o files found in {ai_components_build_path}")
            return True

        logging.info(f"Found {len(ai_obj_files)} .o files in ai_components")

        for obj_file in ai_obj_files:
            result = subprocess.run(["ar", "rcs", libtuyaos_path, obj_file], capture_output=True, text=True)
            if result.returncode != 0:
                logging.error(f"Failed to add {obj_file} to libtuyaos.a: {result.stderr}")

        logging.info(f"Merged {len(ai_obj_files)} .o files from ai_components into libtuyaos.a")
        return True

    def copy_ai_components_headers(self, output_tmp_path):
        ai_components_src = os.path.join(os.path.dirname(self.build_app_path), "ai_components")
        if not os.path.exists(ai_components_src):
            logging.warning(f"ai_components source path not exists: {ai_components_src}")
            return []

        exclude_headers = ["lang_config.h"]
        include_paths = []

        clone_src_path = os.path.join(self.clone_path, "src")
        if not os.path.exists(clone_src_path):
            logging.warning(f"src path not exists: {clone_src_path}")
            return []

        clone_ai_dir = os.path.join(clone_src_path, "ai_components")
        if os.path.exists(clone_ai_dir):
            shutil.rmtree(clone_ai_dir)

        for root, _, files in os.walk(ai_components_src):
            header_files = [f for f in files if f.endswith(".h") and f not in exclude_headers]
            if header_files:
                rel_path = os.path.relpath(root, ai_components_src)
                clone_dst_dir = os.path.join(clone_src_path, "ai_components", rel_path)
                os.makedirs(clone_dst_dir, exist_ok=True)

                for f in header_files:
                    shutil.copy2(os.path.join(root, f), os.path.join(clone_dst_dir, f))

                include_rel_path = os.path.join("src", "ai_components", rel_path).replace("\\", "/")
                if rel_path == ".":
                    include_rel_path = "src/ai_components"
                if include_rel_path not in include_paths:
                    include_paths.append(include_rel_path)

        logging.info(f"Found {len(include_paths)} ai_components include paths")
        return include_paths

    def update_include_tuya_open_with_ai_components(self, include_paths):
        include_file = os.path.join(self.staging_path, "includes", "include_tuya_open.txt")
        if not os.path.exists(include_file):
            logging.error(f"include_tuya_open.txt not exists: {include_file}")
            return False

        with open(include_file, "r") as f:
            existing_lines = f.read().splitlines()

        existing_set = set(line.strip() for line in existing_lines if line.strip())
        new_paths = [p for p in include_paths if p not in existing_set]

        if new_paths:
            existing_lines.extend(new_paths)
            with open(include_file, "w") as f:
                for line in existing_lines:
                    if line.strip():
                        f.write(f"{line}\n")
            logging.info(f"Updated include_tuya_open.txt with {len(new_paths)} new ai_components paths")
        return True

    def copy_tuya_kconfig(self, output_path):
        pass

    def copy_assets(self, output_tmp_path, chip, partitions_file):
        build_ninja_path = os.path.join(
            self.vendor_path, "t5_os", "build", "bk7258", "tuya_app", "bk7258_ap", "build.ninja"
        )
        build_base_path = os.path.join(
            self.vendor_path, "t5_os", "build", "bk7258", "tuya_app", "bk7258_ap"
        )
        if not os.path.exists(build_ninja_path):
            logging.error(f"Can't find {build_ninja_path}")
            return False

        link_info = ""
        with open(build_ninja_path, "r") as f:
            for line in f:
                if "LINK_LIBRARIES" in line:
                    link_info = line.strip()
                    break
        if not link_info:
            logging.error("Can't find LINK_LIBRARIES")
            return False

        output_lib_path = os.path.join(output_tmp_path, "libs")
        if os.path.exists(output_lib_path):
            shutil.rmtree(output_lib_path)
        os.makedirs(output_lib_path)

        self.copy_from_string(link_info, output_lib_path, build_base_path)

        self.staging_path = os.path.join(output_tmp_path, "_staging")
        os.makedirs(self.staging_path, exist_ok=True)
        shutil.copytree(
            os.path.join(self.data_path, "flags"),
            os.path.join(self.staging_path, "flags"),
        )

        libs_flags_file = os.path.join(self.staging_path, "flags", "libs_flags.txt")
        self.get_libs_flags(link_info, libs_flags_file)

        compile_commands_file = os.path.join(
            self.vendor_path, "t5_os", "build", "bk7258", "tuya_app", "bk7258_ap", "compile_commands.json"
        )
        if not os.path.exists(compile_commands_file):
            logging.error(f"Can't find {compile_commands_file}")
            return False

        staging_includes = os.path.join(self.staging_path, "includes")
        os.makedirs(staging_includes, exist_ok=True)
        self.get_include_flags(compile_commands_file, staging_includes)

        self.copy_after_delete(
            os.path.join(self.data_path, "packager-tools"),
            os.path.join(output_tmp_path, "packager-tools"),
        )

        package_tmp_path = os.path.join(
            self.vendor_path, "t5_os", "build", "bk7258", "tuya_app", "package", "tmp"
        )
        packager_tools_out = os.path.join(output_tmp_path, "packager-tools")

        # Bootloader
        bootloader_src = os.path.join(package_tmp_path, "bootloader.bin")
        if os.path.exists(bootloader_src):
            shutil.copy2(bootloader_src, os.path.join(packager_tools_out, "T5_bootloader.bin"))
            logging.info(f"Copied T5_bootloader.bin ({os.path.getsize(bootloader_src)} bytes)")
        else:
            logging.error(f"T5 bootloader not found: {bootloader_src}")
            return False

        # TuyaBoot
        tuyaboot_src = os.path.join(package_tmp_path, "tuyaboot.bin")
        if os.path.exists(tuyaboot_src):
            shutil.copy2(tuyaboot_src, os.path.join(packager_tools_out, "T5_tuyaboot.bin"))
            logging.info(f"Copied T5_tuyaboot.bin ({os.path.getsize(tuyaboot_src)} bytes)")
        else:
            logging.error(f"T5 tuyaboot not found: {tuyaboot_src}")
            return False

        # CP firmware
        cp_app_src = os.path.join(package_tmp_path, "app.bin")
        if os.path.exists(cp_app_src):
            with open(cp_app_src, "rb") as f:
                cp_md5 = hashlib.md5(f.read()).hexdigest()
            cp_size = os.path.getsize(cp_app_src)
            logging.info(f"CP core app.bin: size={cp_size}, md5={cp_md5}")
            shutil.copy2(cp_app_src, os.path.join(packager_tools_out, "t5_cp_app.bin"))
        else:
            logging.error(f"CP core app.bin not found: {cp_app_src}")
            return False

        return True

    def build_platform_t5(self):
        tos = os.path.join(self.clone_path, "tos.py")
        if not os.path.exists(tos):
            logging.error(f"tos.py not found: {tos}")
            return False

        requirements = os.path.join(self.clone_path, "requirements.txt")
        if os.path.exists(requirements):
            subprocess.run(
                ["pip", "install", "-r", requirements],
                capture_output=True,
                text=True,
            )

        work_dir = self.build_app_path
        if not os.path.exists(work_dir):
            logging.error(f"Work directory not exists: {work_dir}")
            return False

        try:
            subprocess.run(
                ["python", tos, "clean", "-f"],
                cwd=work_dir, capture_output=True, text=True, timeout=60,
            )
            logging.info("Build cache cleaned")
        except Exception as e:
            logging.warning(f"Clean failed: {e}, continuing")

        build_lines = []
        try:
            process = subprocess.Popen(
                ["python", tos, "build"],
                cwd=work_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in process.stdout:
                build_lines.append(line.rstrip())
                logging.debug(f"[BUILD] {line.rstrip()}")
            process.wait()
            if process.returncode != 0:
                logging.error(f"Build failed with return code: {process.returncode}")
                logging.error("--- Last 50 lines of build output ---")
                for line in build_lines[-50:]:
                    logging.error(f"[BUILD] {line}")
                return False
        except Exception as e:
            logging.error(f"Build error: {e}")
            return False

        return True

    def apply_platform_patch(self):
        patch_file = os.path.join(self.data_path, "t5_platform.patch")
        if not os.path.exists(patch_file):
            logging.info("No platform patch file found, skipping")
            return True

        logging.info(f"Applying platform patch from: {patch_file}")
        try:
            subprocess.run(
                ["git", "-C", self.clone_path, "reset", "--hard", "HEAD"],
                capture_output=True, text=True, timeout=30,
            )
            subprocess.run(
                ["git", "-C", self.clone_path, "clean", "-fd"],
                capture_output=True, text=True, timeout=30,
            )

            result = subprocess.run(
                ["git", "-C", self.clone_path, "apply", "--whitespace=nowarn", patch_file],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                logging.info("Platform patch applied successfully")
                return True

            logging.error(f"Failed to apply patch: {result.stderr}")
            result = subprocess.run(
                ["git", "-C", self.clone_path, "apply", "--reject", "--whitespace=nowarn", patch_file],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                logging.warning("Patch applied with rejections")
                return True

            logging.error(f"Failed to apply patch: {result.stderr}")
            return False
        except Exception as e:
            logging.error(f"Patch error: {e}")
            return False

    def package(self):
        self.vendor_path = os.path.join(self.clone_path, "platform", "T5AI")

        if not self.git_clone():
            return False
        if not self.apply_platform_patch():
            return False
        ini_file = os.path.join(self.config_path, "app_default.config")
        if not self.set_platform_ini(ini_file):
            return False

        if not self.build_platform_t5():
            return False

        self.update_ci_data()

        output_tmp_path = os.path.join(self.package_info.output_path, "tmp", self.package_info.name)
        if os.path.exists(output_tmp_path):
            shutil.rmtree(output_tmp_path)
        os.makedirs(output_tmp_path)

        output_lib_path = os.path.join(output_tmp_path, "libs")
        os.makedirs(output_lib_path, exist_ok=True)

        build_ninja_main = os.path.join(
            self.vendor_path, "t5_os", "build", "bk7258", "tuya_app", "bk7258", "build.ninja"
        )
        build_base_main = os.path.join(
            self.vendor_path, "t5_os", "build", "bk7258", "tuya_app", "bk7258"
        )
        if os.path.exists(build_ninja_main):
            logging.info("Extracting libraries from bk7258 main core...")
            with open(build_ninja_main, "r") as f:
                for line in f:
                    if "LINK_LIBRARIES" in line:
                        self.copy_from_string(line.strip(), output_lib_path, build_base_main)
                        break

        build_ninja_ap = os.path.join(
            self.vendor_path, "t5_os", "build", "bk7258", "tuya_app", "bk7258_ap", "build.ninja"
        )
        build_base_ap = os.path.join(
            self.vendor_path, "t5_os", "build", "bk7258", "tuya_app", "bk7258_ap"
        )
        if not os.path.exists(build_ninja_ap):
            logging.error(f"AP build.ninja not found: {build_ninja_ap}")
            return False

        link_info_ap = ""
        with open(build_ninja_ap, "r") as f:
            for line in f:
                if "LINK_LIBRARIES" in line:
                    link_info_ap = line.strip()
                    break
        if not link_info_ap:
            logging.error("Can't find LINK_LIBRARIES in AP build.ninja")
            return False

        self.copy_from_string(link_info_ap, output_lib_path, build_base_ap)

        partitions_file = os.path.join(
            self.vendor_path, "t5_os", "projects", "tuya_app", "config", "bk7258", "configuration.json"
        )
        if not self.copy_assets(output_tmp_path, "bk7258", partitions_file):
            return False

        tuya_kconfig_src = os.path.join(
            self.build_app_path, ".build", "include", "tuya_kconfig.h"
        )
        tuya_kconfig_dst_dir = os.path.join(
            output_tmp_path, "platform", "T5AI", "tuyaos", "tuyaos_adapter", "include"
        )
        os.makedirs(tuya_kconfig_dst_dir, exist_ok=True)
        tuya_kconfig_dst = os.path.join(tuya_kconfig_dst_dir, "tuya_kconfig.h")

        if os.path.exists(tuya_kconfig_src):
            with open(tuya_kconfig_src, "r") as f:
                content = f.read()
            content = re.sub(
                r'(#define\s+PROJECT_VERSION\s+"[^"]+")',
                r'#ifndef PROJECT_VERSION\n\1\n#endif',
                content,
            )
            content = re.sub(
                r'(#define\s+TUYA_PRODUCT_ID\s+"[^"]+")',
                r'#ifndef TUYA_PRODUCT_ID\n\1\n#endif',
                content,
            )
            with open(tuya_kconfig_dst, "w") as f:
                f.write(content)
        else:
            logging.error(f"tuya_kconfig.h not found at {tuya_kconfig_src}")
            return False

        logging.info("Processing ai_components...")
        self.copy_ai_components_libs(output_lib_path)
        ai_include_paths = self.copy_ai_components_headers(output_tmp_path)
        if ai_include_paths:
            self.update_include_tuya_open_with_ai_components(ai_include_paths)

        if not self.copy_tuya_open(output_tmp_path):
            return False

        return True

    def update_ci_data(self):
        """Update ci-data with latest build artifacts (bootloader, tuyaboot, CP bin, LD script).

        Artifacts are extracted from the post-build package directory:
        t5_os/build/bk7258/tuya_app/package/tmp/
        """
        packager_tools_dst = os.path.join(self.data_path, "packager-tools")
        package_tmp_path = os.path.join(
            self.vendor_path, "t5_os", "build", "bk7258", "tuya_app", "package", "tmp"
        )

        # Bootloader
        bootloader_src = os.path.join(package_tmp_path, "bootloader.bin")
        if os.path.exists(bootloader_src):
            dst = os.path.join(packager_tools_dst, "T5_bootloader.bin")
            shutil.copy2(bootloader_src, dst)
            with open(dst, "rb") as f:
                md5 = hashlib.md5(f.read()).hexdigest()
            logging.info(f"Updated ci-data: T5_bootloader.bin ({os.path.getsize(dst)} bytes, md5={md5})")
        else:
            logging.error(f"T5 bootloader not found: {bootloader_src}")

        # TuyaBoot
        tuyaboot_src = os.path.join(package_tmp_path, "tuyaboot.bin")
        if os.path.exists(tuyaboot_src):
            dst = os.path.join(packager_tools_dst, "T5_tuyaboot.bin")
            shutil.copy2(tuyaboot_src, dst)
            with open(dst, "rb") as f:
                md5 = hashlib.md5(f.read()).hexdigest()
            logging.info(f"Updated ci-data: T5_tuyaboot.bin ({os.path.getsize(dst)} bytes, md5={md5})")
        else:
            logging.error(f"T5 tuyaboot not found: {tuyaboot_src}")

        # CP firmware
        cp_app_src = os.path.join(package_tmp_path, "app.bin")
        if os.path.exists(cp_app_src):
            dst = os.path.join(packager_tools_dst, "t5_cp_app.bin")
            shutil.copy2(cp_app_src, dst)
            with open(dst, "rb") as f:
                md5 = hashlib.md5(f.read()).hexdigest()
            info_path = os.path.join(packager_tools_dst, "t5_cp_app_info.txt")
            with open(info_path, "w") as f:
                f.write(f"CP Firmware Build Info\n")
                f.write(f"=====================\n")
                f.write(f"Size: {os.path.getsize(dst)} bytes\n")
                f.write(f"MD5: {md5}\n")
                f.write(f"Source: {cp_app_src}\n")
            logging.info(f"Updated ci-data: t5_cp_app.bin ({os.path.getsize(dst)} bytes, md5={md5})")
        else:
            logging.error(f"CP core app.bin not found: {cp_app_src}")

        # Linker script
        ld_src = os.path.join(
            self.vendor_path, "t5_os", "build", "bk7258", "tuya_app", "bk7258_ap",
            "armino", "bk7258_ap", "bk7258_ap_out.ld"
        )
        if os.path.exists(ld_src):
            dst = os.path.join(packager_tools_dst, "T5.ld")
            shutil.copy2(ld_src, dst)
            logging.info(f"Updated ci-data: T5.ld ({os.path.getsize(dst)} bytes)")
        else:
            logging.error(f"T5 linker script not found: {ld_src}")
