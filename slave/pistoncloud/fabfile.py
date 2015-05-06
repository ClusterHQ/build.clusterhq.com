# Copyright Hybrid Logic Ltd.
"""
Configuration for a buildslave to run on PistonCloud

.. warning::
    This points at the staging buildserver by default.
"""

from fabric.api import task, sudo, put, env
from twisted.python.filepath import FilePath
from StringIO import StringIO
import yaml

# http://stackoverflow.com/a/9685171
env.use_ssh_config = True

def configure_acceptance():
    put(
        StringIO(yaml.safe_dump({'metadata': {'creator': 'buildbot'}})),
        '/home/buildslave/acceptance.yml',
        use_sudo=True,
    )


def put_template(template, replacements, remote_path, **put_kwargs):
    local_file = template.temporarySibling()
    try:
        with local_file.open('w') as f:
            content = template.getContent().format(
                **replacements
            )
            f.write(content)

        put(local_file.path, remote_path, **put_kwargs)
    finally:
        local_file.remove()

@task
def install(index, buildslave_name, password, master='build.staging.clusterhq.com'):
    """
    Install a buildslave for running cinder block device API tests against
    Rackspace OpenStack API.
    """
    packages = [
        "https://kojipkgs.fedoraproject.org/packages/buildbot/0.8.10/1.fc22/noarch/buildbot-slave-0.8.10-1.fc22.noarch.rpm",  # noqa
        "git",
        "libffi-devel",
        "python",
        "python-devel",
        "python-virtualenv",
        "openssl-devel",
    ]
    sudo("yum install -y " + " ".join(packages))
    sudo("useradd buildslave")
    sudo(
        u"buildslave create-slave "
        u"/home/buildslave/{buildslave_name} "
        u"{master} "
        u"{buildslave_name}-{index} "
        u"{password}".format(
            buildslave_name=buildslave_name,
            index=index,
            password=password,
            master=master,
        ),
        user='buildslave'
    )

    put_template(
        template=FilePath(__file__).sibling('start.template'),
        replacements=dict(
            buildslave_name=buildslave_name
        ),
        remote_path='/home/buildslave/{buildslave_name}/start'.format(
            buildslave_name=buildslave_name
        ),
        mode=0755,
        use_sudo=True,
    )

    configure_acceptance()

    remote_service_filename = u'{buildslave_name}-slave.service'.format(
        buildslave_name=buildslave_name
    )

    put_template(
        template=FilePath(__file__).sibling('slave.service.template'),
        replacements=dict(
            buildslave_name=buildslave_name
        ),
        remote_path=u'/etc/systemd/system/{}'.format(remote_service_filename),
        use_sudo=True,
    )

    sudo('systemctl start {}'.format(remote_service_filename))
    sudo('systemctl enable {}'.format(remote_service_filename))

@task
def uninstall(buildslave_name):
    """
    Uninstall the buildslave and its service files.
    """
    remote_service_filename = u'{buildslave_name}-slave.service'.format(
        buildslave_name=buildslave_name
    )

    sudo(
        'systemctl stop {}'.format(remote_service_filename),
        warn_only=True,
    )
    sudo(
        'systemctl disable {}'.format(remote_service_filename),
        warn_only=True,
    )
    sudo(
        u'rm /etc/systemd/system/{}'.format(remote_service_filename),
        warn_only=True,
    )
    sudo(
        "userdel --remove buildslave",
        warn_only=True,
    )
