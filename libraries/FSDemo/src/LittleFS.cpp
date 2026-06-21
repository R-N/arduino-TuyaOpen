#include "LittleFS.h"
#include "tal_memory.h"
#include <esp_partition.h>
#include <esp_err.h>
#include <esp_log.h>
#include <esp_flash_partitions.h>
#include <string.h>

// ---------------------------------------------------------------------------
// Dedicated LittleFS for the web app + user data on the `spiffs` partition
// (0x26C000). This filesystem is INDEPENDENT of the Tuya SDK's tal_kv/tal_fs
// lfs (the global `tal_lfs_get()` mounted at the UF region inside the `tuya`
// partition, 0x3b0000).
//
// Historic bug: FS_LITTLEFS used `tal_lfs_get()` (the SDK's single global lfs)
// AND re-mounted it at 0x26C000, while tal_kv mounted the same global lfs at
// UF. Last-mount-won, so app file writes and reads were misrouted between the
// two partitions across the boot boundary -> nothing persisted. Fixed by
// giving this class its own `s_lfs` and doing all file ops with lfs_* directly
// (no tal_fopen / tal_lfs_get). tal_kv keeps its own lfs at UF, untouched.
// ---------------------------------------------------------------------------

static lfs_t s_lfs;
static bool  s_mounted = false;

static lfs_size_t lfs_flash_addr;
static const esp_partition_t *lfs_esp_partition = NULL;

static int user_provided_block_device_read(const struct lfs_config *c, lfs_block_t block, lfs_off_t off, void *buffer, lfs_size_t size)
{
    if (lfs_esp_partition) {
        esp_err_t err = esp_partition_read(lfs_esp_partition, c->block_size * block + off, buffer, size);
        return err == ESP_OK ? LFS_ERR_OK : LFS_ERR_IO;
    }

    OPERATE_RET ret = tkl_flash_read(lfs_flash_addr + c->block_size * block + off, (uint8_t*)buffer, size);
    return (OPRT_OK == ret) ? LFS_ERR_OK : LFS_ERR_IO;
}

static int user_provided_block_device_prog(const struct lfs_config *c, lfs_block_t block, lfs_off_t off, const void *buffer, lfs_size_t size)
{
    if (lfs_esp_partition) {
        esp_err_t err = esp_partition_write(lfs_esp_partition, c->block_size * block + off, buffer, size);
        return err == ESP_OK ? LFS_ERR_OK : LFS_ERR_IO;
    }

    OPERATE_RET ret = tkl_flash_write(lfs_flash_addr + c->block_size * block + off, (uint8_t*)buffer, size);
    return (OPRT_OK == ret) ? LFS_ERR_OK : LFS_ERR_IO;
}

static int user_provided_block_device_erase(const struct lfs_config *c, lfs_block_t block)
{
    if (lfs_esp_partition) {
        esp_err_t err = esp_partition_erase_range(lfs_esp_partition, c->block_size * block, c->block_size);
        return err == ESP_OK ? LFS_ERR_OK : LFS_ERR_IO;
    }

    OPERATE_RET ret = tkl_flash_erase(lfs_flash_addr + c->block_size * block, c->block_size);
    return (OPRT_OK == ret) ? LFS_ERR_OK : LFS_ERR_IO;
}

static int user_provided_block_device_sync(const struct lfs_config *c)
{
    return LFS_ERR_OK;
}

static int mount(TUYA_FLASH_PARTITION_T partition);

static int mount()
{
    TUYA_FLASH_BASE_INFO_T info;
    tkl_flash_get_one_type_info(TUYA_FLASH_TYPE_UF, &info);
    return mount(info.partition[0]);
}

static int mount(TUYA_FLASH_PARTITION_T partition)
{
    if (s_mounted)
        return 0;

    lfs_flash_addr = partition.start_addr;
    lfs_esp_partition = NULL;

    const esp_partition_t *spiffs = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, "spiffs");
    if (spiffs && spiffs->address == partition.start_addr) {
        lfs_esp_partition = spiffs;
    }

    static struct lfs_config lfs_cfg = {0};
    lfs_cfg.read  = user_provided_block_device_read;
    lfs_cfg.prog  = user_provided_block_device_prog;
    lfs_cfg.erase = user_provided_block_device_erase;
    lfs_cfg.sync  = user_provided_block_device_sync;
    lfs_cfg.read_size  = lfs_esp_partition ? 256 : partition.block_size;
    lfs_cfg.prog_size  = lfs_esp_partition ? 256 : partition.block_size;
    lfs_cfg.cache_size = lfs_esp_partition ? 256 : partition.block_size;
    lfs_cfg.block_size = partition.block_size;
    lfs_cfg.block_count = partition.size / partition.block_size;
    lfs_cfg.lookahead_size = lfs_cfg.block_count / 8 + (8 - (lfs_cfg.block_count / 8));
    lfs_cfg.block_cycles = 500;

    Serial.print("LittleFS(app) mount @0x");
    Serial.print(lfs_flash_addr, HEX);
    Serial.print(" blocks=");
    Serial.println(lfs_cfg.block_count);

    int err = lfs_mount(&s_lfs, &lfs_cfg);
    if (err < 0) {
        Serial.print("LittleFS(app) mount err ");
        Serial.print(err);
        Serial.println(", formatting...");
        lfs_format(&s_lfs, &lfs_cfg);
        err = lfs_mount(&s_lfs, &lfs_cfg);
        if (err < 0) {
            Serial.print("LittleFS(app) remount err ");
            Serial.println(err);
            return err;
        }
    }
    s_mounted = true;
    return 0;
}

