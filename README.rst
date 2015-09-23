This is the configuration for ClusterHQ's `Buildbot <http://buildbot.net/>`_.

The Buildbot master is deployed as a Docker container running on an AWS EC2 instance.

Most of the slaves are EC2 latent slaves started by the master.
Some slaves, such as an OS X slave, must be started manually.

Buildbot schedulers start builds triggered by a push to any branch in the Flocker repository or by forced builds.
After a new push to a branch, Buildbot waits a number of seconds before starting a build,
in case another push arrives shortly afterwards.

Most builds are tested as merges against the Flocker ``master`` branch.

Install dependencies
====================

The code uses Fabric to start and manage the Buildbot master.

To install dependencies::

   $ pip install pyyaml fabric libcloud

Create the configuration
========================

The configuration requires secret data that must not be committed to the Github repository.
The secret data is provided in a file ``config.yml``.

A sample configuration is provided in the file ``config.yml.sample``.

The config file for the ClusterHQ master can be found in the ``config@build.clusterhq.com`` file in LastPass.
If you have the ``lastpass`` command-line client installed, you can use Fabric to download the current config::

   $ fab getConfig

Fabric passes these variables to Buildbot via a Docker environment variable as JSON.


Test changes on staging server
==============================

Changes to the Buildbot master can be tested on a staging machine.

Create a staging server
-----------------------

Create an AWS EC2 Security Group to allow inbound traffic as shown below.

.. image:: security-group.png
   :alt: Custom TCP Rule, TCP Protocol, Port Range 5000, Source Anywhere, 0.0.0.0/0
         SSH, TCP Protocol, Port Range 22, Source Anywhere, 0.0.0.0/0
         HTTP, TCP Protocol, Port Range 80, Source Anywhere, 0.0.0.0/0
         Custom TCP Rule, TCP Protocol, Port Range 9989, Source Anywhere, 0.0.0.0/0
         All ICMP, ICMP Protocol, Port Range 0-65535, Source Anywhere, 0.0.0.0/0

The Security Group should allow all outbound traffic.

`Install and configure boto <http://boto.readthedocs.org/en/latest/getting_started.html>`_ to allow scriptable access to AWS.

Run ``python start-aws.py``.
This command will display the external IP address of the EC2 instance.

Run ``python start-aws.py --help`` to see the available options to this command.

Install pre-requisites and start Docker::

   [aws]$ sudo yum install -y docker-io fabric git
   [aws]$ sudo setenforce 0
   [aws]$ sudo systemctl start docker

Create a staging Docker image
-----------------------------

On the staging server, run the following commands::

   [aws]$ git clone https://github.com/ClusterHQ/build.clusterhq.com.git
   [aws]$ cd build.clusterhq.com
   [aws]$ # Change <BRANCH> to the branch of build.clusterhq.com you want
   [aws]$ git checkout <BRANCH>
   [aws]$ sudo docker build --tag clusterhq/build.clusterhq.com:staging .
   [aws]$ EXISTS=$(docker inspect --format="{}" buildmaster-data 2> /dev/null)
   [aws]$ if [ "$EXISTS" == "{}" ]; then sudo docker rm buildmaster-data; fi
   [aws]$ sudo docker run --name buildmaster-data -v /srv/buildmaster/data busybox /bin/true

Create staging configuration
----------------------------

Create a file ``staging.yml`` from the ``config.yml``.

Make the following changes to the ``staging.yml`` file:

#. To use the new EC2 instance and the Docker image tagged ``staging`` created above, change the ``buildmaster.host`` config option to the IP of the EC2 instance, and add a ``buildmaster.docker_tag`` config option with the value ``staging``.

#. To prevent reports being published to the Flocker Github repository, change the ``github.report_status`` config option to ``False``.


Start staging server
--------------------

Once the Docker image has built on the staging server, and the staging.yml file has been created, start the test Buildbot master from the local machine using::

   # restart is used instead of update so as not to pull any images from the Docker Hub
   $ fab restart:staging.yml

