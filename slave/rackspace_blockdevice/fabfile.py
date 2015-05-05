# Copyright Hybrid Logic Ltd.
"""
Configuration for a buildslave to run vagrant on.

.. warning::
    This points at the staging buildserver by default.
"""

from fabric.api import run, task, sudo, put, local
from twisted.python.filepath import FilePath
from StringIO import StringIO
import yaml


def get_vagrant_config():
    output = local('lpass show --notes "vagrant@build.clusterhq.com"',
                   capture=True)
    config = yaml.safe_load(output.stdout)
    return config


def configure_acceptance():
    put(StringIO(yaml.safe_dump({'metadata': {'creator': 'buildbot'}})),
        '/home/buildslave/acceptance.yml')


@task
def install(index, password, master='build.staging.clusterhq.com'):
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
    sudo("buildslave create-slave /home/buildslave/rackspace_blockdevice %(master)s rackspace-blockdevice-%(index)s %(password)s"  # noqa
         % {'index': index, 'password': password, 'master': master},
         user='buildslave')
    put(FilePath(__file__).sibling('start').path,
        '/home/buildslave/rackspace_blockdevice/start', mode=0755)

    configure_acceptance()

    put(FilePath(__file__).sibling('rackspace-blockdevice-slave.service').path,
        '/etc/systemd/system/rackspace-blockdevice-slave.service')

    run('systemctl start rackspace-blockdevice-slave')
    run('systemctl enable rackspace-blockdevice-slave')


@task
def update_config():
    config = get_vagrant_config()
