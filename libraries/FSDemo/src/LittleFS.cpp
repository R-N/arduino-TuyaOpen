#include "LittleFS.h"
#include "tal_memory.h"
#include <esp_partition.h>
#include <esp_err.h>
#include <esp_log.h>
#include <esp_flash_partitions.h>
#include <string.h>

// ---------------------------------------------------------------------------
// Per-instance LittleFS for app data on flash. Each FS_LITTLEFS object owns its
// own lfs mount (LfsState below, pointed to by _state), so the web app on the
// `spiffs` partition (0x26C000) and the user-data partition (0x323000) can be
// mounted simultaneously as two separate FS_LITTLEFS objects.
//
// This filesystem is INDEPENDENT of the Tuya SDK's tal_kv/tal_fs lfs (the global
// `tal_lfs_get()` mounted at the UF region inside the `tuya` partition,
// 0x3b0000). Historic bug: FS_LITTLEFS used `tal_lfs_get()` (the SDK's single
// global lfs) AND re-mounted it at 0x26C000 while tal_kv mounted the same global
// lfs at UF; last-mount-won, so reads/writes were misrouted across the boot
// boundary and nothing persisted. Fixed by giving each instance its own lfs and
// doing all ops with lfs_* directly. tal_kv keeps its own lfs at UF, untouched.
//
// Each instance mounts by matching an esp_partition by start address (set in
// `partition.start_addr`). If lfs_mount fails (blank / corrupt partition) it is
// formatted then re-mounted, so a fresh or damaged partition auto-formats.
// ---------------------------------------------------------------------------

typedef struct {
    lfs_t                  lfs;
    struct lfs_config      cfg;
    const esp_partition_t *esp_part;   // matched by address; NULL -> tkl_flash path
    lfs_size_t             flash_addr;  // absolute base for the tkl_flash fallback
    bool                   mounted;
} LfsState;

static const esp_partition_t *find_part_by_addr(uint32_t addr)
{
    esp_partition_iterator_t it = esp_partition_find(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, NULL);
    const esp_partition_t *found = NULL;
    while (it) {
        const esp_partition_t *p = esp_partition_get(it);
        if (p && p->address == addr) {
            found = p;
            break;
        }
        it = esp_partition_next(it);
    }
    if (it)
        esp_partition_iterator_release(it);
    return found;
}

static int dev_read(const struct lfs_config *c, lfs_block_t block, lfs_off_t off, void *buffer, lfs_size_t size)
{
    LfsState *st = (LfsState*)c->context;
    if (st->esp_part) {
        esp_err_t err = esp_partition_read(st->esp_part, c->block_size * block + off, buffer, size);
        return err == ESP_OK ? LFS_ERR_OK : LFS_ERR_IO;
    }
    OPERATE_RET ret = tkl_flash_read(st->flash_addr + c->block_size * block + off, (uint8_t*)buffer, size);
    return (OPRT_OK == ret) ? LFS_ERR_OK : LFS_ERR_IO;
}

static int dev_prog(const struct lfs_config *c, lfs_block_t block, lfs_off_t off, const void *buffer, lfs_size_t size)
{
    LfsState *st = (LfsState*)c->context;
    if (st->esp_part) {
        esp_err_t err = esp_partition_write(st->esp_part, c->block_size * block + off, buffer, size);
        return err == ESP_OK ? LFS_ERR_OK : LFS_ERR_IO;
    }
    OPERATE_RET ret = tkl_flash_write(st->flash_addr + c->block_size * block + off, (uint8_t*)buffer, size);
    return (OPRT_OK == ret) ? LFS_ERR_OK : LFS_ERR_IO;
}

static int dev_erase(const struct lfs_config *c, lfs_block_t block)
{
    LfsState *st = (LfsState*)c->context;
    if (st->esp_part) {
        esp_err_t err = esp_partition_erase_range(st->esp_part, c->block_size * block, c->block_size);
        return err == ESP_OK ? LFS_ERR_OK : LFS_ERR_IO;
    }
    OPERATE_RET ret = tkl_flash_erase(st->flash_addr + c->block_size * block, c->block_size);
    return (OPRT_OK == ret) ? LFS_ERR_OK : LFS_ERR_IO;
}

static int dev_sync(const struct lfs_config *c)
{
    return LFS_ERR_OK;
}