// "r","w","a","r+","w+","a+" (+ optional 'b') -> lfs open flags
static int lfs_flags_from_mode(const char *mode)
{
    if (!mode) return LFS_O_RDONLY;
    bool plus = (strchr(mode, '+') != NULL);
    switch (mode[0]) {
        case 'r': return plus ? LFS_O_RDWR : LFS_O_RDONLY;
        case 'w': return (plus ? LFS_O_RDWR : LFS_O_WRONLY) | LFS_O_CREAT | LFS_O_TRUNC;
        case 'a': return (plus ? LFS_O_RDWR : LFS_O_WRONLY) | LFS_O_CREAT | LFS_O_APPEND;
        default:  return LFS_O_RDONLY;
    }
}

typedef struct {
    lfs_dir_t       dir;
    struct lfs_info info;
} app_dir_t;

FS_LITTLEFS::FS_LITTLEFS()
{
    ismounted = false;
}

FS_LITTLEFS::~FS_LITTLEFS()
{
}

bool FS_LITTLEFS::begin(){
    if(this->partition.start_addr)
        ismounted = mount(this->partition) >= 0;
    else
        ismounted = mount() >= 0;
    return ismounted;
}

bool FS_LITTLEFS::begin(TUYA_FLASH_PARTITION_T partition){
    this->partition = partition;
    ismounted = mount(this->partition) >= 0;
    return ismounted;
}

static int createDirRecursive(const char *path) {
    int ret = lfs_mkdir(&s_lfs, path);
    if (ret == LFS_ERR_OK || ret == LFS_ERR_EXIST)
        return 0;
    if (ret == LFS_ERR_NOENT) {
        size_t len = strlen(path) + 1;
        char *parentPath = (char*)tal_malloc(len);
        if (!parentPath)
            return -1;
        strcpy(parentPath, path);
        char *lastSlash = strrchr(parentPath, '/');
        if (lastSlash != NULL && lastSlash != parentPath) {
            *lastSlash = '\0';
            int result = createDirRecursive(parentPath);
            tal_free(parentPath);
            if (result != 0)
                return result;
            ret = lfs_mkdir(&s_lfs, path);
            return (ret == LFS_ERR_OK || ret == LFS_ERR_EXIST) ? 0 : -1;
        }
        tal_free(parentPath);
        return -1;
    }
    return -1;
}

int FS_LITTLEFS:: mkdir(const char *path)
{
    if(!ismounted)
        return -1;
    return createDirRecursive(path);
}

int FS_LITTLEFS::remove(const char *path)
{
    if(!ismounted)
        return -1;
    return lfs_remove(&s_lfs, path);
}

int FS_LITTLEFS::exist(const char *path)
{
    if(!ismounted)
        return -1;
    struct lfs_info info;
    return (lfs_stat(&s_lfs, path, &info) >= 0) ? 1 : 0;
}

int FS_LITTLEFS::rename(const char *pathFrom,const char *pathTo)
{
    if(!ismounted)
        return -1;
    return lfs_rename(&s_lfs, pathFrom, pathTo);
}

TUYA_DIR FS_LITTLEFS::openDir(const char *path)
{
    if(!ismounted)
        return NULL;
    app_dir_t *h = (app_dir_t*)tal_malloc(sizeof(app_dir_t));
    if (!h)
        return NULL;
    memset(h, 0, sizeof(app_dir_t));
    if (lfs_dir_open(&s_lfs, &h->dir, path) < 0) {
        tal_free(h);
        return NULL;
    }
    return (TUYA_DIR)h;
}

int FS_LITTLEFS:: closeDir(TUYA_DIR dir)
{
    if(!ismounted || !dir)
        return -1;
    app_dir_t *h = (app_dir_t*)dir;
    int ret = lfs_dir_close(&s_lfs, &h->dir);
    tal_free(h);
    return ret;
}