Connect to the IP address of the EC2 instance and log in to the Buildmaster portal with the credentials from the ``auth`` section of the config file.
Click on the ``flocker`` link to access the web form.

The staging setup is missing the ability to trigger builds in response to Github pushes.
To trigger a build, enter a branch name and click the ``Force`` button to start testing a Flocker branch.

The staging master will start latent slaves on AWS EC2 automatically when builds have been triggered.

Tests that require Mac OS X or starting VM's cannot use AWS EC2 latent slaves.
These tests will remain grey until a non-latent slave connects.
To start a Mac OS X non-latent slave, see below.

Latent slaves will shut-down automatically.
The Buildmaster and non-latent slaves must be shutdown manually.

Deploy changes to production server
===================================

Ensure the dependencies have been installed and configuration created, as described above.

To create a new ``latest`` image in the Docker registry, update the ``master`` branch and push to Github.
The Docker registry will automatically build an image based on the ``master`` branch of https://github.com/ClusterHQ/build.clusterhq.com whenever it is updated.

After pushing a change to ``master``, it takes about 10 minutes for the Docker image build to finish.
The status is available `here <https://registry.hub.docker.com/u/clusterhq/build.clusterhq.com/builds_history/46090/>`_.
You will need to a member of the ``clusterhq`` group on Docker Hub in order to click on build id's to see detailed information about build progress or errors.

The production instance is accessed using a key from https://github.com/hybridlogic/HybridDeployment (this repository is not publicly available).
Add the HybridDeployment master key to your authentication agent::

   $ ssh-add /path/to/HybridDeployment/credentials/master_key

Check if anyone has running builds at http://build.clusterhq.com/buildslaves.

Announce on Zulip's ``Engineering > buildbot`` stream that Buildbot will be unavailable for a few minutes.

Update the live Buildbot to the latest Docker image (this may take some time)::

   $ fab update


Other operations on production server
=====================================

To view the logs::

   $ fab logs

To restart the live Buildbot without changing the image::

   $ fab restart


Wheelhouse
==========

There is a wheelhouse hosted on s3 (thus near the buildslaves).
Credentials [1]_ for ``s3cmd`` can be configured using ``s3cmd --configure``.
It can be updated to include available wheels of packages which are in flocker's ``setup.py`` by running the following commands::

   python setup.py sdist
   pip wheel -f dist "Flocker[dev]==$(python setup.py --version)"
   s3cmd put -P -m "Content-Type:application/python+wheel" wheelhouse/*.whl s3://clusterhq-wheelhouse/fedora20-x86_64
   s3cmd ls s3://clusterhq-wheelhouse/fedora20-x86_64/ | sed 's,^.*/\(.*\),<a href="\1">\1</a><br/>,' | s3cmd put -P -m "text/html" - s3://clusterhq-wheelhouse/fedora20-x86_64/index

The buildslave is constructed with a ``pip.conf`` file that points at https://s3-us-west-2.amazonaws.com/clusterhq-wheelhouse/fedora20-x86_64/index.

.. [1] Create credentials at https://console.aws.amazon.com/iam/home#users.

Slaves
======

Naming
------

Slaves are named with a number of components, separated by ``/``.
The primary component is the name of the operating system running on the slave (e.g. ``fedora-20``).
There is usually a prefix indicating where the slave is hosted (e.g. ``aws`` or ``redhat-openstack``).
If there is an unusual configuration to the slave, there is a tag describing it (e.g. ``zfs-head``).
There is usually a numerical suffix indicating which instance of similarly configured slaves this is.

Slave AMIs
----------

There are two slave `Amazon Machine Images <http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/AMIs.html>`_ per platform.
The images are built by running ``slave/build-images <platform>`` where ``<platform>`` is a directory in ``build/slave``.
This will generate images with ``/<TIMESTAMP>`` suffixes.
These can be promoted by running ``slave/promote-images <platform>`` where ``<platform>`` is a directory in ``build/slave``.
Promoting an image means that this image will be used by default when new slaves are created for the Buildbot master.

