"""Read-only canonical attention list, item view, and explicitly rebuilt HTML board."""
from __future__ import annotations

import sys as _cd5_sys
from pathlib import Path as _CD5Path
if str(_CD5Path(__file__).resolve().parent) not in _cd5_sys.path:
    _cd5_sys.path.insert(0, str(_CD5Path(__file__).resolve().parent))
try:
    from .cd5_config import config as cd5_config, memory_dir, memory_map
except ImportError:
    from cd5_config import config as cd5_config, memory_dir, memory_map


import argparse
import json
import re
import sys
from pathlib import Path

_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

try:
    from .project_memory import pending_attention, select
except ImportError:
    from project_memory import pending_attention, select

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")


def _checkpoint(root: Path) -> dict:
    path = memory_dir(root) / "CHECKPOINT.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("checkpoint is not an object")
        return {"owner": value.get("owner") or {}, "user_stop": value.get("user_stop") or {},
                "next_action": value.get("next_action") or {}, "blocker": value.get("blocker") or {}}
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {"diagnostic": f"CHECKPOINT unavailable; blocker state is unknown ({type(exc).__name__})"}


def _prompt(item: dict, owner: dict) -> str:
    return (f"[attention-explain:{item['id']}] Read the current canonical ATTENTION.jsonl record "
            f"for ID {item['id']} and verify it is still open before answering. Explain its exact "
            f"question in concise Russian using only the cited sources and current CHECKPOINT. "
            f"Current owner from CHECKPOINT: {owner.get('role', 'unknown')} "
            f"({owner.get('thread_id', 'unknown')}). The explanation or button click is not a "
            "decision, approval, consent, human gold, or authorization to run work. Do not resolve "
            "the question or change memory. First verify whether a cited user/system rule really "
            "requires a human answer. If not, identify it as an HQ decision and continue permitted work; "
            "do not ask the user to authorize an internal protocol, forecast or retry.")


def list_items(root: str | Path) -> dict:
    base = Path(root).resolve(strict=True)
    checkpoint = _checkpoint(base)
    owner = checkpoint.get("owner") or {}
    items = pending_attention(base)
    # A wait_user label or STOP does not make every unrelated question a human gate.
    for item in items:
        item["owner"] = {k: owner.get(k) for k in ("role", "thread_id", "configured_model") if owner.get(k)}
        item["request_prompt"] = _prompt(item, owner)
    diagnostic = checkpoint.get("diagnostic")
    required_question = checkpoint.get("blocker", {}).get("human_question")
    if isinstance(required_question, str) and required_question.strip():
        if not any(x["question"].strip() == required_question.strip() for x in items):
            diagnostic = "CHECKPOINT mentions a question without a matching attention item; HQ must inspect its actual source: " + required_question
    return {"items": items, "human_items": [x for x in items if x['requires_human']],
            "owner_actions": [x for x in items if not x['requires_human']],
            "diagnostic": diagnostic, "checkpoint_status": "unavailable" if checkpoint.get('diagnostic') else "read"}


def show_item(root: str | Path, item_id: str) -> dict:
    if not isinstance(item_id, str) or not SAFE_ID.fullmatch(item_id):
        raise ValueError("unsafe attention ID")
    result = list_items(root)
    for item in result["items"]:
        if item["id"] == item_id:
            return {**item, "diagnostic": result["diagnostic"]}
    # Distinguish a closed/stale ID from an unknown ID without displaying its payload.
    try:
        rows = select(root, "attention", [item_id], full=False, include_closed=True)
    except (ValueError, OSError) as exc:
        raise ValueError("unknown attention ID") from exc
    if not rows or rows[0].get("status") == "closed" or rows[0].get("kind") == "attention_archive_ref":
        raise ValueError("attention item is closed or archived")
    raise ValueError("attention item is not an open actionable question")