TUYA_FILEINFO FS_LITTLEFS::readDir(TUYA_DIR dir)
{
    if(!ismounted || !dir)
        return NULL;
    app_dir_t *h = (app_dir_t*)dir;
    int ret = lfs_dir_read(&s_lfs, &h->dir, &h->info);
    if (ret <= 0)        // 0 = end of dir, <0 = error
        return NULL;
    return (TUYA_FILEINFO)&h->info;
}

int FS_LITTLEFS:: getDirName(TUYA_FILEINFO info,const char** name)
{
    if(!ismounted || !info || !name)
        return -1;
    *name = ((struct lfs_info*)info)->name;
    return 0;
}

int FS_LITTLEFS:: isDirectory(const char *path)
{
    if(!ismounted)
        return -1;
    struct lfs_info info;
    if (lfs_stat(&s_lfs, path, &info) < 0)
        return -1;
    return (info.type == LFS_TYPE_DIR) ? 1 : 0;
}

TUYA_FILE FS_LITTLEFS::open(const char *path)
{
    return open(path, "a+");
}

TUYA_FILE FS_LITTLEFS::open(const char *path, const char* mode)
{
    if(!ismounted)
    {
        int ret = this->partition.start_addr ? mount(this->partition) : mount();
        if(ret >= 0)
            ismounted = true;
        else
            return NULL;
    }
    lfs_file_t *f = (lfs_file_t*)tal_malloc(sizeof(lfs_file_t));
    if (!f)
        return NULL;
    memset(f, 0, sizeof(lfs_file_t));
    if (lfs_file_open(&s_lfs, f, path, lfs_flags_from_mode(mode)) < 0) {
        tal_free(f);
        return NULL;
    }
    return (TUYA_FILE)f;
}

int FS_LITTLEFS::close(TUYA_FILE fd)
{
    if(!ismounted||!fd)
        return -1;
    int ret = lfs_file_close(&s_lfs, (lfs_file_t*)fd);
    tal_free(fd);
    return ret;
}

char FS_LITTLEFS:: read(TUYA_FILE fd)
{
    if(!ismounted||!fd)
        return '\0';
    char c = '\0';
    if (lfs_file_read(&s_lfs, (lfs_file_t*)fd, &c, 1) != 1)
        return '\0';
    return c;
}

int FS_LITTLEFS::read(const char *buf,int size,TUYA_FILE fd)
{
    if(!ismounted||!fd ||!buf||!size)
        return -1;
    return lfs_file_read(&s_lfs, (lfs_file_t*)fd, (void*)buf, size);
}

int FS_LITTLEFS::readtillN(char *buf, int size,TUYA_FILE fd)
{
    if(!ismounted||!fd ||!buf||!size)
        return -1;
    int i = 0;
    char c;
    while (i < size - 1) {
        int r = lfs_file_read(&s_lfs, (lfs_file_t*)fd, &c, 1);
        if (r != 1)
            break;
        buf[i++] = c;
        if (c == '\n')
            break;
    }
    buf[i] = '\0';
    return OPRT_OK;
}

int FS_LITTLEFS::write(const char *buf,int size,TUYA_FILE fd)
{
    if(!ismounted||!fd ||!buf||!size)
        return -1;
    return lfs_file_write(&s_lfs, (lfs_file_t*)fd, (void*)buf, size);
}

void FS_LITTLEFS::flush(TUYA_FILE fd)
{
    if(!ismounted||!fd)
        return;
    lfs_file_sync(&s_lfs, (lfs_file_t*)fd);
}

int FS_LITTLEFS::feof(TUYA_FILE fd)
{
    if(!ismounted||!fd)
        return -1;
    lfs_file_t *f = (lfs_file_t*)fd;
    lfs_soff_t pos = lfs_file_tell(&s_lfs, f);
    lfs_soff_t sz  = lfs_file_size(&s_lfs, f);
    return (pos >= sz) ? 1 : 0;
}

int FS_LITTLEFS::lseek(TUYA_FILE fd,int offs, int whence)
{
    if(!ismounted||!fd)
        return -1;
    int lfs_whence = LFS_SEEK_SET;
    if (whence == SEEK_CUR) lfs_whence = LFS_SEEK_CUR;
    else if (whence == SEEK_END) lfs_whence = LFS_SEEK_END;
    return lfs_file_seek(&s_lfs, (lfs_file_t*)fd, offs, lfs_whence);
}

int FS_LITTLEFS::position(TUYA_FILE fd)
{
    if(!ismounted||!fd)
        return -1;
    return lfs_file_tell(&s_lfs, (lfs_file_t*)fd);
}

int FS_LITTLEFS::filesize(const char *filepath)
{
    if(!ismounted)
        return -1;
    struct lfs_info info;
    if (lfs_stat(&s_lfs, filepath, &info) < 0)
        return -1;
    return info.size;
}
