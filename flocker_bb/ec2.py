from zope.interface import implementer, Interface
from twisted.python.constants import Names, NamedConstant
from twisted.internet.threads import deferToThread
from characteristic import attributes
from twisted.python import log
from machinist import (
    TransitionTable, MethodSuffixOutputer,
    trivialInput, constructFiniteStateMachine, Transition,
    IRichInput, stateful)
from flocker_bb.ec2_buildslave import OnDemandBuildSlave
from retry import retry


class RequestLimitExceeded(Exception):
    pass

retry_on_request_limit = retry(
    RequestLimitExceeded, delay=1, backoff=2, max_delay=60, jitter=(0, 5))


# A metadata key name which can be found in image metadata.  This metadata
# items identifies the general purpose of the image.  It may not be unique if
# multiple versions of the image have been created.  It corresponds to the
# names used in the manifest.yml file used to build the images.
BASE_NAME_TAG = "base_name"


class Input(Names):
    REQUEST_START = NamedConstant()
    INSTANCE_STARTED = NamedConstant()
    START_FAILED = NamedConstant()
    REQUEST_STOP = NamedConstant()
    INSTANCE_STOPPED = NamedConstant()
    STOP_FAILED = NamedConstant()


class Output(Names):
    START = NamedConstant()
    STOP = NamedConstant()


class State(Names):
    IDLE = NamedConstant()
    STARTING = NamedConstant()
    START_CANCELLED = NamedConstant()
    ACTIVE = NamedConstant()
    STOPPING = NamedConstant()
    STOP_CANCELLED = NamedConstant()

table = TransitionTable({
    State.IDLE: {
        Input.REQUEST_START: Transition([Output.START], State.STARTING),
        Input.REQUEST_STOP: Transition([], State.IDLE),
    },
    State.STARTING: {
        Input.REQUEST_START: Transition([], State.STARTING),
        Input.REQUEST_STOP: Transition([], State.START_CANCELLED),
        Input.INSTANCE_STARTED: Transition([], State.ACTIVE),
        Input.START_FAILED: Transition([Output.START], State.STARTING),
    },
    State.START_CANCELLED: {
        Input.REQUEST_START: Transition([], State.STARTING),
        Input.REQUEST_STOP: Transition([], State.START_CANCELLED),
        Input.INSTANCE_STARTED: Transition([Output.STOP], State.STOPPING),
        Input.START_FAILED: Transition([], State.IDLE),
    },
    State.ACTIVE: {
        Input.REQUEST_START: Transition([], State.ACTIVE),
        Input.REQUEST_STOP: Transition([Output.STOP], State.STOPPING),
    },
    State.STOPPING: {
        Input.REQUEST_START: Transition([], State.STOP_CANCELLED),
        Input.REQUEST_STOP: Transition([], State.STOPPING),
        Input.INSTANCE_STOPPED: Transition([], State.IDLE),
        Input.STOP_FAILED: Transition([Output.STOP], State.STOPPING),
    },
    State.STOP_CANCELLED: {
        Input.REQUEST_START: Transition([], State.STOP_CANCELLED),
        Input.REQUEST_STOP: Transition([], State.STOPPING),
        Input.INSTANCE_STOPPED: Transition([Output.START], State.STARTING),
        Input.STOP_FAILED: Transition([], State.ACTIVE),
    },
})

RequestStart = trivialInput(Input.REQUEST_START)


@implementer(IRichInput)
@attributes(['instance_id', 'image_metadata', 'instance_metadata'])
class InstanceStarted(object):
    @staticmethod
    def symbol():
        return Input.INSTANCE_STARTED

StartFailed = trivialInput(Input.START_FAILED)
RequestStop = trivialInput(Input.REQUEST_STOP)
InstanceStopped = trivialInput(Input.INSTANCE_STOPPED)
StopFailed = trivialInput(Input.STOP_FAILED)


