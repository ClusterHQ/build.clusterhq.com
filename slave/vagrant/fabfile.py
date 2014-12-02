from fabric.api import run, task, sudo, put
from twisted.python.filepath import FilePath


## TODO: google credentials

@task
def install(index, password):
    run( "wget -O /etc/yum.repos.d/virtualbox.repo http://download.virtualbox.org/virtualbox/rpm/fedora/virtualbox.repo")

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

    put(FilePath(__file__).sibling('fedora-vagrant-slave.service').path, '/etc/systemd/system/fedora-vagrant-slave.service')

    run('systemctl start fedora-vagrant-slave')
    run('systemctl enable fedora-vagrant-slave')
