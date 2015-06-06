# Copyright Hybrid Logic Ltd.
"""
Configuration for a buildslave to run on redhat-openstack

.. warning::
    This points at the staging buildserver by default.
"""
from pipes import quote as shellQuote
from fabric.api import sudo, task, env, put, run, local
from fabric.context_managers import shell_env
from cuisine import file_update, text_ensure_line, mode_sudo, mode_remote
from twisted.python.filepath import FilePath
from StringIO import StringIO
import yaml

# Since version 1.4.0, Fabric uses your ssh config (partly). However,
# you need to explicitly enable it.
# See http://stackoverflow.com/a/9685171
env.use_ssh_config = True

BUILDSLAVE_NAME = "redhat-openstack/centos-7"
BUILDSLAVE_NODENAME = "clusterhq_flocker_buildslave"
BUILDSLAVE_HOME = '/srv/buildslave'

# Be careful here! If our script has bugs we don't want to accidentally
# modify VMs or resources of another more important tenant
TENANT_NAME = "tmz-mdl-1"

NETWORK_MANAGER_CONF_PATH = '/etc/NetworkManager/NetworkManager.conf'
SSHD_CONFIG_PATH = '/etc/ssh/sshd_config'


def cmd(*args):
    """
    Quote the supplied ``list`` of ``args`` and return a command line
    string.

    XXX: This is copied from the ``fabfile.py`` in the root of this repository.
    It should be shared.

    :param list args: The componants of the command line.
    :return: The quoted command line string.
    """
    return ' '.join(map(shellQuote, args))


def get_lastpass_config(key):
    """
    Download a section from LastPass.

    Requires you to have run ``lpass login`` first.
    """
    output = local(cmd('lpass', 'show', '--notes', key),
                   capture=True)
    config = yaml.safe_load(output.stdout)
    return config


@task
def configure_acceptance():
    """
    Download the entire acceptance.yml file from lastpass but only
    upload the metadata and openstack credentials.

    Our redhat-openstack build slave is hosted on a cluster that isn't
    administered by ClusterHQ, so we don't want to share all our
    credentials there.
    """
    acceptance_config = {}
    full_config = get_lastpass_config(
        "acceptance@build.clusterhq.com"
    )
    for key in ('metadata', 'redhat-openstack'):
        acceptance_config[key] = full_config['config'][key]

    put(
        StringIO(yaml.safe_dump(acceptance_config)),
        BUILDSLAVE_HOME + '/acceptance.yml',
        use_sudo=True,
    )


def put_template(template, replacements, remote_path, **put_kwargs):
    """
    Replace Python style string formatting variables in ``template``
    with the supplied ``replacements`` and then ``put`` the resulting
    content to ``remote_path``.
    """
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
def configure_resolvconf():
    """
    Replace the ``/etc/resolv.conf`` file on the target server.
    """
    put(
        StringIO(
            "\n".join([
                "nameserver 8.8.8.8",
                "nameserver 8.8.4.4",
            ]) + "\n"
        ),
        '/etc/resolv.conf',
        use_sudo=True,
        mode=0o644,
    )


@task
def configure_networkmanager():
    """
    Configure NetworkManager to not modify ``resolve.conf``.
    """
    with mode_remote():
        with mode_sudo():
            updated = file_update(
                NETWORK_MANAGER_CONF_PATH,
                lambda content: text_ensure_line(
                    content,
                    'dns=none'
                )
            )
    if updated:
        sudo("systemctl restart NetworkManager")


@task
def configure_sshd():
    """
    Configure SSH to not perform reverse DNS lookups for the IP addresses of in
    coming connections.
    """
    with mode_remote():
        with mode_sudo():
            updated = file_update(
                SSHD_CONFIG_PATH,
                lambda content: text_ensure_line(
                    content,
                    'UseDNS no'
                )
            )
    if updated:
        sudo("systemctl restart sshd")


@task
def create_server(
        keypair_name,
        # m1.large
        flavor=u'4',
        # SC_Centos7
        image=u'ab32525b-f565-49ca-9595-48cdb5eaa794',
        # tmz-mdl-net1
        net_id=u'74632532-1629-44b4-a464-dd31657f46a3',
        node_name=BUILDSLAVE_NODENAME
):
    """
    Run ``nova boot`` to create a new server on which to run the
    redhat-openstack build slave.

    :param str keypair_name: The name of an SSH keypair that has been
        registered on the redhat-openstack nova tenant.
    """
    with shell_env(OS_TENANT_NAME=TENANT_NAME):
        commandline = cmd(
            'nova', 'boot',
            '--image', image,
            '--flavor', flavor,
            '--nic', 'net-id=' + net_id,
            '--key-name', keypair_name,
            # SSH authentication fails unless this is included.
            '--config-drive', 'true',
            # Wait for the machine to become active.
            '--poll',
            node_name
        )

        run(commandline)
        output = run(
            'nova list --fields="Networks" --name={!r}'.format(node_name)
        )
        ip_address = extract_ip_from_nova_list_table(output)
        print "IPADDRESS", ip_address


