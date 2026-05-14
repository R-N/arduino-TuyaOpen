import os
import logging
import shutil
import platform
import subprocess
import json

from .chip_info import *

t3_config_str = '''
{
    "magic": "FreeRTOS",
    "version": "0.1",
    "count": 2,
    "section": [
        {
            "firmware": "bootloader.bin",
            "version": "2M.1220",
            "partition": "bootloader",
            "start_addr": "0x00000000",
            "size": "64K"
        },
        {
            "firmware": "app.bin",
            "version": "2M.1220",
            "partition": "app",
            "start_addr": "0x00010000",
            "size": "2176K"
        }
    ]
}
'''

t5_config_str = '''
{
    "magic": "beken",
    "crc_enable": true,
    "count": 4,
    "section": [
        {
            "firmware": "bootloader.bin",
            "partition": "bootloader",
            "start_addr": "0x00000000",
            "size": "68K"
        },
        {
            "firmware": "tuyaboot.bin",
            "partition": "tuyaboot",
            "start_addr": "0x00011000",
            "size": "68K"
        },
        {
            "firmware": "app.bin",
            "partition": "app",
            "start_addr": "0x00022000",
            "size": "1088K"
        },
        {
            "firmware": "app1.bin",
            "partition": "app1",
            "start_addr": "0x00132000",
            "size": "3808K"
        }
    ]
}
'''

def __crc16(data, offset, length):
    crc = 0xFFFFFFFF
    for i in range(length):
        crc ^= data[offset + i] << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x8005
            else:
                crc = crc << 1
    return crc & 0xFFFF

def __crc16_data(raw_data):
    pack_len = 32
    padding_len = (pack_len - (len(raw_data) % pack_len)) % pack_len
    if padding_len:
        raw_data += bytes([0xFF] * padding_len)

    output_data = bytearray()
    for i in range(0, len(raw_data), pack_len):
        chunk = raw_data[i:i + pack_len]
        output_data.extend(chunk)
        output_data.extend(__crc16(chunk, 0, pack_len).to_bytes(2, byteorder="big"))
    return bytes(output_data)

def __pack_t5_linear_crc(config_json, all_app_pack_file):
    part_items = []
    for section in config_json["section"]:
        firmware = section["firmware"]
        part_addr = int(section["start_addr"], 16)
        if not os.path.exists(firmware):
            logging.error(f"Firmware not found: {firmware}")
            return False
        with open(firmware, "rb") as f:
            raw_data = f.read()
        part_items.append({
            "partition": section["partition"],
            "addr": part_addr,
            "data": __crc16_data(raw_data),
        })

    curr_pos = 0
    with open(all_app_pack_file, "wb") as f:
        for part_item in part_items:
            part_addr = part_item["addr"]
            if curr_pos > part_addr:
                logging.error(f"T5 partition layout error at {part_item['partition']}")
                return False
            if curr_pos:
                f.write(bytes([0xFF] * (part_addr - curr_pos)))
            f.write(part_item["data"])
            curr_pos = part_addr + len(part_item["data"])
        f.write(bytes([0xFF] * 34))

    # Match TuyaOpen build package alignment.
    padding_len = (32 - os.path.getsize(all_app_pack_file) % 32) % 32
    if padding_len:
        with open(all_app_pack_file, "ab") as f:
            f.write(bytes([0xFF] * padding_len))
    return True

