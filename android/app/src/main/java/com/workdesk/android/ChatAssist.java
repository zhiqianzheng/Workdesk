package com.workdesk.android;

import android.accessibilityservice.AccessibilityService;
import android.app.*;
import android.content.*;
import android.graphics.Rect;
import android.os.*;
import android.view.accessibility.*;
import java.util.*;

/** Optional foreground text assist. Exact header + original message + empty draft are mandatory. */
public final class ChatAssist extends AccessibilityService {
    private static volatile ChatAssist instance;
    private static Job pending;
    private final Handler handler=new Handler(Looper.getMainLooper());
    static final class Job {
        final String title,original,answer;final long revision,deadline;boolean filled;
        Job(String t,String o,String a,long r){title=t;original=o;answer=a;revision=r;deadline=SystemClock.elapsedRealtime()+12000;}
    }
    public static boolean available(){return instance!=null;}
    public static void cancel(){ChatAssist service=instance;if(service!=null)service.handler.post(()->pending=null);}
    @Override protected void onServiceConnected(){instance=this;RuntimeState.log("前台辅助已连接；仅在应用内单独勾选后使用");}
    @Override public void onDestroy(){instance=null;pending=null;super.onDestroy();}
    @Override public void onInterrupt(){pending=null;}
    public static void submit(Context context,String title,String original,String answer,PendingIntent open,long revision){
        ChatAssist service=instance;
        if(service==null){RuntimeState.log("前台辅助服务未连接，未发送");return;}
        service.handler.post(()->{
            try {
                if(!RuntimeState.active(service,revision)||!Settings.read(service).optBoolean("assist"))return;
                KeyguardManager keys=service.getSystemService(KeyguardManager.class);
                PowerManager power=service.getSystemService(PowerManager.class);
                if(keys.isKeyguardLocked()||!power.isInteractive()){RuntimeState.log("手机未解锁或屏幕关闭，前台辅助未执行；不会自动解锁");return;}
                if(pending!=null){RuntimeState.log("前台仍有任务，当前回复未发送");return;}
                if(!WeChatNotifications.WECHAT.equals(open.getCreatorPackage()))return;
                pending=new Job(title,original,answer,revision);
                if(Build.VERSION.SDK_INT>=34){ActivityOptions opts=ActivityOptions.makeBasic();opts.setPendingIntentBackgroundActivityStartMode(ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED);
                    open.send(service,0,new Intent(),null,null,null,opts.toBundle());}
                else open.send();
                RuntimeState.log("正在打开微信并核对目标会话；请勿同时手动输入");
                service.handler.postDelayed(service::attempt,500);
            }catch(Exception e){pending=null;RuntimeState.log("无法打开目标微信会话，未发送");}
        });
    }
    @Override public void onAccessibilityEvent(AccessibilityEvent e){if(pending!=null)handler.postDelayed(this::attempt,180);}
    private void attempt(){
        Job job=pending;if(job==null)return;
        if(!RuntimeState.active(this,job.revision)||((KeyguardManager)getSystemService(KEYGUARD_SERVICE)).isKeyguardLocked()){pending=null;RuntimeState.log("前台任务已取消，未继续发送");return;}
        if(SystemClock.elapsedRealtime()>job.deadline){pending=null;RuntimeState.log("未能核对会话、原消息或空输入框，未点击发送；请检查微信草稿");return;}
        AccessibilityNodeInfo root=getRootInActiveWindow();
        if(root==null||!WeChatNotifications.WECHAT.contentEquals(root.getPackageName())){handler.postDelayed(this::attempt,500);return;}
        List<AccessibilityNodeInfo> nodes=new ArrayList<>();collect(root,nodes,0);
        boolean title=false,original=false;int height=getResources().getDisplayMetrics().heightPixels;
        List<AccessibilityNodeInfo> edits=new ArrayList<>(),sends=new ArrayList<>();
        for(AccessibilityNodeInfo node:nodes){
            if(!node.isVisibleToUser())continue;String text=node.getText()==null?"":node.getText().toString();Rect rect=new Rect();node.getBoundsInScreen(rect);
            if(text.equals(job.title)&&rect.top>=0&&rect.bottom<height/3&&!node.isEditable())title=true;
            if(text.equals(job.original)&&rect.top>height/8&&!node.isEditable())original=true;
            if(node.isEditable()&&node.isEnabled())edits.add(node);
            if(("发送".equals(text)||"Send".equals(text))&&node.isClickable()&&node.isEnabled()&&rect.top>height/2)sends.add(node);
        }
        if(!title||!original||edits.size()!=1){handler.postDelayed(this::attempt,500);return;}
        AccessibilityNodeInfo edit=edits.get(0);String draft=edit.getText()==null?"":edit.getText().toString();
        if(!job.filled){
            if(!draft.isEmpty()){pending=null;RuntimeState.log("微信已有未发送草稿，未覆盖、未发送");return;}
            if(!RuntimeState.active(this,job.revision))return;
            Bundle args=new Bundle();args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,job.answer);
            job.filled=edit.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT);
            if(!job.filled){pending=null;RuntimeState.log("无法填写微信输入框，未发送");return;}
            handler.postDelayed(this::attempt,350);return;
        }
        if(!draft.equals(job.answer)){pending=null;RuntimeState.log("输入框内容被改变，未点击发送");return;}
        if(sends.size()!=1){handler.postDelayed(this::attempt,350);return;}
        if(!RuntimeState.active(this,job.revision))return;
        pending=null;boolean clicked=sends.get(0).performAction(AccessibilityNodeInfo.ACTION_CLICK);
        RuntimeState.log(clicked?"已点击微信发送；未确认对方收取，不自动重复点击":"发送按钮未接受操作，请核对微信草稿");
    }
    static void collect(AccessibilityNodeInfo root,List<AccessibilityNodeInfo> nodes,int depth){
        if(depth>25||nodes.size()>1200)return;nodes.add(root);
        for(int i=0;i<root.getChildCount();i++){AccessibilityNodeInfo child=root.getChild(i);if(child!=null)collect(child,nodes,depth+1);}
    }
}
