import base64,json,os
from pathlib import Path
from playwright.sync_api import sync_playwright
from sessions import validate_state
from watcher import atomic_write
root=Path(__file__).resolve().parent
with sync_playwright() as p:
    browser=p.chromium.launch(headless=False)
    context=browser.new_context()
    page=context.new_page(); page.goto('https://x.com/login')
    input('Dang nhap X, mo trang Home thanh cong, roi nhan Enter tai day...')
    try:
        state=validate_state(context.storage_state())
    except ValueError:
        raise SystemExit('Chua thay phien dang nhap X con han. Chay lai sau khi dang nhap thanh cong.')
    output=root/'X_STORAGE_STATE_B64.txt'
    atomic_write(output, base64.b64encode(json.dumps(state).encode()).decode(), private=True)
    print('Da tao X_STORAGE_STATE_B64.txt. Chi dan vao Railway Variables. Khong chia se file nay.')
    browser.close()