def get_qio_binary_t3_t5(chip_info):
    logging.debug(f"platform system: {platform.system()}")
    if platform.system() == 'Windows':
        cmake_Gen_image_tools = os.path.join(chip_info.tools_path, 'windows', 'cmake_Gen_image.exe')
        cmake_encrypt_crc_tool = os.path.join(chip_info.tools_path, 'windows', 'cmake_encrypt_crc.exe')
    elif platform.system() == 'Linux':
        cmake_Gen_image_tools = os.path.join(chip_info.tools_path, 'linux', 'cmake_Gen_image')
        cmake_encrypt_crc_tool = os.path.join(chip_info.tools_path, 'linux', 'cmake_encrypt_crc')
    elif platform.system() == 'Darwin':
        mac_arch = platform.machine()
        logging.info(f"MAC machine is: {mac_arch}")
        cmake_Gen_image_tools = os.path.join(chip_info.tools_path, 'mac', mac_arch, 'cmake_Gen_image')
        cmake_encrypt_crc_tool = os.path.join(chip_info.tools_path, 'mac', mac_arch, 'cmake_encrypt_crc')
    else:
        logging.error(f"Unknown OS: {platform.system()}")
        return False

    bootloader_file = os.path.join(chip_info.tools_path, chip_info.chip + '_bootloader.bin')

    logging.debug(f"cmake_Gen_image: {cmake_Gen_image_tools}")
    logging.debug(f"cmake_encrypt_crc: {cmake_encrypt_crc_tool}")
    logging.debug(f"bootloader_file: {bootloader_file}")

    if not os.path.exists(cmake_Gen_image_tools) or not os.path.exists(cmake_encrypt_crc_tool):
        logging.error("cmake_Gen_image or cmake_encrypt_crc not found")
        return False

    if not os.path.exists(bootloader_file):
        logging.error("bootloader_file not find")
        return False

    os.chdir(chip_info.output_path)

    # Generate json file
    if chip_info.chip == 't3':
        config_str = t3_config_str
    elif chip_info.chip == 'T5':
        config_str = t5_config_str
    else:
        return False

    config_json = json.loads(config_str)
    config_json["section"][0]["firmware"] = bootloader_file
    
    # For T5: set tuyaboot, CP firmware, and AP firmware.
    if chip_info.chip == 'T5':
        tuyaboot_file = os.path.join(chip_info.tools_path, 'T5_tuyaboot.bin')
        cp_app_file = os.path.join(chip_info.tools_path, 't5_cp_app.bin')
        if not os.path.exists(tuyaboot_file):
            logging.error(f"T5 tuyaboot not found: {tuyaboot_file}")
            logging.error("T5 requires tuyaboot at 0x02010000 before CP/AP startup")
            return False
        if not os.path.exists(cp_app_file):
            logging.error(f"CP core app not found: {cp_app_file}")
            logging.error("T5 requires CP core (Communication Processor) to initialize WiFi/BLE before AP core")
            return False
        config_json["section"][1]["firmware"] = tuyaboot_file
        config_json["section"][2]["firmware"] = cp_app_file
        config_json["section"][3]["firmware"] = chip_info.bin_file
    else:
        # T3: only 2 sections
        config_json["section"][1]["firmware"] = chip_info.bin_file
    
    logging.debug("config_json: " + json.dumps(config_json, indent=4))
    config_file = os.path.join(chip_info.output_path, "config.json")
    with open(config_file, 'w') as f:
        json.dump(config_json, f, indent=4)

    all_app_pack_file = os.path.join(chip_info.output_path, 'all_app_pack.bin')
    
    if chip_info.chip == 'T5':
        logging.debug("T5 pack mode: linear crc")
        if not __pack_t5_linear_crc(config_json, all_app_pack_file):
            logging.error("T5 linear crc pack failed")
            return False
    else:
        # T3: 2 files (bootloader + app)
        gen_image_command = [
            cmake_Gen_image_tools,
            'genfile',
            '-injsonfile',
            config_file,
            '-infile',
            bootloader_file,
            chip_info.bin_file,
            '-outfile',
            all_app_pack_file
        ]
        logging.debug("gen_image_command: " + ' '.join(gen_image_command))
        result = subprocess.run(gen_image_command)
        if result.returncode != 0 or not os.path.exists(all_app_pack_file):
            logging.error("gen_image_command failed")
            return False

    chip_info.bin_file_QIO = os.path.join(chip_info.output_path, f"{chip_info.sketch_name}_QIO_{chip_info.sketch_version}.bin")

    if chip_info.chip == 'T5':
        shutil.move(all_app_pack_file, chip_info.bin_file_QIO)
    else:
        all_app_pack_crc_file = os.path.join(chip_info.output_path, 'all_app_pack_crc.bin')
        cmake_encrypt_crc_command = [
            cmake_encrypt_crc_tool,
            '-crc',
            all_app_pack_file
        ]
        logging.debug("cmake_encrypt_crc_command: " + ' '.join(cmake_encrypt_crc_command))
        result = subprocess.run(cmake_encrypt_crc_command)
        if result.returncode != 0 or not os.path.exists(all_app_pack_crc_file):
            logging.error("cmake_encrypt_crc_command failed")
            return False
        shutil.move(all_app_pack_crc_file, chip_info.bin_file_QIO)

    # Print build success information
    qio_bin_name = os.path.basename(chip_info.bin_file_QIO)
    
    logging.info("")
    logging.info("[NOTE]:")
    logging.info("====================[ BUILD SUCCESS ]====================")
    logging.info(f" Target    : {qio_bin_name}")
    logging.info(f" Output    : {chip_info.output_path}")
    logging.info(f" Chip      : {chip_info.chip}")
    logging.info(f" Board     : {chip_info.board}")
    logging.info(f" Framework : Arduino")
    logging.info("========================================================")

    return True

