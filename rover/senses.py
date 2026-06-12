from __future__ import annotations

import argparse
import json
import random
import time
import urllib.request


def post_event(base: str, payload: dict) -> None:
    req = urllib.request.Request(base.rstrip('/') + '/events', data=json.dumps(payload).encode(), method='POST', headers={'content-type': 'application/json'})
    with urllib.request.urlopen(req, timeout=5) as r:
        r.read()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Cleo Rover senses daemon stub')
    parser.add_argument('--base', default='http://127.0.0.1:8099')
    parser.add_argument('--interval', type=float, default=10.0)
    parser.add_argument('--simulate', action='store_true', help='Emit low-rate simulated sound/motion events')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args(argv)
    while True:
        if args.simulate:
            kind = random.choice(['sound', 'motion', 'idle_tick'])
            post_event(args.base, {'kind': kind, 'source': 'senses_stub', 'label': f'sim {kind}', 'value': 0.35})
            print(json.dumps({'ok': True, 'emitted': kind}))
        if args.once:
            return 0
        time.sleep(args.interval)

if __name__ == '__main__':
    raise SystemExit(main())
