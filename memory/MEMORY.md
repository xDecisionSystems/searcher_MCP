# Memory Index

- [Project repo URL](project_repo_url.md) — Repo is always https://github.com/xDecisionSystems/searcher, never prompt for it
- [Project architecture](project_architecture.md) — Four services in one LXC; searcher/browser_worker are open APIs; JWT only guards cdp_gateway (port 8020)
- [No permission prompts for code edits](feedback_stop_asking_permission.md) — Just edit the code, never ask for permission first
- [Report all endpoint responses during testing](feedback_report_endpoint_responses.md) — Always print full response including login_required/captcha prompts; user needs to see required actions
