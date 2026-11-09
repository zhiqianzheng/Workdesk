package com.workdesk.android;

import android.app.*;
import android.content.*;
import android.os.*;
import android.service.notification.*;
import org.json.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** New notifications only. Never scans WeChat databases or consumes old notifications. */
public final class WeChatNotifications extends NotificationListenerService {
    static final String WECHAT="com.tencent.mm";
    @Override public void onListenerConnected(){RuntimeState.connected=true;RuntimeState.connectedAt=System.currentTimeMillis();RuntimeState.log("通知服务已连接；等待新的微信消息");}
    @Override public void onListenerDisconnected(){RuntimeState.connected=false;RuntimeState.log("通知服务已断开，请检查系统授权和后台限制");}
    @Override public void onNotificationPosted(StatusBarNotification sbn){
        try {
            if(!WECHAT.equals(sbn.getPackageName()))return;
            Notification observed=sbn.getNotification();
            if((observed.flags&Notification.FLAG_GROUP_SUMMARY)==0&&observed.extras!=null){
                CharSequence name=observed.extras.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE);
                if(name==null)name=observed.extras.getCharSequence(Notification.EXTRA_TITLE);
                RuntimeState.rememberTitle(string(name));
            }
            if(!RuntimeState.enabled(this))return;
            long since=Math.max(RuntimeState.connectedAt,RuntimeState.state(this).getLong("since",Long.MAX_VALUE));
            if(sbn.getPostTime()<since)return;
            Notification n=sbn.getNotification();
            if((n.flags&Notification.FLAG_GROUP_SUMMARY)!=0||(n.flags&Notification.FLAG_ONGOING_EVENT)!=0)return;
            Bundle e=n.extras;if(e==null)return;
            if(n.when>0&&n.when<since)return;
            String title=string(e.getCharSequence(Notification.EXTRA_TITLE));
            Notification.Style recovered=null;
            try{recovered=Notification.Builder.recoverBuilder(this,n).getStyle();}catch(Exception ignored){}
            List<Notification.MessagingStyle.Message> messages=recovered instanceof Notification.MessagingStyle?((Notification.MessagingStyle)recovered).getMessages():Collections.emptyList();
            List<JSONObject> history=new ArrayList<>();String text="";long messageTime=sbn.getPostTime();
            if(!messages.isEmpty()){
                if(e.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE)!=null)title=e.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE).toString();
                Notification.MessagingStyle.Message latest=messages.get(messages.size()-1);
                // A null sender represents an outgoing/self message in MessagingStyle.
                if(latest.getSender()==null)return;
                text=string(latest.getText());messageTime=latest.getTimestamp();if(messageTime<since)return;
                for(int i=Math.max(0,messages.size()-6);i<messages.size();i++){
                    Notification.MessagingStyle.Message m=messages.get(i);String body=string(m.getText());if(body.isEmpty())continue;
                    history.add(new JSONObject().put("role",m.getSender()==null?"assistant":"user").put("content",body.substring(0,Math.min(body.length(),1800))));
                }
            } else {text=string(e.getCharSequence(Notification.EXTRA_TEXT));}
            if(title.isEmpty()||text.isEmpty()||text.length()>5000||RuntimeState.control(text))return;
            if(text.matches("^(?:\\[?\\d+条\\]?.*|\\[?(?:图片|语音|视频|文件|动画表情)\\]?)$")) {RuntimeState.log("跳过通知摘要或媒体消息；安卓首版仅处理文字");return;}
            if(RuntimeState.isEcho(this,sbn.getKey(),text))return;
            JSONObject config=Settings.read(this);
            if(!config.optBoolean("consent"))return;
            if(!RuntimeState.allowed(title,config.optString("scope")))return;
            if(history.isEmpty())history.add(new JSONObject().put("role","user").put("content",text));
            Notification.Action action=replyAction(n);boolean assist=config.optBoolean("assist")&&ChatAssist.available();
            if(action==null&&(!assist||n.contentIntent==null||!WECHAT.equals(n.contentIntent.getCreatorPackage()))){
                RuntimeState.log("已检测授权会话的新消息，但微信没有快捷回复入口；可查看前台辅助说明");return;
            }
            byte[] hash=MessageDigest.getInstance("SHA-256").digest((sbn.getKey()+"|"+title+"|"+messageTime+"|"+text).getBytes(StandardCharsets.UTF_8));
            StringBuilder digest=new StringBuilder();for(byte b:hash)digest.append(String.format(Locale.ROOT,"%02x",b&255));
            if(!RuntimeState.claim(this,digest.toString()))return;
            final long revision=RuntimeState.revision(this);final String target=title,original=text,key=sbn.getKey();
            final Notification.Action reply=action;final PendingIntent open=n.contentIntent;
            RuntimeState.WORK.execute(()->{
                try {
                    if(!RuntimeState.active(this,revision))return;
                    boolean stillCurrent=false;for(StatusBarNotification item:getActiveNotifications())if(key.equals(item.getKey())&&item.getPostTime()==sbn.getPostTime())stillCurrent=true;
                    if(!stillCurrent){RuntimeState.log("跳过已更新或消失的旧通知");return;}
                    RuntimeState.log("正在为授权会话生成文字回复");String answer=Api.generate(this,config,history,false);
                    if(!RuntimeState.active(this,revision))return;
                    if(RuntimeState.control(answer)){RuntimeState.log("模型输出控制口令，已拦截");return;}
                    StatusBarNotification current=null;
                    for(StatusBarNotification item:getActiveNotifications())if(key.equals(item.getKey())){current=item;break;}
                    if(current==null||current.getPostTime()!=sbn.getPostTime()){
                        RuntimeState.log("通知已改变或移除，旧回复未发送");return;}
                    if(reply!=null){
                        Intent fill=new Intent();Bundle results=new Bundle();
                        for(RemoteInput input:reply.getRemoteInputs())if(input.getAllowFreeFormInput())results.putCharSequence(input.getResultKey(),answer);
                        RemoteInput.addResultsToIntent(reply.getRemoteInputs(),fill,results);
                        if(Build.VERSION.SDK_INT>=28)RemoteInput.setResultsSource(fill,RemoteInput.SOURCE_FREE_FORM_INPUT);
                        if(!RuntimeState.active(this,revision))return;
                        // Persisted claim precedes dispatch: never retry an unknown send.
                        RuntimeState.markEcho(this,key,answer);reply.actionIntent.send(this,0,fill);RuntimeState.log("已提交微信快捷回复；通知接口不能确认送达，未自动重发");
                    }else {RuntimeState.markEcho(this,key,answer);ChatAssist.submit(this,target,original,answer,open,revision);}
                }catch(Exception error){RuntimeState.log("本轮未自动重试："+safe(error));}
            });
        }catch(Exception error){RuntimeState.log("消息接入未完成："+safe(error));}
    }
    static Notification.Action replyAction(Notification n){
        if(n.actions==null)return null;
        for(Notification.Action a:n.actions){
            if(a.actionIntent==null||!WECHAT.equals(a.actionIntent.getCreatorPackage())||a.getRemoteInputs()==null)continue;
            for(RemoteInput r:a.getRemoteInputs())if(r.getAllowFreeFormInput())return a;
        }return null;
    }
    static String string(CharSequence c){return c==null?"":c.toString().trim();}
    static String safe(Exception e){return e instanceof java.net.SocketTimeoutException?"网络超时":e.getMessage()!=null&&e.getMessage().startsWith("接口返回 HTTP")?e.getMessage():"请求、授权或发送状态异常（"+e.getClass().getSimpleName()+"），请核对后再试";}
}
