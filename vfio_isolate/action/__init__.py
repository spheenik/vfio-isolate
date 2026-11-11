from .action import Execution, PreconditionError, RolledBackError
from .compact_memory import CompactMemory
from .cpu_governor import CPUGovernor
from .cpuset_create import CPUSetCreate
from .cpuset_delete import CPUSetDelete
from .cpuset_modify import CPUSetModify
from .drop_caches import DropCaches
from .hugepages import HugePages
from .irq_affinity import IRQAffinityOperation, IRQAffinity
from .move_tasks import MoveTasks
from .workqueue_affinity import WorkqueueOperation, WorkqueueAffinity

ACTIONS = {cls.name: cls for cls in (
    CompactMemory, CPUGovernor, CPUSetCreate, CPUSetDelete, CPUSetModify,
    DropCaches, HugePages, IRQAffinity, MoveTasks,
    WorkqueueAffinity,
)}
