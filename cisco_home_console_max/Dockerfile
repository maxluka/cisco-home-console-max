ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.21
FROM ${BUILD_FROM}

# Pillow from apk so nothing compiles at build time; tzdata for ZoneInfo.
RUN apk add --no-cache python3 py3-pip py3-pillow py3-yaml tzdata

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY app /opt/app
COPY run.sh /
RUN chmod a+x /run.sh

WORKDIR /opt/app
CMD ["/run.sh"]
