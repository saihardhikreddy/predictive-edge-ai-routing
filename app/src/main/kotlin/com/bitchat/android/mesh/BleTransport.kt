package com.bitchat.android.mesh

import android.annotation.SuppressLint
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattServer
import android.bluetooth.BluetoothGattServerCallback
import android.bluetooth.BluetoothGattService
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.AdvertiseCallback
import android.bluetooth.le.AdvertiseData
import android.bluetooth.le.AdvertiseSettings
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.ParcelUuid
import java.io.ByteArrayOutputStream

/**
 * Bluetooth LE plumbing, kept dumb on purpose:
 *  - advertises a 6-byte service-data beacon (node id, battery, buffer)
 *  - scans for other testbed phones
 *  - runs a GATT server with one writable "inbox" characteristic
 *  - sends frames by connecting as a GATT client and writing to the peer's inbox
 *    (one connection at a time; Android BLE stacks dislike concurrency)
 *
 * Every callback is re-posted onto [handler] (the mesh engine thread).
 */
@SuppressLint("MissingPermission")
class BleTransport(
    private val context: Context,
    private val handler: Handler,
    private val onAdvert: (Protocol.Advert, BluetoothDevice, Int) -> Unit,
    private val onFrame: (ByteArray) -> Unit,
    private val onError: (String) -> Unit,
) {
    private val manager = context.getSystemService(BluetoothManager::class.java)
    private val adapter get() = manager?.adapter
    private var server: BluetoothGattServer? = null
    private var advertising = false
    private var scanning = false
    private val serviceParcel = ParcelUuid(Protocol.SERVICE_UUID)

    val isEnabled: Boolean get() = adapter?.isEnabled == true

    // ----------------------------------------------------------- lifecycle

    fun start(advert: ByteArray) {
        stopped = false
        startServer()
        startAdvertising(advert)
        startScan()
    }

    private var stopped = false

    fun stop() {
        stopped = true
        try {
            if (scanning) adapter?.bluetoothLeScanner?.stopScan(scanCallback)
        } catch (_: Exception) {}
        scanning = false
        stopAdvertising()
        try { server?.close() } catch (_: Exception) {}
        server = null
        queue.clear()
        finish(false)
    }

    // --------------------------------------------------------- advertising

    private val advertiseCallback = object : AdvertiseCallback() {
        override fun onStartFailure(errorCode: Int) {
            handler.post { onError("Advertising failed (code $errorCode)") }
            advertising = false
        }
    }

    fun startAdvertising(advert: ByteArray) {
        val adv = adapter?.bluetoothLeAdvertiser ?: run { onError("This phone cannot advertise over BLE"); return }
        stopAdvertising()
        val settings = AdvertiseSettings.Builder()
            .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_LOW_LATENCY)
            .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_MEDIUM)
            .setConnectable(true)
            .setTimeout(0)
            .build()
        val data = AdvertiseData.Builder()
            .setIncludeDeviceName(false)
            .setIncludeTxPowerLevel(false)
            .addServiceData(serviceParcel, advert)
            .build()
        try {
            adv.startAdvertising(settings, data, advertiseCallback)
            advertising = true
        } catch (e: Exception) {
            onError("Advertising error: ${e.message}")
        }
    }

    private fun stopAdvertising() {
        if (!advertising) return
        try { adapter?.bluetoothLeAdvertiser?.stopAdvertising(advertiseCallback) } catch (_: Exception) {}
        advertising = false
    }

    // ------------------------------------------------------------ scanning

    private val scanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            val sd = result.scanRecord?.getServiceData(serviceParcel) ?: return
            val adv = Protocol.parseAdvert(sd) ?: return
            val rssi = result.rssi
            val dev = result.device
            handler.post { onAdvert(adv, dev, rssi) }
        }

        override fun onBatchScanResults(results: MutableList<ScanResult>) {
            results.forEach { onScanResult(0, it) }
        }

        override fun onScanFailed(errorCode: Int) {
            handler.post { onError("Scan failed (code $errorCode)") }
            scanning = false
        }
    }

    private fun startScan() {
        val scanner = adapter?.bluetoothLeScanner ?: run { onError("BLE scanner unavailable"); return }
        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
            .setReportDelay(0)
            .build()
        try {
            scanner.startScan(null, settings, scanCallback)
            scanning = true
        } catch (e: Exception) {
            onError("Scan error: ${e.message}")
        }
    }

    // --------------------------------------------------------- GATT server

    private val prepared = HashMap<String, ByteArrayOutputStream>()

    private val serverCallback = object : BluetoothGattServerCallback() {
        override fun onCharacteristicWriteRequest(
            device: BluetoothDevice, requestId: Int, characteristic: BluetoothGattCharacteristic,
            preparedWrite: Boolean, responseNeeded: Boolean, offset: Int, value: ByteArray?,
        ) {
            val bytes = value ?: ByteArray(0)
            if (preparedWrite) {
                val buf = synchronized(prepared) { prepared.getOrPut(device.address) { ByteArrayOutputStream() } }
                synchronized(buf) { buf.write(bytes) }
            } else if (characteristic.uuid == Protocol.INBOX_UUID) {
                val copy = bytes.copyOf()
                handler.post { onFrame(copy) }
            }
            if (responseNeeded) {
                try { server?.sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, offset, bytes) } catch (_: Exception) {}
            }
        }

        override fun onExecuteWrite(device: BluetoothDevice, requestId: Int, execute: Boolean) {
            val buf = synchronized(prepared) { prepared.remove(device.address) }
            if (execute && buf != null) {
                val bytes = synchronized(buf) { buf.toByteArray() }
                handler.post { onFrame(bytes) }
            }
            try { server?.sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, 0, null) } catch (_: Exception) {}
        }
    }

    private fun startServer() {
        if (server != null) return
        val s = manager?.openGattServer(context, serverCallback) ?: run { onError("Could not open GATT server"); return }
        val service = BluetoothGattService(Protocol.SERVICE_UUID, BluetoothGattService.SERVICE_TYPE_PRIMARY)
        val inbox = BluetoothGattCharacteristic(
            Protocol.INBOX_UUID,
            BluetoothGattCharacteristic.PROPERTY_WRITE or BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE,
            BluetoothGattCharacteristic.PERMISSION_WRITE,
        )
        service.addCharacteristic(inbox)
        s.addService(service)
        server = s
    }

    // ---------------------------------------------------------- GATT client

    private class Outgoing(val device: BluetoothDevice, val bytes: ByteArray, val attempt: Int, val cb: (Boolean) -> Unit)

    private val queue = ArrayDeque<Outgoing>()
    private var current: Outgoing? = null
    private var gatt: BluetoothGatt? = null
    private val timeout = Runnable { finish(false) }

    /** Queue a frame for [device]; [cb] runs on the engine thread with true if the write was acknowledged. */
    fun send(device: BluetoothDevice, bytes: ByteArray, cb: (Boolean) -> Unit) {
        handler.post {
            queue.addLast(Outgoing(device, bytes, 0, cb))
            pump()
        }
    }

    val queueSize: Int get() = queue.size + if (current != null) 1 else 0

    private fun pump() {
        if (current != null || queue.isEmpty()) return
        val o = queue.removeFirst()
        current = o
        handler.postDelayed(timeout, 10_000)
        gatt = try {
            o.device.connectGatt(context, false, clientCallback, BluetoothDevice.TRANSPORT_LE)
        } catch (e: Exception) {
            null
        }
        if (gatt == null) finish(false)
    }

    private fun finish(ok: Boolean) {
        handler.removeCallbacks(timeout)
        val g = gatt
        gatt = null
        try { g?.disconnect() } catch (_: Exception) {}
        try { g?.close() } catch (_: Exception) {}
        val o = current ?: return
        current = null
        if (stopped) {
            o.cb(false)
            return
        }
        if (!ok && o.attempt == 0) {
            // one quick retry: status 133 on the first connect is common on Android
            queue.addFirst(Outgoing(o.device, o.bytes, 1, o.cb))
        } else {
            o.cb(ok)
        }
        handler.postDelayed({ pump() }, 150)
    }

    private val clientCallback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            handler.post {
                if (g != gatt) return@post
                if (newState == BluetoothProfile.STATE_CONNECTED && status == BluetoothGatt.GATT_SUCCESS) {
                    if (!g.requestMtu(517)) g.discoverServices()
                } else {
                    finish(false)
                }
            }
        }

        override fun onMtuChanged(g: BluetoothGatt, mtu: Int, status: Int) {
            handler.post { if (g == gatt) g.discoverServices() }
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            handler.post {
                if (g != gatt) return@post
                val ch = g.getService(Protocol.SERVICE_UUID)?.getCharacteristic(Protocol.INBOX_UUID)
                val o = current
                if (ch == null || o == null) { finish(false); return@post }
                val started = if (Build.VERSION.SDK_INT >= 33) {
                    g.writeCharacteristic(ch, o.bytes, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) == BluetoothGatt.GATT_SUCCESS
                } else {
                    @Suppress("DEPRECATION")
                    run {
                        ch.writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
                        ch.value = o.bytes
                        g.writeCharacteristic(ch)
                    }
                }
                if (!started) finish(false)
            }
        }

        override fun onCharacteristicWrite(g: BluetoothGatt, characteristic: BluetoothGattCharacteristic, status: Int) {
            handler.post { if (g == gatt) finish(status == BluetoothGatt.GATT_SUCCESS) }
        }
    }
}
