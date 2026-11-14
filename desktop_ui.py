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
        if index == 1:action_dock.grid()
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
    def render_scope():
        nonlocal scope_ready
        scope_ready=False
        top=selection.yview()[0]
        selection.delete(0, 'end')
        for i, item in enumerate(contacts):
            checked=all_chats.get() or item['id'] in saved.get('contacts', [])
            name=item.get('remark') or item.get('displayName') or item.get('nickname') or item['id']
            selection.insert('end', ('☑  ' if checked else '☐  ') + name)
            if checked:selection.selection_set(i)
        selection.yview_moveto(top)
        scope_ready=True
    ttk.Label(scope, text='点击会话可逐个选择或取消，立即生效；取消全部选择后不回复好友和群聊。', style='Muted.TLabel').pack(anchor='w')
    def apply_scope(event=None):
        if not scope_ready:
            return
        ids = [contacts[i]['id'] for i in selection.curselection()] if contacts else saved.get('contacts', [])
        if event is not None:
            expected = {item['id'] for item in contacts} if all_chats.get() else set(saved.get('contacts', [])) & {item['id'] for item in contacts}
            if set(ids) == expected:
                return
            all_chats.set(False)
        try:
            result = platform.update_scope(all_chats.get(), ids)
            saved.update(allContacts=all_chats.get(), contacts=ids)
            render_scope()
            scope_note.set('✓ 已生效：全部好友和普通群聊' if all_chats.get() else '✓ 已生效：已选择 %s 个会话' % len(ids))
            status.set(result['status'])
        except Exception as error:
            all_chats.set(saved.get('allContacts', False))
            render_scope()
            scope_note.set('保存失败，已恢复原选择')
            status.set('接管范围未确认保存：' + str(error))
    all_check.configure(command=apply_scope)
    selection.bind('<<ListboxSelect>>', apply_scope)
    def show_contacts(items):
        nonlocal contacts, scope_ready
        scope_ready=False
        contacts=items
        render_scope()
        status.set('已刷新接管对象，点击会话即可选择，修改即时生效。')
    scope_ready = True
    actions = ttk.Frame(scope, style='Card.TFrame');actions.pack(fill='x')
    button(actions, '刷新会话列表', lambda: task(platform.contacts, show_contacts))
    def set_entire_scope(enabled):
        nonlocal scope_ready
        previous = scope_ready
        scope_ready = False
        all_chats.set(enabled)
        selection.selection_clear(0, 'end')
        if enabled:
            selection.selection_set(0, 'end')
        scope_ready = previous
        # Clear remembered individual IDs too when cancelling everything.
        if not enabled:
            old_contacts = saved.get('contacts', [])
            saved['contacts'] = []
            apply_scope()
            if '保存失败' in scope_note.get():
                saved['contacts'] = old_contacts
                render_scope()
        else:
            apply_scope()
    button(actions, '一键接管全部', lambda: set_entire_scope(True))
    button(actions, '一键取消全部', lambda: set_entire_scope(False))

    capabilities = card(pages[1], '回复能力')
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
    for text, variable in [('按需联网查询天气、新闻等（需要服务支持）', web_search),
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
        data.update(contacts=[contacts[i]['id'] for i in selection.curselection()] if contacts else saved.get('contacts', []), allContacts=all_chats.get(),
                    webSearch=web_search.get(), mediaReplies=media_replies.get(), videoAnalysis=video_analysis.get(),
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
                     + '\n\n' + value.get('status', '')
                     + '\n\n处理中 %s · 排队 %s · 待核对 %s' % (metrics.get('active',0),metrics.get('queued',0),metrics.get('blocked',0))
                     + '\n\n监听心跳：%s 秒前' % health_info.get('scanAgeSeconds', '—')))
        details.set(details.get()+'\n\n个人助手：'+('待核对发送结果' if owner_health.get('state')=='blocked' else '工作中' if owner_health.get('state')=='working' else '监听正常' if owner_health.get('ready') else '未就绪或已关闭')
                    +' · 累计回复 %s 条'%owner_health.get('replies',0))
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
        app.bind(sequence, wheel)
    app.console = dict(notebook=notebook, navigate=navigate, fields=fields, status=status, summary=summary,
                       consent=consent, start=start, save=save, canvases=canvases, selection=selection, show_contacts=show_contacts, scope_note=scope_note, set_entire_scope=set_entire_scope,
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
