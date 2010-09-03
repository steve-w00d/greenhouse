from greenhouse.compat import *
from greenhouse.scheduler import *
from greenhouse.utils import *
from greenhouse.pool import *
from greenhouse.io import *
import greenhouse.poller
import greenhouse.emulation


# prime the pump. if there is a traceback before the mainloop greenlet
# has a chance to get into its 'try' block, the mainloop will die of that
# traceback and it will wind up being raised in the main greenlet
@schedule
def f():
    pass
pause()
del f
