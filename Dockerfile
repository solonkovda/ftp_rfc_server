FROM python:3.6-slim

WORKDIR /opt/ftp

COPY ftp_rfc_server/ ./ftp_rfc_server

ENTRYPOINT [ "python3" ]

CMD [ "ftp_rfc_server/main.py" ]