New ephemeral slaves are created when existing slaves are explicitly terminated in EC2,
or when the Buildbot master is restarted,
or after slaves are automatically terminated after a period of inactivity.

Building and promoting images requires a configures ``aws.config.yml`` which can be created from ``aws_config.yml.sample`` at the root of this project.

To test a non-promoted image, create a new Buildbot with ``image_tags: false`` added to the ``aws`` stanza.
This will use the latest image rather than the one tagged ``production: True``.

The images are based on various base OS images available on Amazon.
The specific image used is defined by the per-platform manifest file.

``buildslave-<platform>``
  is used for most builds, and has all the dependencies installed,
  including the latest release of zfs (or a fixed prerelease, when there are relevant bug fixes).
  The image is built by running :file:`slave/<platform>/cloud-init-base.sh` and then installing zfs.
``buildslave-<platform>-zfs-head``
  is used to test against the latest version of zfs.
  It has all the dependencies except zfs installed, and has the latest version of zfs installed when an
  instance is created.  The image is built by running :file:`slave/<platform>/cloud-init-base.sh`.

Both images have :file:`slave/cloud-init.sh` run on them at instance creation time.

Vagrant Builders
----------------

The vagrant builders upload the boxes to Amazon S3.
The bucket (`s3://clusterhq-dev-archive/vagrant`) is set to expire objects after two weeks.

To set this lifecycle setting:

* Right click on the bucket,
* Properties,
* Lifecycle > Add rule,
* "Apply the Rule to", select "A Prefix" and fill in "vagrant/",
* Choose "Action on Objects" "Permanently Delete Only", after 14 days.

Mac OS X Buildslave
-------------------

Configuring an OS X machine to run tests requires root priviledges and for SSH to be configured on this machine.

To configure this machine run::

   fab -f slave/osx/fabfile.py --hosts=${USERNAME}@${OSX_ADDRESS} install:0,${PASSWORD},${MASTER}

The tests do not run with root or administrator privileges.

Where ``${USERNAME}`` is a user on the OS X machine, and ``${PASSWORD}`` is the password in ``slaves.osx.passwords`` from the ``config.yml`` or ``staging.yml`` file used to deploy the BuildBot master on hostname or IP address ``${MASTER}``.

For testing purposes, or if you do not have root privileges, run the following commands to start a build slave (set ``MASTER`` and ``PASSWORD`` as above):

.. code:: shell

   curl -O https://bootstrap.pypa.io/get-pip.py
   python get-pip.py --user
   ~/Library/Python/2.7/bin/pip install --user buildbot-slave virtualenv
   ~/Library/Python/2.7/bin/buildslave create-slave ~/flocker-osx "${MASTER}" osx-0 "${PASSWORD}"
   export PATH=$HOME/Library/python/2.7/bin:$PATH
   twistd --nodaemon -y flocker-osx/buildbot.tac

There is a VMware Fusion OSX VM configured, for running homebrew installation tests.
It is configured with a ``nat`` network, with a static IP address,
and the buildslave user has a password-less ssh-key that can log in to it.

Fedora hardware builders
------------------------

The following builders need to run on Fedora 20 on bare metal hardware:

* flocker-vagrant-dev-box
* flocker/vagrant/build/tutorial
* flocker/acceptance/vagrant/centos-7
* flocker/installed-package/centos-7

To create a Rackspace OnMetal slave to serve this purpose:

* Log into https://mycloud.rackspace.com,
* Create Server > OnMetal Server,
* Give the server an appropriate name,
* Choose the following options: Image: OnMetal - Fedora 20 (Heisenbug), Flavor: OnMetal Compute, An SSH key you have access to
* Create Server,
* When this is complete there will be a command to log into the server, e.g. ``ssh root@${ONMETAL_IP_ADDRESS}``.

To configure any Fedora 20 bare metal machine (e.g. on OnMetal as above)::

   fab -f slave/vagrant/fabfile.py --hosts=root@${ONMETAL_IP_ADDRESS} install:0,${PASSWORD},${MASTER}

