import asyncio
import json
import glob
import os
import time
import numpy as np
from .nats import NATS
from .buffer_layer import Buffer
from .management_layer import Clock, LOGGER, PROCESS
from .module import module

LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)
import copy

class MessageSynchronizer():
    def _do_init(self):
        LOGGER.debug(
            f"Module {self.__class__.__name__} created with instance ID: {id(self)}"
        )
        self.subsc_topics = []
        self.publ_topics = []
        self._lock = asyncio.Lock()
        self.loop = LOOP  # !< The event loop of the module
        self.modules = []
        self.__update_modules()
        self.buffer = {i : Buffer(10000) for i in self.subsc_topics}
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
        
        def make_callback(subsc_topic):
            async def callback(msg):
                await self.__callback(msg, subsc_topic)
            return callback
        for subsc_topic in self.subsc_topics:
            cb = make_callback(subsc_topic)
            LOOP.run_until_complete(
                NATS.init_subscription(
                    callback=cb, module_name=__class__.__name__.lower(), topic=subsc_topic
                )
            )

    async def __execute_step(self):

        # Step 1: Find buffer with smallest length
        smallest_name = min(self.buffer, key=lambda k: len(self.buffer[k]))
        smallest_buffer = self.buffer[smallest_name]
        ref_msg = smallest_buffer.get()
        ref_time = ref_msg[0][1]["timestamp"]      
        sync_entry = {smallest_name: list(ref_msg[0][1].values())[0]}
        # Step 3: For each other buffer, find the closest timestamp
        for name, buf in self.buffer.items():

            if name == smallest_name:
                continue

            # linear search for closest timestamp
            closest = None
            min_diff = float("inf")
            
            for tmp_i in range(len(buf)): 
                msg = buf.get() 
                time_msg = msg[0][1]["timestamp"]    
                diff = abs(time_msg - ref_time)
                
                if diff < min_diff:
                    min_diff = diff
                    closest = msg
                    
                if diff < 0.0001:
                    break
                    
            sync_entry[name] = list(closest[0][1].values())[0]
        
        sync_entry["timestamp"] = ref_time
        fmsg = {"message": {}, "timestamp": 0}
        for key, value in sync_entry.items():
            if key == "timestamp":
                fmsg["timestamp"] = value
            else:
                if key.split(".")[1] not in fmsg["message"]:
                    fmsg["message"][key.split(".")[1]] = [value]
                else:
                    fmsg["message"][key.split(".")[1]].append(value)
                    
        #print(f"\n{fmsg}\n")
        
        await NATS.send("synchronizator.message", fmsg)
        self.the_buffer.add(fmsg)    
    
    
    async def __callback(self, msg, topic):
        """
        This method is the internal message callback.
        It is responsible for calling the user-defined callback and setting the available flag.
        """
        
        msg = NATS.decode(msg, topic)
        
        """
        @TODO: This is probably causing a soft-bug, since the callback could be innvoked
        multiple time by some module message. So the control message may be backpressured
        and the module will not be able to execute the step.
        """
        if msg is not None:
            self.buffer[topic].add(msg)
            if not any(len(buf) == 0 for buf in self.buffer.values()):
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
        general_settings_path = "kernel/.config/config.json"
        LOGGER.debug(f"Updating modules")
    
        with open(general_settings_path, "r") as file:
            msgsynch_conf = json.load(file)["msgSynchron"]


        self.subsc_topics = [f"{p}.{i}" for i in msgsynch_conf["topics"].keys() for p in msgsynch_conf["topics"][i]]
        self.publ_topics = ["msgsync."+ i for i in list(msgsynch_conf["topics"].keys())]