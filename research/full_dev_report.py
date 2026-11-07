"""Summarize the current DEV run without exporting transcripts or credentials."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cqa.domain import config_hash
from cqa.insights import underperformed
from cqa.store import Store


def report(store):
    records, history, attempts, config = store.analytics_snapshot()
    records = [r for r in records if r['dataset_group'] == 'DEV']
    ids = {r['conversation_id'] for r in records}
    latest = {e['conversation_id']: e for e in history if e['conversation_id'] in ids}
    chash = config_hash(config)
    valid = {cid: e for cid, e in latest.items() if e['checklist_hash'] == chash
             and e['meta'].get('provider') != 'rules' and e['original_score']['complete']}
    traces = [a for a in attempts if a['conversation_id'] in ids and a['meta'].get('checklist_hash') == chash]
    usage = [a['meta']['usage'] for a in traces if all(type(a['meta'].get('usage', {}).get(k)) is int
                                                    for k in ['input_tokens', 'output_tokens'])]
    latencies = [a['meta']['elapsed_seconds'] for a in traces if a['status'] != 'running'
                 and isinstance(a['meta'].get('elapsed_seconds'), (int, float))]
    criteria = []
    for c in config['criteria']:
        answers = [next(a for a in e['answers'] if a['criterion_id'] == c['id']) for e in valid.values()]
        criteria.append({'id': c['id'], 'name': c['name'],
                         'applicable': sum(a['value'] not in [None, 'N/A'] for a in answers),
                         'na': sum(a['value'] == 'N/A' for a in answers),
                         'failed': sum(underperformed(c, a['value']) for a in answers),
                         'review_flags': sum(bool(a.get('needs_review')) for a in answers)})
    coverage = {}
    for field in ['language', 'channel']:
        coverage[field] = {value: {'total': sum(r[field] == value for r in records),
                                  'evaluated': sum(r[field] == value and r['conversation_id'] in valid for r in records)}
                           for value in sorted({r[field] for r in records})}
    return {'generated_at_utc': datetime.now(timezone.utc).isoformat(), 'checklist_version': config['version'],
            'checklist_hash': chash, 'total': len(records), 'evaluated': len(valid),
            'missing_ids': sorted(ids - valid.keys()), 'coverage': coverage, 'criteria': criteria,
            'summaries': sum(bool(e.get('insights')) for e in valid.values()),
            'request_analysis': sum(bool(e['meta'].get('request_analysis')) for e in valid.values()),
            'outcome_conflicts': sum(bool(e['meta'].get('outcome_conflict')) for e in valid.values()),
            'gross_error_flags': sum(e['original_score']['gross_error'] for e in valid.values()),
            'attempts': dict(Counter(a['status'] for a in traces)), 'attempts_total': len(traces),
            'input_tokens_known': sum(u['input_tokens'] for u in usage),
            'output_tokens_known': sum(u['output_tokens'] for u in usage), 'usage_known_attempts': len(usage),
            'mean_seconds': round(statistics.mean(latencies), 2) if latencies else None,
            'median_seconds': round(statistics.median(latencies), 2) if latencies else None,
            'latency_known_attempts': len(latencies),
            'cost_known_attempts': sum(a['meta'].get('cost_usd') is not None for a in traces)}


if __name__ == '__main__':
    result = report(Store(ROOT / 'data/cqa.sqlite'))
    destination = ROOT / 'data/full_dev_report.json'
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
