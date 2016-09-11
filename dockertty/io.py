import fcntl
import os

import errno


def set_blocking(fd, blocking=True):
    """
    Set the given file-descriptor blocking or non-blocking

    Return the original blocking status
    """

    old_flag = fcntl.fcntl(fd, fcntl.F_GETFL)

    if blocking:
        new_flag = old_flag & ~ os.O_NONBLOCK
    else:
        new_flag = old_flag | os.O_NONBLOCK

    fcntl.fcntl(fd, fcntl.F_SETFL, new_flag)

    return not bool(old_flag & os.O_NONBLOCK)


class Stream(object):
    ERRNO_RECOVERABLE = [
        errno.EINTR,
        errno.EDEADLK,
        errno.EWOULDBLOCK
    ]

    def __init__(self, fd):
        self.fd = fd
        self.buffer = b''
        self.close_requested = False
        self.closed = False

    def fileno(self):
        return self.fd.fileno()

    def set_blocking(self, value):
        if hasattr(self.fd, "setblocking"):
            self.fd.setblocking(value)
        else:
            return set_blocking(self.fd, value)

    def read(self, n=4096):
        while True:
            try:
                if hasattr(self.fd, 'recv'):
                    return self.fd.recv(n)
                return os.read(self.fd.fileno(), n)
            except EnvironmentError as e:
                if e.errno not in Stream.ERRNO_RECOVERABLE:
                    raise e

    def write(self, data):
        if not data:
            return None

        self.buffer += data
        self.do_write()

        return len(data)

    def do_write(self):
        while True:
            try:
                written = 0

                if hasattr(self.fd, 'send'):
                    written = self.fd.send(self.buffer)
                else:
                    written = os.write(self.fd.fileno(), self.buffer)

                self.buffer = self.buffer[written:]

                if self.close_requested and len(self.buffer) == 0:
                    self.close()

                return written
            except EnvironmentError as e:
                if e.errno not in Stream.ERRNO_RECOVERABLE:
                    raise e

    def needs_write(self):
        return len(self.buffer) > 0

    def close(self):
        self.close_requested = True

        if not self.closed and len(self.buffer) == 0:
            self.closed = True
            if hasattr(self.fd, 'close'):
                self.fd.close()
            else:
                os.close(self.fd.fileno())

    def __repr__(self):
        return "{cls}({fd})".format(cls=type(self).__name__, fd=self.fd)


class Pump(object):

    def __init__(self, from_stream, to_stream, wait_for_output=True, propagate_close=True):
        self.from_stream = from_stream
        self.to_stream = to_stream
        self.wait_for_output = wait_for_output
        self.propagate_close = propagate_close
        self.eof = False

    def fileno(self):
        return self.from_stream.fileno()

    def set_blocking(self, value):
        return self.from_stream.set_blocking(value)

    def flush(self, n=4096):
        """
        Flush n bytes of data from the reader stream to writer stream

        Return the number of bytes that were actually flushed.
        """
        try:
            read = self.from_stream.read(n)

            if read is None or len(read) == 0:
                self.eof = True
                if self.propagate_close:
                    self.to_stream.close()
                return None

            return self.to_stream.write(read)
        except OSError as e:
            if e.errno != errno.EPIPE:
                raise e

    def is_done(self):
        return (not self.wait_for_output or self.eof) and \
            not (hasattr(self.to_stream, 'needs_write') and self.to_stream.nees_write())

    def __repr__(self):
        return "{cls}(from={from_stream}, to={to_stream})".format(
            cls=type(self).__name__,
            from_stream=self.from_stream,
            to_stream=self.to_stream
        )