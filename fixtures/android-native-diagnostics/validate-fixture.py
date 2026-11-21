"""Fail closed before target observation if remote collector did not recover known fault."""
import json
import re
import sys
from pathlib import Path
root = Path(sys.argv[1])
log = (root/'fixture-stdout.txt').read_text()
pc = re.search(r'fault_pc=(0x[0-9a-f]+)', log).group(1)
rows = [json.loads(x) for x in (root/'fixture-observations.jsonl').read_text().splitlines()]
frames = [r for r in rows if r['kind']=='frame' and r['pc']==pc and r['reason_data']==[11] and '0x12345000' in r['description']]
assert frames, 'No known fixture SIGSEGV at declared PC'
codes = [r for r in rows if r['kind']=='code' and r['pc']==pc]
assert any(r['raw_hex'].startswith('c700df9b5713') for r in codes)
assert any(r['kind']=='decode' and r['pc']==pc and r['first_matches'] and r['instructions'][0]['raw_hex']=='c700df9b5713' and r['instructions'][0]['mnemonic']=='movl' for r in rows)
assert any(r['kind']=='registers' and r['pc']==pc and any(int(s['values'].get('rax','0'),16)==0x12345000 for s in r['sets']) for r in rows)
assert any(r['kind']=='fault_region' and r['region']['address']=='0x12345000' and r['region']['read'] and not r['region']['write'] for r in rows)
assert any(r['kind']=='numeric_disassembly' and r['pc']==pc and pc in r['output'] and 'c7 00 df 9b 57 13' in r['output'] for r in rows)
print('PASS: fixture declared PC = fresh frame PC = ReadMemory PC = raw-byte decode PC = explicit disassembly PC; write32 to read-only 0x12345000, rax agrees')