@attributes(['driver'], apply_immutable=True)
class InstanceBooter(object):
    """
    Creates and destroys virtual machines associated with an
    ``OnDemandBuildSlave`` 's in response to the state changes supplied by a
    ``machinist`` loop.

    :ivar ICloudDriver driver: A driver instance which is capable of creating
       and destroying virtual machines for a particular cloud provider.
    """

    def _fsmState(self):
        """
        Return the current state of the finite-state machine driving this
        ``InstanceBooter``.
        """
        return self._fsm.state

    image_metadata = stateful(_fsmState, State.ACTIVE, State.STARTING)
    instance_metadata = stateful(_fsmState, State.ACTIVE)

    def __init__(self):
        self._fsm = constructFiniteStateMachine(
            inputs=Input, outputs=Output, states=State, table=table,
            initial=State.IDLE,
            richInputs=[RequestStart, InstanceStarted, StartFailed,
                        RequestStop, InstanceStopped, StopFailed],
            inputContext={}, world=MethodSuffixOutputer(self))

    def identifier(self):
        return self.driver.name

    def output_START(self, context):
        """
        Create a node.
        """
        def thread_start():
            # Since loading the image metadata is done separately from booting
            # the node, it's possible the metadata here won't actually match
            # the metadata of the image the node ends up running (someone could
            # replace the image with a different one between this call and the
            # node being started).  Since generating images is currently a
            # manual step, this probably won't happen very often and if it does
            # there's a person there who can deal with it.  Also it will be
            # resolved after the next node restart.  It would be better to
            # extract the image metadata from the booted node, though.
            # FLOC-1905
            self.image_metadata = self.driver.get_image_metadata()
            return self.driver.create()
        d = deferToThread(thread_start)

        def started(node):
            self.node = node
            instance_metadata = {
                'instance_id': node.id,
                'instance_name': node.name,
            }
            self._fsm.receive(InstanceStarted(
                instance_id=node.id,
                image_metadata=self.image_metadata,
                instance_metadata=instance_metadata,
            ))
            self.instance_metadata = instance_metadata

        def failed(f):
            log.err(f, "while starting %s" % (self.identifier(),))
            self._fsm.receive(StartFailed())

        d.addCallbacks(started, failed)

    def output_STOP(self, context):
        """
        Destroy a node.
        """
        d = deferToThread(self.node.destroy)

        def stopped(node):
            del self.node
            self._fsm.receive(InstanceStopped())

        def failed(f):
            instance_id = self.node.id
            # Assume the instance is already gone.
            del self.node
            self._fsm.receive(InstanceStopped())
            log.err(f, "while stopping %s" % (self.identifier(),))
            log.msg(
                instance_id=instance_id, **self.driver.log_failure_arguments()
            )

        d.addCallbacks(stopped, failed)

    def start(self):
        self._fsm.receive(RequestStart())

    def stop(self):
        self._fsm.receive(RequestStop())


def get_size(driver, size_id):
    """
    Return a ``NodeSize`` corresponding to a given id.

    :param driver: The libcloud driver to query for sizes.
    """
    try:
        return [s for s in driver.list_sizes() if s.id == size_id][0]
    except IndexError:
        raise ValueError("Unknown size.", size_id)


def get_newest_tagged_image(images, name, tags, get_tags):
    """
    Return the newest image from ``images`` with a matching name and tags.

    :param list images: Images loaded from a libcloud driver.
    :param bytes name: An image name to match.
    :param dict tags: Extra tags which should be present on the image.
    :param get_tags: A one-argument callable which returns the tags on an
        image.

    :return: The new image from ``images`` which matches the given criteria.
    """
    required_tags = tags.copy()
    required_tags[BASE_NAME_TAG] = name

    log.msg(
        format="Checking %(count)d images for tags %(required)s",
        count=len(images),
        required=required_tags,
    )

    def dict_contains(expected, actual):
        return set(expected.items()).issubset(set(actual.items()))

    def timestamp(image):
        return get_tags(image).get('timestamp')

    matching_images = []
    for image in images:
        image_tags = get_tags(image)
        log.msg(
            format="Checking %(image_id)s with %(tags)s",
            image_id=image.id, tags=image_tags,
        )
        if dict_contains(required_tags, image_tags):
            log.msg(
                format="%(image_id)s matched required tags", image_id=image.id,
            )
            matching_images.append(image)

    if matching_images:
        return max(matching_images, key=timestamp)
    raise ValueError("Unknown image.", name)


class ICloudDriver(Interface):
    """
    A thin layer on top of libcloud ``NodeDriver`` which is required to mask
    the differences between cloud provider specific subclasses of
    ``NodeDriver``.
    """
    def create():
        """
        Create a new node

        :return: A libcloud ``Node``.
        """

    def log_failure_arguments():
        """
        :return: A ``dict`` of arguments which will be use to format the
            message sent to ``Zulip`` when a node can not be automatically
            destroyed.
        """

    def get_image_metadata():
        """
        :return: A ``dict`` of metadata for the image used by this buildslave,
            which will be displayed in the build master web interface.
        """


