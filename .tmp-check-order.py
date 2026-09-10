import json, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
d = json.load(open(r'D:\code\ai\shanghai-metro-toilets\data\raw\station_list.json', encoding='utf-8'))
# 列表顺序 vs stat_id 后缀顺序，分别看13号线、1号线
for line in ['13', '1']:
    ents = [(i, e['key'], e['value']) for i, e in enumerate(d) if e['key'].startswith(line.zfill(2))]
    by_list = [e[2] for e in ents]
    by_id = [v for _, _, v in sorted(ents, key=lambda x: int(x[1]))]
    print(f'line {line}: list_order == statid_order -> {by_list == by_id}')
    print('  列表顺序:', ' '.join(by_list))
    print('  id顺序  :', ' '.join(by_id))
