"""Build the actual inline button, bound to a saved event. Never creates a report."""

import sys as _cd5_sys
from pathlib import Path as _CD5Path
if str(_CD5Path(__file__).resolve().parent) not in _cd5_sys.path:
    _cd5_sys.path.insert(0, str(_CD5Path(__file__).resolve().parent))
try:
    from .cd5_config import config as cd5_config, memory_dir, memory_map
except ImportError:
    from cd5_config import config as cd5_config, memory_dir, memory_map

import argparse
import base64
import json
from pathlib import Path
import runpy


def build_fragment(root, event_id, icon):
    root = Path(root).resolve(strict=True)
    payload = runpy.run_path(str(Path(__file__).with_name('duet_attention_ui.py')))['card_payload'](root, event_id)
    template = Path(__file__).with_name('duet_attention_fragment.html').read_text(encoding='utf-8')
    # Encode rather than interpolate title/source text into markup or executable code.
    event_json = json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    data_uri = 'data:image/png;base64,' + base64.b64encode(Path(icon).read_bytes()).decode('ascii')
    fragment = template.replace('__ROOT_ID__', 'duet-attention-' + payload['event_id']).replace('__ICON_DATA_URI__', data_uri).replace('__EVENT_JSON__', event_json)
    output = memory_dir(root) / 'attention/cards' / (payload['event_id'] + '.html')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(fragment, encoding='utf-8')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--event-id', required=True)
    parser.add_argument('--icon', required=True)
    args = parser.parse_args()
    print(build_fragment(args.root, args.event_id, args.icon))
