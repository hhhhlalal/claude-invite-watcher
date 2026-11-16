import base64,json,os
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parent
with sync_playwright() as p:
    browser=p.chromium.launch(headless=False)
    context=browser.new_context()
    page=context.new_page(); page.goto('https://x.com/login')
    input('Dang nhap X, mo trang Home thanh cong, roi nhan Enter tai day...')
    state=context.storage_state()
    # Export only X/Twitter cookies and storage, never unrelated sites.
    state['cookies']=[c for c in state['cookies'] if c['domain'].lstrip('.') in ('x.com','twitter.com')]
    state['origins']=[v for v in state['origins'] if v['origin'] in ('https://x.com','https://twitter.com')]
    if not any(c['name']=='auth_token' for c in state['cookies']):
        raise SystemExit('Chua thay phien dang nhap X. Chay lai sau khi dang nhap thanh cong.')
    output=root/'X_STORAGE_STATE_B64.txt'
    output.write_text(base64.b64encode(json.dumps(state).encode()).decode())
    os.chmod(output,0o600)
    print('Da tao X_STORAGE_STATE_B64.txt. Chi dan vao Railway Variables. Khong chia se file nay.')
    browser.close()
