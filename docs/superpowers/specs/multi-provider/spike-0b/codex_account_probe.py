#!/usr/bin/env python3
"""Spike 0B: drive `codex app-server` account RPCs against a scratch CODEX_HOME.

Usage:
  codex_account_probe.py --home DIR status            # initialize + account/read (no network)
  codex_account_probe.py --home DIR logout            # account/logout (no-op when signed out)
  codex_account_probe.py --home DIR device-login      # account/login/start chatgptDeviceCode;
                                                      # prints verificationUrl + userCode, waits for
                                                      # account/login/completed (NEEDS USER APPROVAL)
  codex_account_probe.py --home DIR device-cancel     # start then account/login/cancel at once

Never prints tokens: account/read only returns type/email/planType, and the probe drops email.
"""
import argparse, json, os, subprocess, sys, threading, queue

CODEX = '/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex'


class Server:
    def __init__(self, home):
        env = {k: os.environ[k] for k in ('PATH', 'HOME', 'USER', 'LANG', 'TMPDIR') if k in os.environ}
        env['CODEX_HOME'] = home
        os.makedirs(home, exist_ok=True)
        self.p = subprocess.Popen([CODEX, 'app-server'], env=env, cwd=home, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                  start_new_session=True)
        self.inbox, self.next_id = queue.Queue(), 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            self.inbox.put(json.loads(line))
        self.inbox.put(None)

    def send(self, msg):
        self.p.stdin.write(json.dumps(msg) + '\n'); self.p.stdin.flush()

    def request(self, method, params=None, timeout=30):
        self.next_id += 1
        rid = self.next_id
        msg = {'id': rid, 'method': method}
        if params is not None:
            msg['params'] = params
        self.send(msg)
        while True:
            m = self.inbox.get(timeout=timeout)
            if m is None:
                raise SystemExit('app-server exited')
            if m.get('id') == rid and 'method' not in m:
                return m
            log('notification', m)

    def wait_method(self, method, timeout):
        while True:
            m = self.inbox.get(timeout=timeout)
            if m is None:
                raise SystemExit('app-server exited')
            log('notification', m)
            if m.get('method') == method:
                return m

    def close(self):
        self.p.stdin.close()
        try:
            self.p.wait(5)
        except subprocess.TimeoutExpired:
            self.p.kill()


def redact(m):
    s = json.dumps(m)
    acct = (m.get('result') or {}).get('account') if isinstance(m.get('result'), dict) else None
    if isinstance(acct, dict) and acct.get('email'):
        s = s.replace(acct['email'], '<email>')
    return s


def log(tag, m):
    print(tag + ': ' + redact(m), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--home', required=True)
    ap.add_argument('action', choices=['status', 'logout', 'device-login', 'device-cancel'])
    a = ap.parse_args()
    s = Server(a.home)
    try:
        log('initialize', s.request('initialize', {'clientInfo': {'name': 'interspace-spike', 'version': '0'},
                                                   'capabilities': {'experimentalApi': True}}))
        s.send({'method': 'initialized'})
        if a.action == 'logout':
            log('account/logout', s.request('account/logout'))
        if a.action in ('device-login', 'device-cancel'):
            r = s.request('account/login/start', {'type': 'chatgptDeviceCode'})
            log('account/login/start', r)
            res = r.get('result') or {}
            if a.action == 'device-cancel':
                log('account/login/cancel', s.request('account/login/cancel', {'loginId': res.get('loginId')}))
            elif res.get('type') == 'chatgptDeviceCode':
                print('\nOpen %s and enter code %s\n' % (res['verificationUrl'], res['userCode']), flush=True)
                s.wait_method('account/login/completed', timeout=900)
        log('account/read', s.request('account/read', {'refreshToken': False}))
    finally:
        s.close()


if __name__ == '__main__':
    main()
