import docker
import time
from expects import expect, be_none, have_property, equal

from dockertty.pty import PseudoTerminal


class TestPseudoTerminal(object):

    def test_pty(self):
        client = docker.from_env()
        container = client.containers.run(
            image='alpine',
            command='ls && sleep 1000',
            detach=True
        )

        pty = PseudoTerminal(client, container)
        expect(pty.container.id).to(equal(container.id))

        try:
            pty.start()

            time.sleep(5)
            output = pty.read(20)
            pty.stop()

            expect(output).not_to(be_none)
        except Exception:
            raise
        finally:
            container.remove(
                force=True
            )
