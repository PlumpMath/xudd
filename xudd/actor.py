from types import GeneratorType
from functools import wraps
import logging

from xudd.tools import split_id


_log = logging.getLogger(__name__)


############
# decorators
############

def autoreply(func):
    """
    Automatically reply to a message if not handled in a handle_message
    method.  Replies in the most minimal way possible.
    """
    @wraps(func)
    def wrapper(self, message):
        result = func(self, message)

        if message.needs_reply():
            message.reply()

        return result

    return wrapper


####################
# Main actor classes
####################


class Actor(object):
    """
    Basic XUDD actor.
    """
    def __init__(self, hive, id):
        self.hive = hive
        self.id = id
        self.local_id = split_id(id)[0]

        # Routing of messages to handler functions
        self.message_routing = {}

        # Registry on coroutines that are currently waiting for a response
        self._waiting_coroutines = {}

    @autoreply
    def handle_message(self, message):
        """
        Handle a message being sent to this actor.
        """
        coroutine_result = None

        # If this message is continuing a coroutine-in-waiting, we'll
        # handle that.
        if message.in_reply_to is not None \
           and message.in_reply_to in self._waiting_coroutines:
            coroutine = self._waiting_coroutines.pop(message.in_reply_to)

            # Send this message reply to this coroutine
            _log.debug("Sending reply: %s", message)
            try:
                coroutine_result = coroutine.send(message)
            except StopIteration:
                # And our job is done
                return

        # Otherwise, this is a new message to handle.
        # TODO: send back a warning message if this is an unhandled directive?
        try:
            message_handler = self.message_routing[message.directive]
            result = message_handler(message)

            if isinstance(result, GeneratorType):
                coroutine = result
                try:
                    coroutine_result = coroutine.send(None)
                except StopIteration:
                    # Guess this coroutine ended without any yields
                    return None

        except KeyError:
            _log.error(u'Unregistered directive {!r}.'.format(
                message.directive))
            _log.debug(u'Message details: {!r}, {!r}'.format(
                message,
                message.body
            ))
            ## Raise an exception here?  Probably?
            # raise

        # If this is a coroutine, then we should handle putting its
        # results into the coroutine registry
        if coroutine_result:
            # since the coroutine returned a message_id that was sent,
            # we should add this message's id to the registry
            
            # TODO: Clean this up in the asyncio branch
            message_id = coroutine_result
            self._waiting_coroutines[message_id] = coroutine
            return


    def send_message(self, *args, **kwargs):
        return self.hive.send_message(*args, **kwargs)

    def wait_on_message(self, to, directive, from_id=None,
                        id=None, body=None, in_reply_to=None):
        """
        Send a message that we'll wait for a reply to.
        """
        return self.hive.send_message(
            to, directive,
            from_id=from_id,
            body=body, in_reply_to=in_reply_to, id=id,
            wants_reply=True)

    def wait_on_self(self):
        """
        Send a message that's actually just going to reply to itself!
        Useful for while loops.
        """
        # Kinda evil.  This message is going to reply to itself, so
        # it's actually generating its own id ahead of time...
        this_message_id = self.hive.gen_message_id()

        return self.hive.send_message(
            to=self.id, directive="self_reply",
            from_id=self.id,
            id=this_message_id, in_reply_to=this_message_id,
            # Okay, I know this is surprising...
            #
            # But since this message actually replies to itself, we
            # don't want to trigger the auto-reply behavior!
            # it is, by definition, already replying!
            wants_reply=False)


class ActorProxy(object):
    def __init__(self, actor_id):
        self.id = actor_id