Where ``${PASSWORD}`` is the password in ``slaves.fedora-20/vagrant.passwords`` from the ``config.yml`` or ``staging.yml`` file used to deploy the BuildBot master on hostname or IP address ``${MASTER}``.

Red Hat Openstack
-----------------

The following builders need to run on Centos-7 on Red Hat Open Stack:

* ``redhat-openstack/centos-7``

To create this machine you'll need to access various machines within redhat-openstack via an "SSH jump host".

The machines are referred to here as:
 * **redhat-openstack-jumphost**: The SSH proxy through which you will connect to servers inside the redhat-openstack network.
 * **redhat-openstack-novahost**: The server which has ``nova`` and other openstack administrative tools installed.
 * **redhat-openstack-buildslave**: The server which will be created to run the ``redhat-openstack/centos-7`` builder.

You'll need to add your public SSH key to the ``redhat-openstack-jumphost``.
A username and key for initial access to the jump host can be found in LastPass.
Using that username and key, log into the jumphost and add your own public SSH key to the ``authorized_keys`` file of the jumphost user.

Next log into the ``redhat-openstack-novahost`` (credentials in LastPass) and add your own public SSH key.

Finally, register your public SSH key with openstack by using the ``nova`` command, as follows:

.. code-block:: console

  [redhat-openstack-novahost] $ cat > id_rsa_joe.blogs@clusterhq.com.pub
  ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC2imO7tTLepxqTvxacpNHKmqsRUdhM1EPdAVrBFadrYAC664LDbOvTqXR0iiVomKsfAe6nK9xZ5YzGFIpcOn/MeH45LOHVy5/+yx06qAnRkCDGZzQN/3qrs2K0v0L4XSIFbWmkFycAzG2phxFyAaJicK9XsJ9JaJ1q9/0FBj1TJ0CA7kCFaz/t0eozzOgr7WsqtidMrgrfrWvZW0GZR2PUc+1Ezt0/OBR8Xir0VGMgeLOrHprAF/BSK+7GLuQ9usa+nu3i46UuKtaVDMrKFCkzSdfNX2xJJYlRUEvLTa1VgswgL1wXXUwxXlDmYdwjF583CSFrVeVzBmRRJqNU/IMb joe.bloggs@clusterhq.com

  [redhat-openstack-novahost] $ nova keypair-add --pub-key id_rsa_joe.bloggs@clusterhq.com.pub clusterhq_joebloggs

Having done this, create or modify a ``~/.ssh/config`` file containing the aliases, usernames, hostnames for each of the servers and proxy commands that will allow direct access to the internal servers via the ``redhat-openstack-jumphost``.

Here is an example of such a file::

   Host redhat-openstack-jumphost
        User <jumphost_username>
        HostName <jumphost_public_hostname_or_ip_address>

   Host redhat-openstack-novahost
        User <novahost_username>
        HostName <novahost_public_hostname_or_ip_address>
        ProxyCommand ssh redhat-openstack-jumphost nc %h %p

With that ``~/.ssh/config`` content in place, run:

.. code-block:: console

   [laptop] $ fab -H redhat-openstack-novahost -f slave/redhat-openstack/fabfile.py create_server:clusterhq_joebloggs


The argument ``clusterhq_joebloggs`` should be replaced with the name of the SSH public key that you registered using ``nova keypair-add`` in an earlier step.

The last line of the output will show the IP address of the new server.

Add that IP address of the new build slave server to your ssh config file::

   Host redhat-openstack-buildslave
        User centos
        HostName <buildbot_internal_ip_address_from_previous_step>
        ProxyCommand ssh redhat-openstack-novahost nc %h %p

Note: You can also log into ``redhat-openstack-novahost`` and run ``nova list`` to show all the openstack virtual machines and their IP addresses.

Test the ``redhat-openstack-buildslave`` by attempting to connect to the build slave with SSH, as follows:

.. code-block:: console

   [laptop] $ ssh redhat-openstack-buildslave

Note: You may need to add your SSH private key to your keyring or SSH agent:

