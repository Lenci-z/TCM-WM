import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

const NUM_FIELDS = [
  { key: 'LVEF', label: 'LVEF(%)', group: '心功能', min: 0, max: 100 },
  { key: 'NT_proBNP', label: 'NT-proBNP(pg/mL)', group: '心功能', min: 0, max: 100000 },
  { key: 'BP_sys', label: '收缩压(mmHg)', group: '心功能', min: 60, max: 260 },
  { key: 'BP_dia', label: '舒张压(mmHg)', group: '心功能', min: 30, max: 150 },
  { key: 'LDL_C', label: 'LDL-C(mmol/L)', group: '代谢', min: 0.1, max: 20 },
  { key: 'HbA1c', label: 'HbA1c(%)', group: '代谢', min: 3, max: 20 },
  { key: 'UACR', label: 'UACR(mg/g)', group: '代谢' },
  { key: 'BMI', label: 'BMI', group: '代谢', min: 10, max: 60 },
  { key: 'six_mwd', label: '6MWD(m)', group: '运动', min: 0, max: 1000 },
  { key: 'grip', label: '握力(kg)', group: '运动' },
  { key: 'PHQ9', label: 'PHQ-9', group: '心理', min: 0, max: 27 },
  { key: 'GAD7', label: 'GAD-7', group: '心理', min: 0, max: 21 },
]

export default function AssessmentPage() {
  const [patients, setPatients] = useState([])
  const [patientId, setPatientId] = useState('')
  const [items, setItems] = useState([])
  const [checks, setChecks] = useState({})
  const [form, setForm] = useState({ assessment_type: '基线', assess_date: '' })
  const [result, setResult] = useState(null)
  const [history, setHistory] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api.listPatients().then(setPatients).catch((e) => setError(e.message))
    api.getPatternKeywords().then((d) => {
      setItems(d.items || [])
      const c = {}
      d.items.forEach((i) => { c[i] = false })
      setChecks(c)
    }).catch((e) => setError(e.message))
  }, [])

  function loadHistory(pid) {
    api.listAssessments(pid).then(setHistory).catch(() => setHistory([]))
  }

  function set(k, v) { setForm((f) => ({ ...f, [k]: v })) }

  async function submit(e) {
    e.preventDefault()
    setError('')
    if (!patientId) { setError('请先选择患者'); return }
    setLoading(true)
    try {
      const body = {
        patient_id: parseInt(patientId, 10),
        assessment_type: form.assessment_type,
        assess_date: form.assess_date || undefined,
        pattern_items: Object.keys(checks).filter((k) => checks[k]),
      }
      NUM_FIELDS.forEach((f) => {
        const v = form[f.key]
        if (v !== undefined && v !== '') body[f.key] = parseFloat(v)
      })
      const data = await api.createAssessment(body)
      setResult(data)
      loadHistory(data.patient_id)
    } catch (err) { setError(err.message) } finally { setLoading(false) }
  }

  const groups = ['心功能', '代谢', '运动', '心理']

  return (
    <div className="assessment">
      <h2>评估录入（自动证型判定 + 自动危险分层）</h2>
      {error && <p className="error">{error}</p>}
      <form className="form-grid" onSubmit={submit}>
        <label>患者
          <select value={patientId} onChange={(e) => { setPatientId(e.target.value); loadHistory(e.target.value) }}>
            <option value="">— 选择患者 —</option>
            {patients.map((p) => (
              <option key={p.patient_id} value={p.patient_id}>{p.patient_id} · {p.name}</option>
            ))}
          </select>
        </label>
        <label>评估类型
          <select value={form.assessment_type} onChange={(e) => set('assessment_type', e.target.value)}>
            <option>基线</option><option>1周复评</option><option>1月复评</option>
            <option>3月复评</option><option>6月复评</option><option>12月复评</option>
          </select>
        </label>
        <label>评估日期 <input value={form.assess_date} onChange={(e) => set('assess_date', e.target.value)} placeholder="留空默认今天" /></label>
        <div className="form-actions" />

        {groups.map((g) => (
          <fieldset key={g} className="group">
            <legend>{g}</legend>
            {NUM_FIELDS.filter((f) => f.group === g).map((f) => (
              <label key={f.key}>
                {f.label}
                <input type="number" step="any" value={form[f.key] ?? ''}
                       onChange={(e) => set(f.key, e.target.value)}
                       placeholder={f.min !== undefined ? `${f.min}-${f.max}` : ''} />
              </label>
            ))}
          </fieldset>
        ))}

        <fieldset className="group full">
          <legend>四诊问卷（勾选症状/舌脉 → 自动证型判定）</legend>
          <div className="checks">
            {items.map((i) => (
              <label key={i} className="check">
                <input type="checkbox" checked={!!checks[i]}
                       onChange={(e) => setChecks((c) => ({ ...c, [i]: e.target.checked }))} />
                {i}
              </label>
            ))}
          </div>
        </fieldset>

        <div className="form-actions">
          <button type="submit" disabled={loading}>{loading ? '判定中…' : '保存并判定'}</button>
        </div>
      </form>

      {result && (
        <div className="result">
          <h2>判定结果</h2>
          <p>证型：<strong>{result.main_pattern || '—'}</strong>
             {result.secondary_pattern ? `（兼 ${result.secondary_pattern}）` : ''}</p>
          <p>危险分层：<strong className={result.risk_level === '高危' ? 'risk-high' : result.risk_level === '中危' ? 'risk-mid' : 'risk-low'}>
            {result.risk_level}</strong></p>
          {(result.risk_triggered || []).map((t, i) => (
            <p key={i} className="trigger">命中：{t.desc}</p>
          ))}
        </div>
      )}

      <h2>评估历史</h2>
      <table className="data-table">
        <thead>
          <tr><th>日期</th><th>类型</th><th>LVEF</th><th>6MWD</th><th>PHQ-9</th></tr>
        </thead>
        <tbody>
          {history.map((h) => (
            <tr key={h.assessment_id}>
              <td>{h.assess_date}</td><td>{h.assessment_type}</td>
              <td>{h.LVEF ?? ''}</td><td>{h.six_mwd ?? ''}</td><td>{h.PHQ9 ?? ''}</td>
            </tr>
          ))}
          {history.length === 0 && <tr><td colSpan="5" className="empty">暂无评估记录</td></tr>}
        </tbody>
      </table>
    </div>
  )
}
