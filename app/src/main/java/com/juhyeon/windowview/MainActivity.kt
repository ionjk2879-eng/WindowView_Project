package com.juhyeon.windowview

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.location.Location
import android.location.LocationManager
import android.os.Bundle
import android.os.CancellationSignal
import android.util.Base64
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.core.location.LocationManagerCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.webkit.WebViewAssetLoader
import java.io.File
import java.util.Locale
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin

/**
 * 창밖 뷰 계산기
 *
 * 화면(3D·계산)은 app/src/main/assets/index.html 이 맡고,
 * 이 Activity는 휴대폰 기능만 연결해요.
 *   - 내 위치(GPS): 위치는 휴대폰 안에서만 쓰고 어디에도 보내지 않아요
 *   - 나침반: 휴대폰이 향한 방향으로 3D 화면을 돌려요
 *   - 공유: 결과 카드 이미지를 카톡·인스타 등으로 보내요
 */
class MainActivity : ComponentActivity(), SensorEventListener {

    private lateinit var web: WebView
    private lateinit var sensorManager: SensorManager
    private var compassOn = false
    private var lastHeadingSentAt = 0L
    private var smoothSin = 0.0
    private var smoothCos = 1.0

    // 위치 권한 요청 결과
    private val locationPermission =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
            if (result.values.any { it }) fetchLocation()
            else callJs("window.onNativeLocationError && window.onNativeLocationError('permission')")
        }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        sensorManager = getSystemService(SENSOR_SERVICE) as SensorManager

        // 디버그 빌드에서는 크롬 chrome://inspect 로 화면 코드를 들여다볼 수 있게
        if (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0) {
            WebView.setWebContentsDebuggingEnabled(true)
        }

        // assets 폴더를 https://appassets.androidplatform.net/assets/ 주소로 열어 줌
        // (file:// 로 열면 fetch()로 data/window.json 을 못 읽어요)
        val assetLoader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()

        web = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.allowFileAccess = false
            settings.allowContentAccess = false
            webViewClient = object : WebViewClient() {
                override fun shouldInterceptRequest(
                    view: WebView,
                    request: WebResourceRequest
                ): WebResourceResponse? = assetLoader.shouldInterceptRequest(request.url)

                // 앱 밖 링크는 열지 않음
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest) =
                    request.url.host != "appassets.androidplatform.net"
            }
            addJavascriptInterface(Bridge(), "Android")
        }
        setContentView(web)

        // 상태바·내비게이션바에 화면이 가리지 않게 여백 주기
        ViewCompat.setOnApplyWindowInsetsListener(web) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (web.canGoBack()) web.goBack() else finish()
            }
        })

        web.loadUrl("https://appassets.androidplatform.net/assets/index.html")
    }

    override fun onResume() {
        super.onResume()
        if (compassOn) registerCompass()
    }

    override fun onPause() {
        super.onPause()
        sensorManager.unregisterListener(this) // 화면을 떠나면 센서를 꺼서 배터리 절약
    }

    override fun onDestroy() {
        web.destroy()
        super.onDestroy()
    }

    /** index.html 의 자바스크립트에서 window.Android.함수() 로 부르는 것들 */
    inner class Bridge {
        @JavascriptInterface
        fun requestLocation() = runOnUiThread {
            val granted = listOf(
                Manifest.permission.ACCESS_FINE_LOCATION,
                Manifest.permission.ACCESS_COARSE_LOCATION
            ).any { ContextCompat.checkSelfPermission(this@MainActivity, it) == PackageManager.PERMISSION_GRANTED }
            if (granted) fetchLocation()
            else locationPermission.launch(
                arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
            )
        }

        @JavascriptInterface
        fun startCompass() = runOnUiThread {
            compassOn = true
            registerCompass()
        }

        @JavascriptInterface
        fun stopCompass() = runOnUiThread {
            compassOn = false
            sensorManager.unregisterListener(this@MainActivity)
        }

        @JavascriptInterface
        fun shareImage(base64Png: String, text: String) = runOnUiThread {
            shareCard(base64Png, text)
        }
    }

    // ───────── 내 위치 ─────────
    @SuppressLint("MissingPermission") // requestLocation()에서 권한을 확인한 뒤에만 불려요
    private fun fetchLocation() {
        val lm = getSystemService(LOCATION_SERVICE) as LocationManager
        val provider = when {
            lm.isProviderEnabled(LocationManager.GPS_PROVIDER) -> LocationManager.GPS_PROVIDER
            lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER) -> LocationManager.NETWORK_PROVIDER
            else -> {
                callJs("window.onNativeLocationError && window.onNativeLocationError('off')")
                return
            }
        }
        LocationManagerCompat.getCurrentLocation(
            lm, provider, CancellationSignal(), ContextCompat.getMainExecutor(this)
        ) { loc: Location? ->
            if (loc == null) {
                callJs("window.onNativeLocationError && window.onNativeLocationError('none')")
            } else {
                // 위치는 화면 계산에만 쓰고 저장하거나 서버로 보내지 않아요
                callJs(
                    String.format(
                        Locale.US, "window.onNativeLocation && window.onNativeLocation(%.6f, %.6f, %.0f)",
                        loc.latitude, loc.longitude, loc.accuracy.toDouble()
                    )
                )
            }
        }
    }

    // ───────── 나침반 ─────────
    private fun registerCompass() {
        val sensor = sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR) ?: run {
            callJs("document.getElementById('hint').textContent = '이 휴대폰에는 나침반 센서가 없어요'")
            return
        }
        sensorManager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_UI)
    }

    private val rotation = FloatArray(9)
    private val orientation = FloatArray(3)

    override fun onSensorChanged(event: SensorEvent) {
        if (event.sensor.type != Sensor.TYPE_ROTATION_VECTOR) return
        SensorManager.getRotationMatrixFromVector(rotation, event.values)
        SensorManager.getOrientation(rotation, orientation)
        val az = orientation[0].toDouble() // 북쪽 기준 라디안 (세로 화면 고정 기준)

        // 흔들림 줄이기: 각도를 sin/cos로 나눠 부드럽게 (359°↔0° 튐 방지)
        smoothSin += (sin(az) - smoothSin) * 0.2
        smoothCos += (cos(az) - smoothCos) * 0.2

        val now = System.currentTimeMillis()
        if (now - lastHeadingSentAt < 80) return // 초당 약 12번만 화면에 전달
        lastHeadingSentAt = now
        val deg = (Math.toDegrees(atan2(smoothSin, smoothCos)) + 360.0) % 360.0
        callJs(String.format(Locale.US, "window.onNativeHeading && window.onNativeHeading(%.1f)", deg))
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit

    // ───────── 공유 카드 ─────────
    private fun shareCard(base64Png: String, text: String) {
        val bytes = Base64.decode(base64Png, Base64.DEFAULT)
        val dir = File(cacheDir, "share").apply { mkdirs() }
        val file = File(dir, "window_view_card.png")
        file.writeBytes(bytes)
        val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", file)
        val send = Intent(Intent.ACTION_SEND).apply {
            type = "image/png"
            putExtra(Intent.EXTRA_STREAM, uri)
            putExtra(Intent.EXTRA_TEXT, text)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        startActivity(Intent.createChooser(send, "결과 카드 공유"))
    }

    private fun callJs(script: String) {
        web.post { web.evaluateJavascript(script, null) }
    }
}
