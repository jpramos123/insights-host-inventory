FROM registry.access.redhat.com/ubi9/ubi-minimal:latest

ARG pgRepo="https://copr.fedorainfracloud.org/coprs/g/insights/postgresql-16/repo/epel-9/group_insights-postgresql-16-epel-9.repo"

USER root

ENV APP_ROOT=/opt/app-root/src
WORKDIR $APP_ROOT

RUN (microdnf module enable -y postgresql:16 || curl -o /etc/yum.repos.d/postgresql.repo $pgRepo) && \
    microdnf install --setopt=tsflags=nodocs -y postgresql python39 rsync tar procps-ng make git && \
    rpm -qa | sort > packages-before-devel-install.txt && \
    microdnf install --setopt=tsflags=nodocs -y libpq-devel python3-devel gcc cargo rust glibc-devel krb5-libs krb5-devel libffi-devel gcc-c++ make zlib zlib-devel openssl-libs openssl-devel libzstd libzstd-devel unzip which diffutils && \
    rpm -qa | sort > packages-after-devel-install.txt

# Download and install librdkafka
RUN curl -L https://github.com/confluentinc/librdkafka/archive/refs/tags/v2.10.1.zip -o /tmp/librdkafka.zip || cp /cachi2/output/deps/generic/v2.10.1.zip /tmp/librdkafka.zip && \
    unzip /tmp/librdkafka.zip -d /tmp && \
    cd /tmp/librdkafka-2.10.1 && \
    ./configure --prefix=/usr && \
    make && \
    make install && \
    ldconfig && \
    rm -rf /tmp/librdkafka*

COPY api/ api/
COPY app/ app/
COPY lib/ lib/
COPY migrations/ migrations/
COPY swagger/ swagger/
COPY tests/ tests/
COPY utils/ utils/
COPY Makefile Makefile
COPY gunicorn.conf.py gunicorn.conf.py
COPY host_reaper.py host_reaper.py
COPY host_synchronizer.py host_synchronizer.py
COPY host_sync_group_data.py host_sync_group_data.py
COPY inv_mq_service.py inv_mq_service.py
COPY inv_publish_hosts.py inv_publish_hosts.py
COPY inv_export_service.py inv_export_service.py
COPY logconfig.yaml logconfig.yaml
COPY manage.py manage.py
COPY pendo_syncher.py pendo_syncher.py
COPY Pipfile Pipfile
COPY Pipfile.lock Pipfile.lock
COPY pytest.ini pytest.ini
COPY rebuild_events_topic.py rebuild_events_topic.py
COPY run_gunicorn.py run_gunicorn.py
COPY run_command.sh run_command.sh
COPY run.py run.py
COPY system_profile_validator.py system_profile_validator.py
COPY inv_migration_runner.py inv_migration_runner.py
COPY generate_stale_host_notifications.py generate_stale_host_notifications.py
COPY create_ungrouped_host_groups.py create_ungrouped_host_groups.py
COPY delete_ungrouped_host_groups.py delete_ungrouped_host_groups.py
COPY assign_ungrouped_hosts_to_groups.py assign_ungrouped_hosts_to_groups.py
COPY export_group_data_s3.py export_group_data_s3.py
COPY delete_hosts_s3.py delete_hosts_s3.py
COPY update_hosts_last_check_in.py update_hosts_last_check_in.py
COPY update_edge_hosts_prs.py update_edge_hosts_prs.py
COPY delete_hosts_without_id_facts.py delete_hosts_without_id_facts.py
COPY host_delete_duplicates.py host_delete_duplicates.py
COPY app_migrations/ app_migrations/
COPY jobs/ jobs/
COPY add_inventory_view.py add_inventory_view.py
COPY delete_host_namespace_access_tags.py delete_host_namespace_access_tags.py
COPY hosts_table_migration_data_copy.py hosts_table_migration_data_copy.py
COPY hosts_table_migration_switch.py hosts_table_migration_switch.py

ENV PIP_NO_CACHE_DIR=1
ENV PIPENV_CLEAR=1
ENV PIPENV_VENV_IN_PROJECT=1

RUN python3 -m pip install --upgrade pip setuptools wheel && \
    python3 -m pip install pipenv && \
    python3 -m pip install dumb-init && \
    pipenv install --system

# remove devel packages that were only necessary for psycopg2 to compile
RUN microdnf remove  -y  libpq-devel python3-devel gcc cargo rust rust-std-static gcc-c++ && \
    microdnf clean all

ENV LD_LIBRARY_PATH=/usr/lib64:/usr/lib

RUN mkdir -p /licenses
COPY LICENSE /licenses

USER 1001

ENTRYPOINT [ "dumb-init", "./run_command.sh" ]

# Define labels for the iop-core-host-inventory
LABEL url="https://www.redhat.com"
LABEL name="iop-core-host-inventory" \
      description="This adds the satellite/iop-core-host-inventory-rhel9 image to the Red Hat container registry. To pull this container image, run the following command: podman pull registry.stage.redhat.io/satellite/iop-core-host-inventory-rhel9" \
      summary="A new satellite/iop-core-host-inventory-rhel9 container image is now available as a Technology Preview in the Red Hat container registry."
LABEL com.redhat.component="iop-core-host-inventory" \
      io.k8s.display-name="IoP Host Inventory" \
      io.k8s.description="This adds the satellite/iop-core-host-inventory image to the Red Hat container registry. To pull this container image, run the following command: podman pull registry.stage.redhat.io/satellite/iop-core-host-inventory-rhel9" \
      io.openshift.tags="insights satellite iop inventory"
