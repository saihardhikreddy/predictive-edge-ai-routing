package com.bitchat.android.mesh

import android.content.ContentValues
import android.content.Context
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Append-only CSV of everything the phone does. One file per phone; merge them
 * on a laptop with tools/analyze_field_logs.py.
 */
class EventLog(private val context: Context, private val nodeId: String) {
    companion object {
        const val HEADER = "ts_ms,node,event,mode,msg,src,dst,peer,rssi,hops,bytes,value,battery"
    }

    private val file = File(context.filesDir, "events_$nodeId.csv")
    private val tail = ArrayDeque<String>()
    private val timeFmt = SimpleDateFormat("HH:mm:ss", Locale.US)

    /** Called for every event (on the writer's thread) so the UI can animate it. */
    var listener: ((event: String, mode: String, msg: String, peer: String, value: String) -> Unit)? = null

    init {
        if (!file.exists()) file.writeText(HEADER + "\n")
    }

    private fun esc(s: String) = if (s.contains(',') || s.contains('"')) "\"" + s.replace("\"", "\"\"") + "\"" else s

    fun write(
        event: String,
        mode: String = "",
        msg: String = "",
        src: String = "",
        dst: String = "",
        peer: String = "",
        rssi: Int? = null,
        hops: Int? = null,
        bytes: Int? = null,
        value: String = "",
    ) {
        val t = System.currentTimeMillis()
        val battery = try {
            context.getSystemService(android.os.BatteryManager::class.java)
                .getIntProperty(android.os.BatteryManager.BATTERY_PROPERTY_CAPACITY)
        } catch (_: Exception) { -1 }
        val line = listOf(
            t.toString(), nodeId, event, mode, msg, src, dst, peer,
            rssi?.toString() ?: "", hops?.toString() ?: "", bytes?.toString() ?: "", esc(value), battery.toString(),
        ).joinToString(",")
        try { file.appendText(line + "\n") } catch (_: Exception) {}
        listener?.invoke(event, mode, msg, peer, value)
        val pretty = buildString {
            append(timeFmt.format(Date(t))).append("  ").append(event)
            if (msg.isNotEmpty()) append(" ").append(msg)
            if (peer.isNotEmpty()) append(" peer=").append(peer)
            if (rssi != null) append(" ").append(rssi).append("dBm")
            if (value.isNotEmpty()) append(" ").append(value)
        }
        synchronized(tail) {
            tail.addLast(pretty)
            while (tail.size > 300) tail.removeFirst()
        }
    }

    fun tail(n: Int): List<String> = synchronized(tail) { tail.toList().takeLast(n).reversed() }

    fun readAll(): String = try { file.readText() } catch (_: Exception) { HEADER + "\n" }

    /** Copies the CSV into Downloads (Android 10+) or the app's external folder. Returns where it went. */
    fun exportToDownloads(): String {
        val name = "mesh_${nodeId}_${SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())}.csv"
        return try {
            if (Build.VERSION.SDK_INT >= 29) {
                val values = ContentValues().apply {
                    put(MediaStore.Downloads.DISPLAY_NAME, name)
                    put(MediaStore.Downloads.MIME_TYPE, "text/csv")
                    put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
                }
                val uri = context.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                    ?: return "Export failed"
                context.contentResolver.openOutputStream(uri)?.use { it.write(file.readBytes()) }
                "Saved to Downloads/$name"
            } else {
                val dir = context.getExternalFilesDir(null) ?: context.filesDir
                val out = File(dir, name)
                file.copyTo(out, overwrite = true)
                "Saved to ${out.absolutePath}"
            }
        } catch (e: Exception) {
            "Export failed: ${e.message}"
        }
    }
}
