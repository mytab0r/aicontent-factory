FROM alpine:3.20

RUN apk add --no-cache autossh openssh-client

COPY entry.sh /entry.sh
RUN chmod +x /entry.sh

ENTRYPOINT ["/entry.sh"]