import binascii
import os

import docker


class PseudoTerminal(object):
    """
    Wraps the PTY allocated to a docker container.
    """

    def __init__(self, container_id, base_url="unix://var/lib/docker"):
        """
        Initialize the PTY with docker.Client and container id.
        """

        self.client = docker.Client(base_url)
        self.container_id = container_id
        self.uuid = binascii.hexlify(os.urandom(20)).decode()
        self.exec_id = self.client.exec_create(
            container_id=self.container_id,
            cmd='echo $$ > /tmp/sh.pid.{} && [ -x /bin/bash ] && /bin/bash || /bin/sh'.format(self.uuid)
        )

    def start(self):
        """
        Start command inside container.
        """
        pass

    def resize(self):
        """
        Resize terminal inside the container.
        """
        pass

    def stop(self):
        """
        Stop command inside container and kill spawned process.
        """
        pass

