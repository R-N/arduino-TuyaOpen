# -*- coding: utf-8 -*-

import logging
import os
import shutil
import json
import subprocess

from .package_platform import PackagePlatform


class PackagePlatformT3(PackagePlatform):
    def copy_from_string(self, input_str, output_lib_path):
        input_str = input_str.strip()
        tmp_list = [x for x in input_str.split(" ") if x]
        lib_list = list(set(lib for lib in tmp_list if lib.endswith(".a")))

        remove_lib_list = ["libtuyaapp.a"]
        rename_lib_dict = {"/bk7236/libs/libbk_phy.a": "libbk7236_bk_phy.a"}

        output_lib_dict = {}
        for lib in lib_list:
            if os.path.basename(lib) in remove_lib_list:
                continue
            if lib.startswith("armino/"):
                lib = os.path.normpath(
                    os.path.join(self.vendor_path, "t3_os", "tuya_build", "bk7236", lib)
                )
            output_lib_dict[lib] = os.path.basename(lib)
            for rename_key, new_name in rename_lib_dict.items():
                if rename_key in lib:
                    output_lib_dict[lib] = new_name
                    break

        for lib, out_name in output_lib_dict.items():
            output_lib_file = os.path.join(output_lib_path, out_name)
            shutil.copy2(lib, output_lib_file)
            logging.info(f"Copy {lib} to {output_lib_file} success")
        return True

    def get_libs_flags(self, input_str, output_file):
        link_txt_lists = [x for x in input_str.split(" ") if x]

        remove_lib_list = ["libtuyaapp.a"]
        for remove_lib in remove_lib_list:
            link_txt_lists = [x for x in link_txt_lists if remove_lib not in x]

        lib_list = [x for x in link_txt_lists if x.startswith("-l") or x.endswith(".a")]

        rename_lib_dict = {"/bk7236/libs/libbk_phy.a": "-lbk7236_bk_phy"}
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
            x for x in include_list if x.startswith("platform/T3/tuyaos/tuyaos_adapter/")
        ]
        with open(os.path.join(output_path, "include_tkl.txt"), "w") as f:
            f.write("platform/T3/tuyaos/tuyaos_adapter/include\n")
            f.write("platform/T3/tuyaos/tuyaos_adapter/include/security\n")
            for item in tuyaos_adapter_include_list:
                f.write(f"{item}\n")

        vendor_include_list = [x for x in include_list if x.startswith("platform/T3/t3_os/")]
        with open(os.path.join(output_path, "include_vendor.txt"), "w") as f:
            f.write("\n".join(vendor_include_list) + "\n")
        return True

    def copy_assets(self, output_tmp_path):
        build_ninja_path = os.path.join(
            self.vendor_path, "t3_os", "tuya_build", "bk7236", "build.ninja"
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

        self.staging_path = os.path.join(output_tmp_path, "_staging")
        os.makedirs(self.staging_path, exist_ok=True)
        shutil.copytree(
            os.path.join(self.data_path, "flags"),
            os.path.join(self.staging_path, "flags"),
        )

        libs_flags_file = os.path.join(self.staging_path, "flags", "libs_flags.txt")
        self.get_libs_flags(link_info, libs_flags_file)

        compile_commands_file = os.path.join(
            self.vendor_path, "t3_os", "tuya_build", "bk7236", "compile_commands.json"
        )
        if not os.path.exists(compile_commands_file):
            logging.error(f"Compile commands file not exists: {compile_commands_file}")
            return False

        staging_includes = os.path.join(self.staging_path, "includes")
        os.makedirs(staging_includes, exist_ok=True)
        self.get_include_flags(compile_commands_file, staging_includes)

        self.copy_after_delete(
            os.path.join(self.data_path, "packager-tools"),
            os.path.join(output_tmp_path, "packager-tools"),
        )

        if not self.copy_tuya_open(output_tmp_path):
            return False
        return True

    def package(self):
        self.vendor_path = os.path.join(self.clone_path, "platform", "T3")

        if not self.git_clone():
            return False
        if not self.init_submodules():
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
