"""Native event-driven replies; no foreground, clipboard, or input automation."""
from concurrent.futures import ThreadPoolExecutor
import getpass
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from datetime import datetime
import urllib.parse
import urllib.request

from ai_reply import generate, protect, AutoReply
from native_backend import NativeAI, NativeConnection


def initialize(root):
    global ROOT, PRIVATE, STATE, STATUS, STOP, BASE, CONFIG
    ROOT = Path(root).resolve()
    PRIVATE = ROOT / 'private-data'
    CONFIG = json.loads((PRIVATE / 'workdesk-native-ai.json').read_text(encoding='utf-8'))
    if not isinstance(CONFIG.get('account'), str) or not CONFIG['account'].strip():
        raise ValueError('Missing account ID')
    STATE = PRIVATE / 'native-ai-state.json'
    STATUS = PRIVATE / 'global-status.json'
    STOP = PRIVATE / 'global.stop'
    BASE = 'http://127.0.0.1:6175/v1/accounts/' + urllib.parse.quote(CONFIG['account'], safe='') + '/'


def allowed(thread):
    return CONFIG.get('allContacts') is True or thread in CONFIG.get('contacts', [])


def save(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    # Windows readers/scanners can briefly prevent replacement of an open file.
    for attempt in range(10):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(.05 * (attempt + 1))


def request(path, data=None, key=None):
    headers = {'Authorization': 'Bearer ' + (PRIVATE / 'api-token').read_text().strip()}
    if key:
        headers['idempotency-key'] = key
    if data is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(BASE + path, headers=headers,
                                 data=None if data is None else json.dumps(data).encode())
    # Explicitly bypass machine proxy for this loopback-only connection.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=35) as response:
        return json.load(response)


def quote(value):
    return urllib.parse.quote(value, safe='')


def ordinary(thread):
    name = thread.get('id', '')
    category = (thread.get('classification') or {}).get('category')
    excluded = {'filehelper', 'weixin', 'fmessage', 'newsapp', 'qqmail',
                'notification_messages', 'brandsessionholder', 'weixinreminder',
                'medianote', 'floatbottle', 'qmessage', 'tmessage'}
    return bool(name and name not in excluded and not name.startswith(('gh_', 'gh-'))
                and category not in ('business', 'system')
                and thread.get('kind') in ('direct', 'group'))


def work(thread, messages, since=0):
    dispatched = False
    started = time.monotonic()
    try:
        info = request('threads/' + quote(thread))
        if not ordinary(info) or not allowed(thread):
            return {'state': 'skipped'}
        rows = request('threads/' + quote(thread) + '/messages?limit=20')['items']
        targets = set(messages)
        received = [row for row in rows if row.get('id') in targets and
                    row.get('direction') == 'incoming' and row.get('type') == 1
                    and row.get('body', '').strip()]
        # A newly received event may precede local projection. Retry instead of
        # silently losing its message identifier.
        missing = targets - {row.get('id') for row in rows}
        for message in missing:
            row = request('messages/' + quote(message))
            if row.get('threadId') != thread:
                raise ValueError('Message thread mismatch')
            if row.get('direction') == 'incoming' and row.get('type') == 1 and row.get('body', '').strip():
                received.append(row)
                rows.append(row)
        if not received:
            return {'state': 'skipped'}
        if since:
            received = [row for row in received if row.get('createdAt') and
                        datetime.fromisoformat(row['createdAt']).timestamp() >= since]
            if not received:
                return {'state': 'skipped_old_history'}
        latest = max(row.get('createdAt', '') for row in received)
        rows = sorted(rows, key=lambda row: (row.get('createdAt', ''), str(row.get('serverId', ''))))
        context = [{'kind': 'text', 'direction': row['direction'], 'text': row['body']}
                   for row in rows if row.get('type') == 1 and row.get('body')
                   and row.get('direction') in ('incoming', 'outgoing')
                   and row.get('createdAt', '') <= latest][-12:]
        config = dict(CONFIG)
        config['apiKey'] = protect(config.pop('encryptedKey'), decrypt=True) if config.get('encryptedKey') else ''
        model_start = time.monotonic()
        reply = generate(config, context)
        model_seconds = round(time.monotonic() - model_start, 2)
        if STOP.exists():
            return {'state': 'cancelled'}
        key = 'global-v1-' + hashlib.sha256((thread + '|' + '|'.join(sorted(messages))).encode()).hexdigest()[:40]
        dispatched = True
        sent = request('sends', {'threadId': thread, 'text': reply}, key)
        deadline = time.monotonic() + 30
        while sent.get('state') in ('queued', 'running', 'preparing', 'uploading', 'submitting') and time.monotonic() < deadline:
            time.sleep(.15)
            sent = request('sends/' + quote(sent['id']))
        if sent.get('state') != 'accepted' or not sent.get('serverId'):
            return {'state': 'uncertain'}
        return {'state': 'accepted', 'modelSeconds': model_seconds,
                'totalSeconds': round(time.monotonic() - started, 2)}
    except Exception as error:
        return {'state': 'uncertain' if dispatched else 'retry', 'errorType': type(error).__name__}


def main():
    if STOP.exists():
        return
    state = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {
        'cursor': str(request('threads?limit=1')['asOfEventCursor']),
        'queue': {}, 'inFlight': {}, 'blocked': {}, 'replies': 0, 'account': CONFIG['account']}
    if state.get('account') != CONFIG['account']:
        raise ValueError('State account mismatch; use a separate Agent WeChat data directory')
    if 'activatedAt' not in state:
        prior = json.loads(STATUS.read_text(encoding='utf-8')) if STATUS.exists() else {}
        state['activatedAt'] = prior.get('startedAt', time.time())
    # Never repeat a possibly dispatched send after a process interruption.
    for thread in state['inFlight']:
        state['blocked'][thread] = 'interrupted_send_needs_review'
    state['inFlight'] = {}
    save(STATE, state)
    futures = {}
    retries = {}
    status = {'pid': os.getpid(), 'scope': 'friends_and_ordinary_groups',
              'inputAutomation': False, 'startedAt': time.time()}
    with ThreadPoolExecutor(max_workers=2) as pool:
        while not STOP.exists() or futures:
            try:
                for thread, future in list(futures.items()):
                    if not future.done():
                        continue
                    result = future.result()
                    messages = state['inFlight'].pop(thread)
                    if result['state'] == 'retry':
                        state['queue'][thread] = list(dict.fromkeys(messages + state['queue'].get(thread, [])))
                        retries[thread] = time.monotonic() + 5
                    elif result['state'] == 'uncertain':
                        state['blocked'][thread] = 'send_result_unknown'
                    elif result['state'] == 'accepted':
                        state['replies'] += 1
                    status['lastResult'] = result
                    del futures[thread]
                    save(STATE, state)
                if STOP.exists():
                    time.sleep(.1)
                    continue
                events = request('events?after=' + quote(state['cursor']) + '&limit=200')
                for event in events.get('items', []):
                    data = event.get('data', {})
                    if event.get('kind') == 'message.committed' and data.get('origin') in ('live', 'catchup') and data.get('direction') == 'incoming':
                        thread, message = data.get('threadId'), data.get('messageId')
                        if thread and message and allowed(thread) and thread not in state['blocked']:
                            queue = state['queue'].setdefault(thread, [])
                            if message not in queue and message not in state['inFlight'].get(thread, []):
                                queue.append(message)
                    state['cursor'] = str(event['cursor'])
                if events.get('items'):
                    save(STATE, state)
                for thread in list(state['queue']):
                    if len(futures) >= 2:
                        break
                    if thread in futures or thread in state['blocked'] or retries.get(thread, 0) > time.monotonic():
                        continue
                    messages = state['queue'].pop(thread)
                    state['inFlight'][thread] = messages
                    save(STATE, state)
                    futures[thread] = pool.submit(work, thread, messages, state['activatedAt'])
                status.update(state='listening', updatedAt=time.time(), replies=state['replies'],
                              active=len(futures), queued=len(state['queue']), blocked=len(state['blocked']),
                              cursor=state['cursor'])
                save(STATUS, status)
            except Exception as error:
                status.update(state='retrying', updatedAt=time.time(), errorType=type(error).__name__)
                try:
                    save(STATUS, status)
                except OSError:
                    # A status-write failure must not kill the event listener.
                    pass
                time.sleep(3)
            time.sleep(.3)
    status.update(state='stopped', updatedAt=time.time())
    save(STATUS, status)


def configure(root):
    import msvcrt
    private = root / 'private-data'
    if not (private / 'api-token').is_file():
        raise ValueError('请先安装并登录 Agent WeChat，确认目录内存在 private-data/api-token。')
    with (private / 'global-listener.lock').open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise ValueError('请先暂停现有 AI，等待监听进程退出后重新配置。') from None
        status_path = private / 'global-status.json'
        status = json.loads(status_path.read_text()) if status_path.exists() else {}
        if NativeAI.process_alive(status.get('pid')):
            raise ValueError('监听进程仍在运行，请先暂停并等待退出。')
        (private / 'global.stop').touch()
        account = input('Agent WeChat account ID: ').strip()
        if not account:
            raise ValueError('必须填写 account ID。')
        settings = {'directory': str(root), 'account': account}
        connection = NativeConnection(settings)
        try:
            connection.request('threads?limit=1')
        finally:
            connection.close()
        print('账号接口连接成功。仅会处理启用后的新文字消息；不会回复公众号或系统通知。')
        data = {'endpoint': input('Chat Completions API 地址（包含 /v1）: ').strip(),
                'model': input('模型 ID: ').strip(),
                'apiKey': getpass.getpass('API 密钥（不回显，本机模型可留空）: '),
                'style': input('回复风格（留空使用自然简短）: ').strip() or '自然口语化，简短友好，根据话题回复一到三句。',
                'interval': 1, 'contacts': [], 'allContacts': False}
        data['allContacts'] = input('接管全部好友与普通群聊？输入 YES 开启，其他输入使用指定名单: ').strip() == 'YES'
        if not data['allContacts']:
            data['contacts'] = [x.strip() for x in input('允许的 thread ID，多个用英文逗号分隔（不是昵称）: ').split(',') if x.strip()]
            if not data['contacts']:
                raise ValueError('指定名单不能为空。')
        config = AutoReply.validate(data)
        config['account'] = account
        key = config.pop('apiKey')
        config['encryptedKey'] = protect(key) if key else ''
        state_path = private / 'native-ai-state.json'
        if state_path.exists() and json.loads(state_path.read_text()).get('account') != account:
            raise ValueError('已有另一账号的监听状态，请使用独立的 Agent WeChat 数据目录。')
        path = private / 'workdesk-native-ai.json'
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
        os.replace(temp, path)
        runtime = Path(__file__).parent / '.runtime'
        runtime.mkdir(exist_ok=True)
        (runtime / 'native-backend.json').write_text(json.dumps(settings), encoding='utf-8')
        print('配置已保存，AI 保持暂停。启动工作台后点击“恢复后台 AI”才会开始提交文字给 API 并自动发送回复。')


def cli():
    import argparse
    import msvcrt
    parser = argparse.ArgumentParser(description='Native Workdesk background AI listener')
    parser.add_argument('--root', required=True, help='Agent WeChat directory containing private-data')
    parser.add_argument('--configure', action='store_true', help='Interactive setup; saves encrypted credentials and leaves AI paused')
    args = parser.parse_args()
    if args.configure:
        try:
            configure(Path(args.root).resolve())
        except Exception:
            print('配置失败：请检查账号、API 输入、文件权限，并确认现有监听器已暂停退出。')
            sys.exit(1)
        sys.exit(0)
    initialize(args.root)
    # OS releases this lock on exit, including crashes; prevents duplicate replies.
    with (PRIVATE / 'global-listener.lock').open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            sys.exit(0)
        main()


if __name__ == '__main__':
    cli()
