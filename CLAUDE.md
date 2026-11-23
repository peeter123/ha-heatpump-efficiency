# CLAUDE.md

@AGENTS.md

## Claude Code specifics

- The `openspec-*` skills (`/openspec-propose`, `/openspec-apply-change` and the others) are in `.claude/skills/`,
  copies of `.agents/skills/` that `openspec update` writes; start sessions in this folder so they load.
- Home Assistant MCP tools (`mcp__home-assistant__ha_*`) are deferred: load them with ToolSearch before calling.
  They reach the live installation; use them only for reads the user asked for, or for live steps with the user's
  go-ahead.
