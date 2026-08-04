import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function FollowupPage() {
  const [patients, setPatients] = useState([])
  const [patientId, setPatientId] = useState('')
  const [rows, setRows] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api.listPatients().then(setPatients).catch((e) => setError(e.message))
  }, [])

  function load(pid) {
    if (!pid) { setRows([]); return }
    api.listFollowups(pid).then(setRows).catch((e) => setError(e.message))
  }

  function onPatient(pid) {
    setPatientId(pid)
    load(pid)
  }

  async function generate() {
    if (!patientId) { setError('请先选择患者'); return }
    setError('')
    setLoading(true)
    try {
      const d = await api.generateFollowups({ patient_id: parseInt(patientId, 10) })
      setError(`已生成 ${d.created} 条随访计划（起算日 ${d.day0}）`)
      load(patientId)
    } catch (err) { setError(err.message) } finally { setLoading(false) }
  }

  async function complete(fu) {
    const handler = window.prompt(`登记随访完成（${fu.fu_type}，计划 ${fu.plan_date}）：\n完成人`, '')
    if (handler === null) return
    try {
      await api.completeFollowup(fu.fu_id, { handler: handler.trim() || undefined })
      load(patientId)
    } catch (err) { setError(err.message) }
  }

  const overdue = rows.filter((r) => r.overdue).length

  return (
    <div className="followup">
      <h2>随访管理（1周/1月/3月/6月/12月 计划 → 复评登记）</h2>
      {error && <p className="error">{error}</p>}
      <div className="form-grid">
        <label>患者
          <select value={patientId} onChange={(e) => onPatient(e.target.value)}>
            <option value="">— 选择患者 —</option>
            {patients.map((p) => (
              <option key={p.patient_id} value={p.patient_id}>{p.patient_id} · {p.name}</option>
            ))}
          </select>
        </label>
        <div className="form-actions">
          <button type="button" onClick={generate} disabled={loading || !patientId}>
            {loading ? '生成中…' : '生成随访计划'}
          </button>
          <span className="hint">{rows.length ? `共 ${rows.length} 条，逾期 ${overdue} 条` : ''}</span>
        </div>
      </div>

      <h2>随访计划</h2>
      <table className="data-table">
        <thead>
          <tr><th>ID</th><th>类型</th><th>计划日期</th><th>实际日期</th><th>状态</th><th>完成人</th><th>操作</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.fu_id} className={r.overdue ? 'row-overdue' : ''}>
              <td>{r.fu_id}</td><td>{r.fu_type}</td><td>{r.plan_date}</td>
              <td>{r.actual_date || ''}</td>
              <td>{r.overdue ? '已逾期' : r.status}</td><td>{r.handler || ''}</td>
              <td>
                {r.status === '待随访' && (
                  <button className="link" onClick={() => complete(r)}>登记完成</button>
                )}
              </td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan="7" className="empty">暂无随访计划，请先生成</td></tr>}
        </tbody>
      </table>
    </div>
  )
}
