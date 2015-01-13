# Copyright Hybrid Logic Ltd.
"""
Configuration for a buildslave to run vagrant on.

.. warning::
    Although this code has been tested to produce a working slave the
    production slave wasn't configured with this code. In particular,
    it points at the staging buildserver by default.
"""

from fabric.api import run, task, sudo, put, local
from twisted.python.filepath import FilePath
from StringIO import StringIO
import yaml


def configure_gsutil():
    """
    Install certificate and configuration for gsutil.

    This allows the slave to upload vagrant images to google cloud.
    """
    boto_config = FilePath(__file__).sibling('boto-config.in').getContent()
    output = local('lpass show --notes "google-cert@build.clusterhq.com"',
                   capture=True)
    cert = yaml.safe_load(output.stdout)
    put(StringIO(boto_config % cert), '/home/buildslave/.boto')
    put(StringIO(cert['certificate']), '/home/buildslave/google.p12')


@task
def install(index, password):
    """
    Install a buildslave with vagrant installed.
    """
    run("wget -O /etc/yum.repos.d/virtualbox.repo http://download.virtualbox.org/virtualbox/rpm/fedora/virtualbox.repo")

    run("""
UNAME_R=$(uname -r)
PV=${UNAME_R%.*}
KV=${PV%%-*}
SV=${PV##*-}
ARCH=$(uname -m)
yum install -y https://kojipkgs.fedoraproject.org//packages/kernel/${KV}/${SV}/${ARCH}/kernel-devel-${UNAME_R}.rpm
""")

    run('yum install -y dkms')
    packages = [
        "https://dl.bintray.com/mitchellh/vagrant/vagrant_1.6.5_x86_64.rpm",
        "VirtualBox-4.3.x86_64",
        "buildbot-slave",
        "mongodb",
        "git",
        "libffi-devel",
        "python",
        "python-devel",
        "python-virtualenv",
        "openssl-devel",
    ]
    run("yum install -y " + " ".join(packages))
    run("useradd buildslave")
    sudo("buildslave create-slave /home/buildslave/fedora-vagrant build.staging.clusterhq.com fedora-vagrant-%s %s" % (index, password), user='buildslave')
    sudo('mkdir ~/.ssh', user='buildslave')
    sudo('ln -s ~/.vagrant.d/insecure_private_key ~/.ssh/id_rsa', user='buildslave')

    put(FilePath(__file__).sibling('fedora-vagrant-slave.service').path,
        '/etc/systemd/system/fedora-vagrant-slave.service')

    configure_gsutil()

    run('systemctl start fedora-vagrant-slave')
    run('systemctl enable fedora-vagrant-slave')
