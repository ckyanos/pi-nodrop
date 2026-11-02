/* pi-nodrop prototype: explicit executor context, snapshotted at fork.
 * Original NoDrop licensing applies to this derivative kernel component. */
#include <linux/hashtable.h>
#include <linux/slab.h>
#include <linux/pid.h>
#include <linux/sched/signal.h>
#include <linux/rwlock.h>
#include <linux/moduleparam.h>
#include "nodrop.h"

unsigned int nod_audit_uid = 1000;
module_param(nod_audit_uid, uint, 0444);
MODULE_PARM_DESC(nod_audit_uid, "Host UID eligible for explicit tool-call audit contexts");

struct audit_entry {
    struct hlist_node node;
    struct pid *group; /* reference prevents numeric PID reuse aliasing */
    struct nod_audit_context context;
};
static DEFINE_HASHTABLE(audit_contexts, 10);
static DEFINE_RWLOCK(audit_lock);
static unsigned int entry_count;
#define AUDIT_MAX_GROUPS 4096

bool nod_audit_get(struct task_struct *task, struct nod_audit_context *context)
{
    struct audit_entry *entry;
    struct pid *group = task_tgid(task);
    unsigned long flags;
    bool found = false;
    memset(context, 0, sizeof(*context));
    read_lock_irqsave(&audit_lock, flags);
    hash_for_each_possible(audit_contexts, entry, node, (unsigned long)group) {
        if (entry->group == group) {
            *context = entry->context;
            found = context->call_ref != 0;
            break;
        }
    }
    read_unlock_irqrestore(&audit_lock, flags);
    return found;
}

int nod_audit_set(struct task_struct *task, const struct nod_audit_context *context)
{
    struct pid *group = task_tgid(task);
    struct audit_entry *entry, *fresh = NULL, *removed = NULL;
    unsigned long flags;
    int ret = 0;
    if (context->reserved || (context->call_ref && context->policy_id != NOD_AUDIT_RAW &&
                             context->policy_id != NOD_AUDIT_COUNTS))
        return -EINVAL;
    if (context->call_ref) {
        fresh = kzalloc(sizeof(*fresh), GFP_ATOMIC);
        if (!fresh) return -ENOMEM;
        fresh->group = get_pid(group);
        fresh->context = *context;
    }
    write_lock_irqsave(&audit_lock, flags);
    hash_for_each_possible(audit_contexts, entry, node, (unsigned long)group) {
        if (entry->group != group) continue;
        if (context->call_ref) entry->context = *context;
        else {
            hash_del(&entry->node);
            entry_count--;
            removed = entry;
        }
        goto done;
    }
    if (fresh) {
        if (entry_count >= AUDIT_MAX_GROUPS) ret = -ENOSPC;
        else {
            hash_add(audit_contexts, &fresh->node, (unsigned long)group);
            entry_count++;
            fresh = NULL;
        }
    }
done:
    write_unlock_irqrestore(&audit_lock, flags);
    if (fresh) { put_pid(fresh->group); kfree(fresh); }
    if (removed) { put_pid(removed->group); kfree(removed); }
    return ret;
}

void nod_audit_fork(struct task_struct *parent, struct task_struct *child)
{
    struct nod_audit_context context;
    if (task_tgid(parent) == task_tgid(child)) return; /* same process */
    if (nod_audit_get(parent, &context) && nod_audit_set(child, &context))
        pr_err("pi-nodrop: context inheritance failed child=%d\n", child->pid);
}

void nod_audit_exit(struct task_struct *task)
{
    struct nod_audit_context empty = {};
    if (atomic_read(&task->signal->live) == 0)
        nod_audit_set(task, &empty);
}

void nod_audit_destroy(void)
{
    struct audit_entry *entry;
    struct hlist_node *tmp;
    unsigned int bucket;
    /* Called only after tracepoint unregistration and synchronization. */
    hash_for_each_safe(audit_contexts, bucket, tmp, entry, node) {
        hash_del(&entry->node);
        put_pid(entry->group);
        kfree(entry);
    }
    entry_count = 0;
}
