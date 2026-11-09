package com.workdesk.android;

import android.content.Context;
import android.content.SharedPreferences;
import java.text.SimpleDateFormat;
import java.util.*;
import java.util.concurrent.*;

/** Only operational status and hashed deduplication receipts persist, never message bodies. */
public final class RuntimeState {
    public static final ExecutorService WORK=new ThreadPoolExecutor(1,1,0,TimeUnit.MILLISECONDS,new ArrayBlockingQueue<>(32));
    private static final ArrayDeque<String> LOG=new ArrayDeque<>();
    private static final LinkedHashSet<String> TITLES=new LinkedHashSet<>();
    public static volatile boolean connected=false;
    public static volatile long connectedAt=System.currentTimeMillis();
    public static volatile String last="尚未连接通知服务";
    static SharedPreferences state(Context c){return c.getSharedPreferences("state",0);}
    public static boolean enabled(Context c){return state(c).getBoolean("enabled",false);}
    public static long revision(Context c){return state(c).getLong("revision",0);}
    public static synchronized void setEnabled(Context c,boolean value){
        state(c).edit().putBoolean("enabled",value).putLong("revision",revision(c)+1).putLong("since",System.currentTimeMillis()).commit();
        if(!value)ChatAssist.cancel();log(value?"已开启，仅接管之后的新通知":"已暂停，未发送的任务已取消");
    }
    public static boolean active(Context c,long revision){return enabled(c)&&revision(c)==revision;}
    static String echoKey(String notification,String text){
        try{byte[] hash=java.security.MessageDigest.getInstance("SHA-256").digest((notification+"|"+text.trim()).getBytes(java.nio.charset.StandardCharsets.UTF_8));return "echo-"+android.util.Base64.encodeToString(hash,android.util.Base64.NO_WRAP);}catch(Exception e){throw new IllegalStateException(e);}
    }
    public static synchronized boolean isEcho(Context c,String notification,String text){return Arrays.asList(state(c).getString("seen","").split("\n")).contains(echoKey(notification,text));}
    public static void markEcho(Context c,String notification,String text){claim(c,echoKey(notification,text));}
    public static synchronized boolean claim(Context c,String digest){
        String seen=state(c).getString("seen","");if(Arrays.asList(seen.split("\n")).contains(digest))return false;
        String all=digest+"\n"+seen;String[] rows=all.split("\n");StringBuilder keep=new StringBuilder();
        for(int i=0;i<Math.min(rows.length,200);i++)keep.append(rows[i]).append('\n');
        return state(c).edit().putString("seen",keep.toString()).commit();
    }
    public static synchronized void log(String text){
        last=text;LOG.addFirst(new SimpleDateFormat("HH:mm:ss",Locale.ROOT).format(new Date())+"  "+text);
        while(LOG.size()>35)LOG.removeLast();
    }
    public static synchronized String logs(){return String.join("\n\n",LOG);}
    public static synchronized void clearLogs(){LOG.clear();}
    public static synchronized void rememberTitle(String title){if(title!=null&&!title.trim().isEmpty()){TITLES.add(title);while(TITLES.size()>50)TITLES.remove(TITLES.iterator().next());}}
    public static synchronized String[] titles(){return TITLES.toArray(new String[0]);}
    public static boolean allowed(String title,String scope){
        if(title==null||title.trim().isEmpty())return false;
        for(String line:scope.split("\\r?\\n"))if(title.equals(line.trim()))return true;
        return false;
    }
    public static boolean control(String text){
        String s=text.replaceAll("[\\s，。！!？?\"“”]","").toLowerCase(Locale.ROOT);
        return s.matches("(?:请|帮我|麻烦)?(?:停止|暂停|关闭|开启|打开|恢复|查询)(?:ai|AI)(?:自动)?回复(?:状态)?(?:吧|一下)?");
    }
    private RuntimeState(){}
}