// Mount `partition` into `st`. Returns 0 on success (formats on first/corrupt).
static int mount_state(LfsState *st, TUYA_FLASH_PARTITION_T partition)
{
    if (st->mounted)
        return 0;

    st->flash_addr = partition.start_addr;
    st->esp_part   = find_part_by_addr(partition.start_addr);

    memset(&st->cfg, 0, sizeof(st->cfg));
    st->cfg.context        = st;
    st->cfg.read           = dev_read;
    st->cfg.prog           = dev_prog;
    st->cfg.erase          = dev_erase;
    st->cfg.sync           = dev_sync;
    st->cfg.read_size      = st->esp_part ? 256 : partition.block_size;
    st->cfg.prog_size      = st->esp_part ? 256 : partition.block_size;
    st->cfg.cache_size     = st->esp_part ? 256 : partition.block_size;
    st->cfg.block_size     = partition.block_size;
    st->cfg.block_count    = partition.size / partition.block_size;
    st->cfg.lookahead_size = st->cfg.block_count / 8 + (8 - (st->cfg.block_count / 8));
    st->cfg.block_cycles   = 500;

    Serial.print("LittleFS(app) mount @0x");
    Serial.print(st->flash_addr, HEX);
    Serial.print(" blocks=");
    Serial.println(st->cfg.block_count);

    int err = lfs_mount(&st->lfs, &st->cfg);
    if (err < 0) {
        Serial.print("LittleFS(app) mount err ");
        Serial.print(err);
        Serial.println(", formatting...");
        lfs_format(&st->lfs, &st->cfg);
        err = lfs_mount(&st->lfs, &st->cfg);
        if (err < 0) {
            Serial.print("LittleFS(app) remount err ");
            Serial.println(err);
            return err;
        }
    }
    st->mounted = true;
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
    // _state is allocated lazily in begin(): this ctor may run during C++ static
    // init, before the Tuya heap/allocator is ready, so don't tal_malloc here.
    ismounted = false;
    _state = nullptr;
}

FS_LITTLEFS::~FS_LITTLEFS()
{
    if (_state) {
        tal_free(_state);
        _state = nullptr;
    }
}

bool FS_LITTLEFS::begin(){
    if (!_state) {
        _state = tal_malloc(sizeof(LfsState));
        if (_state)
            memset(_state, 0, sizeof(LfsState));
    }
    LfsState *st = (LfsState*)_state;
    if (!st) return false;
    if (this->partition.start_addr) {
        ismounted = mount_state(st, this->partition) >= 0;
    } else {
        TUYA_FLASH_BASE_INFO_T info;
        tkl_flash_get_one_type_info(TUYA_FLASH_TYPE_UF, &info);
        ismounted = mount_state(st, info.partition[0]) >= 0;
    }
    return ismounted;
}

bool FS_LITTLEFS::begin(TUYA_FLASH_PARTITION_T partition){
    this->partition = partition;
    return begin();
}

static int createDirRecursive(lfs_t *lfs, const char *path) {
    int ret = lfs_mkdir(lfs, path);
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
            int result = createDirRecursive(lfs, parentPath);
            tal_free(parentPath);
            if (result != 0)
                return result;
            ret = lfs_mkdir(lfs, path);
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
    return createDirRecursive(&((LfsState*)_state)->lfs, path);
}

int FS_LITTLEFS::remove(const char *path)
{
    if(!ismounted)
        return -1;
    return lfs_remove(&((LfsState*)_state)->lfs, path);
}

int FS_LITTLEFS::exist(const char *path)
{
    if(!ismounted)
        return -1;
    struct lfs_info info;
    return (lfs_stat(&((LfsState*)_state)->lfs, path, &info) >= 0) ? 1 : 0;
}

int FS_LITTLEFS::rename(const char *pathFrom,const char *pathTo)
{
    if(!ismounted)
        return -1;
    return lfs_rename(&((LfsState*)_state)->lfs, pathFrom, pathTo);
}

