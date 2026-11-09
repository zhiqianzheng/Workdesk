package com.workdesk.android;

import android.app.*;
import android.content.*;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.*;
import android.provider.Settings;
import android.text.InputType;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.util.*;

/** Native Android console; no remote WebView, account scraping, or embedded developer account. */
public final class MainActivity extends Activity {
    private final int INK=Color.rgb(21,56,60),TEAL=Color.rgb(8,127,114),MUTED=Color.rgb(92,117,119);
    private LinearLayout shell,body;private TextView live;private int page=0;private boolean busy=false;
    private EditText url,model,key,style,scope;private CheckBox web,assist,consent;private String loadedEndpoint="";
    private final List<JSONObject> conversation=new ArrayList<>();private TextView chatText;private EditText chatInput;
    private final Handler timer=new Handler(Looper.getMainLooper());
    private final Runnable refresh=new Runnable(){public void run(){if(live!=null)live.setText(status());timer.postDelayed(this,1000);}};
    @Override public void onCreate(Bundle state){super.onCreate(state);window();render();}
    @Override protected void onResume(){super.onResume();timer.removeCallbacks(refresh);timer.post(refresh);}
    @Override protected void onPause(){timer.removeCallbacks(refresh);super.onPause();}
    private void window(){getWindow().setStatusBarColor(INK);getWindow().setNavigationBarColor(INK);}
    private int dp(int n){return (int)(n*getResources().getDisplayMetrics().density+.5f);}
    private GradientDrawable bg(int color,int radius){GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(radius));return d;}
    private TextView text(String value,int size,int color){TextView t=new TextView(this);t.setText(value);t.setTextSize(size);t.setTextColor(color);t.setLineSpacing(dp(3),1);return t;}
    private LinearLayout column(){LinearLayout l=new LinearLayout(this);l.setOrientation(LinearLayout.VERTICAL);return l;}
    private void gap(LinearLayout parent,int height){View v=new View(this);parent.addView(v,new LinearLayout.LayoutParams(1,dp(height)));}
    private LinearLayout card(String title,String note){LinearLayout c=column();c.setPadding(dp(18),dp(18),dp(18),dp(18));c.setBackground(bg(Color.WHITE,18));
        TextView h=text(title,19,INK);h.setTypeface(null,Typeface.BOLD);c.addView(h);if(note!=null&&!note.isEmpty()){gap(c,8);c.addView(text(note,14,MUTED));}gap(c,12);body.addView(c,new LinearLayout.LayoutParams(-1,-2));gap(body,14);return c;}
    private Button button(LinearLayout parent,String label,boolean primary,Runnable action){Button b=new Button(this);b.setText(label);b.setTextSize(14);b.setAllCaps(false);b.setTextColor(primary?Color.WHITE:INK);b.setBackground(bg(primary?TEAL:Color.rgb(230,240,238),12));
        LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-1,dp(48));lp.topMargin=dp(8);parent.addView(b,lp);b.setOnClickListener(v->{if(!busy)action.run();else toast("正在处理，请稍候");});return b;}
    private EditText field(LinearLayout parent,String label,String value,boolean secret,boolean multi){parent.addView(text(label,13,MUTED));EditText e=new EditText(this);e.setSingleLine(!multi);e.setText(value);e.setTextColor(INK);e.setTextSize(15);e.setPadding(dp(12),dp(10),dp(12),dp(10));e.setBackground(bg(Color.rgb(244,248,247),10));
        if(secret)e.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);
        else if(multi){e.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_MULTI_LINE);e.setMinLines(2);e.setMaxLines(5);}
        LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-1,-2);lp.topMargin=dp(5);lp.bottomMargin=dp(12);parent.addView(e,lp);return e;}
    private CheckBox check(LinearLayout p,String title,boolean value){CheckBox c=new CheckBox(this);c.setText(title);c.setTextColor(INK);c.setChecked(value);p.addView(c);return c;}
    private void render(){
        shell=column();shell.setBackgroundColor(INK);setContentView(shell);
        if(Build.VERSION.SDK_INT>=35)shell.setOnApplyWindowInsetsListener((v,insets)->{v.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());return insets;});
        LinearLayout header=column();header.setPadding(dp(22),dp(18),dp(22),dp(16));header.setBackgroundColor(INK);
        TextView logo=text("W  Workdesk",27,Color.WHITE);logo.setTypeface(null,Typeface.BOLD);header.addView(logo);header.addView(text("ANDROID  ·  个人微信文字助手",12,Color.rgb(158,220,207)));shell.addView(header);
        LinearLayout tabs=new LinearLayout(this);tabs.setBackgroundColor(Color.rgb(240,245,244));String[] names={"概览","AI 设置","对话","记录"};for(int i=0;i<names.length;i++){final int target=i;TextView tab=text(names[i],15,i==page?TEAL:MUTED);tab.setGravity(Gravity.CENTER);tab.setPadding(0,dp(17),0,dp(17));tabs.addView(tab,new LinearLayout.LayoutParams(0,-2,1));tab.setOnClickListener(v->{if(busy){toast("请等待当前操作完成");return;}if(page==1){new AlertDialog.Builder(this).setMessage("未保存的设置将丢失，离开此页？").setPositiveButton("离开",(d,w)->{page=target;render();}).setNegativeButton("继续编辑",null).show();}else{page=target;render();}});}shell.addView(tabs);
        ScrollView scroll=new ScrollView(this);scroll.setBackgroundColor(Color.rgb(240,245,244));scroll.setFillViewport(true);body=column();body.setPadding(dp(16),dp(8),dp(16),dp(24));scroll.addView(body);shell.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        live=null;switch(page){case 0:home();break;case 1:settings();break;case 2:chat();break;default:logs();}
    }
    private String status(){return (RuntimeState.enabled(this)?"接管已开启":"接管已暂停")+" · "+(RuntimeState.connected?"通知服务在线":"通知服务未连接")+"\n"+RuntimeState.last;}
    private JSONObject read(){try{return com.workdesk.android.Settings.read(this);}catch(Exception e){toast("无法解密本机设置，请重新配置");return new JSONObject();}}
    private void home(){
        LinearLayout c=card("按你的节奏，接住新消息","无需电脑常开。当前为安卓独立文字预览版，功能范围与桌面版不同。");live=text(status(),16,INK);c.addView(live);
        button(c,RuntimeState.enabled(this)?"暂停自动回复":"开启自动回复",true,()->{
            if(RuntimeState.enabled(this)){RuntimeState.setEnabled(this,false);render();return;}
            JSONObject cfg=read();if(cfg.optString("endpoint").isEmpty()||cfg.optString("model").isEmpty()||cfg.optString("scope").trim().isEmpty()||!cfg.optBoolean("consent")){toast("先保存 API、接管名单并勾选授权");page=1;render();return;}
            if(!RuntimeState.connected){toast("请先开启系统通知使用权");return;}
            new AlertDialog.Builder(this).setTitle("开启所选会话的文字接管").setMessage("之后这些会话的新通知文字及必要上下文会提交给你配置的 API，并自动发送生成的文字。首次开启不补回旧消息。\n\n不要同时在电脑端接管相同会话，以免双方都回复。")
              .setNegativeButton("取消",null).setPositiveButton("开启",(d,w)->{RuntimeState.setEnabled(this,true);render();}).show();
        });
        c=card("完成手机授权","1. 配置 API 与会话名单\n2. 开启通知使用权\n3. 回到这里开启接管");
        button(c,"打开通知使用权设置",false,()->startActivity(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)));
        button(c,"打开前台辅助设置（可选）",false,()->new AlertDialog.Builder(this).setTitle("前台辅助会操作微信界面")
            .setMessage(getString(R.string.assist_description)+"\n\n这是处理通知不提供快捷回复时的可选方式；仍须在 AI 设置里单独勾选。无法核对会话时不会点击发送。")
            .setNegativeButton("取消",null).setPositiveButton("去系统设置",(d,w)->startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))).show());
        c=card("首版能力与限制","支持：文字自动回复、API 连通性测试、模型查询、独立 AI 文字对话、可选联网检索。\n\n通知被折叠、静音或隐藏内容时可能收不到；部分微信不提供快捷回复，需要解锁后的前台辅助。系统省电策略可能中断后台。\n\n暂不支持自动发送图片、语音转写、视频分析、完整历史、文件传输助手接管及本人微信口令控制。联系人名单按通知标题精确匹配，同名会话需谨慎。手机与电脑的开关互不联动。");
        button(c,"查看隐私与数据说明",false,()->new AlertDialog.Builder(this).setTitle("数据由你控制").setMessage("仅接管名单内的新微信通知文字会交给已配置API。密钥和配置用 Android Keystore 加密保存在本机，不备份。对话上下文和运行记录只在内存；持久化仅保存开关、时间边界与消息哈希去重。\n\n可选前台辅助只检查微信界面，不读取其他应用，不绕过锁屏、不覆盖已有草稿。未知发送不自动重试。应用不内置任何开发者API、密钥或微信登录态。")
            .setPositiveButton("知道了",null).show());
    }
    private void settings(){
        JSONObject cfg=read();loadedEndpoint=cfg.optString("endpoint");LinearLayout c=card("模型服务","填写兼容服务的 HTTPS 地址，留空密钥只会保留同一地址原有的密钥。");
        url=field(c,"API 地址（例如 https://服务域名/v1）",loadedEndpoint,false,false);
        model=field(c,"模型 ID",cfg.optString("model"),false,false);key=field(c,cfg.optString("key").isEmpty()?"API 密钥":"API 密钥（已保存，留空保留）","",true,false);
        button(c,"测试文字连通性",false,()->{JSONObject value=form();if(value!=null)task(()->Api.test(value),result->dialog("连通性测试",result));});
        button(c,"查询支持的模型",false,()->{JSONObject value=form(false);if(value!=null)task(()->String.join("\n",Api.models(value)),result->{String[] ids=result.isEmpty()?new String[0]:result.split("\n");if(ids.length==0){dialog("模型列表","接口没有返回模型；仍可手动填写。");return;}new AlertDialog.Builder(this).setTitle("选择模型（列表不保证每个都可用）").setItems(ids,(d,w)->model.setText(ids[w])).setNegativeButton("取消",null).show();});});
        c=card("表达与接管范围","每行填一个完整的微信通知会话标题；只有这些会话会接管，留空不接管任何会话。");
        scope=field(c,"会话标题名单",cfg.optString("scope"),false,true);
        button(c,"从新通知中选择会话",false,()->{String[] names=RuntimeState.titles();if(names.length==0){dialog("还没有会话标题","先授权通知使用权，再让目标会话发一条新消息。暂停状态也能在本机记住新通知标题，不提交消息给API；不读取旧聊天。");return;}
            new AlertDialog.Builder(this).setTitle("加入接管名单").setItems(names,(d,w)->{String current=scope.getText().toString().trim();if(!RuntimeState.allowed(names[w],current))scope.setText(current.isEmpty()?names[w]:current+"\n"+names[w]);}).setNegativeButton("取消",null).show();});
        style=field(c,"回复风格",cfg.optString("style"),false,true);
        web=check(c,"按需联网（需要 API 支持 Responses web_search）",cfg.optBoolean("web"));
        assist=check(c,"没有快捷回复时使用前台辅助（会打开微信）",cfg.optBoolean("assist"));
        consent=check(c,"允许所选新通知文字提交给以上 API 并自动文字回复",cfg.optBoolean("consent"));
        button(c,"保存配置",true,()->{JSONObject value=form();if(value==null)return;try{
            RuntimeState.setEnabled(this,false);com.workdesk.android.Settings.write(this,value);loadedEndpoint=value.getString("endpoint");key.setText("");toast("已加密保存，接管保持暂停；请在概览确认开启");
        }catch(Exception e){dialog("保存失败","未能加密保存设置，请重试。");}});
    }
    private JSONObject form(){return form(true);}
    private JSONObject form(boolean requireModel){
        try {
            JSONObject old=read(),value=new JSONObject();String endpoint=Api.endpoint(url.getText().toString());String secret=key.getText().toString().trim();
            if(secret.isEmpty()&&!old.optString("key").isEmpty()){
                if(!endpoint.equals(old.optString("endpoint")))throw new Exception("API 地址已改变，请填写新服务的密钥；不会向新地址发送旧密钥");secret=old.optString("key");}
            value.put("endpoint",endpoint).put("key",secret).put("model",model.getText().toString().trim());
            if(requireModel&&value.getString("model").isEmpty())throw new Exception("请填写模型 ID；模型查询也使用当前地址和密钥");
            value.put("scope",scope==null?old.optString("scope"):scope.getText().toString()).put("style",style==null?old.optString("style"):style.getText().toString())
                .put("web",web==null?old.optBoolean("web"):web.isChecked()).put("assist",assist==null?old.optBoolean("assist"):assist.isChecked()).put("consent",consent!=null&&consent.isChecked());return value;
        }catch(Exception e){dialog("检查配置",e.getMessage());return null;}
    }
    private void chat(){
        LinearLayout c=card("和助手聊聊","独立文字对话，可使用已保存的联网选项；这里发送的内容不会发到微信。当前对话仅在内存。");
        chatText=text(chatTranscript(),16,INK);chatText.setTextIsSelectable(true);c.addView(chatText);chatInput=field(c,"你的消息","",false,true);
        button(c,"发送",true,()->{String input=chatInput.getText().toString().trim();if(input.isEmpty())return;JSONObject cfg=read();if(cfg.optString("endpoint").isEmpty()||cfg.optString("model").isEmpty()){dialog("先配置模型","请先到 AI 设置填写并保存 API 与模型。");return;}
            try{conversation.add(new JSONObject().put("role","user").put("content",input));}catch(JSONException ignored){}
            while(conversation.size()>12)conversation.remove(0);chatInput.setText("");chatText.setText(chatTranscript());
            List<JSONObject> snapshot=new ArrayList<>(conversation);task(()->Api.generate(this,cfg,snapshot,true),reply->{try{conversation.add(new JSONObject().put("role","assistant").put("content",reply));}catch(JSONException ignored){}chatText.setText(chatTranscript());});
        });button(c,"清空本次对话",false,()->{conversation.clear();chatText.setText(chatTranscript());});
    }
    private String chatTranscript(){if(conversation.isEmpty())return "发一个问题，开始对话。";StringBuilder s=new StringBuilder();for(JSONObject m:conversation)s.append("user".equals(m.optString("role"))?"你\n":"Workdesk\n").append(m.optString("content")).append("\n\n");return s.toString().trim();}
    private void logs(){LinearLayout c=card("运行记录","仅记录状态，不保存联系人、消息正文、密钥或完整API响应。进程退出后清空。");live=text(status(),15,TEAL);c.addView(live);gap(c,14);TextView entries=text(RuntimeState.logs().isEmpty()?"暂无记录":RuntimeState.logs(),14,INK);entries.setTextIsSelectable(true);c.addView(entries);button(c,"刷新记录",false,this::render);button(c,"清空记录",false,()->{RuntimeState.clearLogs();render();});}
    interface Work {String run()throws Exception;}interface Done{void accept(String value);}
    private void task(Work action,Done done){busy=true;toast("正在连接，请稍候…");new Thread(()->{try{String result=action.run();runOnUiThread(()->{busy=false;if(!isDestroyed())done.accept(result);});}catch(Exception e){runOnUiThread(()->{busy=false;if(!isDestroyed())dialog("操作未完成",e.getMessage()!=null&&e.getMessage().length()<220?e.getMessage():"网络、密钥或接口兼容性异常，请检查配置。");});}},"workdesk-manual").start();}
    private void dialog(String title,String message){new AlertDialog.Builder(this).setTitle(title).setMessage(message).setPositiveButton("知道了",null).show();}
    private void toast(String message){Toast.makeText(this,message,Toast.LENGTH_SHORT).show();}
}
