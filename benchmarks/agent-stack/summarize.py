import csv
import json
from pathlib import Path
import re
import statistics

ROOT=Path(__file__).resolve().parent
wire=[json.loads(line) for line in (ROOT/'results/wire.jsonl').read_text().splitlines()]
rows=[]
for path in sorted((ROOT/'results').glob('*.result.json')):
    result=json.loads(path.read_text());name=path.name.removesuffix('.result.json')
    calls=[w for w in wire if w['trial']==name and w['path'].endswith('/chat/completions')]
    transcript=(ROOT/'results'/f'{name}.acceptance.txt').read_text()
    if result['task']=='cache':
        counts=re.search(r'Ran (\d+) tests?',transcript);total=int(counts[1]) if counts else 0
        failed=sum(int(n) for n in re.findall(r'(?:failures|errors)=(\d+)',transcript))
        passed=total-failed
    else:
        count=re.search(r'(?:ℹ|#) tests (\d+)',transcript);total=int(count[1]) if count else 0
        count=re.search(r'(?:ℹ|#) pass (\d+)',transcript);passed=int(count[1]) if count else 0
    main_calls=[w for w in calls if w.get('tools')]
    ttfts=[w['ttft_s'] for w in main_calls if w.get('ttft_s') is not None]
    row={
        'agent':result['agent'],'task':result['task'],'complete_pass':result['passed'],
        'acceptance_passed':passed,'acceptance_total':total,
        'public_tests_exit':result['public_tests_exit'],
        'protected_files_intact':result['protected_files_intact'],
        'elapsed_s':result['elapsed_s'],'process_exit':result['exit'],'timeout':result['timeout'],
        'api_calls':len(calls),
        'input_tokens_sum':sum(c.get('usage',{}).get('prompt_tokens',0) for c in calls),
        'output_tokens_sum':sum(c.get('usage',{}).get('completion_tokens',0) for c in calls),
        'first_input_tokens':main_calls[0].get('usage',{}).get('prompt_tokens') if main_calls else None,
        'median_ttft_s':round(statistics.median(ttfts),3) if ttfts else None,
        'http_errors':sum(c.get('status',200)>=400 for c in calls),
        'length_stops':sum(c.get('finish_reason')=='length' for c in calls),
        'main_length_stops':sum(c.get('finish_reason')=='length' for c in main_calls),
    }
    rows.append(row)
with (ROOT/'results/summary.csv').open('w') as out:
    writer=csv.DictWriter(out,fieldnames=list(rows[0]) if rows else [],lineterminator='\n')
    writer.writeheader();writer.writerows(rows)
(ROOT/'results/summary.json').write_text(json.dumps(rows,indent=2)+'\n')
for row in rows:
    print(f"{row['agent']:10} {row['task']:8} {'PASS' if row['complete_pass'] else 'FAIL':4} {row['acceptance_passed']}/{row['acceptance_total']} {row['elapsed_s']:7.1f}s {row['output_tokens_sum']:6} output tokens")
