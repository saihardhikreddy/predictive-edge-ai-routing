@file:OptIn(kotlinx.coroutines.FlowPreview::class)

package com.bitchat.android

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothManager
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.webkit.WebViewAssetLoader
import com.bitchat.android.mesh.MeshEngine
import com.bitchat.android.mesh.toJson
import kotlinx.coroutines.flow.sample
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

object EngineHolder {
    @Volatile
    var engine: MeshEngine? = null
}

/**
 * Hosts the 3D mesh UI (assets/web, three.js) in a WebView. The page talks to the
 * Bluetooth engine through one JS function, Android.call(name, argsJson); the engine's
 * state is pushed back as window.meshUpdate(json) a few times a second.
 */
class MainActivity : ComponentActivity() {

    private lateinit var web: WebView
    private lateinit var engine: MeshEngine
    private var pageReady = false

    private val requiredPermissions: Array<String>
        get() = if (Build.VERSION.SDK_INT >= 31) {
            arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT, Manifest.permission.BLUETOOTH_ADVERTISE)
        } else {
            arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
        }

    private val enableBt = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { engine.start() }

    private val permissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { res ->
        if (res.values.all { it }) startWithBluetooth()
        else Toast.makeText(this, "Allow Nearby devices so phones can find each other", Toast.LENGTH_LONG).show()
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        window.statusBarColor = Color.parseColor("#070A10")
        window.navigationBarColor = Color.parseColor("#0E1420")
        engine = EngineHolder.engine ?: MeshEngine(applicationContext).also { EngineHolder.engine = it }

        // serve assets/web from a real https origin so ES modules and the import map work
        val loader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()

        web = WebView(this).apply {
            setBackgroundColor(Color.parseColor("#070A10"))
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.allowFileAccess = false
            settings.allowContentAccess = false
            settings.mediaPlaybackRequiresUserGesture = true
            webChromeClient = WebChromeClient()
            webViewClient = object : WebViewClient() {
                override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                    loader.shouldInterceptRequest(request.url)

                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean =
                    request.url.host != "appassets.androidplatform.net"

                override fun onPageFinished(view: WebView, url: String) {
                    pageReady = true
                    push(engine.state.value.toJson())
                }
            }
            addJavascriptInterface(Bridge(), "Android")
        }
        setContentView(web)
        web.loadUrl("https://appassets.androidplatform.net/assets/web/index.html")

        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                engine.state.sample(200).collect { if (pageReady) push(it.toJson()) }
            }
        }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                moveTaskToBack(true)   // keep the mesh running instead of tearing the activity down
            }
        })
    }

    private fun push(json: String) {
        web.evaluateJavascript("window.meshUpdate && window.meshUpdate($json)", null)
    }

    private fun startMesh() {
        val missing = requiredPermissions.filter { ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isEmpty()) startWithBluetooth() else permissions.launch(missing.toTypedArray())
    }

    @SuppressLint("MissingPermission")
    private fun startWithBluetooth() {
        val adapter = getSystemService(BluetoothManager::class.java)?.adapter
        if (adapter == null) {
            Toast.makeText(this, "This phone has no Bluetooth", Toast.LENGTH_LONG).show()
            return
        }
        if (!adapter.isEnabled) enableBt.launch(Intent(android.bluetooth.BluetoothAdapter.ACTION_REQUEST_ENABLE))
        else engine.start()
    }

    private fun share(text: String) {
        val send = Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_SUBJECT, "Mesh log ${engine.myId}")
            putExtra(Intent.EXTRA_TEXT, text)
        }
        startActivity(Intent.createChooser(send, "Share CSV"))
    }

    /** Everything the page can ask the engine to do. Runs on a binder thread; the engine posts to its own. */
    inner class Bridge {
        @JavascriptInterface
        fun call(name: String, argsJson: String): String {
            val a = try { JSONArray(argsJson) } catch (_: Exception) { JSONArray() }
            when (name) {
                "start" -> runOnUiThread { startMesh() }
                "stop" -> engine.stop()
                "setMode" -> engine.setMode(a.optString(0, "M"))
                "setSinkhole" -> engine.setSinkhole(a.optBoolean(0))
                "setTriage" -> engine.setTriage(a.optBoolean(0, true))
                "setRange" -> engine.setRange(a.optInt(0, -100))
                "setNick" -> engine.setNick(a.optString(0))
                "toggleBlock" -> engine.toggleBlock(a.optString(0))
                "send" -> engine.send(a.optString(0), a.optString(1))
                "startExperiment" -> engine.startExperiment(a.optInt(0, 30), a.optLong(1, 3000), a.optDouble(2, 0.2))
                "stopExperiment" -> engine.stopExperiment()
                "resetStats" -> engine.resetStats()
                "clearTrust" -> engine.clearTrust()
                "exportLog" -> return engine.exportLog()
                "shareLog" -> { val csv = engine.csvText(); runOnUiThread { share(csv) }; return "" }
                else -> return JSONObject().put("error", "unknown action $name").toString()
            }
            return ""
        }
    }
}
