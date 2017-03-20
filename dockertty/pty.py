import os
import signal
import threading
from ssl import SSLError

import binascii

import stream as io
import tty


class WINCHHandler(object):
    """
    WINCH Signal handler to keep the PTY correctly sized.
    """

    def __init__(self, pty):
        """
        Initialize a new WINCH handler for the given PTY.

        Initializing a handler has no immediate side-effects. The `start()`
        method must be invoked for the signals to be trapped.
        """

        self.pty = pty
        self.original_handler = None

    def __enter__(self):
        """
        Invoked on entering a `with` block.
        """

        self.start()
        return self

    def __exit__(self, *_):
        """
        Invoked on exiting a `with` block.
        """

        self.stop()

    def start(self):
        """
        Start trapping WINCH signals and resizing the PTY.

        This method saves the previous WINCH handler so it can be restored on
        `stop()`.
        """

        def handle(signum, frame):
            if signum == signal.SIGWINCH:
                self.pty.resize()

        self.original_handler = signal.signal(signal.SIGWINCH, handle)

    def stop(self):
        """
        Stop trapping WINCH signals and restore the previous WINCH handler.
        """

        if self.original_handler is not None:
            signal.signal(signal.SIGWINCH, self.original_handler)


class PseudoTerminal(object):
    """
    Wraps the pseudo-TTY (PTY) allocated to a docker container.

    The PTY is managed via the current process' TTY until it is closed.
    """

    def __init__(self, client, container):
        """
        Initialize the PTY using the docker.Client instance and container dict.
        """

        self.client = client
        self.container = container
        self.raw = None
        self.uuid = binascii.hexlify(os.urandom(20)).decode()
        self.isalive = True

        self.pipes = self._create_fd()
        self.pipe_in_r, self.pipe_in_w, self.pipe_out_r, self.pipe_out_w = self.pipes

        io.set_blocking(self.pipe_out_r, False)

    @staticmethod
    def _create_fd(bufsize=0):
        in_r, in_w = os.pipe()
        pipe_in_r = os.fdopen(in_r, 'r', bufsize)
        pipe_in_w = os.fdopen(in_w, 'w', bufsize)

        out_r, out_w = os.pipe()
        pipe_out_r = os.fdopen(out_r, 'r', bufsize)
        pipe_out_w = os.fdopen(out_w, 'w', bufsize)

        return pipe_in_r, pipe_in_w, pipe_out_r, pipe_out_w

    def sockets(self):
        """
        Return a single socket which is processing all I/O to exec
        """
        socket = self.container.exec_run(
            cmd='/bin/sh -c "echo $$ > /tmp/sh.pid.{} && [ -x /bin/bash ] && /bin/bash || /bin/sh"'.format(self.uuid),
            stdin=True,
            socket=True,
            tty=True,
            stream=True
        )
        stream = io.Stream(socket)

        return stream

    def write(self, data):
        self.pipe_in_w.write(data)

    def read(self, n=1024):
        return self.pipe_out_r.read(n)

    def _container_info(self):
        """
        Thin wrapper around client.inspect_container().
        """

        return self.container.attrs

    def start(self, sockets=None):
        stream = sockets or self.sockets()
        pumps = []

        pumps.append(io.Pump(io.Stream(self.pipe_in_r), stream, wait_for_output=False))
        pumps.append(io.Pump(stream, io.Stream(self.pipe_out_w), propagate_close=False))

        flags = [p.set_blocking(False) for p in pumps]

        try:
            with WINCHHandler(self):
                t = threading.Thread(target=self._hijack_tty, args=(pumps, ))
                t.setDaemon(True)
                t.start()
        finally:
            if flags:
                for (pump, flag) in zip(pumps, flags):
                    io.set_blocking(pump, flag)

    def israw(self, **kwargs):
        """
        Returns True if the PTY should operate in raw mode.

        If the container was not started with tty=True, this will return False.
        """

        if self.raw is None:
            info = self._container_info()
            self.raw = self.pipe_out_w.isatty() and info['Config']['Tty']

        return self.raw

    def resize(self, size=None):
        """
        Resize the container's PTY.

        If `size` is not None, it must be a tuple of (height,width), otherwise
        it will be determined by the size of the current TTY.
        """

        if not self.israw():
            return

        size = size or tty.size(self.pipe_out_w)

        if size is not None:
            rows, cols = size
            try:
                self.container.resize(height=rows, width=cols)
            except IOError:  # Container already exited
                pass

    def _hijack_tty(self, pumps):
        with tty.Terminal(self.pipe_in_r, raw=self.israw()):
            self.resize()
            while True:
                read_pumps = [p for p in pumps if not p.eof]
                write_streams = [p.to_stream for p in pumps if p.to_stream.needs_write()]

                try:
                    read_ready, write_ready = io.select(read_pumps, write_streams, timeout=60)
                except ValueError as e:
                    self.isalive = False
                    raise e

                try:
                    for write_stream in write_ready:
                        write_stream.do_write()

                    for pump in read_ready:
                        pump.flush()

                    if all([p.is_done() for p in pumps]):
                        break
                except SSLError as e:
                    if 'The operation did not complete' not in e.strerror:
                        raise e

    def stop(self):
        for p in self.pipes:
            if not p.closed:
                p.close()
