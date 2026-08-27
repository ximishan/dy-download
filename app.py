from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QSpinBox, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from backend import BackendManager

APP_VERSION = "1.1.0"


class Worker(QThread):
    output = Signal(str)
    finished_ok = Signal(bool, str)

    def __init__(self, command: list[str], cwd: Path):
        super().__init__()
        self.command = command
        self.cwd = cwd
        self.process: subprocess.Popen | None = None

    def run(self):
        try:
            self.process = subprocess.Popen(
                self.command,
                cwd=self.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self.output.emit(line.rstrip())
            code = self.process.wait()
            self.finished_ok.emit(code == 0, f"进程退出码: {code}")
        except Exception as exc:
            self.finished_ok.emit(False, str(exc))

    def stop(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
            except Exception:
                pass


class CookieDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("手动填写 Cookie")
        self.resize(720, 360)
        layout = QVBoxLayout(self)
        help_text = QLabel(
            "在已登录抖音的浏览器中按 F12 → Network → 打开任意 douyin.com 请求 → "
            "Request Headers → Cookie，复制完整 Cookie 后粘贴到下方。"
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.text = QTextEdit()
        self.text.setPlaceholderText("passport_csrf_token=...; ttwid=...; sid_guard=...; sessionid=...")
        layout.addWidget(self.text)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"dy-download v{APP_VERSION} - 抖音主页批量下载")
        self.resize(1200, 820)
        self.setMinimumSize(1000, 680)

        self.root_dir = Path(__file__).resolve().parent
        self.manager = BackendManager(self.root_dir)
        self.settings = QSettings("ximishan", "dy-download")
        self.worker: Worker | None = None
        self.current_action = ""
        self.items: list[dict] = []
        self.last_download_count = 0

        self._build_ui()
        self._restore_settings()
        self.refresh_environment()
        self.refresh_risk_status()

    def _build_ui(self):
        root = QWidget(self)
        main = QVBoxLayout(root)

        header = QHBoxLayout()
        title = QLabel("抖音主页批量下载")
        title.setStyleSheet("font-size: 24px; font-weight: 700;")
        version = QLabel(f"v{APP_VERSION}")
        version.setStyleSheet("color: #777;")
        header.addWidget(title)
        header.addWidget(version)
        header.addStretch(1)
        main.addLayout(header)

        tabs = QTabWidget()
        tabs.addTab(self._build_download_tab(), "主页下载")
        tabs.addTab(self._build_settings_tab(), "环境与 Cookie")
        tabs.addTab(self._build_log_tab(), "运行日志")
        main.addWidget(tabs, 1)

        footer = QHBoxLayout()
        self.status = QLabel("状态：等待操作")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMaximumWidth(280)
        self.cancel_btn = QPushButton("停止当前任务")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.stop_task)
        footer.addWidget(self.status, 1)
        footer.addWidget(self.progress)
        footer.addWidget(self.cancel_btn)
        main.addLayout(footer)
        self.setCentralWidget(root)

    def _build_download_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        form = QFormLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("可直接粘贴抖音主页分享整段文字或 v.douyin.com 短链")
        form.addRow("抖音主页：", self.url_edit)

        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        choose_btn = QPushButton("选择目录")
        choose_btn.clicked.connect(self.choose_folder)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(choose_btn)
        form.addRow("保存目录：", folder_row)

        option_row = QHBoxLayout()
        self.scan_limit = QSpinBox()
        self.scan_limit.setRange(0, 100000)
        self.scan_limit.setSpecialValueText("全部")
        self.scan_limit.setValue(0)
        self.thread_spin = QSpinBox()
        self.thread_spin.setRange(1, 3)
        self.thread_spin.setValue(3)
        self.browser_fallback = QCheckBox("下载失败时浏览器兜底")
        self.browser_fallback.setChecked(True)
        option_row.addWidget(QLabel("解析数量"))
        option_row.addWidget(self.scan_limit)
        option_row.addSpacing(18)
        option_row.addWidget(QLabel("下载并发"))
        option_row.addWidget(self.thread_spin)
        option_row.addSpacing(18)
        option_row.addWidget(self.browser_fallback)
        option_row.addStretch(1)
        form.addRow("选项：", option_row)
        layout.addLayout(form)

        action_row = QHBoxLayout()
        self.scan_btn = QPushButton("① 解析主页")
        self.scan_btn.setMinimumHeight(38)
        self.scan_btn.clicked.connect(self.scan_profile)
        self.download_btn = QPushButton("② 下载勾选作品")
        self.download_btn.setMinimumHeight(38)
        self.download_btn.clicked.connect(self.download_selected)
        self.resume_btn = QPushButton("重新登录并继续")
        self.resume_btn.setMinimumHeight(38)
        self.resume_btn.clicked.connect(self.relogin_and_resume)
        open_btn = QPushButton("打开下载目录")
        open_btn.clicked.connect(self.open_output_folder)
        action_row.addWidget(self.scan_btn)
        action_row.addWidget(self.download_btn)
        action_row.addWidget(self.resume_btn)
        action_row.addWidget(open_btn)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        risk_row = QHBoxLayout()
        risk_title = QLabel("风控状态：")
        risk_title.setStyleSheet("font-weight: 700;")
        self.risk_level = QLabel("低")
        self.risk_status = QLabel("暂无风控信号")
        self.risk_hits = QLabel("风险计数 0")
        risk_row.addWidget(risk_title)
        risk_row.addWidget(self.risk_level)
        risk_row.addSpacing(12)
        risk_row.addWidget(self.risk_status, 1)
        risk_row.addWidget(self.risk_hits)
        layout.addLayout(risk_row)

        filter_row = QHBoxLayout()
        self.type_filter = QComboBox()
        self.type_filter.addItems(["全部类型", "视频", "图文"])
        self.type_filter.currentIndexChanged.connect(self.apply_filter)
        self.keyword_edit = QLineEdit()
        self.keyword_edit.setPlaceholderText("按标题关键词筛选")
        self.keyword_edit.textChanged.connect(self.apply_filter)
        select_all_btn = QPushButton("全选")
        select_all_btn.clicked.connect(lambda: self.set_visible_checked(True))
        clear_btn = QPushButton("取消全选")
        clear_btn.clicked.connect(lambda: self.set_visible_checked(False))
        self.summary_label = QLabel("尚未解析")
        filter_row.addWidget(QLabel("筛选："))
        filter_row.addWidget(self.type_filter)
        filter_row.addWidget(self.keyword_edit, 1)
        filter_row.addWidget(select_all_btn)
        filter_row.addWidget(clear_btn)
        filter_row.addWidget(self.summary_label)
        layout.addLayout(filter_row)

        splitter = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "选择", "类型", "发布时间", "标题", "点赞", "评论", "图片数", "作品ID"
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        for col in (4, 5, 6, 7):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        splitter.addWidget(self.table)

        self.preview_log = QTextEdit()
        self.preview_log.setReadOnly(True)
        self.preview_log.setMaximumHeight(160)
        self.preview_log.setPlaceholderText("解析/下载/风控状态会显示在这里。")
        splitter.addWidget(self.preview_log)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        return page

    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        env_box = QFormLayout()
        self.core_status = QLabel("未检测")
        self.cookie_status = QLabel("未检测")
        self.risk_detail = QLabel("未检测")
        self.risk_detail.setWordWrap(True)
        env_box.addRow("下载核心：", self.core_status)
        env_box.addRow("Cookie：", self.cookie_status)
        env_box.addRow("风控保护：", self.risk_detail)
        layout.addLayout(env_box)

        row1 = QHBoxLayout()
        prepare_btn = QPushButton("安装/更新下载核心")
        prepare_btn.clicked.connect(self.prepare_backend)
        cookie_btn = QPushButton("浏览器登录获取 Cookie")
        cookie_btn.clicked.connect(lambda: self.fetch_cookie(False))
        manual_btn = QPushButton("手动填写 Cookie")
        manual_btn.clicked.connect(self.manual_cookie)
        refresh_btn = QPushButton("刷新状态")
        refresh_btn.clicked.connect(self.refresh_environment)
        row1.addWidget(prepare_btn)
        row1.addWidget(cookie_btn)
        row1.addWidget(manual_btn)
        row1.addWidget(refresh_btn)
        row1.addStretch(1)
        layout.addLayout(row1)

        note = QLabel(
            "风控保护策略：API 保守限速、下载并发≤3；检测 403/429、空 200、验证码、登录态失效时主动停止。\n"
            "如果因登录态或验证码停止，可使用“重新登录并继续”。SQLite 会跳过已完成作品。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("padding: 16px; background: #f5f5f5; border-radius: 6px;")
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _build_log_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)
        clear_btn = QPushButton("清空日志")
        clear_btn.clicked.connect(self.log.clear)
        layout.addWidget(clear_btn)
        return page

    def _restore_settings(self):
        default_folder = str(Path.home() / "Downloads" / "dy-download")
        self.folder_edit.setText(self.settings.value("output_dir", default_folder))
        self.url_edit.setText(self.settings.value("last_url", ""))
        self.thread_spin.setValue(min(3, int(self.settings.value("threads", 3))))
        self.browser_fallback.setChecked(self.settings.value("browser_fallback", True, type=bool))

    def _save_settings(self):
        self.settings.setValue("output_dir", self.folder_edit.text())
        self.settings.setValue("last_url", self.url_edit.text())
        self.settings.setValue("threads", self.thread_spin.value())
        self.settings.setValue("browser_fallback", self.browser_fallback.isChecked())

    def closeEvent(self, event):
        self._save_settings()
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(1500)
        super().closeEvent(event)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择保存目录", self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)

    def open_output_folder(self):
        path = Path(self.folder_edit.text()).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            QMessageBox.warning(self, "无法打开目录", str(exc))

    def append_log(self, text: str):
        if not text:
            return
        self.log.append(text)
        if not text.startswith("DYSCAN:"):
            self.preview_log.append(text)

    def run_command(self, command: list[str], cwd: Path, label: str, action: str):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "提示", "当前已有任务正在执行。")
            return False
        self.current_action = action
        self.status.setText(f"状态：{label}")
        self.progress.setRange(0, 0)
        self.cancel_btn.setEnabled(True)
        self.append_log(f"> {' '.join(command)}")
        self.worker = Worker(command, cwd)
        self.worker.output.connect(self.handle_worker_output)
        self.worker.finished_ok.connect(self.task_finished)
        self.worker.start()
        return True

    def handle_worker_output(self, line: str):
        if line.startswith("DYSCAN:"):
            try:
                event = json.loads(line[len("DYSCAN:"):])
                kind = event.get("kind")
                payload = event.get("payload")
                if kind == "items":
                    self.items = payload if isinstance(payload, list) else []
                    self.populate_table()
                elif kind == "progress" and isinstance(payload, dict):
                    self.status.setText("状态：" + str(payload.get("message") or "正在解析"))
                    self.preview_log.append(str(payload.get("message") or ""))
                elif kind == "status":
                    self.status.setText("状态：" + str(payload))
                    self.preview_log.append(str(payload))
                elif kind == "error":
                    self.preview_log.append("错误：" + str(payload))
                elif kind == "log":
                    self.preview_log.append(str(payload))
            except Exception:
                self.append_log(line)
            return

        self.append_log(line)
        if "[风控保护]" in line:
            self.refresh_risk_status()

    def task_finished(self, ok: bool, message: str):
        self.cancel_btn.setEnabled(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(100 if ok else 0)
        action = self.current_action
        self.current_action = ""
        self.status.setText("状态：完成" if ok else "状态：失败")
        self.append_log(message)

        if action in {"prepare", "cookie", "cookie_resume"}:
            self.refresh_environment()
        self.refresh_risk_status()

        if action == "prepare" and ok:
            self.preview_log.append("下载核心已准备完成。下一步请获取 Cookie。")
        elif action == "scan" and ok:
            self.preview_log.append(f"主页解析完成：共 {len(self.items)} 条。")
        elif action == "download" and ok:
            QMessageBox.information(self, "下载完成", "勾选的作品已经处理完成。")
        elif action == "resume" and ok:
            QMessageBox.information(self, "恢复完成", "未完成作品已经继续处理完成。")
        elif action == "cookie_resume":
            if ok:
                self.manager.clear_risk_state()
                self.refresh_risk_status()
                self.preview_log.append("新的登录态已获取，正在继续原下载任务。")
                self.resume_download()
            else:
                QMessageBox.warning(self, "重新登录未完成", "没有成功更新 Cookie，请重新尝试。")
                return

        if not ok and action in {"download", "resume"}:
            state = self.manager.read_risk_state()
            reason = state.get("reason") or message
            needs_login = bool(state.get("needs_login"))
            if needs_login:
                QMessageBox.warning(
                    self, "下载已安全停止",
                    f"检测到登录态/风控问题：{reason}\n\n请点击“重新登录并继续”。"
                )
            else:
                QMessageBox.warning(
                    self, "下载已停止",
                    f"{reason}\n\n任务配置已保留，可稍后点击“重新登录并继续”或再次下载。"
                )
        elif not ok and action not in {"cookie_resume"}:
            QMessageBox.warning(self, "任务失败", message + "\n\n请查看“运行日志”获取详细信息。")

    def stop_task(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.status.setText("状态：正在停止…")

    def prepare_backend(self):
        try:
            command, cwd = self.manager.prepare_command()
            self.run_command(command, cwd, "安装/更新核心", "prepare")
        except Exception as exc:
            QMessageBox.warning(self, "准备失败", str(exc))

    def fetch_cookie(self, resume: bool = False):
        try:
            command, cwd = self.manager.cookie_command()
            self.run_command(command, cwd, "等待浏览器登录", "cookie_resume" if resume else "cookie")
        except Exception as exc:
            QMessageBox.warning(self, "无法获取 Cookie", str(exc))

    def relogin_and_resume(self):
        if not self.manager.can_resume_download():
            QMessageBox.information(self, "没有可恢复任务", "当前没有保存的下载任务，请先解析并下载作品。")
            return
        self.fetch_cookie(True)

    def resume_download(self):
        if not self.manager.can_resume_download():
            QMessageBox.information(self, "没有可恢复任务", "没有找到上一次下载配置。")
            return
        try:
            command, cwd = self.manager.download_command()
        except Exception as exc:
            QMessageBox.warning(self, "恢复失败", str(exc))
            return
        self.run_command(command, cwd, "正在继续未完成作品", "resume")

    def manual_cookie(self):
        dialog = CookieDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self.manager.save_manual_cookie(dialog.text.toPlainText())
            self.refresh_environment()
            self.refresh_risk_status()
            QMessageBox.information(self, "已保存", "Cookie 已保存，并已重置登录态风险。")
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))

    def refresh_environment(self):
        ready = (self.manager.backend_dir / "run.py").exists()
        self.core_status.setText("已安装" if ready else "未安装")
        self.core_status.setStyleSheet("color: #16803a;" if ready else "color: #b54708;")
        self._refresh_cookie_status()
        self.refresh_risk_status()

    def _refresh_cookie_status(self):
        text = self.manager.cookie_summary()
        self.cookie_status.setText(text)
        healthy = text.startswith("健康")
        self.cookie_status.setStyleSheet("color: #16803a;" if healthy else "color: #b54708;")

    def refresh_risk_status(self):
        state = self.manager.read_risk_state()
        level = str(state.get("level") or "low")
        status = str(state.get("status") or "等待下载")
        reason = str(state.get("reason") or "暂无风控信号")
        hits = int(state.get("risk_hits") or 0)
        display = {"low": "低", "medium": "中", "high": "高"}.get(level, level)
        color = {"low": "#16803a", "medium": "#b54708", "high": "#b42318"}.get(level, "#555")
        self.risk_level.setText(display)
        self.risk_level.setStyleSheet(f"font-weight:700; color:{color};")
        self.risk_status.setText(f"{status}｜{reason}")
        self.risk_hits.setText(f"风险计数 {hits}")
        self.risk_detail.setText(f"{display}风险｜{status}｜{reason}")
        self.risk_detail.setStyleSheet(f"color:{color};")
        self.resume_btn.setEnabled(self.manager.can_resume_download())

    def scan_profile(self):
        url = self.url_edit.text().strip()
        if not self.manager.validate_profile_url(url):
            QMessageBox.warning(self, "主页链接不正确", "请粘贴抖音主页链接、短链接或完整分享文案。")
            return
        try:
            command, cwd = self.manager.scan_command(url, self.scan_limit.value())
        except Exception as exc:
            QMessageBox.warning(self, "无法解析", str(exc))
            return
        self.items = []
        self.table.setRowCount(0)
        self.summary_label.setText("正在解析…")
        self.preview_log.clear()
        self._save_settings()
        self.run_command(command, cwd, "正在解析主页", "scan")

    def populate_table(self):
        self.table.setRowCount(0)
        for item in self.items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            check.setCheckState(Qt.Checked)
            self.table.setItem(row, 0, check)
            self.table.setItem(row, 1, QTableWidgetItem(str(item.get("type") or "")))
            ts = int(item.get("create_time") or 0)
            date_text = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""
            self.table.setItem(row, 2, QTableWidgetItem(date_text))
            title_item = QTableWidgetItem(str(item.get("title") or ""))
            title_item.setData(Qt.UserRole, item)
            self.table.setItem(row, 3, title_item)
            self.table.setItem(row, 4, QTableWidgetItem(str(item.get("digg_count") or 0)))
            self.table.setItem(row, 5, QTableWidgetItem(str(item.get("comment_count") or 0)))
            self.table.setItem(row, 6, QTableWidgetItem(str(item.get("image_count") or 0)))
            self.table.setItem(row, 7, QTableWidgetItem(str(item.get("aweme_id") or "")))
        self.apply_filter()

    def apply_filter(self):
        wanted_type = self.type_filter.currentText()
        keyword = self.keyword_edit.text().strip().lower()
        visible = videos = galleries = 0
        for row in range(self.table.rowCount()):
            kind = self.table.item(row, 1).text()
            title = self.table.item(row, 3).text().lower()
            show = (wanted_type == "全部类型" or kind == wanted_type) and (not keyword or keyword in title)
            self.table.setRowHidden(row, not show)
            if show:
                visible += 1
                videos += kind == "视频"
                galleries += kind == "图文"
        self.summary_label.setText(f"显示 {visible} 条｜视频 {videos}｜图文 {galleries}")

    def set_visible_checked(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row):
                self.table.item(row, 0).setCheckState(state)

    def selected_items(self) -> list[dict]:
        selected: list[dict] = []
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).checkState() != Qt.Checked:
                continue
            item = self.table.item(row, 3).data(Qt.UserRole)
            if isinstance(item, dict):
                selected.append(item)
        return selected

    def download_selected(self):
        selected = self.selected_items()
        if not selected:
            QMessageBox.information(self, "没有选择作品", "请至少勾选一个作品。")
            return
        output = Path(self.folder_edit.text()).expanduser()
        output.mkdir(parents=True, exist_ok=True)
        try:
            config = self.manager.write_selected_config(
                items=selected,
                output_dir=output,
                threads=self.thread_spin.value(),
                browser_fallback=self.browser_fallback.isChecked(),
            )
            command, cwd = self.manager.download_command(config)
        except Exception as exc:
            QMessageBox.warning(self, "启动下载失败", str(exc))
            return
        self.last_download_count = len(selected)
        self._save_settings()
        self.preview_log.append(f"准备下载 {len(selected)} 条作品。风控保护已开启。")
        self.run_command(command, cwd, f"正在下载 {len(selected)} 条作品", "download")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("dy-download")
    app.setOrganizationName("ximishan")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
