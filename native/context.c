/* In-process Node N-API binding: no per-call CLI, socket or JSON to the kernel. */
#include <node_api.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include "ioctl.h"

static int device = -1;
static int dev(void) {
    const char *path = getenv("PI_NODROP_IOCTL_PATH");
    if (!path || !*path) path = NOD_IOCTL_PATH;
    if (device < 0) device = open(path, O_RDWR | O_CLOEXEC);
    return device;
}
static napi_value fail(napi_env env, const char *operation) {
    char msg[256];
    snprintf(msg, sizeof(msg), "%s: %s", operation, strerror(errno));
    napi_throw_error(env, NULL, msg);
    return NULL;
}
static napi_value set_context(napi_env env, napi_callback_info info) {
    size_t argc = 2;
    napi_value argv[2], value;
    struct nod_audit_context ctx = {0};
    bool lossless;
    napi_get_cb_info(env, info, &argc, argv, NULL, NULL);
    if (argc != 2 || napi_get_value_bigint_uint64(env, argv[0], &ctx.call_ref, &lossless) != napi_ok ||
        !lossless || napi_get_value_uint32(env, argv[1], &ctx.policy_id) != napi_ok) {
        napi_throw_type_error(env, NULL, "setContext requires a uint64 BigInt and policy integer");
        return NULL;
    }
    if (dev() < 0 || ioctl(device, NOD_IOCTL_SET_AUDIT_CONTEXT, &ctx) < 0)
        return fail(env, "set NoDrop context");
    napi_get_undefined(env, &value);
    return value;
}
static napi_value get_context(napi_env env, napi_callback_info info) {
    struct nod_audit_context ctx = {0};
    napi_value result, ref, policy;
    (void)info;
    if (dev() < 0 || ioctl(device, NOD_IOCTL_GET_AUDIT_CONTEXT, &ctx) < 0)
        return fail(env, "get NoDrop context");
    napi_create_object(env, &result);
    napi_create_bigint_uint64(env, ctx.call_ref, &ref);
    napi_create_uint32(env, ctx.policy_id, &policy);
    napi_set_named_property(env, result, "callRef", ref);
    napi_set_named_property(env, result, "policyId", policy);
    return result;
}
struct flush_work { napi_async_work work; napi_deferred deferred; int error; };
static void flush_execute(napi_env env, void *data) {
    struct flush_work *work = data;
    (void)env;
    if (ioctl(device, NOD_IOCTL_FLUSH_AUDIT) < 0) work->error = errno;
}
static void flush_complete(napi_env env, napi_status status, void *data) {
    struct flush_work *work = data;
    napi_value result;
    if (status != napi_ok && !work->error) work->error = ECANCELED;
    if (ioctl(device, NOD_IOCTL_FLUSH_AUDIT) < 0 && !work->error) work->error = errno;
    if (work->error) {
        napi_value message;
        napi_create_string_utf8(env, strerror(work->error), NAPI_AUTO_LENGTH, &message);
        napi_create_error(env, NULL, message, &result);
        napi_reject_deferred(env, work->deferred, result);
    } else {
        napi_get_undefined(env, &result);
        napi_resolve_deferred(env, work->deferred, result);
    }
    napi_delete_async_work(env, work->work);
    free(work);
}
static napi_value flush(napi_env env, napi_callback_info info) {
    napi_value promise, resource;
    struct flush_work *work;
    (void)info;
    if (dev() < 0) return fail(env, "open NoDrop");
    work = calloc(1, sizeof(*work));
    if (!work) { errno = ENOMEM; return fail(env, "allocate flush"); }
    napi_create_promise(env, &work->deferred, &promise);
    napi_create_string_utf8(env, "nodropFlush", NAPI_AUTO_LENGTH, &resource);
    napi_create_async_work(env, NULL, resource, flush_execute, flush_complete, work, &work->work);
    napi_queue_async_work(env, work->work);
    return promise;
}
static napi_value init(napi_env env, napi_value exports) {
    napi_property_descriptor properties[] = {
        {"setContext", NULL, set_context, NULL, NULL, NULL, napi_default, NULL},
        {"flush", NULL, flush, NULL, NULL, NULL, napi_default, NULL},
        {"getContext", NULL, get_context, NULL, NULL, NULL, napi_default, NULL},
    };
    napi_define_properties(env, exports, 3, properties);
    return exports;
}
NAPI_MODULE(NODE_GYP_MODULE_NAME, init)
