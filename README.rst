This is the configuration for ClusterHQ's `buildbot <http://buildbot.net/>`_.

The master is deployed on an EC2 instance running in us-west-2, in a docker container.

The slaves are EC2 latent slaves started by the master.

We use schedulers to start builds, triggered by each push of a commit to a branch and forced builds.
After each commit is pushed, Buildbot waits a number of seconds before starting a build,
in case another commit comes in shortly afterwards.

All builds are tested as merges against master.

Deploying changes
-----------------

The buildbot is deployed from the automated build of the master branch of https://github.com/ClusterHQ/build.clusterhq.com on the docker registry.
It takes about 10 minutes for the build to occur, after pushing to master;
the status is available `here <https://registry.hub.docker.com/u/clusterhq/build.clusterhq.com/builds_history/46090/>`_).

The production instance is accessed using a key from https://github.com/hybridlogic/HybridDeployment (this repository is not publicly available).
Add the HybridDeployment master key to your authentication agent::

   $ ssh-add /path/to/HybridDeployment/credentials/master_key

Go to a checkout of the build.clusterhq.com repository.


Install dependencies::

   $ pip install pyyaml
   $ pip install fabric

The secrets for the master must be stored in a file ``config.yml`` inside the checkout.
Fabric passes these variables to buildbot via a docker environment variable as JSON.
These secrets can be found in the "config@build.clusterhq.com" file in LastPass.
If you have the lastpass command-line client installed, you can use fabric to download the current config::

   $ fab getConfig

Check if anyone has running builds at http://build.clusterhq.com/buildslaves.

Announce on Zulip's Engineering > buildbot stream that Buildbot will be unavailable for a few minutes.

Update the live Buildbot to the latest image (this may take some time)::

   $ fab update

To view the logs::

   $ fab logs

To restart the live Buildbot with the current image::

   $ fab restart

Staging changes
---------------

Buildbot changes can be tested on a staging machine.
The Docker registry will automatically build an image based on the ``staging`` branch, whenever it is updated.

Create a Fedora 20 instance on EC2 and note the IP of this instance.

In the following example the IP is 54.191.9.106.
Set the Security Group of this instance to allow inbound traffic as shown below.

.. image:: security-group.png
   :alt: Custom TCP Rule, TCP Protocol, Port Range 5000, Source Anywhere, 0.0.0.0/0
         SSH, TCP Protocol, Port Range 22, Source Anywhere, 0.0.0.0/0
         HTTP, TCP Protocol, Port Range 80, Source Anywhere, 0.0.0.0/0
         Custom TCP Rule, TCP Protocol, Port Range 9989, Source Anywhere, 0.0.0.0/0
         All ICMP, ICMP Protocol, Port Range 0-65535, Source Anywhere, 0.0.0.0/0

The Security Group should allow all outbound traffic.

To start a suitable instance, run ``python start-aws.py``.
Install and configure Python package ``boto`` to access AWS.
Ensure that the security_group and key_name variables in the file ``start-aws.py`` are set appropriately.

Create staging.yml with the config.yml variables from LastPass.
Change the buildmaster.host config option to the IP of the EC2 instance.
Change the github.report_status config option to False.
Add a buildmaster.docker_tag config option, with the value ``staging``.

Follow the "Deploying changes" setup but there is no need to check for running builds or make an announcement on Zulip.

To start a Buildbot slave on this machine run::

   $ fab start:staging.yml

To update a slave on this machine, run::

   $ fab update:staging.yml

Log in to 54.191.9.106 with the credentials from the ``auth`` section of the config file.

The staging setup is missing the ability to trigger builds in response to pushes happening.

The staging master will start Linux slaves on AWS EC2 automatically.  To start a Mac OS X slave, see below.

Wheelhouse
----------

