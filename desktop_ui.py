"""Native desktop console. Preview mode is isolated and never starts services."""
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, font as tkfont
from PIL import Image, ImageTk, ImageDraw

BG = '#f2f5f5'
INK = '#17343b'
MUTED = '#6b8087'
TEAL = '#147d6c'
LINE = '#dce6e5'
ASSETS = Path(__file__).resolve().parent / 'assets'


def build_console(platform=None, preview=False):
    if platform is None:
        from desktop_app import Platform
        platform = Platform()
    if os.name == 'nt':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Workdesk.Desktop')
    app = tk.Tk(className='Workdesk')
    app.title('Workdesk · 连接与 AI 控制台')
    app.geometry('%sx%s' % (max(960, min(1100, app.winfo_screenwidth()-80)),
                            max(680, min(820, app.winfo_screenheight()-90))))
    app.minsize(960, 680)
    app.configure(bg=BG)
    families = tkfont.families(app)
    family = next((f for f in ['Microsoft YaHei UI', 'Noto Sans CJK SC', 'WenQuanYi Micro Hei', 'Segoe UI'] if f in families), 'TkDefaultFont')
    app.option_add('*Font', (family, 10))
    icon = ImageTk.PhotoImage(Image.open(ASSETS / 'workdesk.png'), master=app)
    app.iconphoto(True, icon)
    app._icon = icon
    if os.name == 'nt':
        app.iconbitmap(str(ASSETS / 'workdesk.ico'))
    style = ttk.Style(app)
    style.theme_use('clam')
    style.configure('.', font=(family, 10), background=BG, foreground=INK)
    style.configure('Card.TFrame', background='white')
    style.configure('TLabel', background=BG)
    style.configure('Card.TLabel', background='white', foreground=INK)
    style.configure('Muted.TLabel', background='white', foreground=MUTED)
    style.configure('TButton', background='#e9f0ef', foreground=INK, borderwidth=0, padding=(15, 10))
    style.map('TButton', background=[('active', '#d8e6e3')], foreground=[('disabled', '#9caaa8')])
    style.configure('Primary.TButton', background=TEAL, foreground='white')
    style.map('Primary.TButton', background=[('active', '#116654'), ('disabled', '#acc6bf')], foreground=[('disabled', 'white')])
    style.configure('Danger.TButton', foreground='#a14137', background='#f8eae7')
    style.configure('TEntry', padding=8, fieldbackground='#f6f9f8', bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
    style.map('TEntry', bordercolor=[('focus', TEAL)])
    style.configure('TCheckbutton', background='white', padding=(0, 5))
    style.map('TCheckbutton', background=[('active', 'white')])
    # Explicit check marks avoid the clam theme's ambiguous cross indicator.
    indicators = []
    size = max(18, round(14 * float(app.tk.call('tk', 'scaling'))))
    for selected, disabled in [(False, False), (True, False), (False, True), (True, True)]:
        picture = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(picture)
        color = '#a7b8b4' if disabled else TEAL
        draw.rounded_rectangle((1, 1, size-2, size-2), radius=3,
                               fill=color if selected else 'white', outline=color, width=2)
        if selected:
            draw.line([(size*.23, size*.51), (size*.43, size*.71), (size*.78, size*.29)],
                      fill='white', width=max(2, round(size*.12)), joint='curve')
        indicators.append(ImageTk.PhotoImage(picture, master=app))
    app._check_indicators = indicators
    style.element_create('Workdesk.Check.indicator', 'image', indicators[0],
                         ('disabled', 'selected', indicators[3]), ('disabled', indicators[2]),
                         ('selected', indicators[1]), sticky='w')
    style.layout('TCheckbutton', [('Checkbutton.padding', {'sticky': 'nswe', 'children': [
        ('Workdesk.Check.indicator', {'side': 'left', 'sticky': ''}),
        ('Checkbutton.focus', {'side': 'left', 'sticky': 'w', 'children': [
            ('Checkbutton.label', {'sticky': 'nswe'})]})]})])
    style.configure('TRadiobutton', background='white', padding=(0, 5))
    style.configure('TNotebook', background=BG, borderwidth=0, tabmargins=0)
    style.configure('TNotebook', bordercolor=BG, lightcolor=BG, darkcolor=BG)
    style.layout('TNotebook.Tab', [])
    style.layout('Vertical.TScrollbar', [('Vertical.Scrollbar.trough', {'sticky':'ns', 'children':[
        ('Vertical.Scrollbar.thumb', {'expand':'1', 'sticky':'nswe'})]})])
    style.configure('Vertical.TScrollbar', background='#c9d8d5', troughcolor=BG, borderwidth=0, width=9)
    style.configure('Horizontal.TProgressbar', background=TEAL, troughcolor=BG, borderwidth=0)
    events = queue.Queue()
    health_events = queue.Queue()
    health_busy = False
    cached_connection = {}
    owner_edited = False
    busy = False
    widgets, contacts = [], []
    status = tk.StringVar(value='准备后台、扫码登录，然后打开工作台。AI 自动回复可按需开启。')
    try:
        saved = json.loads((platform.root / 'private-data/workdesk-native-ai.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        saved = {}
    try:
        saved_mode = json.loads((platform.runtime / 'desktop-mode.json').read_text()).get('mode', 'native')
    except (OSError, ValueError):
        saved_mode = 'native'
    mode = tk.StringVar(value=saved_mode if os.name == 'nt' and saved_mode in ('native', 'uia') else 'native')
    app.columnconfigure(1, weight=1)
    app.rowconfigure(0, weight=1)
    sidebar = tk.Frame(app, bg=INK, width=208)
    sidebar.grid(row=0, column=0, sticky='nsew')
    sidebar.grid_propagate(False)
    mark = ImageTk.PhotoImage(Image.open(ASSETS / 'workdesk.png').resize((58, 58)), master=app)
    tk.Label(sidebar, image=mark, bg=INK).pack(anchor='w', padx=23, pady=(30, 10))
    app._mark = mark
    tk.Label(sidebar, text='Workdesk', font=(family, 21, 'bold'), fg='white', bg=INK).pack(anchor='w', padx=24)
    tk.Label(sidebar, text='微信工作助手', fg='#a2bbb9', bg=INK).pack(anchor='w', padx=25, pady=(3, 32))
    content = ttk.Frame(app, padding=(28, 25, 28, 16))
    content.grid(row=0, column=1, sticky='nsew')
    content.columnconfigure(0, weight=1)
    content.rowconfigure(1, weight=1)
    header = ttk.Frame(content)
    header.grid(row=0, column=0, sticky='ew', pady=(0, 20))
    title = tk.StringVar(value='连接与登录')
    ttk.Label(header, textvariable=title, font=(family, 23, 'bold')).pack(side='left')
    badge = tk.Label(header, text='●  正在检查', bg='#e0ebe7', fg=TEAL, padx=13, pady=7, font=(family, 10, 'bold'))
    badge.pack(side='right')
    notebook = ttk.Notebook(content)
    notebook.grid(row=1, column=0, sticky='nsew')
    pages, canvases = [], []
    for _ in range(3):
        outer = ttk.Frame(notebook)
        notebook.add(outer)
        canvas = tk.Canvas(outer, background=BG, highlightthickness=0)
        bar = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        inner = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=inner, anchor='nw')
        inner.bind('<Configure>', lambda e, c=canvas: c.configure(scrollregion=c.bbox('all')))
        canvas.bind('<Configure>', lambda e, c=canvas, w=window: c.itemconfigure(w, width=e.width))
        pages.append(inner);canvases.append(canvas)
    nav = []
    names = ['连接与登录', 'AI 自动回复', '运行状态']
    def navigate(index):
        notebook.select(index);title.set(names[index])
        if index == 1:
            action_dock.grid()
            if not preview and not contacts and not busy and cached_connection.get('online'):
                task(platform.contacts, show_contacts)
        else:action_dock.grid_remove()
        for i, b in enumerate(nav):
            b.configure(bg='#29494e' if i == index else INK, fg='white' if i == index else '#b7cbca')
    for i, name in enumerate(names):
        b = tk.Button(sidebar, text=f'0{i+1}   {name}', anchor='w', relief='flat', bd=0,
                      bg=INK, fg='#b7cbca', activebackground='#29494e', activeforeground='white',
                      padx=18, pady=13, highlightthickness=0, cursor='hand2', command=lambda i=i: navigate(i))
        b.pack(fill='x', padx=12, pady=3);nav.append(b)
    tk.Label(sidebar, text='本机保存 · 由你掌控\n关闭窗口不会停止后台 AI', justify='left', bg=INK, fg='#9bb6b3',
             font=(family, 9), wraplength=165).pack(side='bottom', anchor='w', padx=23, pady=25)
    action_dock = ttk.Frame(content)
    action_dock.grid(row=2, column=0, sticky='ew', pady=(10, 0))
    footer = ttk.Frame(content)
    footer.grid(row=3, column=0, sticky='ew', pady=(15, 0))
    activity = ttk.Progressbar(footer, mode='indeterminate', length=75)
    ttk.Label(footer, textvariable=status, wraplength=660, foreground=MUTED).pack(side='left', fill='x', expand=True)

    def card(parent, heading, caption=None):
        border = tk.Frame(parent, bg=LINE, padx=1, pady=1)
        border.pack(fill='x', pady=(0, 16))
        frame = ttk.Frame(border, style='Card.TFrame', padding=20)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=heading, style='Card.TLabel', font=(family, 12, 'bold')).pack(anchor='w')
        if caption:
            ttk.Label(frame, text=caption, style='Muted.TLabel', wraplength=690).pack(anchor='w', pady=(5, 14))
        return frame

    def task(fn, done=None, failed=None):
        nonlocal busy
        if busy:return
        busy = True
        for widget in widgets:widget.configure(state='disabled')
        activity.pack(side='right', padx=(12, 0))
        activity.start(12)
        status.set('正在处理，请稍候…')
        def run():
            try:events.put((True, fn(), done))
            except Exception as error:
                events.put((False, str(error) if isinstance(error, ValueError) else '操作失败，请检查网络或重试。', failed))
        threading.Thread(target=run, daemon=True).start()

    def button(parent, text, callback, kind='TButton'):
        b = ttk.Button(parent, text=text, command=callback, style=kind)
        b.pack(side='left', padx=(0, 8), pady=3);widgets.append(b)
        return b

    intro = card(pages[0], '连接微信，开始工作', '使用原生后台连接，不占用你的鼠标和键盘。账号和密钥只保存在这台电脑。')
    for value, label in [('native', '原生后台模式（推荐）'), ('uia', '官方微信窗口模式')]:
        if os.name != 'nt' and value == 'uia':continue
        radio = ttk.Radiobutton(intro, text=label, variable=mode, value=value)
        radio.pack(anchor='w');widgets.append(radio)
    steps = card(pages[0], '三步完成连接')
    step_row = ttk.Frame(steps, style='Card.TFrame');step_row.pack(fill='x', pady=(16, 0))
    connection_note = tk.StringVar(value='首次使用请从准备后台开始；已登录时可直接打开工作台。')
    def prepared(online):
        connection_note.set('微信已登录，可以打开工作台。' if online else '后台已准备好，请扫码并在手机上确认登录。')
        status.set(connection_note.get())
        update_health(False)
    controls = []
    for i, (heading, description, text, callback) in enumerate([
        ('01  准备后台', '检查并启动本机连接服务', '准备后台', lambda: task(platform.prepare, prepared)),
        ('02  手机确认', '用微信扫码，确认登录', '扫码登录', lambda: task(platform.login, lambda _: prepared(True))),
        ('03  开始使用', '打开网页工作台查看会话', '打开工作台', lambda: task(lambda: platform.open(mode.get())))
    ]):
        part = ttk.Frame(step_row, style='Card.TFrame', padding=(0, 0, 12, 0))
        part.grid(row=0, column=i, sticky='nsew');step_row.columnconfigure(i, weight=1)
        ttk.Label(part, text=heading, style='Card.TLabel', font=(family, 11, 'bold')).pack(anchor='w')
        ttk.Label(part, text=description, style='Muted.TLabel', wraplength=190).pack(anchor='w', pady=(6, 12))
        controls.append(button(part, text, callback, 'Primary.TButton' if i == 2 else 'TButton'))
    ttk.Label(steps, textvariable=connection_note, style='Muted.TLabel', wraplength=690).pack(anchor='w', pady=(16, 0))
    guide = card(pages[0], '让助手按你的节奏工作', '连接后进入「AI 自动回复」配置服务与接管范围。开启前需要你明确授权。')
    ttk.Label(guide, text='手机确认登录时可能提示另一设备登录，请留意原有电脑端的会话状态。',
              style='Muted.TLabel', wraplength=690).pack(anchor='w')
    shortcut_actions=ttk.Frame(guide, style='Card.TFrame');shortcut_actions.pack(fill='x', pady=(10,0))
    button(shortcut_actions, '创建桌面快捷方式', lambda: task(platform.create_shortcut, status.set))
    fields = {}
    api = card(pages[1], '模型服务', '填写兼容服务的 API 地址与模型；密钥由系统加密保护，留空保存可保留已有密钥。')
    for name, label, default in [('endpoint','API 地址',''), ('model','模型 ID',''), ('apiKey','API 密钥',''),
                                  ('style','回复风格','自然口语化，简短友好，根据话题回复。')]:
        row = ttk.Frame(api, style='Card.TFrame');row.pack(fill='x', pady=5)
        ttk.Label(row, text=label, width=10, style='Card.TLabel').pack(side='left')
        entry = ttk.Combobox(row, values=[]) if name=='model' else ttk.Entry(row, show='●' if name == 'apiKey' else '')
        entry.insert(0, saved.get(name, default) if name != 'apiKey' else '')
        entry.pack(side='left', fill='x', expand=True);fields[name]=entry;widgets.append(entry)
    diagnostics=ttk.Frame(api,style='Card.TFrame');diagnostics.pack(fill='x',pady=(12,5))
    diagnostic_note=tk.StringVar(value='先获取模型列表，再测试文字对话；测试会发送一条很短的请求，可能使用少量额度。')
    def check_api(models=False):
        data={name:entry.get() for name,entry in fields.items()}
        diagnostic_note.set('正在获取模型列表…' if models else '正在测试，请稍候…')
        def done(result):
            if models:
                fields['model'].configure(values=result)
                if not fields['model'].get() and len(result)==1:fields['model'].set(result[0])
                diagnostic_note.set('已获取 %s 个模型，可在模型 ID 下拉框选择。模型列表不保证每个模型都可实际调用。'%len(result))
            else:diagnostic_note.set(result)
            status.set(diagnostic_note.get())
        task(lambda:platform.api_check(data,models=models),done,diagnostic_note.set)
    button(diagnostics,'测试对话连接',check_api)
    button(diagnostics,'获取模型列表',lambda:check_api(True))
    ttk.Label(api,textvariable=diagnostic_note,style='Muted.TLabel',wraplength=690).pack(anchor='w',pady=(5,0))
    scope = card(pages[1], '接管范围', '只回复你授权的好友和普通群聊，不回复公众号和系统通知。')
    all_chats = tk.BooleanVar(value=saved.get('allContacts', False))
    all_check = ttk.Checkbutton(scope, text='接管全部好友和普通群聊', variable=all_chats)
    all_check.pack(anchor='w');widgets.append(all_check)
    list_frame = ttk.Frame(scope, style='Card.TFrame');list_frame.pack(fill='x', pady=8)
    selection = tk.Listbox(list_frame, selectmode='multiple', height=5, exportselection=False,
                          bg='#f6f9f8', fg=INK, selectbackground='#d5eee5', selectforeground=INK,
                          relief='flat', highlightthickness=1, highlightbackground=LINE, activestyle='none')
    selection.pack(side='left', fill='both', expand=True)
    scroll = ttk.Scrollbar(list_frame, orient='vertical', command=selection.yview)
    scroll.pack(side='right', fill='y');selection.configure(yscrollcommand=scroll.set);widgets.append(selection)
    scope_ready = False
    scope_note = tk.StringVar(value='当前接管全部好友和普通群聊' if all_chats.get() else '当前已选择 %s 个会话' % len(saved.get('contacts', [])))
    ttk.Label(scope, textvariable=scope_note, style='Card.TLabel').pack(anchor='w', pady=(4, 2))
    visible_contacts = []
    scope_query = tk.StringVar(master=app)
    scope_kind = tk.StringVar(master=app, value='全部')
    scope_selected_only = tk.BooleanVar(master=app)
    filters = ttk.Frame(scope, style='Card.TFrame')
    filters.pack(fill='x', before=list_frame, pady=(6, 0))
    ttk.Label(filters, text='搜索', style='Card.TLabel').pack(side='left')
    ttk.Entry(filters, textvariable=scope_query, width=18).pack(side='left', padx=5)
    kind_box = ttk.Combobox(filters, textvariable=scope_kind, values=['全部','好友','群聊'], state='readonly', width=7)
    kind_box.pack(side='left', padx=5)
    ttk.Checkbutton(filters, text='只看已接管', variable=scope_selected_only).pack(side='left')
    def render_scope(*args):
        nonlocal scope_ready, visible_contacts
        scope_ready=False
        top=selection.yview()[0]
        selection.delete(0, 'end')
        visible_contacts=[]
        query=scope_query.get().strip().casefold()
        for item in contacts:
            checked=all_chats.get() or item['id'] in saved.get('contacts', [])
            name=item.get('remark') or item.get('displayName') or item.get('nickname') or item['id']
            group=item.get('kind')=='group' or item['id'].endswith('@chatroom')
            if query and query not in (name+' '+item['id']).casefold():continue
            if scope_kind.get()=='好友' and group or scope_kind.get()=='群聊' and not group:continue
            if scope_selected_only.get() and not checked:continue
            i=len(visible_contacts);visible_contacts.append(item)
            selection.insert('end', ('☑  ' if checked else '☐  ') + name)
            if checked:selection.selection_set(i)
        selection.yview_moveto(top)
        scope_ready=True
    for variable in (scope_query,scope_kind,scope_selected_only):variable.trace_add('write',render_scope)
    ttk.Label(scope, text='选择即时生效；筛选仅影响显示，不改变接管范围。', style='Muted.TLabel').pack(anchor='w')
    def apply_scope(event=None, override=None):
        if not scope_ready:return
        visible_ids={item['id'] for item in visible_contacts}
        selected_ids={visible_contacts[i]['id'] for i in selection.curselection()}
        old_ids=set(saved.get('contacts', []))
        if event is not None:
            expected=visible_ids if saved.get('allContacts') else old_ids & visible_ids
            if selected_ids==expected:return
            # Leaving global mode retains all other loaded conversations.
            old_ids={item['id'] for item in contacts} if saved.get('allContacts') else old_ids
            all_chats.set(False)
        ids=sorted((old_ids-visible_ids)|selected_ids) if event is not None else sorted(old_ids)
        if override is not None:ids=override
        try:
            result=platform.update_scope(all_chats.get(),ids)
            saved.update(allContacts=all_chats.get(), contacts=ids)
            render_scope()
            scope_note.set('✓ 已生效：全部好友和普通群聊' if all_chats.get() else '✓ 已生效：已选择 %s 个会话' % len(ids))
            status.set(result['status'])
        except Exception as error:
            all_chats.set(saved.get('allContacts',False));render_scope()
            scope_note.set('保存失败，已恢复原选择')
            status.set('接管范围未确认保存：'+str(error))
    all_check.configure(command=apply_scope)
    selection.bind('<<ListboxSelect>>', apply_scope)
    def show_contacts(items):
        nonlocal contacts, scope_ready
        scope_ready=False
        contacts=items
        report_choose.configure(values=['我的个人助手（文件传输助手）']+[(item.get('remark') or item.get('displayName') or item.get('nickname') or item['id']) for item in contacts])
        memory_choose.configure(values=['我的个人助手（文件传输助手）']+[(item.get('remark') or item.get('displayName') or item.get('nickname') or item['id']) for item in contacts])
        profile_choose.configure(values=[(item.get('remark') or item.get('displayName') or item.get('nickname') or item['id'])+' · '+item['id'] for item in contacts])
        render_scope()
        status.set('已刷新接管对象，点击会话即可选择，修改即时生效。')
    scope_ready = True
    actions = ttk.Frame(scope, style='Card.TFrame');actions.pack(fill='x')
    button(actions, '刷新会话列表', lambda: task(platform.contacts, show_contacts))
    def set_entire_scope(enabled):
        all_chats.set(enabled)
        apply_scope(override=[])
    button(actions, '一键接管全部', lambda: set_entire_scope(True))
    button(actions, '一键取消全部', lambda: set_entire_scope(False))

    capabilities = card(pages[1], '回复能力', '本区修改需点击下方保存；保存配置会暂停好友群聊，保存并开启会应用后恢复。亲自在微信发言后，该会话自动让开 10 分钟。')
    group_mentions = tk.BooleanVar(master=app, value=saved.get('groupMentionsOnly', True))
    web_search = tk.BooleanVar(value=saved.get('webSearch', False))
    media_replies = tk.BooleanVar(value=saved.get('mediaReplies', False))
    video_analysis=tk.BooleanVar(value=saved.get('videoAnalysis',False))
    voice_replies=tk.BooleanVar(value=saved.get('voiceReplies',False))
    owner_dialog=tk.BooleanVar(value=saved.get('ownerAssistant',False))
    language_names={'zh':'普通话','en':'英语','auto':'自动检测'}
    voice_language=tk.StringVar(value=language_names.get(saved.get('voiceLanguage','zh'),'普通话'))
    from ai_reply import endpoint as normalize_endpoint
    authorized_endpoint = saved.get('consentEndpoint', '')
    def endpoint_authorized():
        try:
            return bool(authorized_endpoint) and normalize_endpoint(fields['endpoint'].get()) == authorized_endpoint
        except Exception:
            return False
    consent = tk.BooleanVar(master=app, value=endpoint_authorized())
    consent_note = tk.StringVar(master=app)
    def consent_changed(*args):
        consent_note.set('已确认当前 API 的会话提交与自动回复授权；运行状态见下方。' if consent.get() else
                         '尚未确认当前 API 授权。此处不会暂停已运行的助手，停止回复请点“暂停 AI”。')
    def endpoint_changed(*args):
        try:
            consent.set(bool(authorized_endpoint) and normalize_endpoint(endpoint_text.get()) == authorized_endpoint)
        except Exception:
            consent.set(False)
    endpoint_text = tk.StringVar(master=app, value=fields['endpoint'].get())
    fields['endpoint'].configure(textvariable=endpoint_text)
    endpoint_text.trace_add('write', endpoint_changed)
    app._endpoint_text = endpoint_text
    consent.trace_add('write', consent_changed)
    consent_changed()
    def mark_owner_edited():
        nonlocal owner_edited
        owner_edited=True
    for text, variable in [('群聊仅在 @我 或引用我的消息时回复（减少插话）', group_mentions),
                           ('按需联网查询天气、新闻等（需要服务支持）', web_search),
                           ('按请求生成图片和表情图片（使用图像额度）', media_replies),
                           ('分析收到的 MP4 视频画面（抽帧，不含声音）', video_analysis),
                           ('本地语音转文字后回复（识别可能有误）', voice_replies),
                           ('文件传输助手个人对话（独立于好友群自动回复）', owner_dialog),
                           ('允许向上述 API 提交接管会话，并自动发送生成的回复', consent)]:
        check = ttk.Checkbutton(capabilities, text=text, variable=variable)
        if variable is owner_dialog:check.configure(command=mark_owner_edited)
        check.pack(anchor='w');widgets.append(check)
    ttk.Label(capabilities, textvariable=consent_note, style='Muted.TLabel', wraplength=670).pack(anchor='w', pady=(4,8))
    voice_row=ttk.Frame(capabilities,style='Card.TFrame');voice_row.pack(fill='x',pady=(8,0))
    ttk.Label(voice_row,text='语音识别语言',style='Card.TLabel').pack(side='left',padx=(0,12))
    language_box=ttk.Combobox(voice_row,textvariable=voice_language,values=list(language_names.values()),width=15,state='readonly')
    language_box.pack(side='left');widgets.append(language_box)
    def form_values():
        data={name: entry.get() for name, entry in fields.items()}
        data.update(contacts=saved.get('contacts', []), allContacts=all_chats.get(),
                    groupMentionsOnly=group_mentions.get(), webSearch=web_search.get(), mediaReplies=media_replies.get(), videoAnalysis=video_analysis.get(),
                    voiceReplies=voice_replies.get(), voiceLanguage=next((k for k,v in language_names.items() if v==voice_language.get()),'zh'),
                    ownerAssistant=owner_dialog.get(), ownerConsent=consent.get(), interval=1)
        return data
    def applied(result):
        nonlocal owner_edited, authorized_endpoint
        owner_edited=False
        if consent.get():
            authorized_endpoint=normalize_endpoint(fields['endpoint'].get())
        fields['apiKey'].delete(0, 'end')
        status.set(result['status'])
    def save():
        if mode.get() == 'uia':status.set('官方窗口模式的 AI 请在网页工作台设置中配置。');return
        if not consent.get():status.set('请先确认当前 API 的会话提交与自动回复授权。');return
        data=form_values()
        task(lambda: platform.configure_ai(data, start=False), applied)
    def start():
        if mode.get() == 'uia':status.set('官方窗口模式的 AI 请在网页工作台设置中开启。');return
        if not consent.get():status.set('请先勾选会话提交与自动回复授权。');return
        data=form_values()
        task(lambda: platform.configure_ai(data, start=True), applied)
    ai_actions = ttk.Frame(action_dock);ai_actions.pack(fill='x')
    button(ai_actions, '保存配置', save)
    button(ai_actions, '保存并开启 / 恢复 AI', start, 'Primary.TButton')
    button(ai_actions, '暂停 AI', lambda: task(lambda: platform.ai().pause(), lambda r: status.set(r['status'])), 'Danger.TButton')
    personal = card(pages[1], '联系人风格与长期备注', '在此选择联系人再点读取，不改变接管勾选。独立规则即时保存；长期备注由你维护。')
    profile_target = tk.StringVar(master=app, value='尚未选择联系人')
    profile_thread = [None]
    profile_choose=ttk.Combobox(personal,textvariable=profile_target,state='readonly')
    profile_choose.pack(fill='x')
    profile_choose.bind('<<ComboboxSelected>>',lambda event: profile_thread.__setitem__(0,None))
    profile_mode = tk.StringVar(master=app,value='自动回复')
    mode_names={'自动回复':'auto','先审核文字':'review','不回复':'off'}
    profile_mode_box=ttk.Combobox(personal,textvariable=profile_mode,values=list(mode_names),state='readonly')
    profile_mode_box.pack(anchor='w',pady=5)
    ttk.Label(personal,text='独立风格',style='Muted.TLabel').pack(anchor='w')
    profile_style=ttk.Entry(personal);profile_style.pack(fill='x');widgets.append(profile_style)
    ttk.Label(personal,text='长期备注（可随时修改或清空）',style='Muted.TLabel').pack(anchor='w')
    profile_memory=ttk.Entry(personal);profile_memory.pack(fill='x');widgets.append(profile_memory)
    def read_profile():
        index=profile_choose.current()
        if index<0 or index>=len(contacts):status.set('请先刷新联系人并在此选择对象。');return
        item=contacts[index];profile_thread[0]=item['id']
        memory_action(thread=item['id'])
        try:value=platform.conversation_profile(item['id'])
        except ValueError as error:status.set(str(error));return
        profile_style.delete(0,'end');profile_style.insert(0,value.get('style',''))
        profile_memory.delete(0,'end');profile_memory.insert(0,value.get('memory',''))
        profile_mode.set(next((k for k,v in mode_names.items() if v==value.get('mode','auto')),'自动回复'))
    def save_profile_ui():
        if not profile_thread[0]:status.set('请先读取一个联系人的规则。');return
        try:status.set(platform.conversation_profile(profile_thread[0],dict(style=profile_style.get(),memory=profile_memory.get(),mode=mode_names[profile_mode.get()])))
        except ValueError as error:status.set(str(error))
    profile_buttons=ttk.Frame(personal,style='Card.TFrame');profile_buttons.pack(fill='x',pady=6)
    button(profile_buttons,'读取选中联系人规则',read_profile)
    button(profile_buttons,'即时保存联系人规则',save_profile_ui)
    memory_card=card(pages[1],'聊天记忆','助手会记住接管聊天中的新文字，以后聊到相关事情时自动参考。你不用手动整理，也不用填写模型。')
    memory_target=['filehelper']
    memory_name=tk.StringVar(master=app,value='我的个人助手（文件传输助手）')
    choose_row=ttk.Frame(memory_card,style='Card.TFrame');choose_row.pack(fill='x',pady=(0,8))
    ttk.Label(choose_row,text='查看谁的记忆',style='Card.TLabel').pack(side='left',padx=(0,8))
    memory_choose=ttk.Combobox(choose_row,textvariable=memory_name,state='readonly',values=['我的个人助手（文件传输助手）'])
    memory_choose.pack(side='left',fill='x',expand=True);memory_choose.current(0)
    memory_state=tk.StringVar(master=app,value='选择对象后，即可查看记忆。')
    ttk.Label(memory_card,textvariable=memory_state,style='Card.TLabel').pack(anchor='w',pady=4)
    memory_hint=tk.StringVar(master=app,value='')
    ttk.Label(memory_card,textvariable=memory_hint,style='Muted.TLabel',wraplength=660).pack(anchor='w',pady=4)
    memory_box=ttk.Frame(memory_card,style='Card.TFrame');memory_box.pack(fill='x',pady=5)
    memory_list=tk.Listbox(memory_box,height=5,exportselection=False)
    memory_list.pack(side='left',fill='x',expand=True)
    memory_scroll=ttk.Scrollbar(memory_box,orient='vertical',command=memory_list.yview)
    memory_scroll.pack(side='right',fill='y');memory_list.configure(yscrollcommand=memory_scroll.set)
    memory_detail=tk.StringVar(master=app,value='')
    detail_label=ttk.Label(memory_card,textvariable=memory_detail,style='Card.TLabel',wraplength=660)
    detail_label.pack(anchor='w',pady=4)
    memory_box.pack_forget()
    memory_rows=[]
    memory_on=[True]
    def show_memory(event=None):
        indices=memory_list.curselection()
        delete_memory.configure(state='normal' if indices else 'disabled')
        if indices:
            row=memory_rows[indices[0]]
            memory_detail.set('收到时间：'+row['stamp']+'\n'+row['text'])
    memory_list.bind('<<ListboxSelect>>',show_memory)
    def memory_action(action=None,thread=None):
        nonlocal memory_rows
        if thread:
            memory_target[0]=thread
            memory_name.set('我的个人助手（文件传输助手）' if thread=='filehelper' else next((item.get('remark') or item.get('displayName') or item.get('nickname') or thread for item in contacts if item['id']==thread),thread))
        target=memory_target[0]
        identifier=None
        if action=='delete':
            indices=memory_list.curselection()
            if not indices:return
            identifier=memory_rows[indices[0]]['message']
        if action=='clear':
            from tkinter import messagebox
            if not messagebox.askyesno('清空聊天记忆','清空“'+memory_name.get()+'”的全部记忆？清空前的旧消息不会自动学回来；主动导入历史时可重新学习。',parent=app):return
        try:
            result=platform.conversation_memory(target,action,identifier)
            memory_on[0]=result['enabled'];memory_rows=result['items']
            memory_list.delete(0,'end');memory_detail.set('')
            if memory_rows:memory_box.pack(fill='x',pady=5,before=detail_label)
            else:memory_box.pack_forget()
            for row in memory_rows:memory_list.insert('end',row['text'].replace('\n',' ')[:70])
            memory_state.set(('● 记忆已开启' if result['enabled'] else '○ 记忆已关闭')+' · 已记住 %s 条'%len(memory_rows))
            if result['enabled']:
                memory_hint.set('还没有记忆。助手处理此对象的新文字后会自动记住，再点“刷新”查看；不会自动导入旧记录，可用下方“预览并学习历史”补充。' if not memory_rows else '点击一条可查看原话。回复时会自动参考相关记忆，不需要你手动选择。')
            else:memory_hint.set('已停止记住和参考此对象的聊天；原有记忆保留，可删除或重新开启。')
            if target=='filehelper':memory_hint.set(memory_hint.get()+' 个人助手需保持开启。')
            else:memory_hint.set(memory_hint.get()+' 好友/群聊需在接管范围内且 AI 已开启。')
            toggle_memory.configure(text='关闭此对象的记忆' if result['enabled'] else '开启此对象的记忆')
            delete_memory.configure(state='disabled');clear_memory.configure(state='normal' if memory_rows else 'disabled')
            status.set('已删除选中记忆。' if action=='delete' else '已清空当前对象记忆。' if action=='clear' else '记忆设置已即时生效，无需保存。' if action else '记忆已刷新。')
        except (ValueError,OSError) as error:memory_hint.set('读取失败：'+str(error))
    def choose_memory(event=None):
        index=memory_choose.current()
        if index==0:memory_action(thread='filehelper')
        elif 0<index<=len(contacts):memory_action(thread=contacts[index-1]['id'])
    memory_choose.bind('<<ComboboxSelected>>',choose_memory)
    memory_buttons=ttk.Frame(memory_card,style='Card.TFrame');memory_buttons.pack(fill='x',pady=5)
    button(memory_buttons,'刷新',lambda:memory_action())
    toggle_memory=button(memory_buttons,'关闭此对象的记忆',lambda:memory_action('disable' if memory_on[0] else 'enable'))
    delete_memory=button(memory_buttons,'删除选中记忆',lambda:memory_action('delete'));delete_memory.configure(state='disabled')
    clear_memory=button(memory_buttons,'清空此对象记忆',lambda:memory_action('clear'));clear_memory.configure(state='disabled')
    ttk.Label(memory_card,text='开关与删除立即生效，无需再点保存。每个对象最多保留500条、90天。',style='Muted.TLabel').pack(anchor='w',pady=(3,8))
    history_row=ttk.Frame(memory_card,style='Card.TFrame');history_row.pack(fill='x',pady=(8,3))
    ttk.Label(history_row,text='从以前的聊天学习',style='Card.TLabel').pack(side='left',padx=(0,8))
    history_days=tk.StringVar(master=app,value='最近30天')
    history_range=ttk.Combobox(history_row,textvariable=history_days,values=['最近7天','最近30天','最近90天'],state='readonly',width=10)
    history_range.pack(side='left')
    def preview_history():
        target=memory_target[0]
        days={'最近7天':7,'最近30天':30,'最近90天':90}[history_days.get()]
        def show_preview(result):
            if not result['count']:
                memory_hint.set('没有读到这个时间范围内可学习的文字。只能读取本机后台已同步的记录，不代表手机里没有历史。');return
            from tkinter import messagebox
            details='对象：'+result['name']+'\n可读取文字：%s 条（最多500条）'%result['count']
            if result['limited']:details+='\n记录较多，本次仅预览已读取部分。'
            details+='\n\n最近原话预览：\n'+'\n'.join(result['examples'][:5])
            details+='\n\n继续后会向已配置的 API 提交部分原话，由 AI 提取记忆；并建立原话检索。不会发送微信消息，不会开启自动回复。是否开始？'
            if not messagebox.askyesno('预览历史学习',details,parent=app):return
            def imported(value):
                memory_action(thread=target)
                memory_hint.set('已处理 %s 条原话，AI 阅读其中 %s 条并提取 %s 条记忆；重复记录自动跳过。'%(value['originals'],value['sampled'],value['summaries']))
            app.after(10,lambda:task(lambda:platform.history_memory_import(result['token']),imported))
        task(lambda:platform.history_memory_preview(target,days),show_preview)
    button(history_row,'预览并学习历史',preview_history)
    ttk.Label(memory_card,text='只读取本机已同步的历史；先预览再学习，不会给对方发消息。',style='Muted.TLabel',wraplength=660).pack(anchor='w',pady=(0,6))
    advanced=ttk.Frame(memory_card,style='Card.TFrame')
    def toggle_memory_advanced():
        if advanced.winfo_manager():advanced.pack_forget();advanced_button.configure(text='高级设置（可选） ▸')
        else:advanced.pack(fill='x',pady=5);advanced_button.configure(text='收起高级设置 ▾')
    advanced_button=button(memory_card,'高级设置（可选） ▸',toggle_memory_advanced)
    ttk.Label(advanced,text='默认本地检索已可使用。仅当你的 API 提供 Embedding 模型时填写下项；启用后会把相关聊天文字提交给该 API。',style='Muted.TLabel',wraplength=660).pack(anchor='w')
    embedding_entry=ttk.Entry(advanced);embedding_entry.pack(fill='x',pady=5)
    if not preview:embedding_entry.insert(0,platform.memory_embedding())
    def save_embedding():
        try:status.set(platform.memory_embedding(embedding_entry.get()))
        except ValueError as error:status.set(str(error))
    button(advanced,'保存高级检索设置',save_embedding)
    if not preview:app.after(100,lambda:memory_action())
    report_card=card(pages[2],'聊天总结报告','选择联系人或群聊，读取指定范围后生成 AI 报告。不会发送微信消息，也不会修改接管或记忆设置。')
    report_choose=ttk.Combobox(report_card,state='readonly',values=['我的个人助手（文件传输助手）'])
    report_choose.pack(fill='x');report_choose.current(0)
    button(report_card,'刷新联系人列表',lambda:task(platform.contacts,show_contacts))
    report_mode=tk.StringVar(master=app,value='日期范围')
    report_mode_box=ttk.Combobox(report_card,textvariable=report_mode,state='readonly',values=['日期范围','最近消息条数','全部已同步记录'])
    report_mode_box.pack(anchor='w',pady=5)
    from datetime import date,timedelta
    ttk.Label(report_card,text='开始日期',style='Card.TLabel').pack(anchor='w')
    report_start=ttk.Entry(report_card);report_start.insert(0,str(date.today()-timedelta(days=7)));report_start.pack(fill='x')
    ttk.Label(report_card,text='结束日期',style='Card.TLabel').pack(anchor='w')
    report_end=ttk.Entry(report_card);report_end.insert(0,str(date.today()));report_end.pack(fill='x',pady=4)
    ttk.Label(report_card,text='开始日期 / 结束日期：YYYY-MM-DD，包含结束日，按本机时区。',style='Muted.TLabel').pack(anchor='w')
    ttk.Label(report_card,text='最近消息条数',style='Card.TLabel').pack(anchor='w')
    report_count=ttk.Entry(report_card);report_count.insert(0,'1000');report_count.pack(fill='x',pady=4)
    ttk.Label(report_card,text='条数填写正整数，无预设上限；全部记录模式不需要填条数。只读取本机已同步记录，图片/语音/视频仅标注类型。消息越多处理越久，可取消。',style='Muted.TLabel',wraplength=660).pack(anchor='w')
    report_note=tk.StringVar(master=app,value='尚未生成报告。')
    ttk.Label(report_card,textvariable=report_note,style='Card.TLabel',wraplength=660).pack(anchor='w',pady=6)
    report_job={'running':False,'cancel':threading.Event(),'result':None}
    report_events=queue.Queue()
    def report_fields(*args):
        report_start.configure(state='normal' if report_mode.get()=='日期范围' else 'disabled')
        report_end.configure(state='normal' if report_mode.get()=='日期范围' else 'disabled')
        report_count.configure(state='normal' if report_mode.get()=='最近消息条数' else 'disabled')
    report_mode.trace_add('write',report_fields);report_fields()
    def show_report():
        result=report_job['result']
        if not result:return
        window=tk.Toplevel(app);window.title('聊天总结报告');window.geometry('850x650')
        from tkinter.scrolledtext import ScrolledText
        body=ScrolledText(window,wrap='word',font=(family,10));body.pack(fill='both',expand=True,padx=12,pady=12)
        body.insert('1.0',result['text']);body.configure(state='disabled')
        for sequence in ('<MouseWheel>','<Button-4>','<Button-5>'):
            body.bind(sequence,lambda event:(body.yview_scroll(wheel_units(event),'units'),'break')[1])
        def export():
            from tkinter import filedialog
            path=filedialog.asksaveasfilename(parent=window,title='导出总结报告',defaultextension='.md',filetypes=[('Markdown报告','*.md'),('文字文件','*.txt')])
            if path:
                try:Path(path).write_text(result['text'],encoding='utf-8');report_note.set('报告已导出。')
                except OSError:report_note.set('导出失败，请检查保存位置。')
        ttk.Button(window,text='导出报告',command=export).pack(pady=(0,10))
    def start_report():
        if report_job['running']:return
        index=report_choose.current()
        if index<0 or index>len(contacts):report_note.set('请先选择联系人或群聊。');return
        target='filehelper' if index==0 else contacts[index-1]['id']
        chosen={'日期范围':'date','最近消息条数':'count','全部已同步记录':'all'}[report_mode.get()]
        try:
            amount=int(report_count.get()) if chosen=='count' else None
            if chosen=='count' and amount<=0:raise ValueError()
        except ValueError:report_note.set('消息条数请填写正整数。');return
        first,last=report_start.get(),report_end.get()
        if chosen=='date':
            from chat_report import date_window
            try:date_window(first,last)
            except ValueError as error:report_note.set(str(error));return
        report_job['running']=True;report_job['cancel'].clear()
        report_note.set('开始读取记录…');report_start_button.configure(state='disabled');report_cancel_button.configure(state='normal')
        def run_report():
            try:
                value=platform.chat_summary_report(target,chosen,first,last,amount,lambda text:report_events.put(('progress',text)),report_job['cancel'].is_set)
                report_events.put(('done',value))
            except Exception as error:report_events.put(('error',str(error) if isinstance(error,ValueError) else '生成失败，请检查微信连接或 API 后重试。'))
        threading.Thread(target=run_report,daemon=True).start()
        poll_report()
    def poll_report():
        try:
            while True:
                kind,value=report_events.get_nowait()
                if kind=='progress':report_note.set(value)
                else:
                    report_job['running']=False;report_start_button.configure(state='normal');report_cancel_button.configure(state='disabled')
                    if kind=='done':report_job['result']=value;report_note.set('报告完成，共处理 %s 条消息。'%value['count']);show_report()
                    else:report_note.set(value)
        except queue.Empty:pass
        if report_job['running']:report_job['after']=app.after(150,poll_report)
    def close_report_job(event):
        if event.widget is app:
            report_job['cancel'].set()
            if report_job.get('after'):
                try:app.after_cancel(report_job['after'])
                except tk.TclError:pass
    app.bind('<Destroy>',close_report_job,add='+')
    report_actions=ttk.Frame(report_card,style='Card.TFrame');report_actions.pack(fill='x')
    report_start_button=button(report_actions,'读取并生成报告',start_report)
    report_cancel_button=button(report_actions,'取消生成',lambda:(report_job['cancel'].set(),report_note.set('正在取消，当前网络请求结束后停止…')));report_cancel_button.configure(state='disabled')
    button(report_actions,'查看上次报告',show_report)
    review = card(pages[2], '待审核文字回复', '只显示最近 24 小时的草稿。批准后由后台复核范围再发送；未知发送结果不会自动重试。')
    review_list=tk.Listbox(review,height=5,exportselection=False);review_list.pack(fill='x')
    review_rows=[]
    draft_text=tk.StringVar(master=app)
    draft_editor=ttk.Entry(review,textvariable=draft_text)
    draft_editor.pack(fill='x',pady=5)
    def show_review(event=None):
        indices=review_list.curselection()
        if indices:draft_text.set(review_rows[indices[0]]['text'])
    review_list.bind('<<ListboxSelect>>',show_review)
    def refresh_reviews():
        nonlocal review_rows
        review_rows=platform.review_drafts();review_list.delete(0,'end')
        for row in review_rows:review_list.insert('end',row['thread']+' · '+row['state']+' · '+row['text'])
        if not review_rows:status.set('暂无待审核草稿。')
    def decide_review(approved):
        indices=review_list.curselection()
        if not indices:status.set('请先选择草稿。');return
        try:status.set(platform.review_drafts(review_rows[indices[0]]['key'],approved,text=draft_text.get() if approved else None))
        except ValueError as error:status.set(str(error))
        refresh_reviews()
    review_buttons=ttk.Frame(review,style='Card.TFrame');review_buttons.pack(fill='x')
    button(review_buttons,'刷新草稿',refresh_reviews)
    button(review_buttons,'批准发送当前文字',lambda:decide_review(True))
    button(review_buttons,'丢弃草稿',lambda:decide_review(False))
    recovery=card(pages[2],'本机偏好备份与恢复','备份范围和风格、联系人备注；不含密钥、登录态或消息队列。恢复前会自动另存当前偏好，需要先停止两个助手。')
    backup_name=tk.StringVar(master=app)
    ttk.Entry(recovery,textvariable=backup_name).pack(fill='x')
    button(recovery,'创建本机快照',lambda:task(platform.backup_settings,lambda value:status.set(value)))
    def restore_preferences():
        from tkinter import messagebox
        if not backup_name.get().strip():status.set('请填写本机快照的完整路径。');return
        if messagebox.askyesno('恢复偏好','恢复所选快照中的范围、风格和联系人备注？当前偏好会先备份。',parent=app):
            name=backup_name.get().strip();task(lambda:platform.backup_settings(name),lambda value:status.set(value))
    button(recovery,'校验并恢复偏好',restore_preferences)
    trial = card(pages[1], '试聊预览', '使用已保存的 API 和风格测试一条虚构消息，只显示在这里，不发微信、不调用图片或联网工具。修改风格后请先保存。')
    trial_input = ttk.Entry(trial)
    trial_input.pack(fill='x', pady=(0,6));widgets.append(trial_input)
    trial_result = tk.StringVar(master=app, value='输入一句虚构的聊天消息，看看助手怎么接话。')
    ttk.Label(trial, textvariable=trial_result, style='Card.TLabel', wraplength=660).pack(anchor='w', pady=8)
    def try_chat():
        text=trial_input.get()
        trial_result.set('正在试聊…')
        task(lambda:platform.preview_reply(text), trial_result.set, trial_result.set)
    button(trial, '预览回复（不发送微信）', try_chat)
    summary = tk.StringVar(value='正在读取运行状态…')
    details = tk.StringVar(value='')
    health = card(pages[2], '当前运行状态')
    ttk.Label(health, textvariable=summary, style='Card.TLabel', font=(family, 16, 'bold'), wraplength=680).pack(anchor='w', pady=(14, 8))
    ttk.Label(health, textvariable=details, style='Muted.TLabel', wraplength=680, justify='left').pack(anchor='w', pady=(0, 15))
    health_actions = ttk.Frame(health, style='Card.TFrame');health_actions.pack(fill='x')
    button(health_actions, '立即检查', lambda: task(platform.health, show_health))
    button(health_actions, '暂停 AI', lambda: task(lambda: platform.ai().pause(), lambda r: status.set(r['status'])), 'Danger.TButton')
    commands = card(pages[2], '在微信里，也能掌控助手', '仅响应你账号发出的口令；好友和群成员的开关及查询口令会被忽略。')
    for heading, example in [('暂停回复', '关闭AI回复 / 停止AI回复'), ('恢复回复', '打开AI回复 / 开启AI回复'),
                             ('查询状态', '查询AI回复状态 / 查询AI自动回复状态'),
                             ('个人助手', '开启个人助手 / 关闭个人助手')]:
        line = ttk.Frame(commands, style='Card.TFrame');line.pack(fill='x', pady=7)
        ttk.Label(line, text=heading, width=12, style='Card.TLabel', font=(family, 10, 'bold')).pack(side='left')
        ttk.Label(line, text=example, style='Muted.TLabel', wraplength=530).pack(side='left')
    ttk.Label(commands, text='暂停后仍可查询、恢复。建议在文件传输助手中使用，查询结果会回复到发出口令的会话。',
              style='Muted.TLabel', wraplength=690).pack(anchor='w', pady=(12, 0))
    def show_health(value):
        nonlocal cached_connection
        cached_connection=value.get('connection', {})
        enabled=value.get('enabled', False)
        online=cached_connection.get('online',False)
        label=('微信已连接' if online else '已登录 · 连接中' if cached_connection.get('authenticated') else
               '等待扫码' if cached_connection.get('serviceReady') else '后台未连接')
        if mode.get()=='uia':label='官方窗口模式'
        badge.configure(text='●  '+label, fg=TEAL if online else '#986b34',
                        bg='#e0eee6' if online else '#f3ebdd')
        metrics=value.get('metrics', {})
        summary.set(('微信连接未就绪，暂不能自动回复' if not online else
                     '监听异常，正在重试' if value.get('health',{}).get('state')!='ready' else
                     '部分会话需要核对' if metrics.get('blocked',0) else
                     '正在处理新消息' if metrics.get('active',0) else '正在接管，等待新消息') if enabled else 'AI 当前已暂停' if value.get('paused') else 'AI 监听未就绪或尚未开启')
        if not owner_edited and not busy:
            try:
                current=json.loads((platform.root/'private-data/workdesk-native-ai.json').read_text(encoding='utf-8'))
                owner_dialog.set(current.get('ownerAssistant',False))
            except (OSError,ValueError):pass
        owner_health=value.get('ownerHealth',{})
        if not enabled and value.get('paused') and value.get('ownerAssistant') and owner_health.get('ready'):
            summary.set('好友/群 AI 已暂停；个人助手可用')
        health_info=value.get('health', {})
        details.set(('本人口令：' + ('监听正常' if value.get('ownerCommands') else '未就绪')
                     + '    ·    累计回复：%s 条' % value.get('metrics', {}).get('replies', 0)
                     + '\n\n微信连接：' + cached_connection.get('detail', '尚未检查')
                     + '\n\nAPI：未持续探测；请在 AI 设置中测试对话连接确认当前可用性。'
                     + '\n\n好友群范围：' + ('全部好友和普通群聊' if value.get('allContacts') else '已选择 %s 个会话' % len(value.get('contacts',[])))
                     + '\n\n' + value.get('status', '')
                     + '\n\n处理中 %s · 排队 %s · 待核对 %s' % (metrics.get('active',0),metrics.get('queued',0),metrics.get('blocked',0))
                     + '\n\n监听心跳：%s 秒前' % health_info.get('scanAgeSeconds', '—')))
        details.set(details.get()+'\n\n个人助手：'+('待核对发送结果' if owner_health.get('state')=='blocked' else '工作中' if owner_health.get('state')=='working' else '监听正常' if owner_health.get('ready') else '未就绪或已关闭')
                    +' · 累计回复 %s 条'%owner_health.get('replies',0))
        holds=value.get('manualHolds',{})
        if holds:
            labels={item['id']:item.get('remark') or item.get('displayName') or item.get('nickname') or item['id'] for item in contacts}
            details.set(details.get()+'\n\n人工接管中：'+ '、'.join(labels.get(k,k) for k in holds)+'（本人发言后让开 10 分钟）')
        if mode.get()=='native':connection_note.set(cached_connection.get('detail','正在检查后台状态…'))
        if not busy and status.get().startswith('准备后台、扫码登录'):
            status.set(cached_connection.get('detail','正在检查后台状态…'))
        if mode.get()=='uia':summary.set('官方窗口模式的运行状态请在网页工作台查看')
        sync_connection_buttons()

    def sync_connection_buttons():
        if busy:return
        native=mode.get()=='native'
        ready=cached_connection.get('serviceReady',False) and not cached_connection.get('errorKind') and not cached_connection.get('needsAccount')
        authenticated=cached_connection.get('authenticated',False)
        controls[0].configure(text='后台已就绪' if ready else '准备后台', state='disabled' if not native or ready else 'normal')
        controls[1].configure(text='微信已登录' if cached_connection.get('online') else '已登录 · 连接中' if authenticated else '扫码登录',
                              state='disabled' if not native or authenticated or not ready else 'normal')
    def mode_changed(*_):
        window_mode=mode.get()=='uia'
        sync_connection_buttons()
        if window_mode:
            connection_note.set('先登录官方电脑版微信，再打开工作台。此模式的 AI 在网页中配置。')
        else:connection_note.set(cached_connection.get('detail','正在检查本机后台…'))
    mode.trace_add('write', mode_changed)
    mode_changed();navigate(0)
    qr_window = tk.Toplevel(app)
    qr_window.title('Workdesk · 手机扫码登录');qr_window.geometry('330x370');qr_window.configure(bg='white')
    qr_window.withdraw();qr_window.protocol('WM_DELETE_WINDOW', qr_window.withdraw)
    qr_window.iconphoto(True, icon)
    tk.Label(qr_window, text='用微信扫码，确认连接', font=(family, 14, 'bold'), bg='white', fg=INK).pack(pady=(22, 12))
    qr = tk.Label(qr_window, bg='white');qr.pack()
    tk.Label(qr_window, text='请在自己的手机上确认登录', bg='white', fg=MUTED).pack(pady=14)
    qr_stamp=None
    def poll():
        nonlocal busy, qr_stamp, health_busy
        try:
            ok, result, done=events.get_nowait();busy=False;activity.stop();activity.pack_forget()
            for widget in widgets:widget.configure(state='normal')
            language_box.configure(state='readonly')
            mode_changed();status.set('操作完成。' if ok else result)
            if done:
                try:done(result)
                except Exception:status.set('结果显示失败，请重新检查状态。')
            qr.configure(image='');qr.image=None;qr_window.withdraw()
        except queue.Empty:pass
        try:
            ok, value=health_events.get_nowait();health_busy=False
            if ok:show_health(value)
            else:
                show_health({'enabled':False,'connection':{'detail':value},'status':'无法确认 AI 状态，请稍后重试。'})
                summary.set('状态检查失败，未确认连接或 AI 状态')
        except queue.Empty:pass
        path=platform.root/'login.png'
        if busy and path.exists():
            try:
                stamp=path.stat().st_mtime_ns
                if stamp != qr_stamp:
                    with Image.open(path) as picture:
                        picture.thumbnail((240,240));photo=ImageTk.PhotoImage(picture.copy(), master=app)
                    qr.configure(image=photo);qr.image=photo;qr_stamp=stamp;qr_window.deiconify()
            except OSError:pass
        app.after(250, poll)
    def update_health(repeat=True):
        nonlocal health_busy
        if not busy and not health_busy and mode.get()=='native':
            health_busy=True
            def check():
                try:health_events.put((True,platform.health()))
                except Exception:health_events.put((False,'本机后台状态读取失败。'))
            threading.Thread(target=check,daemon=True).start()
        if repeat:app.after(3000, update_health)
    def wheel_units(event):
        number = getattr(event, 'num', None)
        if number in (4, 5):
            return -1 if number == 4 else 1
        delta = getattr(event, 'delta', 0)
        return (-max(1, round(abs(delta) / 120)) if delta > 0 else
                max(1, round(abs(delta) / 120)) if delta < 0 else 0)
    def list_wheel(event):
        selection.yview_scroll(wheel_units(event), 'units')
        return 'break'
    def wheel(event):
        canvas = canvases[notebook.index('current')]
        widget = event.widget
        # Only the page under the pointer scrolls; sidebar/footer/dialogs do not.
        while widget is not None and widget is not canvas:
            widget = getattr(widget, 'master', None)
        if widget is canvas:
            canvas.yview_scroll(wheel_units(event), 'units')
            return 'break'
    for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
        selection.bind(sequence, list_wheel)
        # Scrolling past a model/language field must not silently change it.
        fields['model'].bind(sequence, lambda event: 'break')
        language_box.bind(sequence, lambda event: 'break')
        kind_box.bind(sequence, lambda event: 'break')
        profile_mode_box.bind(sequence, lambda event: 'break')
        profile_choose.bind(sequence, lambda event: 'break')
        memory_choose.bind(sequence, lambda event: 'break')
        history_range.bind(sequence, lambda event: 'break')
        report_choose.bind(sequence, lambda event: 'break')
        report_mode_box.bind(sequence, lambda event: 'break')
        memory_list.bind(sequence,lambda event:(memory_list.yview_scroll(wheel_units(event),'units'),'break')[1])
        review_list.bind(sequence, lambda event: (review_list.yview_scroll(wheel_units(event),'units'), 'break')[1])
        app.bind(sequence, wheel)
    app.console = dict(notebook=notebook, navigate=navigate, fields=fields, status=status, summary=summary,
                       consent=consent, start=start, save=save, canvases=canvases, selection=selection, show_contacts=show_contacts, scope_note=scope_note, set_entire_scope=set_entire_scope, memory_action=memory_action, memory_choose=memory_choose, memory_hint=memory_hint, memory_state=memory_state, memory_advanced=advanced, toggle_memory_advanced=toggle_memory_advanced, scope_query=scope_query, scope_kind=scope_kind, scope_selected_only=scope_selected_only,
                       webSearch=web_search, mediaReplies=media_replies, allContacts=all_chats, videoAnalysis=video_analysis, voiceReplies=voice_replies, ownerAssistant=owner_dialog)
    app.console.update(apply_health=show_health, connection_buttons=controls, badge=badge)
    if preview:
        show_health({'enabled':False, 'ownerCommands':True, 'metrics':{'replies':0},
                     'health':{'scanAgeSeconds':0}, 'status':'预览模式，不连接微信，也不发送消息。'})
    else:
        poll();update_health()
        if mode.get()=='native':
            app.after(350, lambda: None if cached_connection.get('serviceReady') else task(platform.prepare, prepared))
    return app
