#include <stdio.h>
#include <unistd.h>
#include <inttypes.h>
#include <sys/time.h>
#include <sys/syscall.h>
#include <sys/stat.h>

#include "config.h"

#include "common.h"
#include "lua_runtime.h"
#include "record_writer.h"
#include "audit_writer.h"


static struct timeval tv;
static unsigned int tid;

struct record_writer rw = {
    .mode = -1,
};

static const char *__print_format[PT_UINT64 + 1][PF_OCT + 1] = {
    [PT_NONE] = {"", "", "", "", ""},                                         /*empty*/
    [PT_INT8] = {"", "%" PRId8, "0x%" PRIx8, "%010" PRId8, "0%" PRIo8},       /*PT_INT8*/
    [PT_INT16] = {"", "%" PRId16, "0x%" PRIx16, "%010" PRId16, "0%" PRIo16},  /*PT_INT16*/
    [PT_INT32] = {"", "%" PRId32, "0x%" PRIx32, "%010" PRId32, "0%" PRIo32},  /*PT_INT32*/
    [PT_INT64] = {"", "%" PRId64, "0x%" PRIx64, "%010" PRId64, "0%" PRIo64},  /*PT_INT64*/
    [PT_UINT8] = {"", "%" PRIu8, "0x%" PRIx8, "%010" PRId8, "0%" PRIo8},      /*PT_UINT8*/
    [PT_UINT16] = {"", "%" PRIu16, "0x%" PRIx16, "%010" PRIu16, "0%" PRIo16}, /*PT_UINT16*/
    [PT_UINT32] = {"", "%" PRIu32, "0x%" PRIx32, "%010" PRIu32, "0%" PRIo32}, /*PT_UINT32*/
    [PT_UINT64] = {"", "%" PRIu64, "0x%" PRIx64, "%010" PRIu64, "0%" PRIo64}  /*PT_UINT64*/
};

static const char *
nod_param_fmt(int type, int fmt)
{
    if (type < 0 || type > PT_UINT64)
        return "%llu";
    if (fmt < 0 || fmt > PF_OCT)
        fmt = PF_DEC;
    return __print_format[type][fmt];
}



static int _parse(FILE *out, struct nod_event_hdr *hdr, char *buffer, void *__data)
{
    size_t i;
    const struct nod_event_info *info;
    const struct nod_param_info *param;
    uint16_t *args;
    char *data;

    if (hdr->type < 0 || hdr->type >= NODE_EVENT_MAX)
        return -1;

    info = &g_event_info[hdr->type];
    args = (uint16_t *)buffer;
    data = (char *)(args + info->nparams);

    fprintf(out, "%lu %u (%u): %s(", hdr->ts, hdr->tid, hdr->cpuid, info->name);

    for (i = 0; i < info->nparams; ++i)
    {
        param = &info->params[i];
        if (i > 0)
            fprintf(out, ", ");
        fprintf(out, "%s=", param->name);
        switch (param->type)
        {
        case PT_CHARBUF:
        case PT_FSPATH:
        case PT_FSRELPATH:
        case PT_BYTEBUF:
            fwrite(data, args[i], 1, out);
            break;

        case PT_FLAGS8:
        case PT_UINT8:
        case PT_SIGTYPE:
            fprintf(out, nod_param_fmt(PT_UINT8, param->fmt), *(uint8_t *)data);
            break;

        case PT_FLAGS16:
        case PT_UINT16:
        case PT_SYSCALLID:
            fprintf(out, nod_param_fmt(PT_UINT16, param->fmt), *(uint16_t *)data);
            break;

        case PT_FLAGS32:
        case PT_UINT32:
        case PT_MODE:
        case PT_UID:
        case PT_GID:
        case PT_SIGSET:
            fprintf(out, nod_param_fmt(PT_UINT32, param->fmt), *(uint32_t *)data);
            break;

        case PT_RELTIME:
        case PT_ABSTIME:
        case PT_UINT64:
            fprintf(out, nod_param_fmt(PT_UINT64, param->fmt), *(uint64_t *)data);
            break;

        case PT_INT8:
            fprintf(out, nod_param_fmt(PT_INT8, param->fmt), *(int8_t *)data);
            break;

        case PT_INT16:
            fprintf(out, nod_param_fmt(PT_INT16, param->fmt), *(int16_t *)data);
            break;

        case PT_INT32:
            fprintf(out, nod_param_fmt(PT_INT32, param->fmt), *(int32_t *)data);
            break;

        case PT_INT64:
        case PT_ERRNO:
        case PT_FD:
        case PT_PID:
            fprintf(out, nod_param_fmt(PT_INT64, param->fmt), *(int64_t *)data);
            break;

        default:
            fprintf(out, "<unknown>");
            break;
        }

        // move to the next argument
        data += args[i];
    }
    fprintf(out, ")\n");
    return 0;
}

