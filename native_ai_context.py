"""Load bounded incoming image context through the local native API."""
from types import SimpleNamespace

from native_images import Previews
from native_files import is_file, fetch_file, document_text
from native_controls import control_text


def replyable(row):
    # Other people's control requests are ignored, not answered or obeyed.
    if row.get('type') == 1 and control_text(row.get('body')):
        return False
    return row.get('direction') == 'incoming' and (
        row.get('type') == 3 or is_file(row) or (row.get('type') == 1 and bool(row.get('body', '').strip())))


def context_for(rows, received, root, base, request):
    latest = max(row.get('createdAt', '') for row in received)
    targets = {row['id'] for row in received if row.get('type') == 3 or is_file(row)}
    ordered = sorted(rows, key=lambda row: (row.get('createdAt', ''), str(row.get('serverId', ''))))
    ordered = [row for row in ordered if not (row.get('type') == 1 and control_text(row.get('body')))]
    recent = [row for row in ordered if row.get('direction') in ('incoming', 'outgoing')
              and row.get('createdAt', '') <= latest][-12:]
    # A text follow-up ("which of these two?") needs the preceding pictures too.
    # Prioritize new attachments; historical pictures fill the remaining budget.
    history = [row['id'] for row in recent if row.get('direction') == 'incoming'
               and row.get('type') == 3 and row['id'] not in targets]
    historical = set(history[-max(0, 4 - len(targets)):]) if len(targets) < 4 else set()
    included = targets | historical
    candidates = [row for row in ordered if row.get('direction') in ('incoming', 'outgoing')
                  and row.get('createdAt', '') <= latest
                  and (row.get('type') == 1 or row.get('id') in included)][-12:]
    selected = {row['id'] for row in candidates if row.get('id') in included}
    if targets - selected or len(selected) > 4:
        raise ValueError('Too many incoming images in one reply; no image silently omitted')
    previews = Previews(SimpleNamespace(root=root, base=base, request=request))
    try:
        result = []
        for row in candidates:
            if row.get('id') in selected and is_file(row):
                name, raw = fetch_file(previews.connection, row['id'], row['threadId'])
                result.append({'kind': 'document', 'direction': 'incoming',
                               'text': '附件：' + name + '\n' + document_text(name, raw)})
            elif row.get('id') in selected:
                result.append({'kind': 'image', 'direction': 'incoming', 'image': previews.fetch(row['id'])})
            elif row.get('body'):
                result.append({'kind': 'text', 'direction': row['direction'], 'text': row['body']})
        return result
    finally:
        previews.close()