def render_board(data: dict) -> str:
    cards = []
    for item in data["items"]:
        # Use text nodes for every value from project memory; no record string enters markup.
        cards.append({k: item.get(k, "") for k in ("id", "status", "title", "question", "source_refs", "owner", "request_prompt")})
    encoded = json.dumps(cards, ensure_ascii=False, separators=(",", ":"))
    encoded = encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    diagnostic = data.get("diagnostic") or ""
    diagnostic_markup = ('<p id="diagnostic" role="status"></p>' if diagnostic else '')
    empty_markup = '<p id="empty">Нет отображаемых вопросов. Проверьте диагностику, если она указана.</p>'
    return f'''<!doctype html>
<html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Внимание штаба · CD5</title>
<style>
:root{{color-scheme:light dark}}body{{margin:0;padding:12px;background:transparent;color:inherit;font:16px/1.5 system-ui,sans-serif}}
main{{max-width:720px}}article{{display:grid;grid-template-columns:72px 1fr;gap:12px;padding:12px 0;border-bottom:1px solid #8886}}
.icon{{font-size:48px;line-height:1;text-align:center}}h2{{font-size:20px;line-height:1.3;margin:0 0 8px}}.question{{margin:0 0 10px;font-size:18px;font-weight:600}}
.meta{{margin:8px 0;font-size:13px;opacity:.8;overflow-wrap:anywhere}}button{{font:600 15px system-ui;padding:10px 14px;border:1px solid #b8770c;border-radius:8px;background:#eeb43f;color:#251b09;cursor:pointer}}
button:focus-visible{{outline:3px solid #e3a229;outline-offset:3px}}[hidden]{{display:none!important}}
@media(max-width:420px){{article{{grid-template-columns:48px 1fr;gap:8px}}.icon{{font-size:38px}}}}
</style><main><h1>Внимание штаба</h1>{diagnostic_markup}{empty_markup}<section id="items"></section>
<script type="application/json" id="attention-data">{encoded}</script>
<script>
(()=>{{const data=JSON.parse(document.getElementById('attention-data').textContent),host=document.getElementById('items');
const empty=document.getElementById('empty');empty.hidden=data.length>0;
const diagnostic={json.dumps(diagnostic, ensure_ascii=False).replace('<', chr(92)+'u003c').replace('>', chr(92)+'u003e')};const diag=document.getElementById('diagnostic');if(diag)diag.textContent=diagnostic;
for(const item of data){{const card=document.createElement('article'),icon=document.createElement('div'),body=document.createElement('div'),title=document.createElement('h2'),question=document.createElement('p'),meta=document.createElement('p'),button=document.createElement('button'),status=document.createElement('p');
icon.className='icon';icon.setAttribute('aria-hidden','true');icon.textContent='⚠️';title.textContent=item.title;question.className='question';question.textContent=item.question;
meta.className='meta';meta.textContent='Статус: '+item.status+' · Владелец: '+((item.owner&&item.owner.role)||'неизвестен')+' · Источники: '+((item.source_refs||[]).join(', ')||'не указаны');
button.type='button';button.textContent='Разъяснить вопрос';status.setAttribute('role','status');status.setAttribute('aria-live','polite');
button.addEventListener('click',async()=>{{button.disabled=true;status.textContent='Проверяю доступность отправки…';try{{if(typeof window.openai?.sendFollowUpMessage!=='function')throw new Error('Кнопка доступна только в интерактивном Codex-предпросмотре.');await window.openai.sendFollowUpMessage({{prompt:item.request_prompt,title:'Разъяснить: '+item.title}});status.textContent='Запрос отправлен. Это не ответ на вопрос и не решение.';}}catch(error){{status.textContent=String(error.message||error);button.disabled=false;}}}});
body.append(title,question,meta,button,status);card.append(icon,body);host.append(card);}}
}})();
</script></main></html>'''


def write_board(root: str | Path, output: str | Path) -> Path:
    target = Path(output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_board(list_items(root)), encoding="utf-8", newline="\n")
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    show = sub.add_parser("show"); show.add_argument("--id", required=True)
    render = sub.add_parser("render"); render.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        result = list_items(args.root) if args.command == "list" else show_item(args.root, args.id) if args.command == "show" else {"path": str(write_board(args.root, args.output))}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
