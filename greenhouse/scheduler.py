import bisect
import collections
import sys
import time
import weakref

from greenhouse.compat import greenlet


__all__ = ["pause", "pause_until", "pause_for", "schedule", "schedule_at",
        "schedule_in", "schedule_recurring", "add_exception_handler"]

_exception_handlers = []

FAST_POLL_TIMEOUT = 0.01
SLOW_POLL_TIMEOUT = 1.0


state = type('_greenhouse_state', (), {})()

# from events that have triggered
state.awoken_from_events = set()

# cooperatively yielded for a set timeout
state.timed_paused = []

# executed a simple cooperative yield
state.paused = []

# map of file numbers to the sockets/files on that descriptor
state.descriptormap = collections.defaultdict(list)

# lined up to run right away
state.to_run = collections.deque()


def _hit_poller(timeout):
    events = state.poller.poll(timeout)
    for fd, eventmap in events:
        socks = []
        for index, weak in enumerate(state.descriptormap[fd]):
            sock = weak()
            if sock is None or sock._closed:
                state.descriptormap[fd].pop(index)
            else:
                socks.append(sock)
        if eventmap & state.poller.INMASK:
            for sock in socks:
                sock._readable.set()
                sock._readable.clear()
        if eventmap & state.poller.OUTMASK:
            for sock in socks:
                sock._writable.set()
                sock._writable.clear()
    state.to_run.extend(state.awoken_from_events)
    state.awoken_from_events.clear()

def _check_paused(skip_simple=False):
    index = bisect.bisect(state.timed_paused, (time.time(), None))
    state.to_run.extend(p[1] for p in state.timed_paused[:index])
    state.timed_paused = state.timed_paused[index:]

    if not skip_simple:
        state.to_run.extend(state.paused)
        state.paused = []

def pause():
    'pause and reschedule the current greenlet and switch to the next'
    schedule(greenlet.getcurrent())
    mainloop.switch()

def pause_until(unixtime):
    '''pause and reschedule the current greenlet until a set time,
    then switch to the next'''
    schedule_at(unixtime, greenlet.getcurrent())
    mainloop.switch()

def pause_for(secs):
    '''pause and reschedule the current greenlet for a set number of seconds,
    then switch to the next'''
    pause_until(time.time() + secs)

def schedule(target=None, args=(), kwargs=None):
    '''set up a greenlet or function to run later

    if *target* is a function, it is wrapped in a new greenlet. the greenlet
    will be run at an undetermined time. also usable as a decorator'''
    if target is None:
        def decorator(target):
            return schedule(target, args=args, kwargs=kwargs)
        return decorator
    if isinstance(target, greenlet):
        glet = target
    else:
        if args or kwargs:
            inner_target = target
            def target():
                inner_target(*args, **(kwargs or {}))
        glet = greenlet(target, state.mainloop)
    state.paused.append(glet)
    return target

def schedule_at(unixtime, target=None, args=(), kwargs=None):
    '''set up a greenlet or function to run at the specified timestamp

    if *target* is a function, it is wrapped in a new greenlet. the greenlet
    will be run sometime after *unixtime*, a timestamp'''
    kwargs = kwargs or {}
    if target is None:
        def decorator(target):
            return schedule_at(unixtime, target, args=args, kwargs=kwargs)
        return decorator
    if isinstance(target, greenlet):
        glet = target
    else:
        if args or kwargs:
            inner_target = target
            def target():
                inner_target(*args, **kwargs)
        glet = greenlet(target, state.mainloop)
    bisect.insort(state.timed_paused, (unixtime, glet))
    return target

def schedule_in(secs, target=None, args=(), kwargs=None):
    '''set up a greenlet or function to run in the specified number of seconds

    if *target* is a function, it is wrapped in a new greenlet. the greenlet
    will be run sometime after *secs* seconds have passed'''
    return schedule_at(time.time() + secs, target, args, kwargs)

def schedule_recurring(interval, target=None, maxtimes=0, starting_at=0,
        args=(), kwargs=None):
    '''set up a function to run at a regular interval

    every *interval* seconds, *target* will be wrapped in a new greenlet
    and run

    if *maxtimes* is greater than 0, *target* will stop being scheduled after
    *maxtimes* runs

    if *starting_at* is greater than 0, the recurring runs will begin at that
    unix timestamp, instead of ``time.time() + interval``'''
    kwargs = kwargs or {}
    starting_at = starting_at or time.time()

    if target is None:
        def decorator(target):
            return schedule_recurring(interval, target, maxtimes, starting_at,
                                      args, kwargs)
        return decorator

    func = target
    if isinstance(target, greenlet):
        if target.dead:
            raise TypeError("can't schedule a dead greenlet")
        func = target.run

    def run_and_schedule_one(tstamp, count):
        # pass in the time scheduled instead of just checking
        # time.time() so that delays don't add up
        if not maxtimes or count < maxtimes:
            func(*args, **kwargs)
            schedule_at(tstamp, run_and_schedule_one,
                    args=(tstamp + interval, count + 1))

    firstrun = starting_at + interval
    schedule_at(firstrun, run_and_schedule_one, args=(firstrun, 0))

    return target

def schedule_to_top(target=None, args=(), kwargs=None):
    '''set up a function or greenlet to run, skipping to the front of the line

    if *target* is a function, it is wrapped in a new greenlet. the greenlet
    will be the next greenlet run, unless you call this function again before
    the next blocking action, in which case that one will have skipped to the
    front as well.
    '''
    if target is None:
        def decorator(target):
            return schedule_to_top(target, args, kwargs)
        return decorator
    if isinstance(target, greenlet):
        glet = target
    else:
        if args or kwargs:
            inner_target = target
            def target():
                inner_target(*args, **(kwargs or {}))
        glet = greenlet(target, state.mainloop)
    state.to_run.appendleft(glet)
    return target

@greenlet
def mainloop():
    while 1:
        if not state: #pragma: no cover
            # python's shutdown sequence gets out of wack when we have
            # greenlets in play. in certain circumstances, modules become
            # None before this code runs.
            break
        try:
            if not state.to_run:
                _hit_poller(FAST_POLL_TIMEOUT)
                _check_paused()

                while not state.to_run:
                    # if there are timed-paused greenlets, we can
                    # just wait until the first of them wakes up
                    if state.timed_paused:
                        until = state.timed_paused[0][0]
                        _hit_poller(until - time.time() + FAST_POLL_TIMEOUT)
                        _check_paused(True)
                    else:
                        _hit_poller(SLOW_POLL_TIMEOUT)

            state.to_run.popleft().switch()
        except Exception, exc:
            if sys:
                _consume_exception(*sys.exc_info())
state.mainloop = mainloop

def _consume_exception(klass, exc, tb):
    _purge_exception_handlers()

    for weak in _exception_handlers:
        try:
            weak()(klass, exc, tb)
        except Exception:
            # exceptions from within exception handlers get
            # squashed so as not to create an infinite loop
            pass

def _purge_exception_handlers():
    bad = [i for i, weak in enumerate(_exception_handlers) if weak() is None]
    for i in bad[::-1]:
        _exception_handlers.pop(i)

def add_exception_handler(handler):
    if not hasattr(handler, "__call__"):
        raise TypeError("exception handlers must be callable")
    _exception_handlers.append(weakref.ref(handler))
