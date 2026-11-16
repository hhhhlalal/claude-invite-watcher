import argparse, datetime as dt, html, json, logging, os, re, sqlite3, time
from pathlib import Path
from urllib.parse import urlsplit, quote

ROOT = Path(__file__).resolve().parent
URLS = re.compile(r'https?://[^\s<>"\u2026]+')

def invite(url):
    try:
        p = urlsplit(url.strip().rstrip('.,);]'))
        if p.scheme != 'https' or p.hostname != 'claude.ai' or p.username or p.password or p.port not in (None, 443):
            return None
        if not re.match(r'^/(duet-invite|invite)(/|$)', p.path):
            return None
        # Keep query: some invitations carry their code there.
        return 'https://claude.ai' + p.path + ('?' + p.query if p.query else '')
    except ValueError:
        return None

def classify(text, urls):
    links = sorted({x for u in urls if (x := invite(u))})
    if links:
        return 'Link moi Claude; chua xac minh hieu luc/7 ngay', links
    low = text.lower()
    if ('claude' in low and re.search(r'7[ -]?(days?|ngày)|seven days|one week', low)
            and re.search(r'invit|referral|trial|dùng thử|miễn phí|free', low)
            and not re.search(r'looking for|anyone have|can someone|xin link|ai có|cần link', low)):
        return 'Bai ung vien 7 ngay; chua tim thay link chinh thuc', []
    return None, []

def database(path):
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE IF NOT EXISTS hits (key TEXT PRIMARY KEY, data TEXT, sent INTEGER DEFAULT 0)')
    return db

def save(db, post):
    # Deduplicate invitation links even when reshared by other accounts.
    keys = post['invites'] or [post['post_url']]
    for key in keys:
        db.execute('INSERT OR IGNORE INTO hits(key,data) VALUES (?,?)', (key, json.dumps(post, ensure_ascii=False)))
    db.commit()

def report(db):
    cards = []
    for (raw,) in db.execute('SELECT DISTINCT data FROM hits ORDER BY rowid DESC'):
        p = json.loads(raw)
        links = [p['post_url']] + p['invites']
        cards.append('<article><b>' + html.escape(p['kind']) + '</b><p>' + html.escape(p['published']) + '</p><pre>' + html.escape(p['text']) + '</pre>' + ''.join('<p><a target="_blank" rel="noopener noreferrer" href="' + html.escape(u, quote=True) + '">' + html.escape(u) + '</a></p>' for u in links) + '</article>')
    (ROOT/'results.html').write_text('<!doctype html><meta charset="utf-8"><title>Claude Invite Watcher</title><style>body{font:16px system-ui;background:#111827;color:#eee;max-width:950px;margin:40px auto}article{background:#1f2937;padding:20px;margin:16px 0;border-radius:12px}a{color:#93c5fd;overflow-wrap:anywhere}pre{white-space:pre-wrap} </style><h1>Claude Invite Watcher</h1><p>F5 để cập nhật. Link chưa được xác minh còn lượt hoặc đủ điều kiện nhận.</p>'+''.join(cards), encoding='utf-8')

def notify_pending(db, cfg):
    import requests
    for key, raw in db.execute('SELECT key,data FROM hits WHERE sent=0').fetchall():
        p = json.loads(raw)
        message = p['kind'] + '\n' + p['post_url'] + '\n' + key
        logging.info('MOI: %s', message)
        try:
            if cfg.get('ntfy_topic'):
                headers = {'Title': 'Claude invite detected'}
                if os.getenv('NTFY_TOKEN'): headers['Authorization'] = 'Bearer '+os.environ['NTFY_TOKEN']
                requests.post(cfg.get('ntfy_server','https://ntfy.sh').rstrip('/')+'/'+quote(cfg['ntfy_topic'], safe=''), data=message.encode(), headers=headers, timeout=20).raise_for_status()
            else:
                try:
                    from plyer import notification
                    notification.notify(title='Claude Invite Watcher', message='Co bai moi. Mo results.html de xem link.', timeout=10)
                except Exception as e:
                    logging.warning('Thong bao desktop khong kha dung: %s; xem results.html', type(e).__name__)
            db.execute('UPDATE hits SET sent=1 WHERE key=?', (key,)); db.commit()
        except requests.RequestException:
            logging.warning('Gui ntfy that bai; se thu lai o vong sau.')

def scan(page, query, cfg):
    import requests
    page.goto('https://x.com/search?q='+quote(query)+'&src=typed_query&f=live', wait_until='domcontentloaded', timeout=45000)
    try: page.locator('article[data-testid="tweet"]').first.wait_for(timeout=20000)
    except Exception:
        raise RuntimeError('Khong doc duoc bai: co the chua dang nhap, X gioi han, loi giao dien hoac khong co ket qua. Kiem tra trinh duyet.')
    found = {}
    for _ in range(cfg['scroll_pages']):
        for row in page.locator('article[data-testid="tweet"]').evaluate_all('els => els.map(e => ({text:e.innerText, time:e.querySelector("time")?.getAttribute("datetime"), post:e.querySelector("time")?.closest("a")?.href, urls:[...e.querySelectorAll("a")].flatMap(a=>[a.href,a.title||"",a.innerText])}))'):
            if not row['post'] or not row['time']: continue
            if urlsplit(row['post']).hostname not in ('x.com','twitter.com'): continue
            published = dt.datetime.fromisoformat(row['time'].replace('Z','+00:00'))
            if (dt.datetime.now(dt.timezone.utc)-published).total_seconds() > cfg['max_age_hours']*3600: continue
            urls = URLS.findall(row['text']) + row['urls']
            for u in list(urls):
                if urlsplit(u).hostname == 't.co':
                    try:
                        r = requests.get(u, allow_redirects=False, timeout=10)
                        urls.append(r.headers.get('Location',''))
                    except requests.RequestException: pass
            kind, links = classify(row['text'], urls)
            if kind: found[row['post']] = dict(post_url=row['post'], published=row['time'], text=row['text'], kind=kind, invites=links)
        page.mouse.wheel(0,1600); page.wait_for_timeout(1800)
    return list(found.values())

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--login',action='store_true'); parser.add_argument('--once',action='store_true'); args=parser.parse_args()
    cfg=json.loads((ROOT/'config.json').read_text(encoding='utf-8-sig'))
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', handlers=[logging.StreamHandler(),logging.FileHandler(ROOT/'watcher.log',encoding='utf-8')])
    from playwright.sync_api import sync_playwright
    db=database(ROOT/'state.db')
    with sync_playwright() as pw:
        context=pw.chromium.launch_persistent_context(str(ROOT/'browser_profile'),headless=False,viewport={'width':1280,'height':900})
        page=context.pages[0] if context.pages else context.new_page()
        if args.login:
            page.goto('https://x.com/login'); input('Dang nhap X trong trinh duyet. Xong thi nhan Enter tai day...'); context.close(); return
        try:
            while True:
                success=0
                for q in cfg['queries']:
                    try:
                        hits=scan(page,q,cfg)
                        for p in hits: save(db,p)
                        success+=1
                        logging.info('Truy van hoan tat: %d bai phu hop',len(hits))
                    except Exception as e: logging.warning('%s: %s',type(e).__name__,str(e)[:250])
                    report(db); notify_pending(db,cfg)
                logging.info('Vong quet: %d/%d truy van doc duoc bai. Ctrl+C de dung.',success,len(cfg['queries']))
                if args.once: break
                time.sleep(max(120,cfg['interval_seconds']) if success else max(600,cfg['interval_seconds']))
        except KeyboardInterrupt: pass
        finally: context.close(); db.close()

if __name__=='__main__': main()