@attributes([
    'driver', 'name', 'region', 'instance_type', 'keypair_name',
    'security_name', 'image_id', 'image_tags', 'user_data',
    'instance_tags'
])
@implementer(ICloudDriver)
class EC2CloudDriver(object):
    """
    A driver for creating ``EC2`` nodes on ``AWS``.
    """
    _INSTANCE_URL = (
        "https://%(region)s.console.aws.amazon.com/ec2/v2/home?"
        "region=%(region)s#Instances:instanceId=%(instance_id)s)"
    )
    _FAILED_MSG_FORMAT = (
        "EC2 Instance [%(instance_id)s](" + _INSTANCE_URL + ") failed to stop."
    )

    @classmethod
    def from_driver_parameters(
            cls, region, identifier, secret_identifier, **kwargs):
        """
        Create an ``EC2`` libcloud ``NodeDriver`` using the supplied region and
        credentials and supply that as the ``driver`` for ``EC2CloudDriver``
        along with all the other keyword arguments it requires.

        :param bytes region: An EC2 region slug.
        :param bytes identifier: An EC2 API identifier.
        :param bytes secret_identifier: An EC2 API "secret" identifier.
        :param dict kwargs: Keyword arguments for ``EC2CloudDriver``.
        :returns: An ``EC2CloudDriver``instance.
        """
        from libcloud.compute.providers import get_driver, Provider
        ec2_driver_factory = get_driver(Provider.EC2)
        driver = ec2_driver_factory(
            key=identifier,
            secret=secret_identifier,
            region=region
        )

        return cls(driver=driver, region=region, **kwargs)

    def log_failure_arguments(self):
        return dict(
            format=self._FAILED_MSG_FORMAT,
            region=self.region,
            zulip_subject="EC2 Instances"
        )

    def get_image(self):
        log.msg(
            format="Getting image for %(image_id)s; required tags %(tags)s",
            image_id=self.image_id, tags=self.image_tags,
        )
        return get_newest_tagged_image(
            # Only get images belonging to us.  There's a ton of public AMIs
            # that are definitely irrelevant.
            images=self.driver.list_images(ex_owner="self"),
            name=self.image_id,
            tags=self.image_tags,
            get_tags=lambda image: image.extra['tags'],
        )

    def get_image_metadata(self):
        image = self.get_image()

        image_metadata = {
            'image_id': image.id,
            'image_name': image.name,
        }
        image_metadata.update(image.extra['tags'])
        return image_metadata

    @retry_on_request_limit
    def create(self):
        """
        Create and start a new EC2 instance.

        All parameters are fixed to the values used to initialize this driver.
        """
        try:
            image = self.get_image()
            return self.driver.create_node(
                name=self.name,
                size=get_size(self.driver, self.instance_type),
                image=image,
                ex_keyname=self.keypair_name,
                ex_userdata=self.user_data,
                ex_metadata=self.instance_tags,
                ex_securitygroup=[self.security_name],
            )
        except Exception as e:
            if "RequestLimitExceeded" in e.message:
                raise RequestLimitExceeded()
            raise


