FROM amazonlinux:latest

RUN dnf install -y postgresql16-server && \
    dnf clean all && \
    /usr/bin/postgresql-setup --initdb

ENV POSTGRES_USER=postgres
ENV POSTGRES_PASSWORD=postgres

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && chown postgres:postgres /entrypoint.sh

USER postgres

EXPOSE 5432

ENTRYPOINT ["/entrypoint.sh"]
