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


@attributes(['_driver'], apply_immutable=True)
class InstanceBooter(object):
    """
    """

    def _fsmState(self):
        """
        Return the current state of the finite-state machine driving this
        L{EC2}.
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
        return self._driver.name

    def output_START(self, context):
        """
        Create a node.
        """
        def thread_start():
            self.image_metadata = self._driver.get_image_metadata()

            return self._driver.create_node()
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
                instance_id=instance_id, **self._driver.log_failure_arguments()
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


def get_image(driver, image_name, image_tags):
    """
    Return a ``NodeImage`` corresponding to a given name of size.

    :param driver: The libcloud driver to query for images.
    """
    def dict_contains(expected, actual):
        return set(expected.items()).issubset(set(actual.items()))

    images = [
        image for
        image in driver.list_images(ex_owner="self")
        if image.extra['tags'].get('base-name') == image_name
        and dict_contains(image_tags, image.extra['tags'])
    ]
    if not images:
        raise ValueError("Unknown image.", image_name)

    def timestamp(image):
        return image.extra.get('timestamp')
    return max(images, key=timestamp)


class ICloudDriver(Interface):
    """
    A thin layer on top of libcloud NodeDriver.
    """
    def create():
        """
        :return: libcloud Node
        """
    def get_image_metadata():
        """
        """


@attributes(
    ['_driver', 'instance_type', 'region', 'keypair_name', 'security_name',
     'image_id', 'username', 'api_key', 'image_tags', 'instance_tags']
)
class EC2CloudDriver(object):
    """
    """

    def log_failure_arguments():
        return dict(
            format=(
                "EC2 Instance [%(instance_id)s]"
                "(https://us-west-2.console.aws.amazon.com/ec2/v2/home?region=us-west-2#Instances:instanceId=%(instance_id)s) "  # noqa
                "failed to stop."
            ),
            zulip_subject="EC2 Instances"
        )

    def get_image_metadata(self):
        image = get_image(
            self._driver, self.image_id, self.image_tags
        )

        image_metadata = {
            'image_id': image.id,
            'image_name': image.name,
        }
        image_metadata.update(image.extra['tags'])
        return image_metadata

    def create(self):
        """
        """
        image = get_image(
            self._driver, self.image_id, self.image_tags
        )

        return self.driver.create_node(
            name=self.name,
            size=get_size(self._driver, self.size),
            image=image,
            ex_keyname=self.keyname,
            ex_userdata=self.userdata,
            ex_metadata=self.instance_tags,
            ex_securitygroup=self.security_groups,
        )


@attributes(
    ['driver', 'flavor', 'region', 'keypair_name', 'image', 'username',
     'api_key', 'image_tags']
)
class RackspaceCloudDriver(object):
    """
    """

    def create(self):
        """
        """
        
    def from_driver_parameters(
            cls, region, username, api_key, **kwargs):
        """
        """
        from libcloud.compute.providers import get_driver, Provider
        rackspace = get_driver(Provider.RACKSPACE)
        driver = rackspace(username, api_key, region)
        return cls(
            driver=driver, 
            region=region, 
            username=username, 
            api_key=api_key, 
            **kwargs
        )
        
    
def rackspace_slave(
        name, password, config, credentials, user_data, buildmaster,
        image_tags, build_wait_timeout, keepalive_interval):
    driver = RackspaceCloudDriver.from_driver_parameters(
        # Hardcoded rackspace flavor...for now
        flavor='general1-8',
        region='dfw',
        keypair_name='richardw-testing',
        image=config['openstack-image'],
        username=credentials['username'],
        api_key=credentials['api_key'],
        image_tags=image_tags,
        user_data=user_data,
        instance_tags={
            'Image': config['openstack-image'],
            # maybe shouldn't be mangled
            'Class': name,
            'Buildmaster': buildmaster
        }
    )
    instance_booter = InstanceBooter(
        driver=driver
    )
    return OnDemandBuildSlave(
        name=name,
        password=password,
        instance_booter=instance_booter,
        build_wait_timeout=build_wait_timeout,
        keepalive_interval=keepalive_interval,
    )
    

def ec2_slave(
        name, password, config, credentials, user_data, region, keypair_name,
        security_name, build_wait_timeout, keepalive_interval, buildmaster,
        image_tags):
    """
    """
    driver = EC2CloudDriver.from_driver_parameters(
        # Hardcoded rackspace flavor...for now
        instance_type=config['instance_type'],
        region=region,
        keypair_name=keypair_name,
        security_name=security_name,
        image_id=config['ami'],
        username=credentials['username'],
        api_key=credentials['api_key'],
        user_data=user_data,
        image_tags=image_tags,
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
    return OnDemandBuildslave(
        name=name,
        password=password,
        instance_booter=instance_booter,
        build_wait_timeout=build_wait_timeout,
        keepalive_interval=keepalive_interval,
    )