void nod_monitor_init(int argc, char *argv[], char *env[])
{
    gettimeofday(&tv, NULL);
    tid = (unsigned int)syscall(SYS_gettid);
    set_record_path(tv, tid);
    set_log_path(tv, tid);
    lua_runtime_init();
}

int nod_monitor_main(char *buffer, struct nod_buffer_info *buffer_info, struct nod_lua_state *global_state, int record_flag, int is_last)
{
#if CONFIG_LINUX_VERSION_CODE >= KERNEL_VERSION(6, 0, 0)

    lua_run_script(global_state);

    char *ptr, *buffer_end;
    struct nod_event_hdr *hdr;
    struct lua_event evt;
    new_record_writer(&rw, record_flag);
    ptr = buffer;
    buffer_end = ptr + buffer_info->tail;
    while (ptr < buffer_end)
    {
        hdr = (struct nod_event_hdr *)ptr;

        if (hdr->len < sizeof(*hdr) ||
            (char *)hdr + hdr->len > buffer_end)
            break;

        buffer_info->n_solved_evts++;
        evt.raw = hdr;
        lua_on_event(&evt);
        if (nod_audit_output(hdr))
            write_record_writer(&rw, ptr);
        ptr += hdr->len;
    }

    if (is_last)
        lua_on_capture_end();

    nod_audit_output_flush();
    close_record_writer(&rw);
    buffer_info->nevents = buffer_info->tail = 0;

    return 0;
#else
    char *ptr, *buffer_end;
    struct nod_event_hdr *hdr;
    FILE *file;
    char log_path[160];

    (void) record_flag;

    lua_run_script(global_state);

    {
        static unsigned long window_seq;
        unsigned long seq = __sync_fetch_and_add(&window_seq, 1);

        snprintf(log_path, sizeof(log_path), CONFIG_STORE_PATH "/%u-%ld-%lu.buf",
                 tid, (long) (tv.tv_sec * 1000000L + tv.tv_usec), seq);
    }
    if (!(file = fopen(log_path, "wb")))
        return 0;

    ptr = buffer;
    buffer_end = ptr + buffer_info->tail;
    while (ptr < buffer_end) {
        hdr = (struct nod_event_hdr *) ptr;

        if (hdr->len < sizeof(*hdr) || (char *) hdr + hdr->len > buffer_end) {
            char msg[320];
            unsigned long *w = (unsigned long *) buffer;
            int n = snprintf(msg, sizeof(msg),
                             "[nodrop] bad window: off=%ld len=%u tail=%u nev=%llu solv=%llu "
                             "w=%lx,%lx,%lx,%lx bi=%p buf=%p\n",
                             (long) (ptr - buffer), hdr->len,
                             buffer_info->tail,
                             (unsigned long long) buffer_info->nevents,
                             (unsigned long long) buffer_info->n_solved_evts,
                             w[0], w[1], w[2], w[3],
                             (void *) buffer_info, (void *) buffer);
            if (n > 0)
                write(2, msg, n);
            {
                FILE *m = fopen("/proc/self/maps", "r");
                if (m) {
                    char line[256];
                    unsigned long want[2];
                    int found = 0;

                    want[0] = (unsigned long) buffer;
                    want[1] = (unsigned long) &buffer_info;
                    while (fgets(line, sizeof(line), m)) {
                        unsigned long lo = 0, hi = 0;
                        int k;

                        if (sscanf(line, "%lx-%lx", &lo, &hi) != 2)
                            continue;
                        for (k = 0; k < 2; k++) {
                            if (want[k] >= lo && want[k] < hi) {
                                write(2, k == 0 ? "[nodrop] buf map: " : "[nodrop] stk map: ",
                                      k == 0 ? 19 : 19);
                                write(2, line, strlen(line));
                                found++;
                                break;
                            }
                        }
                        if (found == 2)
                            break;
                    }
                    fclose(m);
                }
            }
            break;
        }

        buffer_info->n_solved_evts++;
        {
            struct lua_event evt;

            evt.raw = hdr;
            lua_on_event(&evt);
        }
        fwrite(ptr, hdr->len, 1, file);
        ptr += hdr->len;
    }

    if (is_last)
        lua_on_capture_end();

    fclose(file);
    buffer_info->nevents = buffer_info->tail = 0;
    return 0;
#endif
}
