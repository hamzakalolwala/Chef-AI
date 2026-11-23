import AsyncStorage from '@react-native-async-storage/async-storage'
import * as Brightness from 'expo-brightness'
import { CameraView, useCameraPermissions } from 'expo-camera'
import * as Haptics from 'expo-haptics'
import { useKeepAwake } from 'expo-keep-awake'
import { StatusBar } from 'expo-status-bar'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from 'react-native'
import { discoverServer } from './src/discover'
import { type Command, fmt, pickPictureSize, useStreamer } from './src/useStreamer'

const C = {
  bg: '#07080b',
  panel: 'rgba(16,18,24,0.85)',
  line: 'rgba(255,255,255,0.1)',
  text: '#f1ece4',
  muted: '#9a9ca6',
  saffron: '#ffb347',
  teal: '#3ee0c0',
  red: '#ff5a4f',
  blue: '#6ea8ff',
}
const URL_KEY = 'souschef.serverUrl'
const FPS_KEY = 'souschef.fps'

type Screen = 'boot' | 'discover' | 'setup' | 'scan' | 'stream'
const DIM_AFTER_MS = 20000

function normalizeUrl(input: string) {
  let u = input.trim()
  if (!u) return ''
  if (!/^wss?:\/\//.test(u)) u = `ws://${u.replace(/^https?:\/\//, '')}`
  if (!/:\d+/.test(u.replace(/^wss?:\/\//, ''))) u = u.replace(/(wss?:\/\/[^/]+)/, '$1:8000')
  if (!u.includes('/ws/camera')) u = u.replace(/\/?$/, '/ws/camera')
  return u
}

// ------------------------------------------------------------------------------------------
function Button({ label, onPress, kind = 'default', disabled }: { label: string; onPress: () => void; kind?: 'default' | 'primary' | 'danger'; disabled?: boolean }) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={({ pressed }) => [
        s.btn,
        kind === 'primary' && s.btnPrimary,
        kind === 'danger' && s.btnDanger,
        (pressed || disabled) && { opacity: 0.6 },
      ]}
    >
      <Text style={[s.btnText, kind === 'primary' && { color: '#16110a' }]}>{label}</Text>
    </Pressable>
  )
}

// ------------------------------------------------------------------------------------------
function Setup({ url, setUrl, fps, setFps, onScan, onStart, onDiscover }: {
  onDiscover: () => void
  url: string
  setUrl: (u: string) => void
  fps: number
  setFps: (f: number) => void
  onScan: () => void
  onStart: () => void
}) {
  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={s.setup} keyboardShouldPersistTaps="handled">
        <Text style={s.logo}>🍳</Text>
        <Text style={s.title}>Sous Chef Cam</Text>
        <Text style={s.sub}>Turns this phone into the eyes over your stove. Your Mac does the thinking.</Text>

        <Button label="Find my Mac automatically" kind="primary" onPress={onDiscover} />
        <Button label="Scan dashboard QR" onPress={onScan} />
        <Text style={s.or}>or type the address shown on the dashboard</Text>
        <TextInput
          style={s.input}
          value={url}
          onChangeText={setUrl}
          placeholder="192.168.1.20:8000"
          placeholderTextColor={C.muted}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
        />

        <Text style={s.label}>Frames per second</Text>
        <View style={s.seg}>
          {[1, 2, 3].map((f) => (
            <Pressable key={f} onPress={() => setFps(f)} style={[s.segItem, fps === f && s.segActive]}>
              <Text style={[s.segText, fps === f && { color: C.text }]}>{f} fps</Text>
            </Pressable>
          ))}
        </View>
        <Text style={s.hint}>2 fps is plenty for cooking and keeps the phone cool.</Text>

        <Button label="Start streaming" onPress={onStart} disabled={!url.trim()} />

        <View style={s.tips}>
          <Text style={s.tipHead}>Placement tips</Text>
          <Text style={s.tip}>• Mount the phone above / in front of the stove, landscape, all burners in view.</Text>
          <Text style={s.tip}>• Keep it out of the steam column and away from the flame.</Text>
          <Text style={s.tip}>• Plug it in: streaming keeps the screen awake.</Text>
          <Text style={s.tip}>• Same Wi-Fi as the Mac.</Text>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  )
}

// ------------------------------------------------------------------------------------------
function Scanner({ onResult, onCancel }: { onResult: (url: string) => void; onCancel: () => void }) {
  const done = useRef(false)
  return (
    <View style={{ flex: 1 }}>
      <CameraView
        style={StyleSheet.absoluteFill}
        facing="back"
        barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
        onBarcodeScanned={({ data }) => {
          if (done.current || !/^wss?:\/\//.test(data)) return
          done.current = true
          onResult(data)
        }}
      />
      <View style={s.scanFrame} pointerEvents="none" />
      <SafeAreaView style={s.scanBar}>
        <Text style={s.scanText}>Point at the QR code in “Connect phone” on the dashboard</Text>
        <Button label="Cancel" onPress={onCancel} />
      </SafeAreaView>
    </View>
  )
}

// ------------------------------------------------------------------------------------------
function Discovering({ hint, onFound, onFail }: { hint: string; onFound: (url: string) => void; onFail: () => void }) {
  const [progress, setProgress] = useState('')
  useEffect(() => {
    let alive = true
    discoverServer({ hint, onProgress: (d, t) => setProgress(`${d}/${t}`) }).then((u) => {
      if (!alive) return
      if (u) onFound(u)
      else onFail()
    })
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return (
    <View style={[s.setup, { alignItems: 'center', justifyContent: 'center', flex: 1 }]}>
      <ActivityIndicator color={C.saffron} size="large" />
      <Text style={s.title}>Looking for your Mac…</Text>
      <Text style={s.sub}>Make sure the Sous Chef AI server is running and this phone is on the same Wi-Fi. {progress}</Text>
    </View>
  )
}

/** Dim the screen while streaming (less heat + battery on a phone parked by the stove); a touch wakes it. */
function useAutoDim(active: boolean) {
  const original = useRef<number | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const wake = useCallback(() => {
    if (!active) return
    if (original.current != null) Brightness.setBrightnessAsync(original.current).catch(() => {})
    clearTimeout(timer.current)
    timer.current = setTimeout(() => Brightness.setBrightnessAsync(0.02).catch(() => {}), DIM_AFTER_MS)
  }, [active])
  useEffect(() => {
    if (!active) return
    Brightness.getBrightnessAsync().then((b) => (original.current = b)).catch(() => {})
    wake()
    return () => {
      clearTimeout(timer.current)
      if (original.current != null) Brightness.setBrightnessAsync(original.current).catch(() => {})
    }
  }, [active, wake])
  return wake
}

function Stream({ url, fps, setFps, onStop }: { url: string; fps: number; setFps: (f: number) => void; onStop: () => void }) {
  useKeepAwake()
  const wake = useAutoDim(true)
  const [torch, setTorch] = useState(false)
  const cam = useRef<CameraView>(null)
  const [ready, setReady] = useState(false)
  const [size, setSize] = useState<string | undefined>()
  const [paused, setPaused] = useState(false)
  const { width, height } = useWindowDimensions()
  const landscape = width > height
  // Remote control from the dashboard, so a phone with a broken screen never needs touching.
  const onCommand = useCallback(
    (c: Command) => {
      if (c.cmd === 'pause') setPaused(true)
      else if (c.cmd === 'resume') setPaused(false)
      else if (c.cmd === 'fps' && typeof c.value === 'number') setFps(Math.min(5, Math.max(1, c.value)))
      else if (c.cmd === 'torch') setTorch(!!c.value)
      else if (c.cmd === 'buzz') {
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning)
        setTorch(true)
        setTimeout(() => setTorch(false), 1200)
      }
    },
    [setFps],
  )
  const { conn, burners, serverFps, sentFps, lastEvent, profile, cycleProfile, fogged } = useStreamer(url, cam, {
    fps,
    running: !paused,
    ready,
    torch,
    onCommand,
  })

  // Preview box with the same aspect as the captured picture (4:3), so zone overlays line up.
  const aspect = landscape ? 4 / 3 : 3 / 4
  const boxW = Math.min(width, height * aspect)
  const boxH = boxW / aspect

  const dot = conn === 'open' ? C.teal : conn === 'connecting' ? C.saffron : C.red
  const connText = conn === 'open' ? `Live · sending ${sentFps.toFixed(1)} fps` : conn === 'connecting' ? 'Connecting…' : paused ? 'Paused' : 'Reconnecting…'

  return (
    <View style={s.streamRoot} onTouchStart={wake}>
      <View style={{ width: boxW, height: boxH }}>
        <CameraView
          ref={cam}
          style={StyleSheet.absoluteFill}
          facing="back"
          enableTorch={torch}
          animateShutter={false}
          pictureSize={size}
          onCameraReady={async () => {
            try {
              const sizes = (await cam.current?.getAvailablePictureSizesAsync()) ?? []
              setSize(pickPictureSize(sizes))
            } catch {
              /* keep default size */
            }
            setReady(true)
          }}
        />
        {/* burner zones from the dashboard, so you can line the phone up */}
        {burners.map((b) => {
          const color = b.status === 'danger' ? C.red : b.flame ? C.saffron : 'rgba(255,255,255,0.6)'
          return (
            <View
              key={b.id}
              pointerEvents="none"
              style={[s.zone, {
                left: b.zone.x * boxW,
                top: b.zone.y * boxH,
                width: b.zone.w * boxW,
                height: b.zone.h * boxH,
                borderColor: color,
              }]}
            >
              <View style={[s.zoneTag, { backgroundColor: color }]}>
                <Text style={s.zoneTagText} numberOfLines={1}>
                  {b.flame ? '🔥 ' : ''}{b.dish ?? b.name}{b.seconds ? ` ${fmt(b.seconds)}` : ''}
                </Text>
              </View>
            </View>
          )
        })}
      </View>

      <SafeAreaView style={s.topBar} pointerEvents="box-none">
        <View style={s.statusPill}>
          <View style={[s.dot, { backgroundColor: dot }]} />
          <Text style={s.statusText}>{connText}</Text>
          {conn === 'open' && <Text style={[s.statusText, { color: C.muted }]}>  · Mac {serverFps.toFixed(1)} fps</Text>}
        </View>
        {profile && (
          <Pressable onPress={cycleProfile} style={s.profilePill} accessibilityLabel="Switch taste profile">
            <Text style={s.statusText}>Cooking for {profile.emoji} {profile.name}  ⇄</Text>
          </Pressable>
        )}
      </SafeAreaView>

      {fogged && (
        <View style={s.fog} pointerEvents="none">
          <Text style={s.fogTitle}>💨 Lens fogged</Text>
          <Text style={s.fogText}>Wipe the lens (or the shield). Timers are holding until the view is clear.</Text>
        </View>
      )}

      {lastEvent && lastEvent.level !== 'info' && !fogged && (
        <View style={[s.alert, lastEvent.level === 'danger' && { borderColor: C.red }]} pointerEvents="none">
          <Text style={[s.alertText, lastEvent.level === 'danger' && { color: '#ffd8d4' }]}>{lastEvent.message}</Text>
        </View>
      )}

      <SafeAreaView style={s.bottomBar}>
        <View style={s.row}>
          <Button label={paused ? 'Resume' : 'Pause'} onPress={() => setPaused(!paused)} />
          <Button label="Stop" kind="danger" onPress={onStop} />
        </View>
        <Text style={s.urlText} numberOfLines={1}>{url}</Text>
      </SafeAreaView>
    </View>
  )
}

// ------------------------------------------------------------------------------------------
export default function App() {
  const [perm, requestPerm] = useCameraPermissions()
  const [screen, setScreen] = useState<Screen>('boot')
  const [url, setUrl] = useState('')
  const [fps, setFps] = useState(2)

  // Hands-free start: reconnect to the last Mac, or go find one. No taps needed after the first run.
  useEffect(() => {
    AsyncStorage.multiGet([URL_KEY, FPS_KEY]).then(([[, u], [, f]]) => {
      if (u) setUrl(u)
      if (f) setFps(Number(f) || 2)
      setScreen('discover')
    })
  }, [])

  const save = (u: string, f = fps) => AsyncStorage.multiSet([[URL_KEY, u], [FPS_KEY, String(f)]])

  const ensurePerm = async () => perm?.granted || (await requestPerm()).granted

  let body: React.ReactNode
  if (perm && !perm.granted && !perm.canAskAgain) {
    body = (
      <View style={s.setup}>
        <Text style={s.title}>Camera access is off</Text>
        <Text style={s.sub}>Enable camera access for Sous Chef Cam in Settings to stream your stove.</Text>
      </View>
    )
  } else if (screen === 'scan') {
    body = (
      <Scanner
        onCancel={() => setScreen('setup')}
        onResult={(u) => {
          setUrl(u)
          save(u)
          setScreen('stream')
        }}
      />
    )
  } else if (screen === 'boot') {
    body = <View />
  } else if (screen === 'discover') {
    body = (
      <Discovering
        hint={url}
        onFound={async (u) => {
          setUrl(u)
          save(u)
          setScreen((await ensurePerm()) ? 'stream' : 'setup')
        }}
        onFail={() => setScreen('setup')}
      />
    )
  } else if (screen === 'stream') {
    body = (
      <Stream
        url={normalizeUrl(url)}
        fps={fps}
        setFps={(f) => {
          setFps(f)
          save(url, f)
        }}
        onStop={() => setScreen('setup')}
      />
    )
  } else {
    body = (
      <Setup
        url={url}
        setUrl={setUrl}
        fps={fps}
        setFps={(f) => {
          setFps(f)
          save(url, f)
        }}
        onScan={async () => (await ensurePerm()) && setScreen('scan')}
        onDiscover={() => setScreen('discover')}
        onStart={async () => {
          const u = normalizeUrl(url)
          setUrl(u)
          save(u)
          if (await ensurePerm()) setScreen('stream')
        }}
      />
    )
  }

  return (
    <View style={s.root}>
      <StatusBar style="light" hidden={screen === 'stream'} />
      {screen === 'setup' || screen === 'discover' ? <SafeAreaView style={{ flex: 1 }}>{body}</SafeAreaView> : body}
    </View>
  )
}

// ------------------------------------------------------------------------------------------
const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: C.bg },
  setup: { padding: 24, gap: 12, paddingTop: 40 },
  logo: { fontSize: 48, textAlign: 'center' },
  title: { color: C.text, fontSize: 30, fontWeight: '700', textAlign: 'center' },
  sub: { color: C.muted, fontSize: 15, textAlign: 'center', lineHeight: 21, marginBottom: 12 },
  or: { color: C.muted, textAlign: 'center', fontSize: 13, marginTop: 4 },
  input: { borderWidth: 1, borderColor: C.line, borderRadius: 12, padding: 14, color: C.text, fontSize: 16, backgroundColor: 'rgba(255,255,255,0.04)' },
  label: { color: C.muted, fontSize: 13, marginTop: 8 },
  seg: { flexDirection: 'row', borderWidth: 1, borderColor: C.line, borderRadius: 12, overflow: 'hidden' },
  segItem: { flex: 1, padding: 12, alignItems: 'center' },
  segActive: { backgroundColor: 'rgba(255,255,255,0.12)' },
  segText: { color: C.muted, fontWeight: '600' },
  hint: { color: C.muted, fontSize: 12 },
  btn: { borderWidth: 1, borderColor: C.line, backgroundColor: 'rgba(255,255,255,0.08)', borderRadius: 12, paddingVertical: 14, paddingHorizontal: 18, alignItems: 'center' },
  btnPrimary: { backgroundColor: C.saffron, borderColor: C.saffron },
  btnDanger: { backgroundColor: 'rgba(255,90,79,0.2)', borderColor: 'rgba(255,90,79,0.6)' },
  btnText: { color: C.text, fontWeight: '600', fontSize: 15 },
  tips: { marginTop: 18, padding: 16, borderRadius: 14, borderWidth: 1, borderColor: C.line, gap: 6 },
  tipHead: { color: C.text, fontWeight: '600', marginBottom: 2 },
  tip: { color: C.muted, fontSize: 13, lineHeight: 19 },
  scanFrame: { position: 'absolute', alignSelf: 'center', top: '30%', width: 240, height: 240, borderWidth: 3, borderColor: C.saffron, borderRadius: 20 },
  scanBar: { position: 'absolute', bottom: 0, left: 0, right: 0, padding: 20, gap: 12 },
  scanText: { color: C.text, textAlign: 'center', fontSize: 15, backgroundColor: C.panel, padding: 12, borderRadius: 12, overflow: 'hidden' },
  streamRoot: { flex: 1, backgroundColor: '#000', alignItems: 'center', justifyContent: 'center' },
  zone: { position: 'absolute', borderWidth: 2, borderRadius: 10 },
  zoneTag: { position: 'absolute', top: -2, left: -2, paddingHorizontal: 6, paddingVertical: 2, borderTopLeftRadius: 8, borderBottomRightRadius: 8, maxWidth: '100%' },
  zoneTagText: { color: '#111', fontSize: 11, fontWeight: '700' },
  topBar: { position: 'absolute', top: 0, left: 0, right: 0, alignItems: 'center', paddingTop: 8 },
  statusPill: { flexDirection: 'row', alignItems: 'center', backgroundColor: C.panel, paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, marginTop: 8 },
  fog: { position: 'absolute', alignSelf: 'center', top: '38%', maxWidth: '85%', backgroundColor: 'rgba(90,14,10,0.85)', borderColor: C.red, borderWidth: 1, borderRadius: 16, padding: 16, alignItems: 'center' },
  fogTitle: { color: '#fff', fontSize: 20, fontWeight: '700' },
  fogText: { color: '#ffd8d4', textAlign: 'center', marginTop: 4 },
  profilePill: { backgroundColor: C.panel, paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, marginTop: 6, borderWidth: 1, borderColor: C.line },
  dot: { width: 9, height: 9, borderRadius: 5, marginRight: 8 },
  statusText: { color: C.text, fontSize: 13, fontWeight: '600' },
  alert: { position: 'absolute', top: 110, alignSelf: 'center', maxWidth: '90%', backgroundColor: C.panel, borderWidth: 1, borderColor: C.saffron, padding: 12, borderRadius: 12 },
  alertText: { color: C.saffron, fontWeight: '600', textAlign: 'center' },
  bottomBar: { position: 'absolute', bottom: 0, left: 0, right: 0, alignItems: 'center', paddingBottom: 12, gap: 6 },
  row: { flexDirection: 'row', gap: 10 },
  urlText: { color: C.muted, fontSize: 11, maxWidth: '90%' },
})
