"""Load bounded incoming image context through the local native API."""
from types import SimpleNamespace

from native_images import Previews
from native_files import is_file, fetch_file, document_text
from native_controls import control_text
from native_video import is_video, is_channels, fetch_video, channels_context
from native_voice import is_voice, fetch_voice


def replyable(row):
    # Other people's control requests are ignored, not answered or obeyed.
    if row.get('type') == 1 and control_text(row.get('body')):
        return False
    return row.get('direction') == 'incoming' and (
        row.get('type') == 3 or is_file(row) or is_video(row) or is_channels(row) or is_voice(row)
        or (row.get('type') == 1 and bool(row.get('body', '').strip())))


def context_for(rows, received, root, base, request, video_enabled=False,voice_enabled=False,voice_language='zh', include_documents=False):
    latest = max(row.get('createdAt', '') for row in received)
    targets = {row['id'] for row in received if row.get('type') == 3 or is_file(row) or is_video(row) or is_channels(row) or is_voice(row)}
    ordered = sorted(rows, key=lambda row: (row.get('createdAt', ''), str(row.get('serverId', ''))))
    ordered = [row for row in ordered if not (row.get('type') == 1 and control_text(row.get('body')))]
    recent = [row for row in ordered if row.get('direction') in ('incoming', 'outgoing')
              and row.get('createdAt', '') <= latest][-12:]
    # A text follow-up ("which of these two?") needs the preceding pictures too.
    # Prioritize new attachments; historical pictures fill the remaining budget.
    history = [row['id'] for row in recent if row.get('direction') == 'incoming'
               and (row.get('type') == 3 or (include_documents and is_file(row))) and row['id'] not in targets]
    historical = set(history[-max(0, 4 - len(targets)):]) if len(targets) < 4 else set()
    included = targets | historical
    candidates = [row for row in ordered if row.get('direction') in ('incoming', 'outgoing')
                  and row.get('createdAt', '') <= latest
                  and (row.get('type') == 1 or row.get('id') in included
                       or (row.get('direction') == 'outgoing' and row.get('type') == 3))][-12:]
    selected = {row['id'] for row in candidates if row.get('id') in included}
    if targets - selected or len(selected) > 4:
        raise ValueError('Too many incoming images in one reply; no image silently omitted')
    previews = Previews(SimpleNamespace(root=root, base=base, request=request))
    try:
        result = []
        videos = 0
        for row in candidates:
            if row.get('id') in selected and is_voice(row):
                try:
                    if not voice_enabled:raise ValueError('尚未开启本地语音转写，请账号主人在控制台授权。')
                    text=fetch_voice(previews.connection,row,language=voice_language)
                except Exception as error:
                    text='未能理解这段语音：'+(str(error) if isinstance(error,ValueError) else '语音组件或下载未就绪。')+' 请对方用文字补充，不要猜测。'
                result.append({'kind':'document','direction':'incoming','text':text})
            elif row.get('id') in selected and is_channels(row):
                result.append({'kind':'document','direction':'incoming','text':channels_context(row)})
            elif row.get('id') in selected and is_video(row):
                videos += 1
                try:
                    if not video_enabled:raise ValueError('尚未开启视频画面分析，请由账号主人在控制台授权。')
                    if videos>1:raise ValueError('每次只能分析一个视频，其他视频尚未分析，请分开发送。')
                    result.append(fetch_video(previews.connection,row))
                except Exception as error:
                    reason=str(error) if isinstance(error,ValueError) else '视频下载或解码未完成。'
                    result.append({'kind':'document','direction':'incoming','text':'未分析这个视频：'+reason+' 不要猜测其画面或声音。'})
            elif row.get('id') in selected and is_file(row):
                try:
                    name, raw = fetch_file(previews.connection, row['id'], row['threadId'])
                    text = '附件：' + name + '\n' + document_text(name, raw)
                except Exception:
                    text = '未能读取这个附件：可能下载未完成、文件损坏、加密或超出解析限制。请对方重发或补充文字，不能声称已阅读内容。'
                result.append({'kind': 'document', 'direction': 'incoming', 'text': text})
            elif row.get('id') in selected:
                result.append({'kind': 'image', 'direction': 'incoming', 'image': previews.fetch(row['id'])})
            elif row.get('direction') == 'outgoing' and row.get('type') == 3:
                result.append({'kind':'text','direction':'outgoing','text':'[此前已发送一张图片或表情图片，内容未重新读取；不要臆测具体画面，也不要机械重复发图。]'})
            elif row.get('body'):
                result.append({'kind': 'text', 'direction': row['direction'], 'text': row['body']})
        return result
    finally:
        previews.close()
