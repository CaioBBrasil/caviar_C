import asyncio
import time
import copy
from abc import ABC, abstractmethod

from .management_layer import Clock, LOGGER, PROCESS
from .step_layer import ExecuteStep, Step, Substep
from .handler import handler

class Scheduler(ABC):
    """
    This class represents the scheduler for the simulation.
    """

    _event = 0  # !< The event id of the simulation.
    _modules = None  # !< The enabled modules of the simulation.
    # __clock = Clock()  # !< Clock object
    """The enabled modules of the simulation."""

    def __init__(self, interval: float):
        """
        Constructor that initializes the Scheduler object.

        @param interval: The time interval of the simulation.
        """
        self.__clock = Clock(interval)
        pass

    @handler.async_exception_handler
    async def _wait(self, timeout=0.2):
        """
        This method waits for a certain amount of time.

        @param timeout: The amount of time to wait.
        """
        await asyncio.sleep(timeout)

    @abstractmethod
    def _encapsulate(self):
        """
        This method encapsulates the substeps of the simulation.
        """
        pass

    @abstractmethod
    def _execute_step(self):
        """
        This method executes the step of the simulation.
        """
        pass

    @handler.async_exception_handler
    async def execute_steps_in_loop(self):
        """
        This method executes the steps in a loop.
        """
        LOGGER.info("Executing steps...")
        while True:
            start_time = time.time_ns()
            LOGGER.debug(f"Event_id: {self._event}")
            await self._execute_step()
            """
            @TODO: Check wheter its necessary to have a clock to control 
            the sampling frequency of the caviar simulation. This is probably
            unnecessary, since the co-simulator should be faster than any module,
            """
            await self._wait(self.__clock.get_step_time())
            self._event += 1
            LOGGER.debug(
                f"Step {self._event} executed in {(time.time_ns() - start_time) / 1e6} ms"
            )

    # @handler.exception_handler
    def update_modules(self, *modules):
        """
        This method updates the enabled modules of the simulation.

        @param modules: The enabled modules of the simulation.
        """
        self._modules = modules



#############################################################
class Sync(Scheduler):
    """
    This class represents the synchronization for the simulation.
    """

    __allowed_substeps = []
    __encapsulated = None

    def __check__allowance(self):
        """
        This method checks if there is available input in all enabled modules.
        As default, all modules are allowed to run in synchronous mode.
        """
        LOGGER.debug("Checking allowance...")
        for module_dict in self._modules:
            for reference, dependency in module_dict.items():
                LOGGER.debug(f"Module added to run {reference}...")
                self.__allowed_substeps.append(Substep(reference))

    def __init__(self, interval: float):
        """
        Constructor that initializes the Sync object.

        @param interval: The time interval of the simulation.
        """
        super(Sync, self).__init__(interval)

    def _encapsulate(self):
        """
        In syncrhonous case, encapsulation is done for *each* substep,
        assuming multiple substeps as steps in a single event.
        """
        self.__encapsulated = []
        if self.__allowed_substeps:
            for substep in self.__allowed_substeps:
                LOGGER.debug(f"Encapsulating substep: {substep}")
                self.__encapsulated.append(Step(*[substep]))

    async def _execute_step(self):
        """
        This method executes the step of the simulation.
        """
        all_modules: dict = copy.deepcopy(self._modules[0])
        count = 0
        LOGGER.debug(f"All modules to run: {all_modules}")
        while all_modules:
            for reference in list(all_modules.keys()):
                if not all_modules[reference]:
                    substep = Substep(reference)
                    step = Step(*[substep])
                    await ExecuteStep.execute_step(step)
                    all_modules.pop(reference)
                    LOGGER.debug(
                        f"Module {reference} ran and now are removed from the list: {all_modules}"
                    )
                else:
                    modules_state = PROCESS.check_state()
                    if not modules_state:
                        count += 1
                        LOGGER.debug(f"No modules available: {modules_state}")
                        await self._wait(1)
                        if count > 5:
                            LOGGER.error("No modules available to run. Exiting...")
                            count = 0
                            return
                    else:
                        LOGGER.debug(f"Modules available: {modules_state}")
                        if reference in modules_state:
                            substep = Substep(reference)
                            step = Step(*[substep])
                            await ExecuteStep.execute_step(step)
                            all_modules.pop(reference)
                            # all_modules.remove(module_dict)

    def __clean__allowed_substeps(self):
        """
        This method cleans the allowed substeps.
        """
        self.__allowed_substeps.clear()
        LOGGER.debug("Allowed substeps cleaned.")


###############################################################
class Async(Scheduler):
    """
    This class represents the asynchronous simulation.
    In a asynchronous simulation, the modules are executed in
    parallel where all are encapsulated in a substep, and consequently in a step.
    Since, the message passing is done in a asynchronous way, the modules will always
    execute with (t-1) messages.

    +---------+
    | Step 1
    | +-----+
    | | s1  |
    | +-----+
    | +-----+
    | | s2  |
    | +-----+
    | +-----+
    | | s3  |
    | +-----+
    +---------+


    """

    __allowed_substeps = []
    __encapsulated = None

    def __init__(self, interval: float):
        """
        Constructor that initializes the Async object.

        @param interval: The time interval of the simulation.
        """
        super(Async, self).__init__(interval)

    def _encapsulate(self):
        """
        This method encapsulates the substeps of the simulation.
        """
        if self.__allowed_substeps:
            self.__encapsulated = Step(*self.__allowed_substeps)
        
    def __check__allowance(self):
        """
        This method checks if there is available input in all enabled modules
        """
        LOGGER.debug("Checking allowance...")
        available_modules = PROCESS.check_state()
        for module_dict in self._modules:
            for reference, dependency in module_dict.items():
                if not dependency:
                    """
                    If the module has no dependencies, it is allowed to run
                    """
                    self.__allowed_substeps.append(Substep(reference))
                    continue
                LOGGER.debug(f"Checking module {reference}...")
                if available_modules and reference in available_modules:
                    """
                    If the module is not allowed, the execute step will be skipped
                    """
                    LOGGER.debug(f"Module {reference} is allowed.")
                    self.__allowed_substeps.append(Substep(reference))
        LOGGER.debug(f"Allowed modules to run in Event: {self.__allowed_substeps}")

    async def _execute_step(self):
        """
        This method executes the step of the simulation.
        """
        self.__check__allowance()
        if self.__allowed_substeps:
            
            self._encapsulate()
            LOGGER.debug(f"Allowed to walk {self.__allowed_substeps}")
            await ExecuteStep.execute_step(self.__encapsulated)
            self.__clean__allowed_substeps()

    def __clean__allowed_substeps(self):
        """
        This method cleans the allowed substeps.
        """
        self.__allowed_substeps.clear()
        LOGGER.debug("Allowed substeps cleaned.")
