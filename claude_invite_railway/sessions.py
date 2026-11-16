"""Keep X-only storage state and refreshed cookies on the mounted volume."""
import base64
import binascii
import hashlib
import json
import time
from pathlib import Path
from watcher import atomic_write


def validate_state(state, check_expiry=True):
    if not isinstance(state, dict) or not isinstance(state.get('cookies'), list):
        raise ValueError('Invalid X session structure')
    cookies = []
    for cookie in state['cookies']:
        if not isinstance(cookie, dict):
            raise ValueError('Invalid cookie structure')
        if cookie.get('domain', '').lstrip('.') in ('x.com', 'twitter.com'):
            cookies.append(cookie)
    auth = [c for c in cookies if c.get('name') == 'auth_token' and c.get('value')]
    if not auth:
        raise ValueError('X session has no auth_token; export again after login')
    if check_expiry and not any(c.get('expires', -1) == -1 or c.get('expires', -1) > time.time() for c in auth):
        raise ValueError('X session has expired; export again')
    origins = state.get('origins', [])
    if not isinstance(origins, list):
        raise ValueError('Invalid origins structure')
    return {'cookies': cookies, 'origins': [o for o in origins if isinstance(o, dict) and o.get('origin') in ('https://x.com', 'https://twitter.com')]}


def decode_state(encoded, check_expiry=True):
    try:
        return validate_state(json.loads(base64.b64decode(''.join(encoded.split()), validate=True)), check_expiry=check_expiry)
    except (binascii.Error, UnicodeError, json.JSONDecodeError, TypeError, AttributeError) as error:
        raise ValueError('Invalid X_STORAGE_STATE_B64; export the session again') from error


class SessionStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.state_path = self.directory / 'session-state.json'
        self.seed_path = self.directory / 'session-seed.sha256'

    def load(self, encoded):
        # An old import may have expired while the on-disk cookies were refreshed.
        imported = decode_state(encoded, check_expiry=False)
        seed = hashlib.sha256(json.dumps(imported, sort_keys=True).encode()).hexdigest()
        if self.seed_path.exists() and self.seed_path.read_text() == seed:
            try:
                return validate_state(json.loads(self.state_path.read_text(encoding='utf-8')))
            except (OSError, ValueError):
                pass
        self.save(imported)
        atomic_write(self.seed_path, seed, private=True)
        return imported

    def save(self, state):
        atomic_write(self.state_path, json.dumps(validate_state(state)), private=True)
