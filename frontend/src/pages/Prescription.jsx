import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function PrescriptionPage() {
  const [patients, setPatients] = useState([])
  const [patientId, setPatientId] = useState('')
  const [latest, setLatest] = useState(null)
  const [form, setForm] = useState({ pattern: '', risk_level: '', phase: 'II', week_no: 1 })
  const [rx, setRx] = useState(null)          // 当前生成的处方
  const [history, setHistory] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api.listPatients().then(setPatients).catch((e) => setError(e.message))
  }, [])

  function loadHistory(pid) {
    api.listPrescriptions(pid).then(setHistory).catch(() => setHistory([]))
  }

  function onPatient(pid) {
    setPatientId(pid)
    setRx(null)
    if (pid) {
      loadHistory(pid)
      api.latestAssessment(pid).then((d) => {
        setLatest(d)
        setForm((f) => ({ ...f, pattern: d.pattern || '', risk_level: d.risk_level || '' }))
      }).catch(() => setLatest(null))
    } else {
      setHistory([]); setLatest(null)
    }
  }

  async function generate(e) {
    e.preventDefault()
    setError('')
    if (!patientId) { setError('请先选择患者'); return }
    if (!form.pattern || !form.risk_level) { setError('请选择证型与危险分层（可点自动读取）'); return }
    setLoading(true)
    try {
      const data = await api.generateRx({
        patient_id: parseInt(patientId, 10),
        pattern: form.pattern, risk_level: form.risk_level,
        phase: form.phase, week_no: parseInt(form.week_no, 10) || 1,
      })
      setRx(data)
      loadHistory(data.patient_id)
    } catch (err) { setError(err.message) } finally { setLoading(false) }
  }

  async function saveDraft() {
    if (!rx) return
    setError('')
    try {
      const updated = await api.updateRx(rx.rx_id, {
        baduanjin_level: rx.baduanjin_level, aerobic_type: rx.aerobic_type,
        aerobic_duration: rx.aerobic_duration, aerobic_freq: rx.aerobic_freq,
        rpe_min: rx.rpe_min, rpe_max: rx.rpe_max, hr_min: rx.hr_min, hr_max: rx.hr_max,
      })
      setRx(updated)
      loadHistory(updated.patient_id)
    } catch (err) { setError(err.message) }
  }

  async function sign() {
    if (!rx) return
    const signName = window.prompt('医师签名（签发不可跳过）：', '')
    if (signName === null) return
    if (!signName.trim()) { setError('签名不能为空'); return }
    try {
      const updated = await api.signRx(rx.rx_id, { physician_sign: signName.trim() })
      setRx(updated)
      loadHistory(updated.patient_id)
    } catch (err) { setError(err.message) }
  }

  function setRxField(k, v) { setRx((r) => ({ ...r, [k]: v })) }

  return (
    <div className="rx">
      <h2>处方管理（一键生成 → 医师调整 → 签发 → 打印）</h2>
      {error && <p className="error">{error}</p>}
      <form className="form-grid" onSubmit={generate}>
        <label>患者
          <select value={patientId} onChange={(e) => onPatient(e.target.value)}>
            <option value="">— 选择患者 —</option>
            {patients.map((p) => (
              <option key={p.patient_id} value={p.patient_id}>{p.patient_id} · {p.name}</option>
            ))}
          </select>
        </label>
        <label>证型
          <select value={form.pattern} onChange={(e) => setForm((f) => ({ ...f, pattern: e.target.value }))}>
            <option value="">—</option>
            {['气虚血瘀', '气滞血瘀', '痰浊闭阻', '寒凝心脉', '气阴两虚', '肝阳上亢'].map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </label>
        <label>危险分层
          <select value={form.risk_level} onChange={(e) => setForm((f) => ({ ...f, risk_level: e.target.value }))}>
            <option value="">—</option>
            {['低危', '中危', '高危'].map((r) => <option key={r}>{r}</option>)}
          </select>
        </label>
        <label>分期
          <select value={form.phase} onChange={(e) => setForm((f) => ({ ...f, phase: e.target.value }))}>
            <option>I</option><option>II</option><option>III</option>
          </select>
        </label>
        <label>周次 <input type="number" min="1" max="52" value={form.week_no}
               onChange={(e) => setForm((f) => ({ ...f, week_no: e.target.value }))} /></label>
        <div className="form-actions">
          <button type="submit" disabled={loading || !patientId}>{loading ? '生成中…' : '一键生成处方'}</button>
          {latest && <span className="hint">最新评估：{latest.pattern || '无证型'} / {latest.risk_level || '无分层'} / PHQ-9 {latest.phq9 ?? '—'}</span>}
        </div>
      </form>

      {rx && (
        <div className="rx-detail">
          <h2>处方 #{rx.rx_id}（{rx.status}）｜ 矩阵 {rx.matrix_code}</h2>
          <div className="form-grid">
            <label>八段锦级别 <select value={rx.baduanjin_level || ''}
                  onChange={(e) => setRxField('baduanjin_level', e.target.value)}>
                {['', 'L0', 'L1', 'L2', 'L3', 'L3+'].map((l) => <option key={l}>{l}</option>)}
              </select></label>
            <label>有氧类型 <input value={rx.aerobic_type || ''} onChange={(e) => setRxField('aerobic_type', e.target.value)} /></label>
            <label>时长(分) <input type="number" value={rx.aerobic_duration ?? ''}
                  onChange={(e) => setRxField('aerobic_duration', e.target.value)} /></label>
            <label>频次(次/周) <input type="number" value={rx.aerobic_freq ?? ''}
                  onChange={(e) => setRxField('aerobic_freq', e.target.value)} /></label>
            <label>RPE 下限 <input type="number" value={rx.rpe_min ?? ''} onChange={(e) => setRxField('rpe_min', e.target.value)} /></label>
            <label>RPE 上限 <input type="number" value={rx.rpe_max ?? ''} onChange={(e) => setRxField('rpe_max', e.target.value)} /></label>
            <label>HR 下限 <input type="number" value={rx.hr_min ?? ''} onChange={(e) => setRxField('hr_min', e.target.value)} /></label>
            <label>HR 上限 <input type="number" value={rx.hr_max ?? ''} onChange={(e) => setRxField('hr_max', e.target.value)} /></label>
          </div>
          {(rx.safety?.warnings || []).length > 0 && (
            <div className="safety">
              <strong>安全提示：</strong>
              {rx.safety.warnings.map((w, i) => (
                <span key={i} className="tag">
                  {typeof w === 'string' ? w : (w.detail || w.desc || JSON.stringify(w))}
                </span>
              ))}
            </div>
          )}
          <div className="form-actions">
            {rx.status !== '已签发' && (
              <>
                <button type="button" onClick={saveDraft}>保存调整</button>
                <button type="button" onClick={sign}>签发处方</button>
              </>
            )}
            {rx.status === '已签发' && (
              <a className="btn-link" href={`/api/prescriptions/${rx.rx_id}/pdf`} target="_blank" rel="noreferrer">打印 PDF</a>
            )}
          </div>
        </div>
      )}

      <h2>处方历史（{history.length}）</h2>
      <table className="data-table">
        <thead>
          <tr><th>ID</th><th>日期</th><th>矩阵</th><th>八段锦</th><th>状态</th><th>签名</th></tr>
        </thead>
        <tbody>
          {history.map((h) => (
            <tr key={h.rx_id}>
              <td>{h.rx_id}</td><td>{h.gen_date}</td><td>{h.matrix_code}</td>
              <td>{h.baduanjin_level || ''}</td><td>{h.status}</td><td>{h.physician_sign || ''}</td>
            </tr>
          ))}
          {history.length === 0 && <tr><td colSpan="6" className="empty">暂无处方</td></tr>}
        </tbody>
      </table>
    </div>
  )
}
