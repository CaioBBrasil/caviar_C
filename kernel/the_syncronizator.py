import asyncio
import json
import glob
import os
import time
from .nats import NATS
from .buffer_layer import Buffer
from .management_layer import Clock, LOGGER, PROCESS
from .module import module
LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)

class msg_syncronizator():
    def _do_init(self):
        LOGGER.debug(
            f"Module {self.__class__.__name__} created with instance ID: {id(self)}"
        )
        self._lock = asyncio.Lock()
        self.loop = LOOP  # !< The event loop of the module
        self.modules = []
        self.__update_modules()
        self.buffer = {i : Buffer(10000) for i in self.modules}
        self.the_buffer =  Buffer(10000)
        self.auxmodu = []

    def initialize(self):
        """
        This method initializes the module.
        """

        """
        @TODO: I think subscribing should be done first, since, for some reason, the module
        may need to send some message to be initialized. This is kind of a _async_ dependency
        but yeah I need to think more about this.
        """
        self._do_init()
        LOGGER.debug(f"Initializing {self.__class__.__name__.upper()} subscription")
        self.__init_subscription()

        """
        @TODO: Maybe (and just maybe) we should use NATS to check if the module is ready"""
        PROCESS._child_conn.send("")  # empty string just to flag the process as ready

        # Use run_forever here is not a big deal, since this is a subprocess and when
        # it is killed, it will be destroyed too.
        LOOP.run_forever()

    def __init_subscription(self):
        def make_callback(module_name):
            async def callback(msg):
                await self.__callback(msg, module_name)
            return callback

        for module_name in self.modules:
            
            cb = make_callback(module_name)
            LOOP.run_until_complete(
                NATS.init_subscription(
                    callback=cb, module_name=module_name
                )
            )


    def __execute_step(self):
        
        if any(len(buf) == 0 for buf in self.buffer.values()):
            time.sleep(0.001)
        

        # Step 1: Find buffer with smallest length
        smallest_name = min(self.buffer, key=lambda k: len(self.buffer[k]))
        
        smallest_buffer = self.buffer[smallest_name]
        ref_msg = smallest_buffer.get()
        
        ref_time = ref_msg[-1]
       
        sync_entry = {smallest_name: ref_msg}
        
        # Step 3: For each other buffer, find the closest timestamp
        for name, buf in self.buffer.items():
            if name == smallest_name:
                continue

            # linear search for closest timestamp
            closest = None
            min_diff = float("inf")

            for msg in buf.get():
                diff = abs(msg[-1] - ref_time)
                if diff < min_diff:
                    min_diff = diff
                    closest = msg
                    
            if False:
                # Optional: enforce tolerance
                if min_diff <= tolerance:
                    # Remove the matched msg from the buffer
                    buf.remove(closest)
                    sync_entry[name] = closest
                else:
                    # No match → message dropped or wait? You choose.
                    sync_entry[name] = None



    async def __callback(self, msg, module_name):
        """
        This method is the internal message callback.
        It is responsible for calling the user-defined callback and setting the available flag.
        """
        
        msg = NATS.decode(msg, module_name)
        print(module_name)
        """
        @TODO: This is probably causing a soft-bug, since the callback could be innvoked
        multiple time by some module message. So the control message may be backpressured
        and the module will not be able to execute the step.
        """
        if msg is not None:
            self.buffer[module_name].add(msg)
            if module_name == self.modules[-1]:
                async with self._lock:
                    await self.__execute_step()
                return
        LOGGER.debug(
            f"Module {self.__class__.__name__} received message: {msg} in subprocess {os.getpid()}"
        )
        PROCESS.QUEUE.put(
                [self.__class__.__name__, True]
            )  # Notify the orchestrator that the module is ready to execute the step
        

    def __update_modules(self):
        """
        This method updates the modules section of the config.json file and saves
        the module names and the order of initialization in the core object.
        """
        LOGGER.debug(f"Updating modules")

        module_paths = glob.glob(
            str("modules/*/.config/config.json")
        )  # Assuming all modules are in modules dir
        for path in module_paths:
            with open(path, "r") as file:
                module_config = json.load(file)

                if module_config["module"]["id"] != "mobility":
                    continue
                module_name = module_config["module"]["name"]
                self.modules.append(module_name)