There is a wheelhouse hosted on s3 (thus near the buildslaves).
Credentials [1]_ for ``s3cmd`` can be configured using ``s3cmd --configure``.
It can be updated to include available wheels of packages which are in flocker's ``setup.py`` by running the following commands::

   python setup.py sdist
   pip wheel -f dist "Flocker[doc,dev]==$(python setup.py --version)"
   s3cmd put -P -m "Content-Type:application/python+wheel" wheelhouse/*.whl s3://clusterhq-wheelhouse/fedora20-x86_64
   s3cmd ls s3://clusterhq-wheelhouse/fedora20-x86_64/ | sed 's,^.*/\(.*\),<a href="\1">\1</a><br/>,' | s3cmd put -P -m "text/html" - s3://clusterhq-wheelhouse/fedora20-x86_64/index

The buildslave is constructed with a ``pip.conf`` file that points at https://s3-us-west-2.amazonaws.com/clusterhq-wheelhouse/fedora20-x86_64/index.

.. [1] Create credentials at https://console.aws.amazon.com/iam/home#users.

Slave AMIs
----------

There are two slave AMIs.
The images are built by running ``slave/build-images``.
This will generate images with ``staging-`` prefixes.
These can be promoted by rnning ``slave/promote-images``.

The images are based on the offical fedora 20 image (``ami-cc8de6fc``) with ``slave/cloud-init-base.sh``.
Each image uses `slave/cloud-init.sh` with some substitutions as user-data, to start the buildbot.

``fedora-buildslave``
  is used for most builds, and has all the dependencies installed,
  including the latest release of zfs (or a fixed prerelease, when there are relevant bug fixes).
  The image is built by running :file:`slave/cloud-init-base.sh` and then installing zfs.
``fedora-buildslave-zfs-head``
  is used to test against the lastest version of zfs.
  It has all the dependencies except zfs installed, and has the latest version of zfs installed when an
  instance is created.  The image is built by running :file:`slave/cloud-init-base.sh`.

Both images have :file:`salve/cloud-init.sh` run on them at instance creation time.

Google Storage
--------------

The vagrant builders upload the boxes to google cloud storage.
The bucket (`gs://clusterhq-vagrant-buildbot/`) is set to expire objects after two weeks.
The lifecycle configuration file is in :file:`vagrant/clusterhq-vagrant-buildbot.lifecycle.json`.
It was configured by::

  gsutil lifecycle set vagrant/clusterhq-vagrant-buildbot.lifecycle.json gs://clusterhq-vagrant-buildbot/

Mac OS X Buildslave
-------------------

Configuring an OS X machine to run tests requires root priviledges and for SSH to be configured on this machine.

To configure this machine run::

   fab -f slave/osx/fabfile.py --hosts=${USERNAME}@${OSX_ADDRESS} install:0,${PASSWORD},${MASTER}

The tests do not run with root or administrator privileges.

Where ${USERNAME} is a user on the OS X machine, and ${PASSWORD} is the password in ``slaves.osx.passwords`` from the ``config.yml`` used to deploy the BuildBot master at ${MASTER}.

For testing purposes, or if you do not have root privileges, run the following commands to start a build slave:

.. code:: shell

   # Set MASTER and PASSWORD as above
   curl -O https://bootstrap.pypa.io/get-pip.py
   python get-pip.py --user
   ~/Library/Python/2.7/bin/pip install --user buildbot-slave==0.8.10 virtualenv==12.0.7
   ~/Library/Python/2.7/bin/buildslave create-slave ~/flocker-osx "${MASTER}" osx-0 "${PASSWORD}"
   export PATH=$HOME/Library/python/2.7/bin:$PATH
   twistd --nodaemon -y flocker-osx/buildbot.tac

Monitoring
----------

There is monitoring setup for buildbot, using `prometheus <http://prometheus.io/>`_.
It is configured to poll ``/metrics`` on both the production and staging buildbots.
It is currently running alongside both ``build.clusterhq.com`` and ``build.staging.clusterhq.com``.
It can be started by::

   fab --hosts=${USERNAME}@${HOST} startPrometheus
