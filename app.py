from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from backend import BackendManager


class Worker(QThread):
    output = Signal(str)
    finished_ok = Signal(bool, str)

    def __init__(self, command: list[str], cwd: Path):
        super().__init__()
        self.command = command
        self.cwd = cwd

    def run(self):
        try:
            process = subprocess.Popen(
                self.command,
                cwd=self.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                self.output.emit(line.rstrip())
            code = process.wait()
            self.finished_ok.emit(code == 0, f"进程退出码: {code}")
        except Exception as exc:
            self.finished_ok.emit(False, str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("dy-download - 抖音主页批量下载")
        self.resize(860, 620)

        self.manager = BackendManager(Path(__file__).resolve().parent)
        self.worker: Worker | None = None

        root = QWidget(self)
        layout = QVBoxLayout(root)

        title = QLabel("抖音主页批量下载")
        title.setStyleSheet("font-size: 22px; font-weight: 700; padding: 8px 0;")
        layout.addWidget(title)

        form = QFormLayout()

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://www.douyin.com/user/...")
        form.addRow("抖音主页：", self.url_edit)

        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit(str(Path.home() / "Downloads" / "dy-download"))
        choose_btn = QPushButton("选择目录")
        choose_btn.clicked.connect(self.choose_folder)
        folder_row.addWidget(self.folder_edit)
        folder_row.addWidget(choose_btn)
        form.addRow("保存目录：", folder_row)

        self.count_spin = QSpinBox()
        self.count_spin.setRange(0, 100000)
        self.count_spin.setValue(0)
        self.count_spin.setSpecialValueText("全部")
        form.addRow("下载数量：", self.count_spin)

        self.thread_spin = QSpinBox()
        self.thread_spin.setRange(1, 16)
        self.thread_spin.setValue(5)
        form.addRow("并发线程：", self.thread_spin)

        self.browser_fallback = QCheckBox("接口分页失败时启用浏览器兜底")
        self.browser_fallback.setChecked(True)
        form.addRow("稳定模式：", self.browser_fallback)

        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.prepare_btn = QPushButton("安装/更新下载核心")
        self.cookie_btn = QPushButton("浏览器登录获取 Cookie")
        self.download_btn = QPushButton("开始下载主页作品")
        self.prepare_btn.clicked.connect(self.prepare_backend)
        self.cookie_btn.clicked.connect(self.fetch_cookie)
        self.download_btn.clicked.connect(self.start_download)
        buttons.addWidget(self.prepare_btn)
        buttons.addWidget(self.cookie_btn)
        buttons.addWidget(self.download_btn)
        layout.addLayout(buttons)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("运行日志会显示在这里……")
        layout.addWidget(self.log, 1)

        self.status = QLabel("状态：等待操作")
        layout.addWidget(self.status)

        self.setCentralWidget(root)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择保存目录", self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)

    def append_log(self, text: str):
        self.log.append(text)

    def run_command(self, command: list[str], cwd: Path, label: str):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "提示", "当前已有任务正在执行。")
            return
        self.status.setText(f"状态：{label}")
        self.append_log(f"> {' '.join(command)}")
        self.worker = Worker(command, cwd)
        self.worker.output.connect(self.append_log)
        self.worker.finished_ok.connect(self.task_finished)
        self.worker.start()

    def task_finished(self, ok: bool, message: str):
        self.status.setText("状态：完成" if ok else "状态：失败")
        self.append_log(message)
        if not ok:
            QMessageBox.warning(self, "任务失败", message)

    def prepare_backend(self):
        try:
            command, cwd = self.manager.prepare_command()
        except Exception as exc:
            QMessageBox.warning(self, "准备失败", str(exc))
            return
        self.run_command(command, cwd, "安装/更新核心")

    def fetch_cookie(self):
        try:
            command, cwd = self.manager.cookie_command()
        except Exception as exc:
            QMessageBox.warning(self, "无法获取 Cookie", str(exc))
            return
        self.run_command(command, cwd, "等待浏览器登录")

    def start_download(self):
        url = self.url_edit.text().strip()
        if "/user/" not in url:
            QMessageBox.warning(self, "主页链接不正确", "请输入完整的抖音用户主页链接。")
            return

        output = Path(self.folder_edit.text()).expanduser()
        output.mkdir(parents=True, exist_ok=True)

        try:
            config_path = self.manager.write_config(
                url=url,
                output_dir=output,
                count=self.count_spin.value(),
                threads=self.thread_spin.value(),
                browser_fallback=self.browser_fallback.isChecked(),
            )
            command, cwd = self.manager.download_command(config_path)
        except Exception as exc:
            QMessageBox.warning(self, "启动失败", str(exc))
            return

        self.run_command(command, cwd, "正在下载")


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
