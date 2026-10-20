"""
A command run in its own process group, with its output as lines.

Stopping sends SIGINT to the whole group, like Ctrl+C in a terminal, then
SIGTERM and SIGKILL to whatever is still alive, so no Gazebo server or ROS
node is left running after a stop.
"""

import os
import re
import signal

from PyQt5.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, pyqtSignal

# Terminal color codes (Gazebo prints them even without a terminal).
ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')

# Seconds after SIGINT before SIGTERM, and after SIGTERM before SIGKILL.
INT_TIMEOUT = 15
TERM_TIMEOUT = 5


def group_alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def signal_group(pgid, sig):
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


class Runner(QObject):
    line = pyqtSignal(str)          # a line of the output
    started = pyqtSignal()
    finished = pyqtSignal(int)      # exit code, after the whole process group is gone

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        # Plain, unbuffered output of the ROS tools.
        env.insert('RCUTILS_COLORIZED_OUTPUT', '0')
        env.insert('RCUTILS_LOGGING_BUFFERED_STREAM', '0')
        env.insert('PYTHONUNBUFFERED', '1')
        self.proc.setProcessEnvironment(env)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.started.connect(self._started)
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(self._error)
        self.pgid = None
        self.stopping = False
        self._buffer = ''
        self._exit_code = 0
        self._timers = []

    def running(self):
        """True while the command or any process of its group runs."""
        return self.proc.state() != QProcess.NotRunning or (self.pgid is not None and group_alive(self.pgid))

    def start(self, argv, cwd=None):
        if self.running():
            raise RuntimeError('already running')
        self.stopping = False
        self._buffer = ''
        if cwd:
            self.proc.setWorkingDirectory(cwd)
        self.proc.start(argv[0], argv[1:])

    def stop(self):
        """Stop the command and every process it started (asynchronously; see 'finished')."""
        if not self.running() or self.stopping:
            return
        self.stopping = True
        self.line.emit('--- Stopping (Ctrl+C) ---')
        signal_group(self.pgid, signal.SIGINT)
        self._later(INT_TIMEOUT, self._terminate)

    def stop_and_wait(self):
        """Stop and block until everything is gone (for closing the application)."""
        if not self.running():
            return
        signal_group(self.pgid, signal.SIGINT)
        for sig, timeout in ((signal.SIGTERM, INT_TIMEOUT), (signal.SIGKILL, TERM_TIMEOUT)):
            if self._wait_group(timeout):
                return
            signal_group(self.pgid, sig)
        self._wait_group(TERM_TIMEOUT)

    # --- internals ---

    def _wait_group(self, seconds):
        self.proc.waitForFinished(int(seconds * 1000))
        for _ in range(int(seconds * 10)):
            if not group_alive(self.pgid):
                return True
            self.proc.waitForFinished(100)
        return not group_alive(self.pgid)

    def _later(self, seconds, function):
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(function)
        timer.start(int(seconds * 1000))
        self._timers.append(timer)

    def _cancel_timers(self):
        for timer in self._timers:
            timer.stop()
            timer.deleteLater()
        self._timers = []

    def _terminate(self):
        if self.pgid is not None and group_alive(self.pgid):
            self.line.emit('--- Still running, terminating (SIGTERM) ---')
            signal_group(self.pgid, signal.SIGTERM)
            self._later(TERM_TIMEOUT, self._kill)

    def _kill(self):
        if self.pgid is not None and group_alive(self.pgid):
            self.line.emit('--- Still running, killing (SIGKILL) ---')
            signal_group(self.pgid, signal.SIGKILL)
            self._later(1, self._check_gone)

    def _started(self):
        # The command is started with setsid, so its pid is its process group id.
        self.pgid = self.proc.processId()
        self.started.emit()

    def _read(self):
        data = bytes(self.proc.readAllStandardOutput()).decode('utf-8', 'replace')
        lines = (self._buffer + data.replace('\r\n', '\n').replace('\r', '\n')).split('\n')
        self._buffer = lines.pop()
        for text in lines:
            text = ANSI.sub('', text).rstrip()
            if text:
                self.line.emit(text)

    def _finished(self, code, status):
        if self._buffer:
            self.line.emit(self._buffer)
            self._buffer = ''
        self._exit_code = code if status == QProcess.NormalExit else -1
        if self.pgid is not None and group_alive(self.pgid):
            # The main process is gone, but processes it started are not (e.g. a Gazebo server).
            self.line.emit('--- Terminating the processes left running ---')
            signal_group(self.pgid, signal.SIGTERM)
            self._cancel_timers()
            self._later(TERM_TIMEOUT, self._kill)
            self._later(0.5, self._check_gone)
        else:
            self._done()

    def _check_gone(self):
        if self.pgid is not None and group_alive(self.pgid):
            self._later(0.5, self._check_gone)
        else:
            self._done()

    def _done(self):
        if self.pgid is None:
            return
        self._cancel_timers()
        self.pgid = None
        self.stopping = False
        self.finished.emit(self._exit_code)

    def _error(self, error):
        if error == QProcess.FailedToStart:
            self.line.emit(f'--- Failed to start: {self.proc.errorString()} ---')
            self.finished.emit(-1)
