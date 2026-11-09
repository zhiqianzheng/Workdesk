package com.workdesk.android;

import android.app.*;
import android.content.*;
import android.content.pm.*;
import android.os.*;
import org.json.*;
import java.io.*;

/** Dependency-free emulator acceptance; never contacts real WeChat users. */
public final class Acceptance extends Instrumentation {
    private Bundle args;private int checks;
    @Override public void onCreate(Bundle b){args=b==null?new Bundle():b;start();}
    void check(boolean yes,String reason){if(!yes)throw new AssertionError(reason);checks++;}
    @Override public void onStart(){
        Bundle result=new Bundle();Context app=getTargetContext();
        try {
            if("true".equals(args.getString("pause_only"))){RuntimeState.setEnabled(app,false);result.putString("stream","Paused\n");finish(Activity.RESULT_OK,result);return;}
            check(Api.endpoint("https://example.com/v1/").equals("https://example.com/v1/chat/completions"),"normalize base");
            for(String bad:new String[]{"http://example.com/v1","https://user:key@example.com/v1","https://example.com/v1?key=secret","https://example.com/v1#secret"}){
                boolean rejected=false;try{Api.endpoint(bad);}catch(Exception e){rejected=true;}check(rejected,"reject unsafe endpoint");}
            check(RuntimeState.allowed("Friend","Friend\nGroup"),"scope exact permitted");check(!RuntimeState.allowed("Friend 2","Friend"),"scope partial rejected");check(!RuntimeState.allowed("Friend",""),"empty scope closed");
            RuntimeState.setEnabled(app,true);long epoch=RuntimeState.revision(app);check(RuntimeState.active(app,epoch),"enabled");
            RuntimeState.setEnabled(app,false);check(!RuntimeState.active(app,epoch),"pause cancels in-flight");RuntimeState.setEnabled(app,true);check(!RuntimeState.active(app,epoch),"old generation remains cancelled");RuntimeState.setEnabled(app,false);
            RuntimeState.markEcho(app,"notification","synthetic answer");check(RuntimeState.isEcho(app,"notification","synthetic answer"),"own reply echo ignored");check(!RuntimeState.isEcho(app,"other","synthetic answer"),"echo scoped to notification");
            String id="acceptance-"+System.nanoTime();check(RuntimeState.claim(app,id),"new event claimed");check(!RuntimeState.claim(app,id),"same event not replayed");
            JSONObject cfg=new JSONObject().put("key","not-a-real-secret").put("endpoint","https://example.com/v1/chat/completions").put("scope","Friend");
            Settings.write(app,cfg);check("not-a-real-secret".equals(Settings.read(app).getString("key")),"keystore round trip");
            check(!app.getSharedPreferences("private",0).getString("config","").contains("not-a-real-secret"),"no plaintext secret");
            check((app.getApplicationInfo().flags&ApplicationInfo.FLAG_ALLOW_BACKUP)==0,"no configuration backup");
            ServiceInfo info=app.getPackageManager().getServiceInfo(new ComponentName(app,WeChatNotifications.class),0);
            check("android.permission.BIND_NOTIFICATION_LISTENER_SERVICE".equals(info.permission),"system-bound notification service");
            Notification.Action wrong=new Notification.Action.Builder(null,"reply",PendingIntent.getBroadcast(app,11,new Intent(app,MainActivity.class),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_MUTABLE)).addRemoteInput(new RemoteInput.Builder("reply").setLabel("Reply").build()).build();
            Notification fake=new Notification.Builder(app,"test").addAction(wrong).build();check(WeChatNotifications.replyAction(fake)==null,"foreign reply action rejected");
            Settings.write(app,new JSONObject());
            Activity activity=startActivitySync(new Intent(app,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));waitForIdleSync();
            check(activity!=null&&!activity.isFinishing(),"native UI launch");
            if("true".equals(args.getString("integration"))){
                File input=new File(app.getFilesDir(),"integration-input.json");byte[] bytes=new byte[(int)input.length()];try(FileInputStream in=new FileInputStream(input)){int offset=0,n;while(offset<bytes.length&&(n=in.read(bytes,offset,bytes.length-offset))>0)offset+=n;}
                JSONObject privateConfig=new JSONObject(new String(bytes,java.nio.charset.StandardCharsets.UTF_8));input.delete();
                Settings.write(app,privateConfig);RuntimeState.setEnabled(app,true);
            }
            result.putString("stream","PASS "+checks+" Android acceptance checks\n");finish(Activity.RESULT_OK,result);
        }catch(Throwable error){result.putString("stream","FAIL "+error.getClass().getSimpleName()+": "+error.getMessage()+"\n");finish(Activity.RESULT_CANCELED,result);}
    }
}
