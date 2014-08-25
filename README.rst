This is the configuration for ClusterHQ's `buildbot <http://buildbot.net/>`.

The master is deployed on an EC2 instance running in eu-west, in a docker container.
The docker image is stored on the docker registry, and is automatically updated when the master branch is updated
(it takes about 10 minutes for the build to occur, the status is available `here <https://registry.hub.docker.com/u/clusterhq/build.clusterhq.com/builds_history/46090/>`).

The slaves are EC2 latent slaves (spot instances) started by the master.
They are based off the `fedora-buildslave-base` AMI in us-west-2.
The image is based on the offical fedora 20 image (`ami-cc8de6fc`) with `slave/cloud-init-base.sh`.
Each image uses `slave/cloud-init.sh` with some substitutions as user-data, to start the buildbot.

We use schedulers to start builds, triggered by each push of a commit to a branch and forced builds.
After each commit is pushed, Buildbot waits a number of seconds before starting a build,
in case another commit comes in shortly afterwards.

All builds are tested as merges against master.

There is a fabfile with commands ``start`` and ``update`` for deploying the buildbot (currently written assuming a ubuntu trusty host).

Deploying changes
-----------------

Clone HybridDeployment https://github.com/ClusterHQ/build.clusterhq.com

Add the HybridDeployment master key to your authentication agent::

   $ ssh-add /path/to/HybridDeployment/credentials/master_key

Go to a checkout of the build.clusterhq.com repository, with Docker running.

The secrets for the master must be stored in a file ``config.yml`` inside the checkout.
These secrets can be found in the "FlockerBuildbot Credentials" file in LastPass.
Fabric passes these variables to buildbot via a docker environment variable as JSON.

Install dependencies::

   $ pip install pyyaml
   $ pip install fabric

Check if anyone has running builds at http://build.clusterhq.com/buildslaves.

Announce on Zulip's Engineering > buildbot stream that Buildbot will be unavailable for a few minutes.

Update the live Buildbot (this may take some time)::

   $ fab update

To view the logs::

   $ fab logs

To restart the live Buildbot::

   $ fab restart

Staging changes
---------------

Buildbot changes can be tested on a staging machine.
The docker registry will automatically build an image based on the staging branch, whenever it is updated.

Create an Ubuntu 14.04 spot instance on EC2 and note the IP of this instance.
In the following example the IP is 54.191.9.106.
Set the Security Group of this instance to allow inbound traffic as shown below.

.. image:: security-group.png
   :alt: Custom TCP Rule, TCP Protocol, Port Range 5000, Source Anywhere, 0.0.0.0/0
         SSH, TCP Protocol, Port Range 22, Source Anywhere, 0.0.0.0/0
         HTTP, TCP Protocol, Port Range 80, Source Anywhere, 0.0.0.0/0
         Custom TCP Rule, TCP Protocol, Port Range 9989, Source Anywhere, 0.0.0.0/0
         All ICMP, ICMP Protocol, Port Range 0-65535, Source Anywhere, 0.0.0.0/0

The Security Group should allow all outbound traffic.

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

The staging setup is missing the ability to trigger builds in response to commits happening.

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
