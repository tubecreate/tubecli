# -*- coding: utf-8 -*-
# Lập lịch có THẬT SỰ lướt web không? Đối chiếu 2 nguồn độc lập:
#   (1) data/extensions_data/agent_runs/runs-*.jsonl  — lịch NÓI nó chạy
#   (2) History (SQLite) trong từng hồ sơ trình duyệt — trình duyệt THỰC SỰ mở gì
# Một lượt chỉ là lướt thật khi History có URL đúng khung giờ của lượt đó.
import io, json, os, re, shutil, sqlite3, sys, tempfile
from datetime import datetime, timedelta

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
B = os.environ.get('TUBECLI_DIR') or os.getcwd()
if not os.path.isdir(os.path.join(B, 'data', 'extensions_data')):
    for c in ('/root/tubecli', '/opt/tubecli', os.path.expanduser('~/tubecli')):
        if os.path.isdir(os.path.join(c, 'data', 'extensions_data')):
            B = c
            break
D = os.path.join(B, 'data', 'extensions_data')
if not os.path.isdir(D):
    sys.exit('Khong thay data/extensions_data — cd vao thu muc tubecli roi chay lai.')
RUNS, PROFS = os.path.join(D, 'agent_runs'), os.path.join(D, 'browser', 'browser_profiles')
SINCE = datetime.now() - timedelta(days=DAYS)
print('kho: %s | %d ngay gan nhat (tu %s)\n' % (B, DAYS, SINCE.strftime('%d/%m %H:%M')))

runs = {}
for fn in sorted(os.listdir(RUNS)) if os.path.isdir(RUNS) else []:
    if not (fn.startswith('runs-') and fn.endswith('.jsonl')):
        continue
    for ln in io.open(os.path.join(RUNS, fn), encoding='utf-8', errors='replace'):
        try:
            d = json.loads(ln)
            t = datetime.fromisoformat(str(d['ts']).replace('Z', ''))
        except Exception:
            continue
        if t < SINCE:
            continue
        r = runs.setdefault(d.get('run_id'), {'t0': t, 't1': t})
        r['t0'], r['t1'] = min(r['t0'], t), max(r['t1'], t)
        # 'warnings': luot chay xong ma van khong sach (ANTIDETECT_OFF = mo trinh
        # duyet KHONG co dau van tay). Ma thoat 0 nen no lan hoan vao cac luot tot.
        for k in ('profile', 'query', 'trigger', 'outcome', 'return_code', 'warnings'):
            if d.get(k) not in (None, ''):
                r[k] = d[k]
        if d.get('kind') == 'end':
            r['tail'] = (d.get('log_tail') or '')[-800:]
S = sorted([r for r in runs.values() if r.get('trigger') == 'schedule' or r.get('profile')],
           key=lambda r: r['t0'])
out = {}
for r in S:
    k = r.get('outcome', 'chua ghi ket')
    if r.get('warnings'):
        k += ' (!' + ','.join(str(w) for w in r['warnings']) + ')'
    out[k] = out.get(k, 0) + 1
print('=== 1. LICH NOI NO CHAY: %d luot ===' % len(S))
print('   ' + (' | '.join('%s: %d' % kv for kv in sorted(out.items(), key=lambda x: -x[1])) or '(khong co luot nao)'))
print('   ho so: ' + (', '.join(sorted({r.get('profile', '?') for r in S})) or '-') + '\n')

def visits(p):
    for rel in (os.path.join(p, 'Default', 'History'), os.path.join(p, 'History')):
        src = os.path.join(PROFS, rel)
        if not os.path.exists(src):
            continue
        tmp = tempfile.mkdtemp()
        try:
            dst = os.path.join(tmp, 'H')
            shutil.copy2(src, dst)
            for e in ('-wal', '-shm'):
                if os.path.exists(src + e):
                    shutil.copy2(src + e, dst + e)
            c = sqlite3.connect(dst)
            v = [(datetime.fromtimestamp(t / 1e6 - 11644473600), u) for t, u in
                 c.execute('SELECT v.visit_time,u.url FROM visits v JOIN urls u ON u.id=v.url ORDER BY 1')]
            c.close()
            return v
        except Exception as e:
            print('   (loi doc History %s: %s)' % (p, e))
            return []
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return None

print('=== 2. TRINH DUYET THUC SU MO GI (History cuc bo) ===')
H = {}
for p in sorted({r.get('profile') for r in S if r.get('profile')}) or (sorted(os.listdir(PROFS))[:6] if os.path.isdir(PROFS) else []):
    v = visits(p)
    if v is None:
        print('   %-20s CHUA CO file History — ho so nay chua mo trang nao bao gio' % p)
        H[p] = []
        continue
    H[p] = v
    print('   %-20s %4d URL trong khung | %5d tu truoc toi nay | lan cuoi %s'
          % (p, len([x for x in v if x[0] >= SINCE]), len(v),
             v[-1][0].strftime('%d/%m %H:%M') if v else '-'))

print('\n=== 3. DOI CHIEU TUNG LUOT ===')
real = fake = 0
for r in S[-25:]:
    p = r.get('profile', '')
    a, b = r['t0'] - timedelta(minutes=1), r['t1'] + timedelta(minutes=2)
    hit = [u for t, u in H.get(p, []) if a <= t <= b]
    real, fake = real + bool(hit), fake + (not hit)
    print('   %s %-14s %-40s %s' % (r['t0'].strftime('%d/%m %H:%M'), p[:14], (r.get('query') or '')[:40],
                                    ('OK %d trang' % len(hit)) if hit else 'KHONG mo trang nao'))
    if not hit and r.get('tail'):
        for ln in reversed(r['tail'].splitlines()):
            if ln.strip() and ('!!!' in ln or re.search(r'error|failed|cannot', ln, re.I)):
                print('        ly do: ' + ln.strip()[:110])
                break

print('\n=== KET LUAN ===')
if not S:
    print('   Lich chua chay luot nao — van de o bo lap lich, chua toi luot trinh duyet.')
elif real == 0:
    print('   %d/%d luot KHONG mo noi mot trang. Tien trinh co sinh ra (bang ghi "running")' % (fake, fake))
    print('   nhung chet truoc khi toi web — dung ly do lich su Google trong.')
elif fake:
    print('   %d luot luot that | %d luot chet truoc khi mo trang.' % (real, fake))
else:
    print('   Ca %d luot deu mo trang that. Lap lich dang chay dung.' % real)
print('   (Lich su tai khoan Google chi ghi khi ho so DA dang nhap Google va bat Web & App')
print('    Activity. History cuc bo o tren moi la bang chung chuan.)')
