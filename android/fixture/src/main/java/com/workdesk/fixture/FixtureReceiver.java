package com.workdesk.fixture;
import android.app.*;
import android.content.*;

/** Install exclusively on a clean emulator; deliberately stands in for the WeChat package. */
public final class FixtureReceiver extends BroadcastReceiver {
 @Override public void onReceive(Context c,Intent intent){
  NotificationManager manager=c.getSystemService(NotificationManager.class);
  manager.createNotificationChannel(new NotificationChannel("fixture","Synthetic messages",NotificationManager.IMPORTANCE_DEFAULT));
  PendingIntent reply=PendingIntent.getBroadcast(c,1,new Intent(c,ReplyReceiver.class),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_MUTABLE);
  Notification.Action action=new Notification.Action.Builder(null,"Reply",reply).addRemoteInput(new RemoteInput.Builder("answer").setLabel("Reply").build()).build();
  long now=System.currentTimeMillis();
  Notification.MessagingStyle style=new Notification.MessagingStyle("Fixture account").setConversationTitle(intent.getStringExtra("title")==null?"Workdesk test":intent.getStringExtra("title"))
    .addMessage(intent.getStringExtra("text")==null?"这是一条合成验收消息，请简短回应。":intent.getStringExtra("text"),now,"Fixture Friend");
  Notification n=new Notification.Builder(c,"fixture").setSmallIcon(android.R.drawable.ic_dialog_email).setWhen(now).setStyle(style).addAction(action).build();manager.notify(1,n);
 }
}
