#ifndef PI_NODROP_AUDIT_WRITER_H
#define PI_NODROP_AUDIT_WRITER_H
#include "events.h"
int nod_audit_output(const struct nod_event_hdr *hdr);
void nod_audit_output_flush(void);
#endif
