import base64
import json
import logging
import os
from fcntl import fcntl, F_GETFL, F_SETFL
from time import sleep
from optparse import OptionParser
from os import O_NONBLOCK

import binascii

import tornado.web
import tornado.ioloop
import tornado.websocket
import tornado.httpserver
import tornado.netutil
import tornado.process
from ptyprocess import PtyProcessUnicode


logger = None


def setup_logging(filename):
    global logger
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('[%(asctime)s][%(levelname)s] %(filename)s:%(lineno)d\t: %(message)s')
    file_handler = logging.handlers.RotatingFileHandler(filename=filename, maxBytes=50 * 1024 * 1024, backupCount=10)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


class TerminalHandler(tornado.web.RequestHandler):
    """
    Handler for GET method of WebConsole page
    """

    def get(self, container_id):
        self.render("static/terminal.html")


class TerminalSocketHandler(tornado.websocket.WebSocketHandler):
    """
    WebSocket handler to connect with WebConsole
    """

    clients = dict()
    pipe = None

    def start_pty(self, *args):
        if not self.container_id:
            self.send_error_and_close("Error: container not found.")
            return
        try:
            # create a pseudo terminal of container by command:
            # `docker exec -ti <container_id> /bin/sh -c '[ -x /bin/bash ] && /bin/bash || /bin/sh'`
            # and then set the stream to non-blocking mode.
            pty = PtyProcessUnicode.spawn(
                ['docker', 'exec', '-ti', self.container_id, '/bin/sh', '-c',
                 'echo $$ > /tmp/sh.pid.{} && [ -x /bin/bash ] && /bin/bash || /bin/sh ]'.format(self.uuid)])
            flags = fcntl(pty.fileobj, F_GETFL)
            fcntl(pty.fileobj, F_SETFL, flags | O_NONBLOCK)

            setattr(self, "pty", pty)
            TerminalSocketHandler.clients.update({self: pty})
            logger.info('Connect to console of container {}'.format(self.container_id))
        except Exception as e:
            self.send_error_and_close("Error: cannot start console: {}".format(e))

    def resize_pty(self, message):
        """
        Set the terminal window size of the child pty.

        Receive and decode message sent from gotty.js and set window size of pty.
        The message format is: "{'rows': 10, 'columns': 20}"
        """
        data = json.loads(message)
        if hasattr(self, "pty"):
            self.pty.setwinsize(data['rows'], data['columns'])

    def response(self, message_type, message_content):
        """
        Response message to browser.

        The first byte of data distinguish type of message, the rest are content
        of message, encoded with base64 methods.
        """
        message = {
            "type": message_type,
            "content": base64.b64encode(message_content)
        }
        self.write_message(json.dumps(message))

    @classmethod
    def send_message(cls):
        if cls.clients:
            for conn, pty in cls.clients.items():
                try:
                    # check if pty is alive or not
                    if not pty.isalive():
                        conn.close()
                        return

                    # Read data from pipe.stdout and encode it with base64 method
                    # NOTE: message which contains non ascii character may cause the connection closed
                    message = pty.read(1024)
                    conn.response("output", message)
                except:
                    continue

    def send_error_and_close(self, message):
        """
        Response an error message and close the connection with browser.
        """
        self.response("error", message)
        self.close()

    def send_pong(self, *args):
        """
        Response to browser's ping message.
        """
        self.response("pong", "")

    def receive_input(self, message):
        """
        Read input from browser and write to pty.
        """
        if hasattr(self, "pty"):
            self.pty.write(message)

    def kill_spawned_process(self):
        """
        Kill spawned process inside container.

        If process of `docker exec` was killed, the spawned process inside container is
        still running. So we should kill spawned process before kill `docker exec`.
        """
        p = PtyProcessUnicode.spawn(['docker', 'exec', self.container_id, '/bin/sh', '-c',
                                     'kill -1  $(cat /tmp/sh.pid.{})'.format(self.uuid)])
        # wait till complete execution of command
        while p.isalive():
            sleep(1)
        p.close()

    def handle_invalid_message(self, message):
        """
        Handle invalid message
        """
        logger.warning("Invalid message type received: {}".format(message))

    def open(self, container_id):
        self.container_id = container_id
        setattr(self, "container_id", container_id)
        setattr(self, "uuid", binascii.hexlify(os.urandom(20)).decode())

        if not self.container_id:
            logger.error("Container with container_id {} not found.".format(container_id))
            self.send_error_and_close("Container not found.")
            return

        self.stream.set_nodelay(True)

    def on_message(self, message):
        try:
            data = json.loads(message)
        except Exception:
            logger.exception('Error: Invalid message.')
            return

        msg_type = data['type']
        msg_content = data['content']
        receiver = {
            'ping': self.send_pong,
            'init': self.start_pty,
            'resize': self.resize_pty,
            'input': self.receive_input,
        }

        receiver.get(msg_type, self.handle_invalid_message)(msg_content)

    def on_close(self):
        # pop connection from ConsoleSocketHandler and
        # close pseudo terminal and terminate subprocess
        if self in TerminalSocketHandler.clients:
            TerminalSocketHandler.clients.pop(self)
            if hasattr(self, "pty") and self.pty.isalive():
                self.kill_spawned_process()
                logger.info(
                    "Socket closed, kill subprocess of container {} (pid {})".format(self.container_id, self.pty.pid))
                self.pty.close()


if __name__ == '__main__':
    parser = OptionParser()
    parser.add_option("-p", "--port", default=21888, dest="port", help="Set port of dockertty listen to")
    parser.add_option("-l", "--log-path", default="/var/log/dockertty.log", dest="log_path", help="Path to print log")

    (options, args) = parser.parse_args()

    setup_logging(options.log_path)

    static_path = os.path.join(os.path.dirname(__file__), "static")
    app = tornado.web.Application(
        handlers=[
            (r'^/terminal/(.*)/ws', TerminalSocketHandler),
            (r'^/terminal/(.*)', TerminalHandler),
        ],
        static_path=static_path
    )
    server = tornado.httpserver.HTTPServer(app)
    server.bind(options.port)
    server.start(0)

    main_loop = tornado.ioloop.IOLoop.instance()
    console_sched = tornado.ioloop.PeriodicCallback(TerminalSocketHandler.send_message, 100, io_loop=main_loop)
    console_sched.start()
    main_loop.start()