def extract_ip_from_nova_list_table(table_text):
    """
    $ nova list --name=clusterhq_flocker_buildslave --fields=Networks
    +--------------------------------------+----------------------------+
    | ID                                   | Networks                   |
    +--------------------------------------+----------------------------+
    | 7965dddd-809d-4fa3-90fe-73c582536a3c | tmz-mdl-net1=172.19.139.51 |
    +--------------------------------------+----------------------------+
    """
    lines = []
    for line in table_text.splitlines():
        line = line.rstrip()
        if set(line) == set('+-'):
            continue
        lines.append(line)

    assert len(lines) == 2
    # Remove first and last pipes
    headings, values = list(line.lstrip('| ').rstrip(' |') for line in lines)
    # Split on internal pipes
    headings = list(heading.strip() for heading in headings.split(' | '))
    values = list(values.strip() for value in values.split(' | '))
    assert len(headings) == len(values)
    assert headings == ['ID', 'Networks']
    networks = values[-1]
    network, ip_address = networks.split('=')
    return ip_address


@task
def delete_server():
    """
    Call ``nova delete`` to delete the server on which the redhat-openstack
    build slave is running.
    """
    with shell_env(OS_TENANT_NAME=TENANT_NAME):
        run('nova delete ' + BUILDSLAVE_NODENAME)


@task
def configure(index, password, master='build.staging.clusterhq.com'):
    """
    Install all the packages required by ``buildslave`` and then
    configure the redhat-openstack buildslave.

    :param int index: The index of this redhat-openstack build slave. You
        should probably just say 0.
    :param unicode password: The password that the build slave will
        use when authenticating with the build master.
    :param unicode master: The hostname or IP address of the build
        master that this build slave will attempt to connect to.
    """
    # The default DNS servers on our redhat-openstack tenant prevent
    # resolution of public DNS names.
    # Prevent NetworkManager from using them
    configure_networkmanager()
    # And instead use Google's public DNS servers for the duration of the
    # build slave installation.
    configure_resolvconf()
    # Prevent reverse DNS lookups
    configure_sshd()

    sudo("yum install -y epel-release")

    packages = [
        "https://kojipkgs.fedoraproject.org/packages/buildbot/0.8.10/1.fc22/noarch/buildbot-slave-0.8.10-1.fc22.noarch.rpm",  # noqa
        "git",
        "python",
        "python-devel",
        "python-tox",
        "python-virtualenv",
        "libffi-devel",
        "@buildsys-build",
        "openssl-devel",
        "wget",
        "curl",
        "enchant",
    ]

    sudo("yum install -y " + " ".join(packages))

    slashless_name = BUILDSLAVE_NAME.replace("/", "-") + '-' + str(index)
    builddir = 'builddir-' + str(index)

    sudo("mkdir -p {}".format(BUILDSLAVE_HOME))

    configure_acceptance()

    sudo(
        u"buildslave create-slave "
        u"{buildslave_home}/{builddir} "
        u"{master} "
        u"{buildslave_name}/{index} "
        u"{password}".format(
            buildslave_home=BUILDSLAVE_HOME,
            builddir=builddir,
            master=master,
            buildslave_name=BUILDSLAVE_NAME,
            index=index,
            password=password,
        ),
    )

    put_template(
        template=FilePath(__file__).sibling('start.template'),
        replacements=dict(buildslave_home=BUILDSLAVE_HOME, builddir=builddir),
        remote_path=BUILDSLAVE_HOME + '/' + builddir + '/start',
        mode=0755,
        use_sudo=True,
    )

    remote_service_filename = slashless_name + '.service'

    put_template(
        template=FilePath(__file__).sibling('slave.service.template'),
        replacements=dict(
            buildslave_name=slashless_name,
            buildslave_home=BUILDSLAVE_HOME,
            builddir=builddir,
        ),
        remote_path=u'/etc/systemd/system/' + remote_service_filename,
        use_sudo=True,
    )

    sudo('systemctl start {}'.format(remote_service_filename))
    sudo('systemctl enable {}'.format(remote_service_filename))
