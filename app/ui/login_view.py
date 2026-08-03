# -*- coding: utf-8 -*-
"""
登录窗口（P3-T2）：登录认证 + 首次初始化管理员。
设计来源：docs/分阶段开发设计与任务列表.md §4.5
"""
import tkinter as tk
from tkinter import ttk, messagebox

from log import get_logger

_logger = get_logger("view.login")


class LoginView(tk.Toplevel):
    """登录/初始化管理员窗口。模态：登录成功前不进入主程序。

    模式：
      mode="login"     —— 普通登录（用户名/密码）
      mode="init"      —— 首次初始化管理员（用户名/密码/确认密码/显示名）
    成功回调 on_success(token)；初始化模式回调 on_init_success(user_id)。
    """

    def __init__(self, master, auth, mode="login", on_success=None):
        super().__init__(master)
        self.auth = auth
        self.mode = mode
        self.on_success = on_success
        self.title("初始化管理员" if mode == "init" else "登录 - 中西医结合心血管康复系统")
        self.resizable(False, False)
        self.grab_set()  # 模态
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build(self):
        pad = 10
        frm = ttk.Frame(self, padding=16)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="中西医结合心血管康复系统",
                  font=("微软雅黑", 13, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 10))

        r = 1
        if self.mode == "init":
            tk.Label(frm, text="首次使用：创建管理员账号", fg="#8B2F2F").grid(
                row=r, column=0, columnspan=2, sticky="w", pady=(0, 6))
            r += 1
            ttk.Label(frm, text="显示名：").grid(row=r, column=0, sticky="e", padx=4, pady=3)
            self.var_display = tk.StringVar()
            ttk.Entry(frm, textvariable=self.var_display, width=22).grid(
                row=r, column=1, sticky="w", padx=4, pady=3)
            r += 1

        ttk.Label(frm, text="用户名：").grid(row=r, column=0, sticky="e", padx=4, pady=3)
        self.var_user = tk.StringVar()
        ttk.Entry(frm, textvariable=self.var_user, width=22).grid(row=r, column=1, sticky="w", padx=4, pady=3)
        r += 1
        ttk.Label(frm, text="密码：").grid(row=r, column=0, sticky="e", padx=4, pady=3)
        self.var_pwd = tk.StringVar()
        ttk.Entry(frm, textvariable=self.var_pwd, width=22, show="*").grid(
            row=r, column=1, sticky="w", padx=4, pady=3)
        r += 1
        if self.mode == "init":
            ttk.Label(frm, text="确认密码：").grid(row=r, column=0, sticky="e", padx=4, pady=3)
            self.var_pwd2 = tk.StringVar()
            ttk.Entry(frm, textvariable=self.var_pwd2, width=22, show="*").grid(
                row=r, column=1, sticky="w", padx=4, pady=3)
            r += 1

        self.var_msg = tk.StringVar(value="")
        tk.Label(frm, textvariable=self.var_msg, fg="#8B2F2F",
                 font=("微软雅黑", 9)).grid(row=r, column=0, columnspan=2, sticky="w", pady=(4, 0))
        r += 1

        btns = ttk.Frame(frm)
        btns.grid(row=r, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btns, text="登录" if self.mode == "login" else "创建并登录",
                   command=self._submit).pack(side="left", padx=6)
        ttk.Button(btns, text="退出", command=self._on_close).pack(side="left", padx=6)

    def _submit(self):
        username = self.var_user.get().strip()
        password = self.var_pwd.get()
        if not username or not password:
            self.var_msg.set("用户名和密码不能为空")
            return
        if self.mode == "init":
            if password != self.var_pwd2.get():
                self.var_msg.set("两次密码输入不一致")
                return
            if len(password) < 8:
                self.var_msg.set("密码至少 8 位")
                return
            try:
                from security import get_security
                sec = get_security()
                user_id = self.auth.repo.create_user(
                    username, sec.hash_password(password),
                    self.var_display.get().strip() or username, "管理员")
                _logger.info("初始化管理员完成: %s", username)
                self.auth.repo.record_audit(user_id, "CREATE", "user", user_id,
                                            None, None, f"初始化管理员 {username}")
                messagebox.showinfo("初始化完成", "管理员账号已创建，请登录")
                self.mode = "login"
                self.title("登录 - 中西医结合心血管康复系统")
                self.var_pwd.set("")
                self.var_pwd2.set("")
                self.var_msg.set("")
                for w in self.winfo_children():
                    pass  # 保持布局，切回登录态
                return
            except Exception as e:
                _logger.error("初始化管理员失败: %s", e)
                self.var_msg.set(f"创建失败：{e}")
                return
        # 登录
        token = self.auth.login(username, password)
        if token:
            _logger.info("登录成功: %s", username)
            self.destroy()
            if self.on_success:
                self.on_success(token)
        else:
            self.var_msg.set("登录失败：用户名或密码错误（连续 5 次将锁定 15 分钟）")
            self.var_pwd.set("")

    def _on_close(self):
        """退出：关闭整个应用（登录不成功不进入主程序）。"""
        self.destroy()
        self.master.destroy()