@attributes(
    ['driver', 'name', 'flavor', 'keypair_name', 'image_id', 'image_tags',
     'instance_tags', 'user_data', 'region']
)
@implementer(ICloudDriver)
class RackspaceCloudDriver(object):
    """
    A driver for creating ``Compute`` nodes on ``Rackspace``.
    """
    # ClusterHQ organization
    _TENANT_ID = "929000"
    _FAILED_MSG_FORMAT = (
        "Rackspace Instance [%(instance_id)s]"
        "(https://mycloud.rackspace.com/cloud/" + _TENANT_ID + "/servers#"
        "compute%%2CcloudServersOpenStack%%2C%(region_slug)s/"
        "%(instance_id)s) failed to stop."
    )

    @classmethod
    def from_driver_parameters(
            cls, region, username, api_key, **kwargs):
        """
        Create an ``Rackspace`` libcloud ``NodeDriver`` using the supplied
        region and credentials and supply that as the ``driver`` for
        ``RackspaceCloudDriver`` along with all the other keyword arguments it
        requires.

        :param bytes region: A Rackspace region slug.
        :param bytes username: A Rackspace API username.
        :param bytes api_key: A Rackspace API key.
        :param dict kwargs: Keyword arguments for ``RackspaceCloudDriver``.
        :returns: A ``RackspaceCloudDriver``instance.
        """
        from libcloud.compute.providers import get_driver, Provider
        rackspace = get_driver(Provider.RACKSPACE)
        driver = rackspace(username, api_key, region)
        return cls(driver=driver, region=region, **kwargs)

    def get_image(self):
        return get_newest_tagged_image(
            images=self.driver.list_images(),
            name=self.image_id,
            tags=self.image_tags,
            get_tags=lambda image: image.extra['metadata'],
        )

    def create(self):
        """
        Create and start a new Rackspace Cloud Server.

        All parameters are fixed to the values used to initialize this driver.
        """
        image = self.get_image()
        return self.driver.create_node(
            name=self.name,
            size=get_size(self.driver, self.flavor),
            image=image,

            ex_keyname=self.keypair_name,
            ex_metadata=self.instance_tags,

            # If you don't turn on the config drive then your user data gets
            # tossed in a black hole.
            ex_config_drive=True,
            ex_userdata=self.user_data,
        )

    def get_image_metadata(self):
        image = self.get_image()
        image_metadata = {
            'image_id': image.id,
            'image_name': image.name,
        }
        image_metadata.update(image.extra['metadata'])
        return image_metadata

    def log_failure_arguments(self):
        return dict(
            format=self._FAILED_MSG_FORMAT,
            region_slug=self.region,
            zulip_subject="Rackspace Instances"
        )


def get_image_tags(credentials):
    """
    Extracts the ``image_tags`` dictionary from the ``credentials`` section of
    a buildbot ``config.yml`` file.
    These tags are used for filtering the list of images that can be used when
    creating buildslave nodes.
    If the image_tags section is missing, a default dictionary of tags is
    returned which will result in only production images being used.
    If the image_tags key is present by has a value of ``None``, an empty
    ``dict`` will be returned.

    :param dict credentials: The ``credentials`` section of a buildbot
        ``config.yml`` file.
    :returns: ``dict``
    """
    return credentials.get("image_tags", {"production": "true"}) or {}


def rackspace_slave(
        name, password, config, credentials, user_data, buildmaster,
        build_wait_timeout, keepalive_interval, max_builds,
):
    """
    :return: An ``OnDemandBuildSlave`` that uses a ``RackspaceCloudDriver`` for
        creating and destroying new buildslave nodes.
    """
    driver = RackspaceCloudDriver.from_driver_parameters(
        name=name,
        flavor='general1-8',
        region=credentials["region"],
        keypair_name=credentials["keyname"],
        image_id=config['openstack-image'],
        username=credentials['username'],
        api_key=credentials['key'],
        image_tags=get_image_tags(credentials),
        user_data=user_data,
        instance_tags={
            'Image': config['openstack-image'],
            # maybe shouldn't be mangled
            'Class': name,
            'Buildmaster': buildmaster
        }
    )
    instance_booter = InstanceBooter(
        driver=driver,
    )
    return OnDemandBuildSlave(
        password=password,
        instance_booter=instance_booter,
        build_wait_timeout=build_wait_timeout,
        keepalive_interval=keepalive_interval,
        max_builds=max_builds,
    )


def ec2_slave(
        name, password, config, credentials, user_data, region, keypair_name,
        security_name, build_wait_timeout, keepalive_interval, buildmaster,
        max_builds,
):
    """
    :return: An ``OnDemandBuildSlave`` that uses an ``EC2CloudDriver`` for
        creating and destroying new buildslave nodes.
    """
    driver = EC2CloudDriver.from_driver_parameters(
        # libcloud ec2 driver parameters
        region=region,
        identifier=credentials['identifier'],
        secret_identifier=credentials['secret_identifier'],

        # Other
        name=name,
        instance_type=config['instance_type'],
        keypair_name=keypair_name,
        security_name=security_name,
        image_id=config['ami'],
        image_tags=get_image_tags(credentials),
        user_data=user_data,
        instance_tags={
            'Image': config['ami'],
            # maybe shouldn't be mangled
            'Class': name,
            'Buildmaster': buildmaster
        }
    )
    instance_booter = InstanceBooter(
        driver=driver
    )
    return OnDemandBuildSlave(
        password=password,
        instance_booter=instance_booter,
        build_wait_timeout=build_wait_timeout,
        keepalive_interval=keepalive_interval,
        max_builds=max_builds,
    )
