from zope.interface import implementer
from twisted.python.constants import Names, NamedConstant
from twisted.internet.threads import deferToThread
from characteristic import attributes
from twisted.python import log
from machinist import (
    TransitionTable, MethodSuffixOutputer,
    trivialInput, constructFiniteStateMachine, Transition,
    IRichInput, stateful)


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


@attributes([
    'name',
    'image_name',
    'size',
    'keyname',
    'security_groups',
    'userdata',
    'instance_tags',
    'image_tags',
], apply_immutable=True)
class EC2(object):

    def _fsmState(self):
        """
        Return the current state of the finite-state machine driving this
        L{EC2}.
        """
        return self._fsm.state

    image_metadata = stateful(_fsmState, State.ACTIVE, State.STARTING)
    instance_metadata = stateful(_fsmState, State.ACTIVE)

    def __init__(self, access_key, secret_access_token, region):
        # Import these here, so that this can be imported without
        # installng libcloud.
        from libcloud.compute.providers import get_driver, Provider
        self._driver = get_driver(Provider.EC2)(
            key=access_key,
            secret=secret_access_token,
            region=region)

        self._fsm = constructFiniteStateMachine(
            inputs=Input, outputs=Output, states=State, table=table,
            initial=State.IDLE,
            richInputs=[RequestStart, InstanceStarted, StartFailed,
                        RequestStop, InstanceStopped, StopFailed],
            inputContext={}, world=MethodSuffixOutputer(self))

    def identifier(self):
        return self.name

    def output_START(self, context):
        """
        Create a node.
        """
        def thread_start():
            image = get_image(
                self._driver, self.image_name, self.image_tags)
            self.image_metadata = {
                'image_id': image.id,
                'image_name': image.name,
            }
            self.image_metadata.update(image.extra['tags'])
            return self._driver.create_node(
                name=self.name,
                size=get_size(self._driver, self.size),
                image=image,
                ex_keyname=self.keyname,
                ex_userdata=self.userdata,
                ex_metadata=self.instance_tags,
                ex_securitygroup=self.security_groups,
            )
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
            log.err(f, "while starting %s" % (self.name,))
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
            log.err(f, "while stopping %s" % (self.name,))
            log.msg(
                format="EC2 Instance [%(instance_id)s](https://us-west-2.console.aws.amazon.com/ec2/v2/home?region=us-west-2#Instances:instanceId=%(instance_id)s) failed to stop.",  # noqa
                instance_id=instance_id,
                zulip_subject="EC2 Instances")

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
