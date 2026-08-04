import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

const EMPTY = {
  name: '', gender: '', birth_date: '', contact: '', inpatient_no: '',
  register_date: '', physician: '', status: '在组', disease_category: 'CAD_PCI',
}

export default function PatientsPage() {
  const [patients, setPatients] = useState([])
  const [form, setForm] = useState({ ...EMPTY })
  const [editingId, setEditingId] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function load() {
    try {
      setPatients(await api.listPatients())
    } catch (e) { setError(e.message) }
  }
  useEffect(() => { load() }, [])

  function set(k, v) { setForm((f) => ({ ...f, [k]: v })) }

  async function submit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      if (editingId) {
        await api.updatePatient(editingId, form)
      } else {
        await api.createPatient(form)
      }
      setForm({ ...EMPTY })
      setEditingId(null)
      await load()
    } catch (err) { setError(err.message) } finally { setLoading(false) }
  }

  function edit(p) {
    setEditingId(p.patient_id)
    setForm({
      name: p.name || '', gender: p.gender || '', birth_date: p.birth_date || '',
      contact: p.contact || '', inpatient_no: p.inpatient_no || '',
      register_date: p.register_date || '', physician: p.physician || '',
      status: p.status || '在组', disease_category: p.disease_category || 'CAD_PCI',
    })
  }

  async function remove(p) {
    if (!window.confirm(`确定删除患者 ${p.name}？有业务记录的患者将被拒绝`)) return
    try {
      await api.deletePatient(p.patient_id)
      await load()
    } catch (err) { setError(err.message) }
  }

  return (
    <div className="patients">
      <h2>{editingId ? `编辑患者 #${editingId}` : '新建患者'}</h2>
      {error && <p className="error">{error}</p>}
      <form className="form-grid" onSubmit={submit}>
        <label>姓名 <input value={form.name} onChange={(e) => set('name', e.target.value)} required /></label>
        <label>性别
          <select value={form.gender} onChange={(e) => set('gender', e.target.value)}>
            <option value="">—</option><option>男</option><option>女</option>
          </select>
        </label>
        <label>出生日期 <input value={form.birth_date} onChange={(e) => set('birth_date', e.target.value)} placeholder="1960-01-01" /></label>
        <label>联系电话 <input value={form.contact} onChange={(e) => set('contact', e.target.value)} /></label>
        <label>住院号 <input value={form.inpatient_no} onChange={(e) => set('inpatient_no', e.target.value)} /></label>
        <label>建档日期 <input value={form.register_date} onChange={(e) => set('register_date', e.target.value)} placeholder="留空默认今天" /></label>
        <label>主管医师 <input value={form.physician} onChange={(e) => set('physician', e.target.value)} /></label>
        <label>状态
          <select value={form.status} onChange={(e) => set('status', e.target.value)}>
            <option>在组</option><option>出院</option><option>失访</option>
          </select>
        </label>
        <label>病种
          <select value={form.disease_category} onChange={(e) => set('disease_category', e.target.value)}>
            <option>CAD_PCI</option>
          </select>
        </label>
        <div className="form-actions">
          <button type="submit" disabled={loading}>{loading ? '保存中…' : (editingId ? '保存修改' : '建档')}</button>
          {editingId && <button type="button" className="ghost" onClick={() => { setEditingId(null); setForm({ ...EMPTY }) }}>取消编辑</button>}
        </div>
      </form>

      <h2>患者列表（{patients.length}）</h2>
      <table className="data-table">
        <thead>
          <tr><th>ID</th><th>姓名</th><th>性别</th><th>出生日期</th><th>联系电话</th>
              <th>建档日期</th><th>主管医师</th><th>状态</th><th>操作</th></tr>
        </thead>
        <tbody>
          {patients.map((p) => (
            <tr key={p.patient_id}>
              <td>{p.patient_id}</td><td>{p.name}</td><td>{p.gender || ''}</td>
              <td>{p.birth_date || ''}</td><td>{p.contact || ''}</td>
              <td>{p.register_date || ''}</td><td>{p.physician || ''}</td>
              <td>{p.status || ''}</td>
              <td>
                <button className="link" onClick={() => edit(p)}>编辑</button>
                <button className="link danger" onClick={() => remove(p)}>删除</button>
              </td>
            </tr>
          ))}
          {patients.length === 0 && (
            <tr><td colSpan="9" className="empty">暂无患者，请先建档</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
