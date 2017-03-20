import os
import socket
import tempfile
from io import StringIO

import sys
from expects import expect, equal, be_none, be_true, be_false
from dockertty.stream import Stream, Pump


def is_fd_closed(fd):
    try:
        os.fstat(fd)
        return False
    except OSError:
        return True


class TestStream(object):

    def test_read_from_socket(self):
        a, b = socket.socketpair()
        a.send(b'test')
        stream = Stream(b)
        expect(stream.read(32)).to(equal(b'test'))

    def test_write_to_socket(self):
        a, b = socket.socketpair()
        stream = Stream(a)
        stream.write(b'test')
        expect(b.recv(32)).to(equal(b'test'))

    def test_read_from_file(self):
        with tempfile.TemporaryFile() as f:
            stream = Stream(f)
            f.write(b'test')
            f.seek(0)
            expect(stream.read(32)).to(equal(b'test'))

    def test_read_returns_empty_string_at_eof(self):
        with tempfile.TemporaryFile() as f:
            stream = Stream(f)
            expect(stream.read(32)).to(equal(b''))

    def test_write_to_file(self):
        with tempfile.TemporaryFile() as f:
            stream = Stream(f)
            stream.write(b'test')
            f.seek(0)
            expect(f.read(32)).to(equal(b'test'))

    def test_write_returns_length_written(self):
        with tempfile.TemporaryFile() as f:
            stream = Stream(f)
            expect(stream.write(b'test')).to(equal(4))

    def test_write_returns_none_when_no_data(self):
        stream = Stream(StringIO())
        expect(stream.write('')).to(be_none)

    def test_repr(self):
        fd = StringIO()
        stream = Stream(fd)
        expect(repr(stream)).to(equal("Stream(%s)" % fd))

    def test_close(self):
        a, b = socket.socketpair()
        stream = Stream(a)
        stream.close()
        expect(is_fd_closed(a.fileno())).to(be_true)


class TestPump(object):

    def test_fileno_delegates_to_from_stream(self):
        pump = Pump(sys.stdout, sys.stderr)
        expect(pump.fileno()).to(equal(sys.stdout.fileno()))

    def test_flush_pipes_data_between_streams(self):
        a = StringIO(u'food')
        b = StringIO()
        pump = Pump(a, b)
        pump.flush(3)
        expect(a.read(1)).to(equal('d'))
        expect(b.getvalue()).to(equal('foo'))

    def test_flush_returns_length_written(self):
        a = StringIO(u'fo')
        b = StringIO()
        pump = Pump(a, b)
        expect(pump.flush(3)).to(equal(2))

    def test_repr(self):
        a = StringIO(u'fo')
        b = StringIO()
        pump = Pump(a, b)
        expect(repr(pump)).to(equal("Pump(from=%s, to=%s)" % (a, b)))

    def test_is_done_when_pump_does_not_require_output_to_finish(self):
        a = StringIO()
        b = StringIO()
        pump = Pump(a, b, False)
        expect(pump.is_done()).to(be_true)

    def test_is_done_when_pump_does_require_output_to_finish(self):
        a = StringIO(u'123')
        b = StringIO()
        pump = Pump(a, b, True)
        expect(pump.is_done()).to(be_false)

        pump.flush()
        expect(pump.is_done()).to(be_false)

        pump.flush()
        expect(pump.is_done()).to(be_true)
