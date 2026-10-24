"""Read an agent run log into one neutral list of actions.

Claude: `claude -p ... --output-format stream-json --verbose` (one JSON object per line).
Codex: `codex exec --json` (one JSON event per line). The Codex event names below are
taken from its documented JSONL stream and are not yet verified on a real run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

# Tool names that start another agent or session.
AGENT_TOOLS = {'Agent', 'Task', 'start_session', 'mcp__ccd_session__start_session', 'spawn_agent'}
FILE_TOOLS = {'Edit', 'Write', 'MultiEdit', 'NotebookEdit'}
SHELL_TOOLS = {'Bash', 'PowerShell', 'shell'}


@dataclass
class Action:
    name: str
    input: dict = field(default_factory=dict)
    depth: int = 0              # 0 = the main agent, 1 = inside a launched agent, ...
    paths: list = field(default_factory=list)
    command: str = ''

    @property
    def launches_agent(self):
        return self.name in AGENT_TOOLS or self.name.endswith('start_session') or 'spawn' in self.name.lower()

    @property
    def brief(self):
        """Assignment text given to a launched agent or session."""
        return str(self.input.get('prompt') or self.input.get('message') or self.input.get('task') or '')


@dataclass
class Transcript:
    actions: list = field(default_factory=list)
    texts: list = field(default_factory=list)   # the main agent's text messages, in order
    final_text: str = ''
    format: str = ''

    def agent_launches(self):
        return [a for a in self.actions if a.launches_agent]


def _lines(path):
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _tool_paths(data):
    return [str(data[k]) for k in ('file_path', 'notebook_path', 'path') if data.get(k)]


def parse_claude(path):
    run = Transcript(format='claude')
    depth_of_tool = {}
    for event in _lines(path):
        if event.get('type') == 'result':
            run.final_text = str(event.get('result') or run.final_text)
            continue
        if event.get('type') != 'assistant':
            continue
        parent = event.get('parent_tool_use_id')
        depth = 0 if not parent else depth_of_tool.get(parent, 0) + 1
        for block in (event.get('message') or {}).get('content') or []:
            if block.get('type') == 'text' and depth == 0:
                run.texts.append(block.get('text', ''))
            elif block.get('type') == 'tool_use':
                data = block.get('input') or {}
                name = block.get('name', '')
                depth_of_tool[block.get('id')] = depth
                run.actions.append(Action(name, data, depth, _tool_paths(data),
                                          str(data.get('command', '')) if name in SHELL_TOOLS else ''))
    if not run.final_text and run.texts:
        run.final_text = run.texts[-1]
    return run


def parse_codex(path):
    run = Transcript(format='codex')
    for event in _lines(path):
        if event.get('type') != 'item.completed':
            continue
        item = event.get('item') or {}
        kind = item.get('type', '')
        if kind == 'agent_message':
            run.texts.append(str(item.get('text', '')))
        elif kind == 'command_execution':
            run.actions.append(Action('shell', item, 0, [], str(item.get('command', ''))))
        elif kind == 'file_change':
            paths = [str(c.get('path', '')) for c in item.get('changes') or []]
            run.actions.append(Action('apply_patch', item, 0, paths))
        elif kind == 'mcp_tool_call':
            name = 'mcp__%s__%s' % (item.get('server', ''), item.get('tool', ''))
            run.actions.append(Action(name, item.get('arguments') or {}, 0))
        elif kind not in ('reasoning', 'todo_list', 'error', 'web_search'):
            # Unknown item types (for example native subagent calls) are kept by name.
            run.actions.append(Action(kind, item, 0))
    if run.texts:
        run.final_text = run.texts[-1]
    return run


def parse(path, version):
    return parse_claude(path) if version == 'claude' else parse_codex(path)
