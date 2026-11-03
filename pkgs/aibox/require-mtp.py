#!/usr/bin/env python3
"""Fail the pinned server's load if requested MTP was not initialized.

Upstream logs a warning and continues without speculation in this path. AI Box
profiles require MTP. Exact one-occurrence replacement rejects source drift.
"""
from pathlib import Path
import sys


def patch(source):
    path = Path(source) / "tools/server/server-context.cpp"
    text = path.read_text()
    anchor = "        for (int i = 0; i < params_base.n_parallel; i++) {\n            server_slot & slot = slots[i];"
    guard = '''        // AI Box: an explicitly requested MTP profile must never degrade silently.
        if (spec_mtp) {
            if (!spec) {
                SRV_ERR("%s", "AI Box requires active draft-mtp; refusing fallback\\n");
                return false;
            }
            const auto active = common_speculative_get_types(spec.get());
            if (std::find(active.begin(), active.end(), COMMON_SPECULATIVE_TYPE_DRAFT_MTP) == active.end()) {
                SRV_ERR("%s", "AI Box requires active draft-mtp; refusing fallback\\n");
                return false;
            }
        }

'''
    if text.count(anchor) != 1 or "AI Box requires active draft-mtp" in text:
        raise ValueError("Pinned MTP guard anchor changed; review source before building")
    path.write_text(text.replace(anchor, guard + anchor))


if __name__ == "__main__":
    patch(sys.argv[1])
