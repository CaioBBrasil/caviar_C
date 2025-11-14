import asyncio

from .management_layer import LOGGER
from .nats import NATS
from .buffer_layer import Buffer

################################################
class ExecuteStep:
    """
    This static class is responsible for executing the step of the simulation.
    """

    @staticmethod
    def __deserialize(step):
        """
        This method deserializes the step of the simulation.
        It basically retrieves the sub_steps references to trigger the
        module.__execute_step.

        @param step: The step to be deserialized.

        @return: The deserialized step -> List.
        """
        LOGGER.debug(f"Deserializing {step}")
        sub_steps = step.get_substeps()
        # @TODO: check if it is necessary to return the id of the substep
        return [substep.reference for substep in sub_steps]

    @staticmethod
    async def execute_step(step):
        """
        This method executes the step of the simulation.
        In this case, it triggers the module.__execute_step, using a NATS multicast.

        @param references: A list of references to _module.execute_step_
        """
        references = ExecuteStep.__deserialize(step)
        
        """
        @TODO: Right now the references are strings, but I think its not efficient to do this"""

        await NATS.multicast(references)

################################################
class Step:
    """Class to encapsulate each step of the simulation."""

    _next_id = 0
    _timeout = 0

    def __init__(self, *substeps):
        self._id = Step._next_id
        Step._next_id += 1
        self._substeps = substeps

    @property
    def steps(self):
        return self._substeps

    @property
    def timeout(self):
        return self._timeout

    @property
    def step_id(self):
        return self._id

    def __str__(self):
        return f"Step(id={self._id}, steps={self._substeps})"

    def __repr__(self):
        return str(self)

    @classmethod
    def create(cls, *substeps):
        """
        Class method to create a new Step instance and return it as a dictionary.
        """
        instance = cls(*substeps)
        return {"ID": instance._id, "substeps": instance._substeps}

    def get_substeps(self):
        """
        Method to return the substeps of the step.
        """
        return self._substeps

################################################
class Substep:
    """Class to encapsulate each substep of the simulation."""

    _next_id = 0
    _timeout = 0.0

    def __init__(self, ref):
        self._id = Substep._next_id
        Substep._next_id += 1
        self._reference = ref

    @property
    def reference(self):
        return self._reference

    @property
    def id(self):
        return self._id

    @property
    def timeout(self):
        return self._timeout

    def __str__(self):
        return f"substep(id={self._id}, reference={self._reference})"

    def __repr__(self):
        return str(self)
