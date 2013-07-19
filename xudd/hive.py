from threading import Thread, Lock

try:
    from queue import Queue, Empty
except ImportError:
    from Queue import Queue, Empty


class HiveWorker(Thread):
    """
    A worker thread that gives life to actors, allowing them to process
    messages.
    """
    def __init__(self, hive, actor_queue, max_messages=5, wait_timeout=1):
        """
        Args:
         - actor_queue: queue of actors to be processed at present
         - max_messages: maximum number of messages to process per actor
         - wait_timeout: amount of time to block without getting a
           message before we give up (this way we can still stop if
           useful)
        """
        super(HiveWorker, self).__init__(self)
        self.hive = hive
        self.actor_queue = actor_queue
        self.wait_timeout = wait_timeout
        self.max_messages = max_messages

        self.should_stop = False

    def run(self):
        while not self.should_stop:
            self.process_actor()

    def stop(self):
        self.should_stop = True

    def process_actor(self):
        """
        Take an actor off the queue and process its messages... if
        there's anything to process
        """
        # Get an actor from the actor queue
        # 
        try:
            actor = self.actor_queue.get(
                block=True, timeout=self.wait_timeout)
        except Empty:
            # We didn't do anything this round, oh well
            return False

        # Process messages from this actor
        messages_processed = 0
        while self.max_messages is None \
              or messages_processed < self.max_messages:
            # Get a message off the message queue
            # (I don't think we need to lock while pulling one off the stack,
            #  but doesn't hurt?)
            with actor.message_queue.lock:
                try:
                    message = actor.message_queue.queue.get(block=False)
                except Empty:
                    # No messages on the queue anyway, might as well break out
                    # from this
                    break

            actor.handle_message(message)
            messages_processed += 1

        # Request checking if actor should be requeued with hive
        self.hive.request_possibly_requeue_actor(actor)


class Hive(Thread):
    """
    Hive handles all actors and the passing of messages between them.

    Inter-hive communication may exist in the future, it doesn't yet ;)
    """
    def __init__(self, num_workers=5):
        # NO locking on this presently, though maybe we should?
        # At the very least, one *should not* iterate through this dictionary
        # ... wouldn't be hard to set up a lock if we need it
        self.__actor_registry = {}

        # Actor queue
        self.__actor_queue = Queue()
        self.__actors_in_queue = set()

        self.num_workers = num_workers
        self.__workers = []

        # This is actions for ourself to take, such as checking if an
        # actor should be re-queued, and queueing messages to an actor
        self.hive_action_queue = Queue()

        self.should_stop = False

    def __init_and_start_workers(self):
        for i in range(self.num_workers):
            worker = HiveWorker()
            self.__workers.append(worker)
            worker.start()

    def register_actor(self, actor):
        pass

    def remove_actor(self, actor_id):
        pass

    def send_message(self, message_things_here):
        """
        API for sending a message to an actor.

        Note, not the same as queueing a message which is a more low-level
        action.  This also constructs a proper Message object.
        """
        pass

    def request_possibly_requeue_actor(self, actor):
        self.action_queue.put(
            ("check_queue_actor", actor))

    def queue_message(self, message):
        """
        Queue a message to its appropriate actor.
        """
        try:
            actor = self.__actor_registry[message.to]
        except KeyError:
            # TODO:
            #   In the future, if this fails, we should send a message back to
            #   the original sender informing them of such
            print (
                "Wouldn't it be nice if we handled sending "
                "messages to an actor that didn't exist more gracefully?")
            return False
        
        # --- lock during this to avoid race condition of actor ---
        #     with messages not appearing on actor_queue
        with actor.message_queue.lock:
            actor.message_queue.queue.put(message)
            # Add the wrapped actor, if it's not in that set already
            self.queue_actor(actor)

    def run(self):
        self.__init_and_start_workers()
        self.workloop()

    def queue_actor(self, actor):
        """
        Queue an actor... it's got messages to be processed!
        """
        self.__actor_queue.queue.put(actor)
        self.__actors_in_queue.add(actor)

    def workloop(self):
        # ... should we convert the hive to an actor that processes
        # its own messages? ;)

        # Process actions
        while not self.should_stop:
            action = self.hive_action_queue.get(
                block=True, timeout=1)
            action_type = action[0]

            # The actor just had their stuff processed... see if they
            # should be put back on the actor queue
            if action_type == "check_queue_actor":
                actor = action[1]
                with actor.message_queue.lock:
                    # Should we requeue?
                    if actor.message_queue.queue.empty():
                        # apparently not, remove the actor from the
                        # "actors in queue" set
                        self.actor_queue.actors_in_queue.pop(actor)
                    else:
                        # Looks like so!
                        self.queue_actor(actor)

            elif action_type == "queue_message":
                message = action[1]
                self.queue_message(message)

            else:
                raise UnknownHiveAction(
                    "Unknown action: %s" % action_type)


class UnknownHiveAction(Exception): pass


class HiveProxy(object):
    """
    Proxy to the Hive.

    Doesn't expose the entire hive because that could result in
    actors playing with things they shouldn't. :)
    """
    def __init__(self, hive):
        self.__hive = hive

    def register_actor(self, *args, **kwargs):
        self.__hive.register_actor(*args, **kwargs)

    def send_message(self, *args, **kwargs):
        self.__hive.send_message(*args, **kwargs)

    def gen_message_queue(self, *args, **kwargs):
        self.__hive.gen_message_queue(*args, **kwargs)

