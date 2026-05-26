---
name: feedback_report_endpoint_responses
description: Always report full endpoint responses during testing, especially login_required and captcha prompts.
metadata:
  type: feedback
---

When testing download endpoints, always read and report the complete response to the user — including login_required, captcha prompts, user_prompt fields, and any required action notifications. Do not silently move on if a download returns an actionable status. The user needs to see these responses as part of the testing process.

**Why:** User said "Even when testing I should receive all notifications that the endpoint sends back, especially for required actions -- that is a part of the testing process."

**How to apply:** After any download test (download_paper, download_ebsco_paper, download_papers, etc.), always print the full JSON response to the user. If status is login_required, captcha, or any non-success state, call it out explicitly and quote the user_prompt field so the user knows what action is needed.
