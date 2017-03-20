FROM python:2.7-alpine
MAINTAINER jetmuffin <jeffchen328@gmail.com>

COPY . /dockertty
WORKDIR /dockertty

RUN pip install -r requirements.txt


EXPOSE 21888
ENTRYPOINT ["/usr/local/bin/python", "dockertty/server.py"]