TUYA_DIR FS_LITTLEFS::openDir(const char *path)
{
    if(!ismounted)
        return NULL;
    app_dir_t *h = (app_dir_t*)tal_malloc(sizeof(app_dir_t));
    if (!h)
        return NULL;
    memset(h, 0, sizeof(app_dir_t));
    if (lfs_dir_open(&((LfsState*)_state)->lfs, &h->dir, path) < 0) {
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
    int ret = lfs_dir_close(&((LfsState*)_state)->lfs, &h->dir);
    tal_free(h);
    return ret;
}

TUYA_FILEINFO FS_LITTLEFS::readDir(TUYA_DIR dir)
{
    if(!ismounted || !dir)
        return NULL;
    app_dir_t *h = (app_dir_t*)dir;
    int ret = lfs_dir_read(&((LfsState*)_state)->lfs, &h->dir, &h->info);
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
    if (lfs_stat(&((LfsState*)_state)->lfs, path, &info) < 0)
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
        if (!begin())
            return NULL;
    }
    lfs_file_t *f = (lfs_file_t*)tal_malloc(sizeof(lfs_file_t));
    if (!f)
        return NULL;
    memset(f, 0, sizeof(lfs_file_t));
    if (lfs_file_open(&((LfsState*)_state)->lfs, f, path, lfs_flags_from_mode(mode)) < 0) {
        tal_free(f);
        return NULL;
    }
    return (TUYA_FILE)f;
}

int FS_LITTLEFS::close(TUYA_FILE fd)
{
    if(!ismounted||!fd)
        return -1;
    int ret = lfs_file_close(&((LfsState*)_state)->lfs, (lfs_file_t*)fd);
    tal_free(fd);
    return ret;
}

char FS_LITTLEFS:: read(TUYA_FILE fd)
{
    if(!ismounted||!fd)
        return '\0';
    char c = '\0';
    if (lfs_file_read(&((LfsState*)_state)->lfs, (lfs_file_t*)fd, &c, 1) != 1)
        return '\0';
    return c;
}

int FS_LITTLEFS::read(const char *buf,int size,TUYA_FILE fd)
{
    if(!ismounted||!fd ||!buf||!size)
        return -1;
    return lfs_file_read(&((LfsState*)_state)->lfs, (lfs_file_t*)fd, (void*)buf, size);
}

int FS_LITTLEFS::readtillN(char *buf, int size,TUYA_FILE fd)
{
    if(!ismounted||!fd ||!buf||!size)
        return -1;
    lfs_t *lfs = &((LfsState*)_state)->lfs;
    int i = 0;
    char c;
    while (i < size - 1) {
        int r = lfs_file_read(lfs, (lfs_file_t*)fd, &c, 1);
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
    return lfs_file_write(&((LfsState*)_state)->lfs, (lfs_file_t*)fd, (void*)buf, size);
}

void FS_LITTLEFS::flush(TUYA_FILE fd)
{
    if(!ismounted||!fd)
        return;
    lfs_file_sync(&((LfsState*)_state)->lfs, (lfs_file_t*)fd);
}

int FS_LITTLEFS::feof(TUYA_FILE fd)
{
    if(!ismounted||!fd)
        return -1;
    lfs_t *lfs = &((LfsState*)_state)->lfs;
    lfs_file_t *f = (lfs_file_t*)fd;
    lfs_soff_t pos = lfs_file_tell(lfs, f);
    lfs_soff_t sz  = lfs_file_size(lfs, f);
    return (pos >= sz) ? 1 : 0;
}

int FS_LITTLEFS::lseek(TUYA_FILE fd,int offs, int whence)
{
    if(!ismounted||!fd)
        return -1;
    int lfs_whence = LFS_SEEK_SET;
    if (whence == SEEK_CUR) lfs_whence = LFS_SEEK_CUR;
    else if (whence == SEEK_END) lfs_whence = LFS_SEEK_END;
    return lfs_file_seek(&((LfsState*)_state)->lfs, (lfs_file_t*)fd, offs, lfs_whence);
}

int FS_LITTLEFS::position(TUYA_FILE fd)
{
    if(!ismounted||!fd)
        return -1;
    return lfs_file_tell(&((LfsState*)_state)->lfs, (lfs_file_t*)fd);
}

int FS_LITTLEFS::filesize(const char *filepath)
{
    if(!ismounted)
        return -1;
    struct lfs_info info;
    if (lfs_stat(&((LfsState*)_state)->lfs, filepath, &info) < 0)
        return -1;
    return info.size;
}
