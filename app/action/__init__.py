from .compact_memory import \
    Param as ParamCompactMemory, \
    execute as action_compact_memory

from .cpuset_create import \
    Param as ParamCPUSetCreate, \
    execute as action_cpuset_create

from .cpuset_delete import \
    Param as ParamCPUSetDelete, \
    execute as action_cpuset_delete

from .drop_caches import \
    Param as ParamDropCaches, \
    execute as action_drop_caches

from .move_tasks import \
    Param as ParamMoveTasks, \
    execute as action_move_tasks
