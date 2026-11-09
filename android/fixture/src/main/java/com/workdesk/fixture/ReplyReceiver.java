package com.workdesk.fixture;
import android.app.RemoteInput;
import android.content.*;
import android.os.Bundle;
import java.io.*;
public final class ReplyReceiver extends BroadcastReceiver {
 @Override public void onReceive(Context c,Intent intent){
  Bundle b=RemoteInput.getResultsFromIntent(intent);if(b==null||b.getCharSequence("answer")==null)return;
  try(FileOutputStream out=c.openFileOutput("accepted-reply.txt",Context.MODE_PRIVATE)){out.write(b.getCharSequence("answer").toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));}catch(Exception ignored){}
 }
}
