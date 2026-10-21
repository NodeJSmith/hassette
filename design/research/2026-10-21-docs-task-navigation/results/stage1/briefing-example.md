You're a Python developer who is new to Hassette, a framework for writing Home Assistant automations in
Python. You have a running Home Assistant instance and you've finished Hassette's Quickstart, so you have a small
app running. You don't know Hassette beyond that.

Here is what you want to know:

> I run Hassette in Docker and my app needs the apprise Python package, which isn't in the image. How do I get it installed in the container?

Find the answer in the Hassette documentation. The documentation is only available through this command-line
tool, which works like a browser for the docs site. Use it the way a person uses the site: look at the sidebar,
search, open pages, follow links.

- Show the sidebar:     cd /home/jessica/source/hassette/.claude/worktrees/3148 && uv run --with beautifulsoup4 python /tmp/claude-1000/-home-jessica-source-hassette--claude-worktrees-3148/5d0b0fd8-d6d7-40c6-9346-08b24e65b789/scratchpad/nav-queue/docs.py --site /tmp/claude-1000/-home-jessica-source-hassette--claude-worktrees-3148/5d0b0fd8-d6d7-40c6-9346-08b24e65b789/scratchpad/nav-queue/site-copy --trace /tmp/claude-1000/-home-jessica-source-hassette--claude-worktrees-3148/5d0b0fd8-d6d7-40c6-9346-08b24e65b789/scratchpad/nav-queue/traces/n01.jsonl nav
- Search the docs:      cd /home/jessica/source/hassette/.claude/worktrees/3148 && uv run --with beautifulsoup4 python /tmp/claude-1000/-home-jessica-source-hassette--claude-worktrees-3148/5d0b0fd8-d6d7-40c6-9346-08b24e65b789/scratchpad/nav-queue/docs.py --site /tmp/claude-1000/-home-jessica-source-hassette--claude-worktrees-3148/5d0b0fd8-d6d7-40c6-9346-08b24e65b789/scratchpad/nav-queue/site-copy --trace /tmp/claude-1000/-home-jessica-source-hassette--claude-worktrees-3148/5d0b0fd8-d6d7-40c6-9346-08b24e65b789/scratchpad/nav-queue/traces/n01.jsonl search "<words>"
- Open a page:          cd /home/jessica/source/hassette/.claude/worktrees/3148 && uv run --with beautifulsoup4 python /tmp/claude-1000/-home-jessica-source-hassette--claude-worktrees-3148/5d0b0fd8-d6d7-40c6-9346-08b24e65b789/scratchpad/nav-queue/docs.py --site /tmp/claude-1000/-home-jessica-source-hassette--claude-worktrees-3148/5d0b0fd8-d6d7-40c6-9346-08b24e65b789/scratchpad/nav-queue/site-copy --trace /tmp/claude-1000/-home-jessica-source-hassette--claude-worktrees-3148/5d0b0fd8-d6d7-40c6-9346-08b24e65b789/scratchpad/nav-queue/traces/n01.jsonl open <page path, as shown by nav, search or a link>

Don't read files in the repository or use any other source; the tool is your only window onto the docs. Stop as
soon as you are confident you have the answer, or when you conclude the docs don't cover it.

When you're done, use the Write tool to save a JSON object (only the JSON) to /tmp/claude-1000/-home-jessica-source-hassette--claude-worktrees-3148/5d0b0fd8-d6d7-40c6-9346-08b24e65b789/scratchpad/nav-queue/out/n01.json:

{"answer": "<what to do, concretely: the call, setting, or command and its key arguments>",
  "confidence": "high | medium | low",
  "found_on": ["<page paths where you found it>"],
  "gave_up": false}

Set "gave_up" to true, and say what you looked for in "answer", if the docs don't answer the question.
Then reply with only the word "done".
