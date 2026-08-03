# -*- coding: utf-8 -*-
"""
处方单 PDF 导出（文档 2.6 五大处方整合输出样式）
reportlab + 系统中文字体（微软雅黑 msyh.ttc → simhei.ttf 兜底）
"""
import json
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                Table, TableStyle, HRFlowable)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors

# ---------- 中文字体注册 ----------
_FONT_CANDIDATES = [
    ("MSYH", r"C:\Windows\Fonts\msyh.ttc"),
    ("MSYH", r"C:\Windows\Fonts\msyh.ttf"),
    ("SimHei", r"C:\Windows\Fonts\simhei.ttf"),
]


def _register_font():
    for name, path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path, subfontIndex=0))
                return name
            except Exception:
                continue
    return "Helvetica"  # 无中文字体时兜底


def export_rx_pdf(patient_info: dict, rx: dict, out_path: str) -> str:
    """导出处方单 PDF。纯逻辑，无 conn（P2-T4）。
    参数：
      patient_info: {'name', 'gender', 'birth_date'}（由 repo.get_patient_for_pdf() 获取）
      rx: prescription 表行（dict）
    """
    font = _register_font()
    title_st = ParagraphStyle("title", fontName=font, fontSize=16, leading=22,
                              alignment=1, textColor=colors.HexColor("#8B2F2F"))
    head_st = ParagraphStyle("head", fontName=font, fontSize=10, leading=15)
    sec_st = ParagraphStyle("sec", fontName=font, fontSize=11, leading=16,
                            textColor=colors.HexColor("#8B2F2F"), spaceBefore=6)
    body_st = ParagraphStyle("body", fontName=font, fontSize=10, leading=15, leftIndent=8)
    foot_st = ParagraphStyle("foot", fontName=font, fontSize=10, leading=15)

    name = (patient_info or {}).get("name", "")
    gender = (patient_info or {}).get("gender", "")
    birth = (patient_info or {}).get("birth_date", "")

    tcm = json.loads(rx.get("tcm_json") or "{}")
    res = json.loads(rx.get("resistance_json") or "{}")
    rf = json.loads(rx.get("risk_factor_json") or "{}")
    hr_txt = f"{rx.get('hr_min')}–{rx.get('hr_max')} 次/分" if rx.get("hr_min") else "以 RPE 为准（服β受体阻滞剂）"
    res_txt = "已禁用（禁忌命中）" if not res.get("enabled", True) else (
        f"{res.get('type')} {res.get('sets')}组×{res.get('reps')}次 × {res.get('frequency_per_week')}次/周")

    doc = SimpleDocTemplate(out_path, pagesize=A4,
                            leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm,
                            title=f"康复处方单 {rx.get('matrix_code')}")
    story = []
    story.append(Paragraph("中西医结合心血管康复处方单", title_st))
    story.append(Paragraph(f"编号：CR-2026-{str(rx.get('rx_id') or '____'):>04}    签发日期：{rx.get('gen_date')}", head_st))
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#8B2F2F")))

    info = Table([
        ["患者", f"{name}（{'男' if gender == '男' else '女'}）", "出生", birth or "—"],
        ["矩阵分层", rx.get("matrix_code") or "—", "阶段", f"{rx.get('phase')}期 第{rx.get('week_no')}周"],
    ], colWidths=[18 * mm, 55 * mm, 18 * mm, 55 * mm])
    info.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(info)
    story.append(Spacer(1, 3 * mm))

    sections = [
        ("① 运动处方", [
            f"八段锦：{rx.get('baduanjin_level')}（按分级动作要求完成）",
            f"有氧运动：{rx.get('aerobic_type')} {rx.get('aerobic_duration')} 分钟 × {rx.get('aerobic_freq')} 次/周（热身5分 + 主体 + 整理5分）",
            f"目标强度：RPE {rx.get('rpe_min')}–{rx.get('rpe_max')}；心率 {hr_txt}",
            f"抗阻训练：{res_txt}",
        ]),
        ("② 中医处方（中医师签署）", [
            f"治法：{tcm.get('method', '')}",
            f"穴位：{'、'.join(tcm.get('acupoints', []))}",
            f"食疗方向：{tcm.get('diet_notes', '')}",
        ]),
        ("③ 营养处方", [
            f"膳食建议：{tcm.get('diet_notes', '')}",
            f"禁忌：{'、'.join(tcm.get('contraindications', []))}；钠 <5g/日",
        ]),
        ("④ 心理处方", [
            "正念呼吸 10 分/日；量表评估结果见随访记录",
        ]),
        ("⑤ 危险因素管理", [
            f"LDL-C 目标 <{rf.get('LDL_C_target', '1.4')} mmol/L；血压目标 <{rf.get('BP_target', '130/80')} mmHg",
            "戒烟、限酒、限盐；按证型食疗与情志调摄执行",
        ]),
    ]
    for sec_title, items in sections:
        story.append(Paragraph(sec_title, sec_st))
        for it in items:
            story.append(Paragraph(f"· {it}", body_st))

    story.append(Spacer(1, 5 * mm))
    story.append(HRFlowable(width="100%", thickness=0.8, color=colors.grey))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("本处方为临床决策支持工具生成，须经执业医师审核签发后执行。"
                           "运动中出现胸痛、头晕、气促等应立即停止并联系医师。", foot_st))
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(f"医师签名：____________（{rx.get('physician_sign') or ''}）", foot_st))

    doc.build(story)
    return out_path


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from db import get_conn
    conn = get_conn()
    rx = conn.execute(
        "SELECT * FROM prescription WHERE status='已签发' ORDER BY rx_id DESC LIMIT 1"
    ).fetchone()
    if not rx:
        print("暂无已签发处方，跳过 PDF 测试")
    else:
        out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "_test_rx.pdf")
        export_rx_pdf(repo.get_patient_for_pdf(rx["patient_id"]), dict(rx), out)
        print("PDF 生成:", out, os.path.getsize(out), "bytes")
    conn.close()
