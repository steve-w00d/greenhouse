import socket as socket_module
import threading as threading_module
import Queue as queue_module

from greenhouse import compat, io, scheduler, utils


def enable(builtins=1, socket=1, thread=1, threading=1, queue=1):
    if builtins:
        builtins()
    if socket:
        socket()
    if thread:
        thread()
    if threading:
        threading()
    if queue:
        queue()


def disable(builtins=1, socket=1, thread=1, threading=1, queue=1):
    if builtins:
        builtins(enable=False)
    if socket:
        socket(enable=False)
    if thread:
        thread(enable=False)
    if threading:
        threading(enable=False)
    if queue:
        queue(enable=False)


_open = __builtins__['open']
_file = __builtins__['file']

def builtins(enable=True):
    if enable:
        __builtins__['open'] = __builtins__['file'] = io.File
    else:
        __builtins__['open'] = _open
        __builtins__['file'] = _file


_socket = socket_module.socket

def socket(enable=True):
    if enable:
        socket_module.socket = Socket
    else:
        socket_module.socket = _socket


_allocate_lock = thread_module.allocate_lock
_allocate = thread_module.allocate
_start_new_thread = thread_module.start_new_thread
_start_new = thread_module.start_new

def _green_start(function, args, kwargs=None):
    glet = compat.greenlet(
            lambda: function(*args, **(kwargs or {})),
            scheduler.state.mainloop)
    scheduler.schedule(glet)
    return id(glet)

def thread(enable=True):
    if enable:
        thread_module.allocate_lock = thread_module.allocate = utils.Lock
        thread_module.start_new_thread = thread_module.start_new = _green_start
    else:
        thread_module.allocate_lock = _allocate_lock
        thread_module.allocate = _allocate
        thread_module.start_new_thread = _start_new_thread
        thread_module.start_new = _start_new


_event = threading_module.Event
_lock = threading_module.Lock
_rlock = threading_module.RLock
_condition = threading_module.Condition
_semaphore = threading_module.Semaphore
_boundedsemaphore = threading_module.BoundedSemaphore
_timer = threading_module.Timer
_thread = threading_module.Thread
_local = threading_module.local

def threading(enable=True):
    if enable:
        threading_module.Event = utils.Event
        threading_module.Lock = utils.Lock
        threading_module.RLock = utils.RLock
        threading_module.Condition = utils.Condition
        threading_module.Semaphore = utils.Semaphore
        threading_module.BoundedSemaphore = utils.BoundedSemaphore
        threading_module.Timer = utils.Timer
        threading_module.Thread = utils.Thread
        threading_module.local = utils.Local
    else:
        threading_module.Event = _event
        threading_module.Lock = _lock
        threading_module.RLock = _rlock
        threading_module.Condition = _condition
        threading_module.Semaphore = _semaphore
        threading_module.BoundedSemaphore = _boundedsemaphore
        threading_module.Timer = _timer
        threading_module.Thread = _thread
        threading_module.local = _local


_queue = queue_module.Queue

def queue(enable=True):
    if enable:
        queue_module.Queue = utils.Queue
    else:
        queue_module.Queue = _queue
