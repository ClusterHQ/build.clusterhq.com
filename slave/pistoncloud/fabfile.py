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

    service_filename = u'{buildslave_name}-slave.service'.format(
        buildslave_name=buildslave_name
    )

    put(
        FilePath(__file__).sibling('slave.service').path,
        u'/etc/systemd/system/{}'.format(service_filename)
    )

    run('systemctl start {}'.format(service_filename))
    run('systemctl enable {}'.format(service_filename))
