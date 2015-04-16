from fabric.api import sudo, task, settings, cd, put
from twisted.python.filepath import FilePath


@task
def create_user(username, uid=650):
    """
    Create an OS X user.

    UID must be > 500 for the user to show up in
    /System/Library/PreferencePanes/Accounts.prefPane.

    UID cannot conflict with an existing user.
    UID and PrimaryGroupID were chosen to mimic a created standard user on a
    test Mac.
    The PrimaryGroupID is for the "staff" group.
    """
    sudo("""
    dscl . -create /Users/%(username)s
    dscl . -create /Users/%(username)s UserShell /bin/bash
    dscl . -create /Users/%(username)s RealName "ClusterHQ Buildslave"
    dscl . -create /Users/%(username)s UniqueID "%(uid)s"
    dscl . -create /Users/%(username)s PrimaryGroupID 20
    dscl . -create /Users/%(username)s NFSHomeDirectory /Users/%(username)s
    createhomedir -c %(username)s
    """ % {'username': username, 'uid': uid})


@task
def install(index, password, master='build.staging.clusterhq.com'):
    slave_home = FilePath('/Users/buildslave')

    create_user('buildslave')
    with settings(sudo_user='buildslave', shell_env={'HOME': slave_home.path}), cd(slave_home.path): # noqa
        sudo("curl -O https://bootstrap.pypa.io/get-pip.py")
        sudo("python get-pip.py --user")
        sudo("~/Library/Python/2.7/bin/pip install --user buildbot-slave==0.8.10 virtualenv==12.0.7")  # noqa

        sudo("~/Library/Python/2.7/bin/buildslave create-slave ~/flocker-osx %(master)s osx-%(index)s %(password)s"  # noqa
             % {'index': index, 'password': password, 'master': master})

    put(FilePath(__file__).sibling('launchd.plist').path,
        '/Library/LaunchDaemons/net.buildslave.plist', use_sudo=True)
    put(FilePath(__file__).sibling('start-buildslave').path,
        slave_home.child('flocker-osx').child('start-buildslave').path,
        mode=0755, use_sudo=True)
    sudo('chown root:wheel /Library/LaunchDaemons/net.buildslave.plist')
