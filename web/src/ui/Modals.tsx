import QRCode from 'qrcode'
import { type ReactNode, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { clock, minutes } from '../lib/format'
import type { HistoryRow, ServerInfo } from '../lib/types'

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className={`modal ${wide ? 'wide' : ''}`} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function ConnectPhone({ info, onClose }: { info: ServerInfo | null; onClose: () => void }) {
  const [qr, setQr] = useState<string | null>(null)
  useEffect(() => {
    if (info) QRCode.toDataURL(info.camera_ws, { margin: 1, width: 260, color: { dark: '#0b0c10', light: '#f6efe4' } }).then(setQr)
  }, [info])
  const local = info?.lan_ip?.startsWith('127.')
  return (
    <Modal title="Connect your phone" onClose={onClose}>
      <div className="connect">
        {qr ? <img src={qr} alt="QR code for the camera connection" className="qr" /> : <div className="qr placeholder" />}
        <ol>
          <li>Phone and Mac on the <b>same Wi-Fi</b>.</li>
          <li>Open the <b>Tadka Cam</b> app → <b>Scan dashboard QR</b>.</li>
          <li>Prop the phone above the stove so every burner is in frame, then tap <b>Start</b>.</li>
        </ol>
        <code className="url">{info?.camera_ws ?? '…'}</code>
        {local && <p className="error">Couldn't find a Wi-Fi address for this Mac — is it on Wi-Fi?</p>}
        <p className="hint">If macOS asks whether Python may accept incoming connections, choose Allow.</p>
      </div>
    </Modal>
  )
}

export function History({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.history>> | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    api.history().then(setData).catch((e) => setErr(String(e.message)))
  }, [])
  return (
    <Modal title="Cooking history" onClose={onClose} wide>
      {err && <p className="error">{err}</p>}
      {data && data.sessions.length === 0 && <p className="hint">No finished sessions yet. They appear here once a burner has been off for a few minutes.</p>}
      {data && data.stats.length > 0 && (
        <div className="stats">
          {data.stats.map((s) => (
            <div className="stat" key={s.dish}>
              <b>{s.dish}</b>
              <span>{s.sessions}× · avg {minutes(s.avg_seconds)}</span>
            </div>
          ))}
        </div>
      )}
      {data && data.sessions.length > 0 && (
        <table className="history">
          <thead>
            <tr><th>When</th><th>Burner</th><th>Dish</th><th>On flame</th><th>Target</th><th>Stirs</th><th>Alerts</th></tr>
          </thead>
          <tbody>
            {data.sessions.map((r: HistoryRow) => (
              <tr key={r.id}>
                <td>{new Date(r.started_at * 1000).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })}</td>
                <td>{r.burner_name}</td>
                <td>{r.dish ?? 'Unknown'}{r.overridden ? ' ✎' : ''}</td>
                <td>{clock(r.cook_seconds)}</td>
                <td>{minutes(r.target_seconds)}</td>
                <td>{r.stirs}</td>
                <td>{r.alerts || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Modal>
  )
}
