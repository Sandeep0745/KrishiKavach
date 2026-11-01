"""Arm clear-to-danger weather locally; never calls the manual scenario-start endpoint."""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ghante_shared import config, http


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='reset the sandbox, arm weather, and verify 340 cases')
    parser.add_argument('--live', action='store_true', help='restore real Open-Meteo monitoring')
    args = parser.parse_args()
    if args.live:
        result = http.post_json(config.ORCH_URL + '/api/weather/live', {}, 5)
        print(result['summary'])
        return 0
    if args.run:
        http.post_json(config.ORCH_URL + '/api/scenario/reset', {}, 15)
    result = http.post_json(config.ORCH_URL + '/api/weather/demo', {}, 5)
    print(result['summary'], flush=True)
    print('Open the dashboard. Do not press Start storm.', flush=True)
    if not args.run:
        return 0
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        watch = http.get_json(config.ORCH_URL + '/api/weather/status', 5)
        state = http.get_json(config.ORCH_URL + '/api/state', 5)
        if watch['state'] == 'error':
            print(watch['summary'])
            return 1
        affected = state.get('stats', {}).get('affected', 0)
        if watch['trigger_count'] > result['trigger_count'] and affected == 340:
            report = {'automatic_trigger': True, 'provider': watch['provider'], 'affected': affected,
                      'scenario': state['scenario']['state'], 'risk': watch['risks'][0],
                      'manual_start_endpoint_called': False}
            target = config.LOG_DIR / 'weather-demo-result.json'
            target.write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps(report, indent=2), flush=True)
            print('PASS: automatic weather trigger opened all 340 sandbox cases. Log:', target)
            return 0
        time.sleep(1)
    print('FAIL: automatic weather demonstration did not open the district cases in time.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
