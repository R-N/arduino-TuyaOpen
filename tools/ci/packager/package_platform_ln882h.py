# -*- coding: utf-8 -*-

import logging
import os
import subprocess
import shutil

from .package_platform import PackagePlatform


class PackagePlatformLn882h(PackagePlatform):
    def ar_platform(self, vendor_obj_list, output_file):
        ar_tool = os.path.join(self.compiler_path, "arm-none-eabi-ar")
        if not os.path.exists(ar_tool):
            logging.error(f"ar tool not exists: {ar_tool}")
            return False
        if not os.path.exists(vendor_obj_list):
            logging.error(f"Vendor obj file not exists: {vendor_obj_list}")
            return False

        with open(vendor_obj_list, "r") as f:
            for obj_file in f.read().splitlines():
                obj_file_path = os.path.join(self.vendor_path, "ln882h_os", obj_file)
                if not os.path.exists(obj_file_path):
                    logging.error(f"Object file not exists: {obj_file_path}")
                    return False
                subprocess.run([ar_tool, "rcs", output_file, obj_file_path], check=True)

        logging.info(f"ar {output_file} success")
        return True

    def package(self):
        self.vendor_path = os.path.join(self.clone_path, "platform", "LN882H")
        self.compiler_path = os.path.join(
            self.clone_path, "platform", "tools", "gcc-arm-none-eabi-10.3-2021.10", "bin"
        )

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

        libs_output_path = os.path.join(output_tmp_path, "libs")
        os.makedirs(libs_output_path, exist_ok=True)

        vendor_obj_list = os.path.join(self.data_path, "vendor_obj.txt")
        vendor_lib_file = os.path.join(libs_output_path, "libln882hVendor.a")
        if not self.ar_platform(vendor_obj_list, vendor_lib_file):
            return False

        libs_list_file = os.path.join(self.data_path, "vendor_libs_list.txt")
        if not self.copy_libs(libs_list_file, libs_output_path, self.clone_path):
            logging.error(f"Copy libs failed {libs_list_file}")
            return False

        self.copy_after_delete(
            os.path.join(self.data_path, "packager-tools"),
            os.path.join(output_tmp_path, "packager-tools"),
        )

        if not self.copy_tuya_open(output_tmp_path):
            return False
        return True
