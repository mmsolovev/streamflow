"""Pipeline runtime layer: live collection / long-running processes.

Keep this package for code that runs during an active stream (or other continuous
runtime), e.g. polling Twitch, collecting events, writing incremental snapshots, etc.

One-shot jobs / CLI entrypoints were moved to `pipeline.orchestrator`.
"""


