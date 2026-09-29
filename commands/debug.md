---
description: "Start precision diagnosis or show debug-agent status, evidence, acceptance and recovery; configure session reminders."
argument-hint: "[status|evidence|again|done-check|resume|on|off|help|问题描述]"
---

从宿主提供的 `CLAUDE_PLUGIN_ROOT`，或本文件 `commands/debug.md` 的真实父目录确定插件根目录。直接读取 `<插件根>/skills/debug-agent/SKILL.md`；普通问题直接推进，显式状态或恢复参数才读取命令路由。不调用同名 Skill 工具，避免路由递归。

本次用户参数：$ARGUMENTS
