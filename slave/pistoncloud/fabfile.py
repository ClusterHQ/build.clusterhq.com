# Copyright Hybrid Logic Ltd.
"""
Configuration for a buildslave to run on PistonCloud

.. warning::
    This points at the staging buildserver by default.
"""

from fabric.api import run, task, sudo, put
from twisted.python.filepath import FilePath
from StringIO import StringIO
import yaml


def configure_acceptance():
    put(StringIO(yaml.safe_dump({'metadata': {'creator': 'buildbot'}})),
        '/home/buildslave/acceptance.yml')


@task
def install(index, buildslave_name, password, master='build.staging.clusterhq.com'):
    """
    Install a buildslave for running cinder block device API tests against
    Rackspace OpenStack API.
    """
    packages = [
        "https://kojipkgs.fedoraproject.org//packages/buildbot/0.8.10/1.fc22/noarch/buildbot-slave-0.8.10-1.fc22.noarch.rpm",  # noqa
        "git",
        "libffi-devel",
        "python",
        "python-devel",
        "python-virtualenv",
        "openssl-devel",
    ]
    run("yum install -y " + " ".join(packages))
    run("useradd buildslave")
    sudo(
        "buildslave create-slave /home/buildslave/%(buildslave_name) %(master)s %(buildslave_name)-%(index)s %(password)s"  # noqa
        % {
            'buildslave_name': buildslave_name,
            'index': index,
            'password': password,
            'master': master
        },
        user='buildslave'
    )
    put(
        FilePath(__file__).sibling('start').path,
        '/home/buildslave/{buildslave_name}/start'.format(
            buildslave_name=buildslave_name
        ),
        mode=0755
    )

    configure_acceptance()

    remote_service_filename = u'{buildslave_name}-slave.service'.format(
        buildslave_name=buildslave_name
    )

    service_file_template = FilePath(__file__).sibling('slave.service.template')
    local_service_file = service_file_template.temporarySibling()
    try:
        with local_service_file.open('w') as f:
            service_file_content = service_file_template.getContent().format(
                buildslave_name=buildslave_name
            )
            f.write(service_file_content)

        put(
            local_service_file.path,
            u'/etc/systemd/system/{}'.format(remote_service_filename)
        )
    finally:
        local_service_file.remove()

    run('systemctl start {}'.format(remote_service_filename))
    run('systemctl enable {}'.format(remote_service_filename))
