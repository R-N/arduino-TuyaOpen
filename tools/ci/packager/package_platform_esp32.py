# -*- coding: utf-8 -*-

import logging
import os
import shutil
import json

from .package_platform import PackagePlatform


class PackagePlatformEsp32(PackagePlatform):
    def copy_from_string(self, input_str, output_lib_path):
        tmp_list = [x for x in input_str.split() if x]
        lib_fragments = sorted(set(lib for lib in tmp_list if lib.endswith(".a")))

        remove_lib_list = ["libtuyaapp.a"]
        rename_lib_dict = {
            "esp-idf/mbedtls/mbedtls/library/libmbedtls.a": "libmbedtls_library.a"
        }

        output_libs = {}
        for lib_fragment in lib_fragments:
            full_lib_path = lib_fragment
            if lib_fragment.startswith("esp-idf/"):
                full_lib_path = os.path.normpath(
                    os.path.join(self.vendor_path, "tuya_open_sdk", "build", lib_fragment)
                )
            output_lib_name = os.path.basename(lib_fragment)
            if output_lib_name in remove_lib_list:
                continue
            for rename_key, new_name in rename_lib_dict.items():
                if rename_key in lib_fragment:
                    output_lib_name = new_name
                    break
            if output_lib_name in output_libs:
                logging.error(f"Lib name '{output_lib_name}' duplicated")
                continue
            output_libs[output_lib_name] = full_lib_path

        for out_name, src_path in output_libs.items():
            if not os.path.exists(src_path):
                logging.warning(f"Source library not found, skipping: {src_path}")
                continue
            shutil.copy2(src_path, os.path.join(output_lib_path, out_name))
        return True

    def copy_from_link_path(self, input_str, output_path):
        tmp_list = [x for x in input_str.split() if x]
        lib_list = []
        for lib in tmp_list:
            if lib.startswith("-L"):
                path = lib[2:]
                if path not in lib_list:
                    lib_list.append(path)

        for lib in lib_list:
            output_lib = os.path.join(output_path, lib[len(self.vendor_path) + 1:])
            os.makedirs(os.path.dirname(output_lib), exist_ok=True)
            shutil.copytree(lib, output_lib)
        return True

    def get_libs_flags(self, input_str, output_file):
        link_txt_lists = [x for x in input_str.split() if x]

        remove_lib_list = ["libtuyaapp.a"]
        for remove_lib in remove_lib_list:
            link_txt_lists = [x for x in link_txt_lists if remove_lib not in x]

        lib_list = link_txt_lists[2:]

        rename_lib_dict = {
            "esp-idf/mbedtls/mbedtls/library/libmbedtls.a": "libmbedtls_library.a"
        }
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

        one_line = False
        with open(output_file, "w") as f:
            for lib in write_lib_list:
                lib_stripped = lib.strip()
                if lib_stripped == "-u":
                    one_line = True
                else:
                    one_line = False
                f.write(f"{lib_stripped} " if one_line else f"{lib_stripped}\n")
        return True

    def get_ld_flags(self, build_ninja_path, output_file):
        ld_flags_list = []
        with open(build_ninja_path, "r") as f:
            for line in f:
                if "LINK_FLAGS" in line:
                    ld_flags_list = [x for x in line.split() if x]
                    break

        ld_flags_list = ld_flags_list[2:]
        ld_flags_list.insert(0, "-Wno-frame-address")
        ld_flags_list.insert(0, "-mlongcalls")
        ld_flags_list = [x for x in ld_flags_list if "-Wl,--Map=" not in x]

        one_line = False
        with open(output_file, "w") as f:
            for ld_flag in ld_flags_list:
                l_stripped = ld_flag.strip()
                if l_stripped == "-T":
                    one_line = True
                else:
                    one_line = False
                f.write(f"{l_stripped} " if one_line else f"{l_stripped}\n")
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
            x for x in include_list if x.startswith("platform/ESP32/tuya_open_sdk/tuyaos_adapter/")
        ]
        with open(os.path.join(output_path, "include_tkl.txt"), "w") as f:
            f.write("platform/ESP32/tuya_open_sdk/build/config\n")
            f.write("platform/ESP32/tuya_open_sdk/tuyaos_adapter/include\n")
            f.write("platform/ESP32/tuya_open_sdk/tuyaos_adapter/include/security\n")
            for item in tuyaos_adapter_include_list:
                f.write(f"{item}\n")

        vendor_include_list = [x for x in include_list if x.startswith("platform/ESP32/esp-idf/")]
        with open(os.path.join(output_path, "include_vendor.txt"), "w") as f:
            f.write("\n".join(vendor_include_list) + "\n")

    def copy_assets(self, output_tmp_path):
        build_ninja_path = os.path.join(
            self.clone_path, "platform", "ESP32", "tuya_open_sdk", "build", "build.ninja"
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
            logging.error("Can't find LINK_LIBRARIES in build.ninja")
            return False

        output_lib_path = os.path.join(output_tmp_path, "libs")
        if os.path.exists(output_lib_path):
            shutil.rmtree(output_lib_path)
        os.makedirs(output_lib_path)
        self.copy_from_string(link_info, output_lib_path)

        link_path = ""
        with open(build_ninja_path, "r") as f:
            for line in f:
                if "LINK_PATH" in line:
                    link_path = line.strip()
                    break
        if link_path:
            self.copy_from_link_path(link_path, os.path.join(output_tmp_path, "link_path"))

        self.staging_path = os.path.join(output_tmp_path, "_staging")
        os.makedirs(self.staging_path, exist_ok=True)
        shutil.copytree(
            os.path.join(self.data_path, "flags"),
            os.path.join(self.staging_path, "flags"),
        )

        libs_flags_file = os.path.join(self.staging_path, "flags", "libs_flags.txt")
        self.get_libs_flags(link_info, libs_flags_file)

        ld_flags_file = os.path.join(self.staging_path, "flags", "ld_flags.txt")
        self.get_ld_flags(build_ninja_path, ld_flags_file)

        compile_commands_file = os.path.join(
            self.vendor_path, "tuya_open_sdk", "build", "compile_commands.json"
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

        app_bin_path = os.path.join(
            self.clone_path, "apps", "tuya_cloud", "switch_demo", ".build", "bin"
        )
        if not os.path.exists(app_bin_path):
            logging.error(f"Can't find {app_bin_path}")
            return False

        for name in ["bootloader.bin", "ota_data_initial.bin", "partition-table.bin"]:
            src = os.path.join(app_bin_path, name)
            if not os.path.exists(src):
                logging.error(f"Can't find {src}")
                return False
            shutil.copy2(src, os.path.join(output_tmp_path, "packager-tools", name))

        tuya_kconfig_src = os.path.join(
            self.clone_path, "apps", "tuya_cloud", "switch_demo", ".build", "include", "tuya_kconfig.h"
        )
        tuya_kconfig_dst_dir = os.path.join(
            output_tmp_path, "platform", "ESP32", "tuya_open_sdk", "tuyaos_adapter", "include"
        )
        tuya_kconfig_dst = os.path.join(tuya_kconfig_dst_dir, "tuya_kconfig.h")

        if os.path.exists(tuya_kconfig_src):
            os.makedirs(tuya_kconfig_dst_dir, exist_ok=True)
            with open(tuya_kconfig_src, "r") as f:
                content = f.read()
            if "#ifndef PROJECT_VERSION" not in content:
                lines = content.split("\n")
                new_lines = []
                for line in lines:
                    if line.strip().startswith("#define PROJECT_VERSION"):
                        new_lines.append("#ifndef PROJECT_VERSION")
                        new_lines.append(line)
                        new_lines.append("#endif")
                    else:
                        new_lines.append(line)
                content = "\n".join(new_lines)
            with open(tuya_kconfig_dst, "w") as f:
                f.write(content)

        if not self.copy_tuya_open(output_tmp_path):
            return False
        return True

    def package(self):
        self.vendor_path = os.path.join(self.clone_path, "platform", "ESP32")

        if not self.git_clone():
            return False

        ini_file = os.path.join(self.config_path, "app_default.config")
        if not self.set_platform_ini(ini_file):
            return False

        if not self.build_platform():
            return False

        output_tmp_path = os.path.join(self.package_info.output_path, "tmp", self.package_info.name)
        if os.path.exists(output_tmp_path):
            shutil.rmtree(output_tmp_path)
        os.makedirs(output_tmp_path)

        return self.copy_assets(output_tmp_path)