.. code-block:: console

   [laptop] $ ssh-add

Now configure the new server.
The following step will install:

* the buildbot buildslave package on the server and
* a systemd service which will be started automatically.

Run the following ``fabric`` task:

.. code-block:: console

   [laptop] $ fab -H redhat-openstack-buildslave -f slave/redhat-openstack/fabfile.py configure:0,${PASSWORD},${BUILDMASTER}

Where ``${PASSWORD}`` is the password in ``slaves.redhat-openstack/centos-7.passwords`` from the ``config.yml`` or ``staging.yml`` file,
and ``${BUILDMASTER}`` is the IP address of the BuildBot master that you want this buildslave to connect to.

Note: See "Create the configuration" section above if you do not have a ``config.yml`` or ``staging.yml`` configuration file.

Next steps:

* Check that the new build slave has connected to the master by viewing the build master web interface and by monitoring the build slave and build master log files.
* Check that builders have been assigned to the new build slave.
* Check that the assigned builders are able to perform all the required steps by forcing a build.
* If the builds on the new builder are expected to fail, add the name of the new builder to the ``failing_builders`` section of the ``config.yml`` file.
* The redhat-openstack build slave can be destroyed by running ``fab -f slave/redhat-openstack/fabfile.py delete_server``.

Fixing issues
=============

**VirtualBox errors**

Sometimes a message similar to the following is shown::

   ERROR    : [/etc/sysconfig/network-scripts/ifup-eth] Error, some other host already uses address 172.16.255.240.

See https://github.com/mitchellh/vagrant/issues/1693 for explanations and workarounds for this issue.

One way to work around this issue is to remove existing Virtual Machines.
To do this, run the following commands.
``${IP_ADDRESS}`` should be the address of the host.
For example, the Flocker host is on `soyoustart <https://www.soyoustart.com/>`_.

Show all active Vagrant environments for the buildslave user:

.. code:: shell

   ssh root@${IP_ADDRESS}
   su - buildslave
   vagrant global-status

Destroy all vagrant boxes.
Note, this will cause any currently running tests using these VMs to fail:

.. code:: shell

   # For each ID shown by vagrant global-status:
   vagrant destroy ${ID}

Kill all VBoxHead processes and unregister the killed VMs from VirtualBox:

.. code:: shell

   for box in $(VBoxManage list vms | cut -f -1 -d ' ' );
   do
      eval VBoxManage unregistervm $box ;
   done

Monitoring
==========

There is monitoring setup for buildbot, using `prometheus <http://prometheus.io/>`_.
It is configured to poll ``/metrics`` on both the production and staging buildbots.
It is currently running alongside both ``build.clusterhq.com`` and ``build.staging.clusterhq.com``.
It can be started by::

   fab --hosts=${USERNAME}@${HOST} startPrometheus

Disk Usage and Clearing Space
=============================

The Buildbot master stores artifacts from previous builds.
A script is run daily to delete some data which is 14+ days old.

To find where space is being used run::

   $ su -u root
   $ cd /
   # The following shows directory contents sorted by size
   $ du -sk * | sort -n
   # cd into any suspiciously large directories, probably the largest, and
   # repeat until the culprit is found.
   $ cd suspiciously-large-directory

Then fix the problem causing the space to be filled.

A temporary fix is to delete old files.
The following deletes files which are 7+ days old::

   $ find . -type f -mtime +7 -exec unlink {} \;

Alternatively it is possible to increase the volume size on the Amazon S3 instance hosting the BuildBot master.

The following steps can be used to change a volume size:

- Stop the S3 instance.
- Snapshot the volume being used by the instance.
- Create a volume from the snapshot with the desired size.
- Detach the old volume.
- Attach the new volume
- Start the instance.

Building Pull Requests
======================

To force a build on a Pull Request, perhaps from a fork, use the "Force" button with "refs/pull/≤pull request number>/head" as the branch name.
Be careful when doing this because the code in the Pull Request will be run on the Buildslaves, and this could be dangerous code.
