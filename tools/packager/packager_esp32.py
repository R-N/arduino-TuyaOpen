import os
import logging
import shutil
import platform

from .chip_info import *

OFFSET_START = 0x0
OFFSET_BOOTLOADER = 0x1000
OFFSET_PARTITIONS = 0x8000
# OFFSET_OTA_DATA_INITIAL = 0xd000
OFFSET_OTA_DATA_INITIAL = 0xE000
OFFSET_APPLICATION = 0x20000
OFFSET_SPIFFS = 0x26C000
OFFSET_COREDUMP = 0x3F0000
# OFFSET_END = 0x190000
OFFSET_END = 0x400000

SPIFFS_SIZE = 0x134000
COREDUMP_SIZE = 0x10000

def esp32_image_gen(chip_info):
    bin_path_bootloader = os.path.join(chip_info.tools_path, "bootloader.bin")
    bin_path_partitions_table = os.path.join(chip_info.tools_path, "partitions.bin")
    bin_path_ota_data_init = os.path.join(chip_info.tools_path, "ota_data_initial.bin")
    bin_path_app = os.path.join(chip_info.output_path, f"{chip_info.sketch_name}_app.bin")

    # output bin
    chip_info.bin_file_QIO = os.path.join(chip_info.output_path, f"{chip_info.sketch_name}_QIO_{chip_info.sketch_version}.bin")

    if not os.path.exists(bin_path_bootloader):
        logging.error(f"{bin_path_bootloader} not found")
        return False
    
    if not os.path.exists(bin_path_partitions_table):
        logging.error(f"{bin_path_partitions_table} not found")
        return False
    
    if not os.path.exists(bin_path_ota_data_init):
        logging.error(f"{bin_path_ota_data_init} not found")
        return False
    
    if not os.path.exists(bin_path_app):
        logging.error(f"{bin_path_app} not found")
        return False
    
    bin_files_in = [
        ("bootloader", OFFSET_BOOTLOADER, bin_path_bootloader),
        ('partitions', OFFSET_PARTITIONS, bin_path_partitions_table),
        ('ota_data_initial', OFFSET_OTA_DATA_INITIAL, bin_path_ota_data_init),
        ('application', OFFSET_APPLICATION, bin_path_app)
    ]

    with open(chip_info.bin_file_QIO, 'wb') as bin_out:
        cur_offset = OFFSET_START
        for name, offset, bin_in in bin_files_in:
            if offset < cur_offset:
                logging.error(f"{name} overlaps previous region!")
                return False

            bin_out.write(b'\xff' * (offset - cur_offset))
            cur_offset = offset
            with open(bin_in, 'rb') as bin_in:
                data = bin_in.read()
                bin_out.write(data)
                cur_offset += len(data)

        # Fill until SPIFFS
        if cur_offset < OFFSET_SPIFFS:
            bin_out.write(b'\xff' * (OFFSET_SPIFFS - cur_offset))
            cur_offset = OFFSET_SPIFFS

        # Jump over SPIFFS without writing
        # end_of_spiffs = OFFSET_SPIFFS + SPIFFS_SIZE
        # if cur_offset < end_of_spiffs:
        #     cur_offset = end_of_spiffs
            
        # Fill until end of coredump
        end_of_coredump = OFFSET_COREDUMP + COREDUMP_SIZE
        if cur_offset < end_of_coredump:
            bin_out.write(b'\xff' * (end_of_coredump - cur_offset))
            cur_offset = end_of_coredump

        if OFFSET_END < cur_offset:
            logging.error("Final binary exceeds flash size!")
            return False

        # offset = OFFSET_END
        # bin_out.write(b'\xff' * (offset - cur_offset))
        bin_out.write(b'\xff' * (OFFSET_END - cur_offset))
        logging.debug(f"ESP32 QIO binary: {chip_info.bin_file_QIO}")
        logging.debug("package success.")
    
    # Copy bin_path_app
    chip_info.bin_file_UA = os.path.join(chip_info.output_path, f"{chip_info.sketch_name}_UA_{chip_info.sketch_version}.bin")
    chip_info.bin_file_UG = os.path.join(chip_info.output_path, f"{chip_info.sketch_name}_UG_{chip_info.sketch_version}.bin")
    shutil.copy2(bin_path_app, chip_info.bin_file_UA)
    shutil.copy2(bin_path_app, chip_info.bin_file_UG)

    # remove bin_path_app
    os.remove(bin_path_app)

    return True

def get_qio_binary_esp32(chip_info):
    logging.debug(f"platform system: {platform.system()}")

    if False == esp32_image_gen(chip_info):
        logging.error("esp32_image_gen failed")
        return False

    # Print build success information
    qio_bin_name = os.path.basename(chip_info.bin_file_QIO)
    
    logging.info("")
    logging.info("[NOTE]:")
    logging.info("====================[ BUILD SUCCESS ]====================")
    logging.info(f" Target    : {qio_bin_name}")
    logging.info(f" Tools     : {chip_info.tools_path}")
    logging.info(f" Output    : {chip_info.output_path}")
    logging.info(f" Chip      : {chip_info.chip}")
    logging.info(f" Board     : {chip_info.board}")
    logging.info(f" Framework : Arduino")
    logging.info("========================================================")

    return True

