import argparse, datetime as dt, html, json, logging, os, re, sqlite3, time
from pathlib import Path
from urllib.parse import urlsplit, quote

ROOT = Path(__file__).resolve().parent
URLS = re.compile(r'https?://[^\s<>"\u2026]+')

class ScanError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

def atomic_write(path, text, private=False):
    path = Path(path)
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w', encoding='utf-8') as output:
        if private:
            os.chmod(temp, 0o600)
        output.write(text)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, path)

def invite(url):
    try:
        url = html.unescape(url.strip()).rstrip('.,);]')
        if any(ord(c) < 32 for c in url) or '\u2026' in url:
            return None
        p = urlsplit(url)
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
    if ('claude' in low and re.search(r'(?<!\w)(?:7[ -]?(?:days?|ngày)|seven days|one week)(?!\w)', low)
            and re.search(r'invit|referral|trial|dùng thử|miễn phí|free', low)
            and not re.search(r'looking for|anyone have|can someone|xin link|ai có|cần link', low)):
        return 'Bai ung vien 7 ngay; chua tim thay link chinh thuc', []
    return None, []

def database(path):
    db = sqlite3.connect(path, timeout=30)
    db.execute('PRAGMA journal_mode=WAL')
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
    for (raw,) in db.execute('SELECT data FROM hits GROUP BY data ORDER BY MAX(rowid) DESC LIMIT 500'):
        p = json.loads(raw)
        links = [p['post_url']] + p['invites']
        cards.append('<article><b>' + html.escape(p['kind']) + '</b><p>' + html.escape(p['published']) + '</p><pre>' + html.escape(p['text']) + '</pre>' + ''.join('<p><a target="_blank" rel="noopener noreferrer" href="' + html.escape(u, quote=True) + '">' + html.escape(u) + '</a></p>' for u in links) + '</article>')
    atomic_write(ROOT/'results.html', '<!doctype html><meta charset="utf-8"><title>Claude Invite Watcher</title><style>body{font:16px system-ui;background:#111827;color:#eee;max-width:950px;margin:40px auto}article{background:#1f2937;padding:20px;margin:16px 0;border-radius:12px}a{color:#93c5fd;overflow-wrap:anywhere}pre{white-space:pre-wrap} </style><h1>Claude Invite Watcher</h1><p><a href="/status">Trạng thái quét</a> · F5 để cập nhật. Link chưa được xác minh còn lượt hoặc đủ điều kiện nhận. Hiển thị tối đa 500 kết quả gần nhất.</p>'+''.join(cards))

def send_push(cfg, message, title='Claude invite detected'):
    import requests
    headers = {'Title': title}
    if os.getenv('NTFY_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['NTFY_TOKEN']
    with requests.post(cfg.get('ntfy_server', 'https://ntfy.sh').rstrip('/') + '/' + quote(cfg['ntfy_topic'], safe=''),
                       data=message.encode('utf-8'), headers=headers, timeout=(5, 15), allow_redirects=False) as response:
        if not 200 <= response.status_code < 300:
            raise requests.HTTPError('ntfy delivery was not accepted')

def notify_pending(db, cfg):
    import requests
    groups = {}
    for key, raw in db.execute('SELECT key,data FROM hits WHERE sent=0 ORDER BY rowid LIMIT 100').fetchall():
        groups.setdefault(raw, []).append(key)
    sent, failed = 0, 0
    for raw, keys in groups.items():
        p = json.loads(raw)
        message = p['kind'] + '\n' + p['post_url'] + '\n' + '\n'.join(keys)
        try:
            if cfg.get('ntfy_topic'):
                send_push(cfg, message)
            else:
                try:
                    from plyer import notification
                    notification.notify(title='Claude Invite Watcher', message='Co bai moi. Mo results.html de xem link.', timeout=10)
                except Exception as e:
                    logging.warning('Thong bao desktop khong kha dung: %s; xem results.html', type(e).__name__)
                    failed += 1
                    continue
            db.executemany('UPDATE hits SET sent=1 WHERE key=?', [(key,) for key in keys]); db.commit()
            sent += 1
        except requests.RequestException:
            failed += 1
            logging.warning('Gui ntfy that bai; se thu lai o vong sau.')
    return {'sent': sent, 'failed': failed}

def resolve_short_url(url, cache):
    import requests
    try:
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.hostname != 't.co' or parts.username or parts.port not in (None, 443):
            return None
    except ValueError:
        return None
    if url not in cache:
        if len(cache) >= 20:
            return None
        cache[url] = None
        try:
            with requests.get(url, allow_redirects=False, timeout=(3, 5), stream=True) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    cache[url] = invite(response.headers.get('Location', ''))
        except requests.RequestException:
            pass
    return cache[url]

def row_to_post(row, cfg, cache):
    try:
        post = urlsplit(row.get('post') or '')
        if post.scheme != 'https' or post.hostname not in ('x.com', 'twitter.com') or not re.fullmatch(r'/[^/]+/status/\d+', post.path):
            return None
        published = dt.datetime.fromisoformat(row['time'].replace('Z', '+00:00'))
        if published.tzinfo is None:
            return None
        age = (dt.datetime.now(dt.timezone.utc) - published).total_seconds()
        if age < -300 or age > cfg['max_age_hours'] * 3600:
            return None
    except (ValueError, KeyError, TypeError):
        return None
    urls = URLS.findall(row['text']) + row.get('urls', [])
    # X often displays the official URL without its scheme; do not use truncated display URLs.
    urls += ['https://' + u for u in row.get('urls', []) if u.startswith('claude.ai/') and '\u2026' not in u]
    for url in list(urls):
        if (resolved := resolve_short_url(url, cache)):
            urls.append(resolved)
    kind, links = classify(row['text'], urls)
    if kind:
        return dict(post_url='https://x.com'+post.path, published=row['time'], text=row['text'], kind=kind, invites=links)
    return None

def scan(page, query, cfg):
    page.goto('https://x.com/search?q='+quote(query)+'&src=typed_query&f=live', wait_until='domcontentloaded', timeout=45000)
    try: page.locator('article[data-testid="tweet"]').first.wait_for(timeout=cfg.get('results_timeout_ms', 20000))
    except Exception:
        if '/login' in page.url or '/i/flow/' in page.url:
            raise ScanError('login_required')
        if page.get_by_text(re.compile(r'No results for|Không có kết quả cho', re.I)).count():
            return []
        raise ScanError('X_unavailable_or_no_results')
    found = {}
    cache = {}
    for _ in range(cfg['scroll_pages']):
        for row in page.locator('article[data-testid="tweet"]').evaluate_all('els => els.map(e => ({text:e.querySelector("[data-testid=tweetText]")?.innerText || e.innerText, time:e.querySelector("time")?.getAttribute("datetime"), post:e.querySelector("time")?.closest("a")?.href, urls:[...e.querySelectorAll("a")].flatMap(a=>[a.href,a.title||"",a.innerText])}))'):
            post = row_to_post(row, cfg, cache)
            if post:
                found[post['post_url']] = post
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
