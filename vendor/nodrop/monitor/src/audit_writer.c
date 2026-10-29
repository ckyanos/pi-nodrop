/* Producer-local audit output policy. Counts deliberately retain only the
 * event-type histogram; raw mode retains the original syscall arguments. */
#include <stdio.h>
#include <inttypes.h>
#include <string.h>
#include <unistd.h>
#include <sys/syscall.h>
#include "audit_writer.h"
#include "config.h"
#include "ioctl.h"

struct count_slot {
    uint64_t call_ref, count, first_ns, last_ns;
    uint32_t type, tid, tgid;
};
static struct count_slot slots[256];
static unsigned int used;

void nod_audit_output_flush(void)
{
    char path[180];
    FILE *out;
    unsigned int i;
    if (!used) return;
    snprintf(path, sizeof(path), CONFIG_STORE_PATH "/%ld.counts.jsonl", syscall(SYS_gettid));
    out = fopen(path, "a");
    if (!out) { perror("pi-nodrop count output"); return; }
    for (i = 0; i < used; i++) {
        struct count_slot *s = &slots[i];
        fprintf(out, "{\"call_ref\":\"%016" PRIx64 "\",\"policy_id\":2,"
                "\"type\":%u,\"name\":\"%s\",\"count\":%" PRIu64 ","
                "\"tid\":%u,\"tgid\":%u,\"first_ns\":%" PRIu64 ",\"last_ns\":%" PRIu64 "}\n",
                s->call_ref, s->type, g_event_info[s->type].name, s->count,
                s->tid, s->tgid, s->first_ns, s->last_ns);
    }
    if (fclose(out)) { perror("pi-nodrop count close"); return; }
    used = 0;
}

int nod_audit_output(const struct nod_event_hdr *hdr)
{
    unsigned int i;
    struct count_slot *s;
    if (hdr->policy_id != NOD_AUDIT_COUNTS) return 1;
    if (hdr->type >= NODE_EVENT_MAX) return 1;
    for (i = 0; i < used; i++)
        if (slots[i].call_ref == hdr->call_ref && slots[i].type == hdr->type) break;
    if (i == used) {
        if (used == 256) {
            nod_audit_output_flush();
            if (used == 256) return 1; /* output failed: preserve raw event */
            i = 0;
        }
        s = &slots[i];
        memset(s, 0, sizeof(*s));
        s->call_ref = hdr->call_ref;
        s->type = hdr->type;
        s->tid = hdr->tid;
        s->tgid = hdr->tgid;
        s->first_ns = hdr->ts;
        used++;
    }
    s = &slots[i];
    s->count++;
    s->last_ns = hdr->ts;
    return 0;
}
