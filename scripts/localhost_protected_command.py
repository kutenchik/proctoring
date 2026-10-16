"""Bounded Stage 4C coordinator using only the existing authenticated teacher API."""
import argparse
import json
from pathlib import Path
import time
from uuid import uuid4

import httpx

RUN = Path(__file__).resolve().parents[1] / 'build/localhost-protected/manual-01'
PAYLOADS = {
    'warning': {'text': 'Controlled protected-localhost check: timer should continue.'},
    'pause': {'reason': 'Agreed Stage 4C teacher pause check'},
    'resume': {'reason': 'Clear only the agreed teacher pause'},
    'add_time': {'seconds': 60, 'reason': 'Agreed Stage 4C extension check'},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=PAYLOADS)
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--operator-approved', action='store_true')
    args = parser.parse_args()
    if not args.operator_approved:
        parser.error('Explicit operator readiness for the bounded sequence is required')
    if len(args.attempt) != 32 or any(c not in '0123456789abcdef' for c in args.attempt):
        parser.error('Expected exact attempt ID')
    credentials = json.loads((RUN / 'operator-private.json').read_text())
    exam = json.loads((RUN / 'exams.json').read_text())['A-normal']
    # Claim once before sending; a lost response must never cause an accidental repeat.
    record = RUN / f'command-{args.action}.json'
    with httpx.Client(base_url='http://127.0.0.1:8000', trust_env=False,
                      timeout=3, headers={'Origin': 'http://127.0.0.1:5174'}) as client:
        response = client.post('/api/v1/auth/login', json={k: credentials[k] for k in ('email', 'password')})
        response.raise_for_status()
        client.headers['X-CSRF-Token'] = response.json()['csrf_token']
        response = client.get(f'/api/v1/exams/{exam["id"]}/attempts')
        response.raise_for_status()
        if args.attempt not in {a['attempt_id'] if 'attempt_id' in a else a['id'] for a in response.json()['items']}:
            raise ValueError('Attempt is not part of the prepared normal test exam')
        request = {'request_id': uuid4().hex, 'type': args.action, 'payload': PAYLOADS[args.action]}
        with record.open('x') as stream:
            json.dump({'attempt_id': args.attempt, 'request': request, 'status': 'not_yet_confirmed'}, stream)
        response = client.post(f'/api/v1/attempts/{args.attempt}/commands', json=request)
        response.raise_for_status()
        command = response.json()['command']
        deadline = time.monotonic() + 12
        while command['status'] in ('sent', 'delivered') and time.monotonic() < deadline:
            time.sleep(.25)
            response = client.get(f'/api/v1/attempts/{args.attempt}/commands')
            response.raise_for_status()
            command = next(c for c in response.json()['items'] if c['command_id'] == command['command_id'])
        record.write_text(json.dumps(command, indent=2))
        print(json.dumps(command))
        if command['status'] != 'applied':
            raise SystemExit('Command not confirmed applied; do not replay automatically')


if __name__ == '__main__':
    main()
