---
name: feedback_stop_asking_permission
description: Never ask the user for permission before editing code — just make the change.
metadata:
  type: feedback
---

Just edit the code and run tests. Do not ask for permission before making code changes or performing testing operations. Make the change or run the test, then report what was done.

**Why:** User explicitly said "Stop asking me if its okay to edit code. Just edit it." and "When testing dont ask me if its okay to perform testing operations, just perform the test, Ive already given permission."

**How to apply:** Whenever a code fix or improvement is identified, apply it immediately. Whenever a test needs to be run, run it. Reserve confirmation only for destructive or irreversible actions (deleting files, force-pushing, dropping data).
